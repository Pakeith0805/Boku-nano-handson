"""意味ASTの指紋（依存性注入版、単体で完結）。

2種類のハッシュを持つ。役割が違うので混同しないこと。

| | 何から作るか | 何に使うか |
| --- | --- | --- |
| `semantic_hash` | op列の正準JSON | 分割の単位、漏洩検査 |
| `behavior_hash` | 固定入力集合に対する出力列 | 可換対・意味的縮退の検出 |

op評価（`evaluate`）と固定入力集合（`probes`）はどちらも呼び出し側が渡す。
このファイル自身はopの意味を知らないし、probe setの作り方も知らない。
そうしておくことで、op実装やprobe生成ロジックをどこか1箇所にしか書かずに済む
（このファイルにも複製すると、直したときに片方だけ直し忘れる余地ができる）。

由来情報（生成時刻など）はどの関数にも渡さない。ハッシュに混ざると、
同一入力での再実行が別のハッシュになり、再現性の確認ができなくなるため。
"""

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

ProbeInput = tuple[tuple[int, ...], int]
"""固定入力集合の1件。`(xs, k)`。"""

Evaluate = Callable[[Sequence[str], tuple[int, ...], int], Sequence[int]]
"""op列を `(xs, k)` に適用して出力列を返す関数の型。実装は呼び出し側が持つ。"""


def _sha256(text: str) -> str:
    """UTF-8でエンコードした文字列のSHA-256（16進64桁）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(ops: Sequence[str]) -> str:
    """op列だけの正準表現。定数や由来情報は含めない。なくても良いが、将来的にjsonの書き方などが変わったときにも対応できるように存在している。"""
    return json.dumps(list(ops), ensure_ascii=False, separators=(",", ":"))


def semantic_hash(ops: Sequence[str]) -> str:
    """op列の正準JSONのハッシュ。順序が違えば別の値になる。"""
    return _sha256(canonical_json(ops))


def behavior_outputs(
    ops: Sequence[str],
    probes: Sequence[ProbeInput],
    evaluate: Evaluate,
) -> tuple[tuple[int, ...], ...]:
    """固定入力集合を受け取り、出力列を出す。`behavior_hash`・`always_empty`・`is_identity` の材料。"""
    return tuple(tuple(evaluate(ops, xs, k)) for xs, k in probes)


def behavior_hash_of(outputs: Sequence[Sequence[int]]) -> str:
    """出力列を受け取り、ハッシュを作る。入力集合の順序に依存する。"""
    payload = json.dumps(
        [list(output) for output in outputs],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return _sha256(payload)


def behavior_hash(
    ops: Sequence[str],
    probes: Sequence[ProbeInput],
    evaluate: Evaluate,
) -> str:
    """固定入力集合に対する出力列のハッシュを出す。"""
    return behavior_hash_of(behavior_outputs(ops, probes, evaluate))


def is_always_empty(outputs: Sequence[Sequence[int]]) -> bool:
    """固定入力集合の全入力で出力が空になるか判定。"""
    return all(len(output) == 0 for output in outputs)


def is_identity_over(
    probes: Sequence[ProbeInput], outputs: Sequence[Sequence[int]]
) -> bool:
    """固定入力集合の全入力で入力と同じ出力になるか判定。"""
    return all(
        tuple(output) == xs for (xs, _), output in zip(probes, outputs, strict=True)
    )


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """1つの意味ASTの指紋一式。"""

    semantic_hash: str
    behavior_hash: str
    always_empty: bool
    is_identity: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic_hash": self.semantic_hash,
            "behavior_hash": self.behavior_hash,
            "always_empty": self.always_empty,
            "is_identity": self.is_identity,
        }


def fingerprint(
    ops: Sequence[str],
    probes: Sequence[ProbeInput],
    evaluate: Evaluate,
) -> Fingerprint:
    """指紋を一度の評価でまとめて作る。時刻は受け取らない（由来情報をハッシュに混ぜないため）。"""
    outputs = behavior_outputs(ops, probes, evaluate)
    return Fingerprint(
        semantic_hash=semantic_hash(ops),
        behavior_hash=behavior_hash_of(outputs),
        always_empty=is_always_empty(outputs),
        is_identity=is_identity_over(probes, outputs),
    )


def group_by_behavior(
    op_sequences: Sequence[Sequence[str]],
    probes: Sequence[ProbeInput],
    evaluate: Evaluate,
) -> dict[str, list[tuple[str, ...]]]:
    """`behavior_hash` ごとにop列をまとめる。衝突グループの報告に使う。除去はしない。"""
    groups: dict[str, list[tuple[str, ...]]] = {}
    for ops in op_sequences:
        key = behavior_hash(ops, probes, evaluate)
        groups.setdefault(key, []).append(tuple(ops))
    return groups
