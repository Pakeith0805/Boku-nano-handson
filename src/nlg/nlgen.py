"""意味ASTから、承認済み日本語表現辞書を使って指示文を組み立てる。

`src/codegen/codegen.py`の`enumerate_candidates`と対になる、日本語側の列挙関数を持つ。
codegenが「同じ意味を持つ複数のPython実装」を列挙するのに対し、こちらは「同じ意味を持つ
複数の日本語指示文」を列挙する。opごとに承認済みの言い回しが複数あるので（例えば`ge`は
13通り）、その**組み合わせの直積**が指示文のバリエーションになる——これはcodegen側の
構造の軸（内包表記/ループなど）と同じ位置づけの「軸」である。

## 連用形連結（C方式）

複数opの言い回しを1文に組み立てる際、最後のop以外は連用形で連結する
（`registry_version: ops24-v1` の辞書は全て終止形で査読・凍結してあるため、
組み立て機の側で変換する）。連用形連結（C方式）を採用した経緯は
`scripts/teacher/op_seeds.yaml` の `frame` コメントを参照。

## 依存性注入

言い回し辞書（`phrases/ja_phrases_v1.yaml`）そのものはここでは読まない。読み込みには
`yaml`（外部ライブラリ）が要るため、`src/`を標準ライブラリだけに保つ境界
（`tests/test_core_has_no_external_deps.py`）に反する。呼び出し側（`scripts/`）がYAMLを
読み、`dict[op, dict[id, phrase]]`の形で渡す（`src/semantics/fingerprint.py`が
`evaluate`・`probes`を外から受け取るのと同じ依存性注入の形）。
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from dataclasses import dataclass

from src.semantics.semantic_ast import SemanticAST

FRAME: str = "整数を要素に持つリストに対して"
"""意味AST→日本語文の書き出し。全ての文がここから始まる。

`scripts/teacher/op_seeds.yaml`の`frame`と同じ値でなければならない。`src/`から
YAMLを読めない制約上、値をここに複製している（重複であって由来ではない——意味の確定は
`op_seeds.yaml`側にある）。
"""

TRAIN_PHRASE_LIMIT: int = 10
"""訓練（および通常の検証/テスト）に使う言い回しの番号の上限。

