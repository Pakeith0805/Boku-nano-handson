"""組合せ汎化テスト用に、特定のop組合せを訓練/検証から隔離する。

課題文の例：「訓練では『偶数抽出』と『降順整列』を別々に見せ、テストでは両者を組み合わせる」。
これを実現するには、予約したop組合せ（例: `{even, desc}`）を含む意味ASTを**丸ごと**訓練・
検証から除外し、専用のテストプールに回す必要がある。単体のop（`even`単体、`desc`単体）は
訓練に残す——「個々の操作は学習したが、その組合せは見ていない」という状況を作るのが目的で、
op自体を隠してしまっては汎化のテストにならないため。

この隔離は`src/select/split.py`の`behavior_hash`分割より**前**に行う。分割の対象母集団から
先に抜いておかないと、予約したはずの組合せが偶然train側に混ざる。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

RESERVED_PAIRS: tuple[frozenset[str], ...] = (
    frozenset({"even", "desc"}),
    frozenset({"add_k", "take_first"}),
    frozenset({"gt", "reverse"}),
)
"""組合せ汎化テスト用に予約する3組。`even`+`desc`と`gt`+`reverse`は抽出×並べ替え、
`add_k`+`take_first`は変換×切り出しで、カテゴリの組合せに変化を持たせている。24opから
3組・6opぶんを使うので互いに重複しない。1組あたり5,678件（全体の2.12%）が隔離され、
3組合計で16,962件（6.34%）が組合せ汎化テストに回る。"""


@dataclass(frozen=True, slots=True)
class CombinationSplit:
    """組合せ汎化の隔離結果。"""

    remaining: tuple[str, ...]
    """予約した組合せを含まない、通常の分割（train/val/test）に回してよいASTの`ast_id`。"""

    reserved: tuple[str, ...]
    """予約した組合せを1つ以上含む、組合せ汎化テスト専用の`ast_id`。"""


def contains_reserved_pair(ops: Sequence[str], pairs: Sequence[frozenset[str]]) -> bool:
    """`ops`が予約ペアのいずれかを（順序を問わず）両方含むか。"""
    op_set = set(ops)
    return any(pair <= op_set for pair in pairs)


def carve_out_combinations(
    records: Sequence[Mapping[str, Any]], pairs: Sequence[frozenset[str]]
) -> CombinationSplit:
    """予約ペアを1つ以上含むASTを`reserved`へ、それ以外を`remaining`へ振り分ける。

    単体で予約opを含むASTを訓練から除く必要はない——除外するのは**両方揃って**いる
    ASTだけである（`contains_reserved_pair`が判定するのはペア全体の包含）。
    """
    remaining: list[str] = []
    reserved: list[str] = []
    for r in records:
        if contains_reserved_pair(r["semantic_ast"], pairs):
            reserved.append(r["ast_id"])
        else:
            remaining.append(r["ast_id"])
    return CombinationSplit(remaining=tuple(remaining), reserved=tuple(reserved))
