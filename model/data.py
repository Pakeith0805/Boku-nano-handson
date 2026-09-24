"""訓練/検証データセット(JSONL)をトークナイズし、1レコード=1系列で返すための関数が入ったスクリプト。

各レコードは`<bos><task>{instruction_ja}<code>{reference_code}<eos>`の形にエンコードする。
`loss_mask`は「その位置の次のトークンを予測する損失を数えるか」を表し、instruction部分
(bos/task/instruction本文)には立てない——学習させたいのは日本語指示からコードへの写像だから。
"""

from __future__ import annotations

import json
import random
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

from tokenizers import Tokenizer
from src.verify.records import is_verified

# こうやって書くと、SpecialIDs.padみたいな感じで呼び出せるようになる。初期化後の書き換え不可
class SpecialIds(NamedTuple):
    pad: int
    bos: int
    eos: int
    task: int
    code: int

# Special Tokenのidがすべて入ったタプルを返す関数。
def load_special_ids(tokenizer: Tokenizer) -> SpecialIds:
    # Special tokenを引数にとり、それが、存在しないSpecial tokenだった場合にエラーを返し、あった場合はそのidを通す関数
    def id_of(token: str) -> int:
        candi_special_token_id = tokenizer.token_to_id(token)
        if candi_special_token_id is None:
            raise ValueError(f"tokenizerに特殊トークンが無い: {token}")
        return candi_special_token_id

    return SpecialIds(
        pad=id_of("<|pad|>"),
        bos=id_of("<|bos|>"),
        eos=id_of("<|eos|>"),
        task=id_of("<|task|>"),
        code=id_of("<|code|>"),
    )

# 学習用jsonを読み込み、日本語と、それに対応するコードのみを抜き出す。
def load_records(path: Path) -> list[tuple[str, str]]:
    """検証済みの行から指示・コードを取り出す。不合格・フラグ欠落は除外。"""
    records: list[tuple[str, str]] = []
    rejected = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if not is_verified(r):
                rejected += 1
                continue
            records.append((r["instruction_ja"], r["reference_code"]))
    if rejected:
        warnings.warn(f"{path}: 検証不合格またはフラグ欠落の{rejected}件を除外", stacklevel=2)
    if not records:
        raise ValueError(f"検証済みレコードがありません: {path}")
    return records

# トークナイズされた、学習に実際に使う数字のリストを返す関数
def encode_record(
    tokenizer: Tokenizer, instruction: str, code: str, ids: SpecialIds
) -> tuple[list[int], list[int]]:
    """1レコードをトークン列`[bos, task, *instr, code, *code, eos]`とloss_maskにする。

    maskが1なのは「codeトークン(コード本文の最初を予測する)」〜「eos自身」まで。
    instruction部分(bos/task/instruction本文)は0にする。
    """
    # instr_idsには、元々の文がtokenizeされた後の、decodeすれば文章に戻る数字のリストが入っている
    instr_ids = tokenizer.encode(instruction).ids
    code_ids = tokenizer.encode(code).ids

    # *をつけると、その場でリストを展開する。リストが入れ子構造にならない。
    tokens = [ids.bos, ids.task, *instr_ids, ids.code, *code_ids, ids.eos]
    mask = [0] * (2 + len(instr_ids)) + [1] * (len(code_ids) + 2)
    return tokens, mask

# レコードの順番をシャッフルし、順番に読んでいく関数
def iter_padded_records(
    records: list[tuple[str, str]], # (指示文, コード)のペアのリスト
    tokenizer: Tokenizer,
    ids: SpecialIds,
    *,
    max_seq_len: int,
    rng: random.Random,
) -> Iterator[tuple[list[int], list[int]]]:
    """`records`を(エポックごとにシャッフルして)何周でも回し、1レコード分の
    `(トークン列, loss_mask)`を無限に生成する。stopは呼び出し側で制御。seedも呼び出し側で。
    """
    # list(range(len(records)))で、recordsの長さだけ、0,1,2…というリストが出来る
    order = list(range(len(records)))
    while True:
        rng.shuffle(order)
        for i in order:
            instruction, code = records[i]
            tokens, mask = encode_record(tokenizer, instruction, code, ids)
            if len(tokens) > max_seq_len:
                raise ValueError(
                    f"レコードが max_seq_len({max_seq_len}) を超えている: {len(tokens)}トークン "
                    f"(instruction={instruction!r})"
                )
            yield tokens, mask # returnと違い、終わらない。ここで呼び出し元に値を返し、nextが呼ばれたらまた動き出す。
