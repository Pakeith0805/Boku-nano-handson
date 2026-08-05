"""バインディング（`k`の具体化）。

`k`を参照するopを持つ意味ASTは、2つの形態のどちらかで実体化できる。

1. **パラメータ版**（`None`）：全スロットを`k`のまま残す。検証は任意の`k`で行える
2. **リテラル版**（`int`）：全スロットを同一の値`v`に具体化する。検証は`k = v`で行う

混在（スロットごとに違う値を入れる）は型として表現できない
（`Binding = int | None`）。パラメータ版・リテラル版のどちらでもない状態は
そもそも作れないようにすることが、この型の役割である。

使える`v`は`uniform_literal_domain`（各スロットの値域の共通部分）の要素に限る。
リテラル版のコードは「参照インタプリタを`k = v`で評価した結果」と一致するので、
パラメータ版とまったく同じ検証機構が使い回せる。

## opに焼き付いた定数はバインディングではない

`double`の`2`、`square`の2乗、`even`の`%2`のような定数はopの意味の一部であり、
`k`とは無関係（`k`を変えても動かない）。これらのopの`binding_slots`は0個で、
そもそもバインディングの対象にならない。
"""

from collections.abc import Sequence
from typing import Any

Binding = int | None
"""`k`の具体化。`None` ＝ パラメータ版、`int` ＝ リテラル版（その値に固定）。"""


def uniform_literal_domain(binding_slots: Sequence[dict[str, Any]]) -> tuple[int, ...]:
    """全スロットを同一の値に具体化する場合に使えるリテラル。

    各スロットの`literal_domain`の共通部分。スロットが無ければ空タプル
    （`k`を参照するopが無いASTには具体化する対象が無い）。

    `binding_slots`は`SemanticAST.to_dict()`/レコードの`binding_slots`と同じ形
    （各要素が`{"index":..., "op":..., "literal_domain":[...]}`の辞書）を受け取る。
    """
    if not binding_slots:
        return ()
    allowed = set(binding_slots[0]["literal_domain"])
    for slot in binding_slots[1:]:
        allowed &= set(slot["literal_domain"])
    return tuple(sorted(allowed))


def enumerate_bindings(
    binding_slots: Sequence[dict[str, Any]], include_literal: bool
) -> list[Binding]:
    """1つの意味ASTに対して作るバインディングの一覧。

    パラメータ版（`None`）は常に含む——`k`参照opを持たないASTが1例も作れなくなる
    ことを避けるため、こちらに切り替えは置かない。`include_literal`が`True`かつ
    `k`参照opがあれば、`uniform_literal_domain`の各値をリテラル版として追加する。
    """
    domain = uniform_literal_domain(binding_slots)
    if not domain or not include_literal:
        return [None]
    return [None, *domain]