`phrases/ja_phrases_v1.yaml`の番号（`ge-05`など）は承認日時順の連番であり、`scripts/
review_phrases.py`の`TARGET`（1opあたり最低10件）と同じ10を境にする。1〜10番は**全op
で必ず存在する**（`TARGET`未達のopは追加ラウンドで埋めてから凍結するため）一方、11番
以降は目標を超えて多く承認されたopにしか存在しない。この「あぶれた分」を言い換えテスト
専用のholdoutに回す——訓練側の番号を`scripts/review_phrases.py`の`TARGET`と同一に保つ
必要があるため、値は手で揃えること。
"""

RULES: tuple[tuple[str, str], ...] = (
    # 一段活用（〜る）。直前の段で語幹を止める。2文字の語尾で見ないと
    # 「取る」「選ぶ」のような五段活用と区別がつかない。
    ("する", "し"),
    ("える", "え"),
    ("せる", "せ"),
    ("べる", "べ"),
    ("ける", "け"),
    ("める", "め"),
    ("おく", "おき"),
    # 五段活用のうち、上の一段パターンに当てはまらない語を個別に持つ。
    # `ja_phrases_v1.yaml` に出てくるのがこの2語だけなので、一般化した
    # 「る→り」規則は置かない（一段活用の「る」と衝突するため）。
    ("取る", "取り"),
    ("選ぶ", "選び"),
    # 五段活用（う段→い段）。
    ("す", "し"),
    ("う", "い"),
    ("つ", "ち"),
    ("く", "き"),
)
"""語尾の変換規則。長い語尾から順に試すこと（`える`より先に`る`を見ない）。"""


def to_renyou(phrase: str) -> str:
    """終止形で終わる言い回しを連用形に変換する。

    どの規則にも合わなければ例外を投げる。組み立て機が知らない語尾を
    そのまま通すと、文法的に誤った文が査読を経ずに出てしまうため。
    """
    for suffix, replacement in RULES:
        if phrase.endswith(suffix):
            return phrase[: -len(suffix)] + replacement
    raise ValueError(f"連用形への変換規則がない語尾: {phrase!r}")


def _concrete(phrase: str) -> str:
    """`{k}`プレースホルダを、生成コードの引数名である`k`にそのまま置き換える。

    `literal_probe`（`op_seeds.yaml`の7）は機械検査用の具体値であり、指示文には出さない。
    生成コードは常に`k`をパラメータのまま持つ（リテラルに固定しない）ので、指示文も
    「kより大きい」のように抽象的な参照のままにする。
    """
    return phrase.replace("{k}", "k")


def _sentence(phrases_in_order: list[str]) -> str:
    """1つのopにつき1つずつ選んだ言い回し（AST順）から、指示文1本を組み立てる。

    最後のop以外は`to_renyou`で連用形にし、最後のopだけ終止形のまま
    `solve関数を書いてください。`に直結させる。
    """
    clauses = [
        to_renyou(_concrete(phrase)) if i < len(phrases_in_order) - 1 else _concrete(phrase)
        for i, phrase in enumerate(phrases_in_order)
    ]
    return f"{FRAME}、" + "、".join(clauses) + "solve関数を書いてください。"


@dataclass(frozen=True, slots=True)
class SentenceCandidate:
    """列挙された指示文候補1件。

    `phrase_ids`はAST順に並んだ、各opで採用した言い回しのID（`phrases/ja_phrases_v1.yaml`の
    `ge-05`のようなキー）。集計・重複排除・抽出スクリプトでの均し方の追跡に使う。
    """

    phrase_ids: tuple[str, ...]
    text: str


def _phrase_index(phrase_id: str) -> int:
    """`ge-05`のような言い回しIDから、末尾の連番（5）を取り出す。"""
    return int(phrase_id.rsplit("-", 1)[-1])


def split_phrase_pool(
    phrases: Mapping[str, Mapping[str, str]], *, train_limit: int = TRAIN_PHRASE_LIMIT
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """言い回し辞書を、訓練用（番号が`train_limit`以下）と言い換えテスト用（それより後）に分ける。

    番号は承認日時順の連番なので、辞書を再コンパイルしても分割結果は安定する
    （新しい承認は常に末尾の番号に付くため）。`train_limit`件しか承認されていないop
    （＝ちょうど`TARGET`件）は言い換えテスト側に出てこない——そのopを含むASTは
    `enumerate_candidates`に言い換えテスト用の辞書を渡すと`KeyError`になる。これは
    「そのopには言い換えテスト用の予備が無い」という意図した挙動であり、そのASTは
    言い換えテストの対象から外れるだけでよい。
    """
    train: dict[str, dict[str, str]] = {}
    paraphrase_test: dict[str, dict[str, str]] = {}
    for op, entries in phrases.items():
        train[op] = {
            pid: phrase for pid, phrase in entries.items() if _phrase_index(pid) <= train_limit
        }
        rest = {
            pid: phrase for pid, phrase in entries.items() if _phrase_index(pid) > train_limit
        }
        if rest:
            paraphrase_test[op] = rest
    return train, paraphrase_test


def enumerate_candidates(
    ast: SemanticAST, phrases: Mapping[str, Mapping[str, str]]
) -> list[SentenceCandidate]:
    """このASTから作れる日本語指示文を**全部**列挙する（上限なし）。

    `src/codegen/codegen.py`の`enumerate_candidates`と対になる関数。間引き（何件・どれを
    採用するか）は行わない——それは抽出スクリプトの責務。ここではASTに含まれる各opの
    承認済み言い回し（`phrases[op]`）の**直積**を取るだけである。

    `phrases`は`{op名: {言い回しID: 言い回し文字列}}`の形（`phrases/ja_phrases_v1.yaml`を
    そのまま読み込んだ形）。ASTに含まれるopが`phrases`に無ければ`KeyError`になる
    （目標未達のopをうっかり使わないようにするための、意図した挙動）。

    語尾が`RULES`に無い言い回しが混じっていれば`to_renyou`が`ValueError`を投げて止まる。
    黙って候補を1つ減らして通すと、辞書の側の不備（語尾の登録漏れ）に気づけなくなるため、
    ここでは握りつぶさない。
    """
    per_op_choices = [sorted(phrases[op].items()) for op in ast.ops]

    candidates = []
    for combo in itertools.product(*per_op_choices):
        ids = tuple(pid for pid, _ in combo)
        text = _sentence([phrase for _, phrase in combo])
        candidates.append(SentenceCandidate(phrase_ids=ids, text=text))
    return candidates
