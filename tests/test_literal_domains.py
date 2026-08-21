"""リテラル値域の期待値（`registry.py` L117-118）。

**`_domain()` を経由せずに値を直接書く。** これがこのファイルの存在理由である。
`_domain(lowest)` は「除外はすべて下限側にある」という観察を使った圧縮表現なので、
ヘルパー経由で期待値を作ると `LITERAL_MAX` を動かしただけで10opの値域が一斉に動き、
照合が素通りする。展開した形を独立に書いておくことで初めて検査になる。

後半では、除外の**根拠そのもの**を参照インタプリタで検証する。値域の下限は
「そのopのどのリテラルが他のopと衝突するか」という意味論的な事実を符号化したものであり、
参照インタプリタがある以上その事実は主張ではなく検証できる対象である。
"""

import pytest

from src.interp.interp import run
from src.semantics.registry import OP_REGISTRY

# 改訂版 L269-277。`_domain()` を呼ばずに展開して書く。
EXPECTED_DOMAINS: dict[str, tuple[int, ...]] = {
    # ---- 除外なし（下限1）----
    "gt": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    "lt": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    "le": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    "add_k": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    "sub_k": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    "take_first": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    "take_last": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    # ---- @1 は `positive` と同一なので除外（L275）----
    "ge": (2, 3, 4, 5, 6, 7, 8, 9, 10),
    # ---- @1 は恒真、@2 は `even` と同一なので除外（L274-275）----
    "multiple_of": (3, 4, 5, 6, 7, 8, 9, 10),
    # ---- @1 は恒等、@2 は `double`、@3 は `triple` と同一なので除外（L273-275）----
    "mul_k": (4, 5, 6, 7, 8, 9, 10),
}

# 除外した値と、その根拠になっている衝突相手。`"identity"` は恒等変換
# （＝入力をそのまま返す）を指し、対応するopは存在しない。
EXCLUSIONS: list[tuple[str, int, str]] = [
    ("ge", 1, "positive"),
    ("multiple_of", 1, "identity"),
    ("multiple_of", 2, "even"),
    ("mul_k", 1, "identity"),
    ("mul_k", 2, "double"),
    ("mul_k", 3, "triple"),
]

# 衝突の有無を見るための入力。境界値・符号の混在・未整列・重複を含める。
# `probes/` の凍結済み固定入力集合には**あえて依存しない**——あちらが壊れたときに
# こちらまで一緒に沈黙するのを避けるため、この検査は自前の入力で完結させる。
INPUTS: tuple[tuple[int, ...], ...] = (
    (),
    (0,),
    (1,),
    (2,),
    (3,),
    (7,),
    (-7,),
    (5, 1, 9, 3),
    (2, 4, 6, 8, 10),
    (3, 6, 9, 12),
    (7, 7, 7, 7, 7),
    (1, 2),
    (-5, -4, -3, -2, -1),
    (-100, -7, -3, -2, -1, 0, 1, 2, 3, 4, 7, 100),
    (-100, 100),
    (0, 1, -1),
    tuple(range(1, 11)),
)


def behavior(ops: tuple[str, ...], k: int) -> tuple[tuple[int, ...], ...]:
    """`INPUTS` 全件に対する出力列。同じop列でも `k` が違えば別の振る舞いになる。"""
    return tuple(tuple(run(ops, xs, k)) for xs in INPUTS)


IDENTITY = tuple(INPUTS)
"""恒等変換の出力列。入力をそのまま返す。"""


def test_expected_domains_cover_every_k_op():
    """期待値の表が `uses_k` のop（10個）を過不足なく覆っている。

    表に書き忘れたopが黙って検査対象から外れるのを防ぐ。
    """
    k_ops = {name for name, spec in OP_REGISTRY.items() if spec.uses_k}
    assert set(EXPECTED_DOMAINS) == k_ops


@pytest.mark.parametrize("name", sorted(EXPECTED_DOMAINS))
def test_literal_domain_matches_the_expected_value(name):
    """値域が期待値と一致する。"""
    assert OP_REGISTRY[name].literal_domain == EXPECTED_DOMAINS[name]


@pytest.mark.parametrize(
    "name", sorted(n for n, s in OP_REGISTRY.items() if not s.uses_k)
)
def test_non_k_ops_have_no_literal_domain(name):
    """`k` を取らないopの値域は空。焼き付いた定数（`double` の2など）は
    `k` と無関係なので、そもそも具体化の対象にならない。"""
    assert OP_REGISTRY[name].literal_domain == ()


@pytest.mark.parametrize("name", sorted(EXPECTED_DOMAINS))
def test_domain_is_contiguous_up_to_the_maximum(name):
    """値域は下限から `LITERAL_MAX` まで連続している（途中に穴が無い）。

    `_domain(lowest)` はこの性質に依存した表現である。下限側でない除外を持つopが
    将来加わったらヘルパーでは表せないので、その到来をここで検出する
    （`registry.py` L113-118 の警告）。
    """
    domain = OP_REGISTRY[name].literal_domain
    assert domain == tuple(range(domain[0], 10 + 1))


@pytest.mark.parametrize(("name", "literal", "collides_with"), EXCLUSIONS)
def test_excluded_literals_really_do_collide(name, literal, collides_with):
    """**除外した値は、実際に他のopと同じ振る舞いになる。**

    値域の下限は意味論的な事実の符号化なので、その事実を参照インタプリタで確かめる。
    ここが落ちたら、除外の根拠（改訂版 L273-277）そのものが間違っている。
    """
    excluded = behavior((name,), literal)
    expected = IDENTITY if collides_with == "identity" else behavior((collides_with,), 1)
    assert excluded == expected, f"{name}@{literal} は {collides_with} と一致するはず"


@pytest.mark.parametrize(("name", "literal", "collides_with"), EXCLUSIONS)
def test_excluded_literals_are_outside_the_domain(name, literal, collides_with):
    """衝突する値が値域に**残っていない**。上のテストと対で、除外の網羅性を見る。"""
    assert literal not in OP_REGISTRY[name].literal_domain


@pytest.mark.parametrize("name", sorted(EXPECTED_DOMAINS))
def test_kept_literals_are_not_equivalent_to_any_single_op(name):
    """**残したリテラルは、どの単一opとも一致しないし恒等でもない。**

    除外のもれを検出する。`EXCLUSIONS` の表は「除外した値が衝突すること」しか言わないので、
    それだけでは「衝突するのに除外し忘れた値」が素通りする。両方向を見て初めて
    「値域の下限がちょうど正しい位置にある」と言える。

    なお `lt@1` が残っているのは意図的である（`x < 1` はゼロを含み、`negative`（`x < 0`）
    とは異なる、L277）。この検査はその判断も裏付ける。
    """
    non_k = [n for n, s in OP_REGISTRY.items() if not s.uses_k]
    for literal in OP_REGISTRY[name].literal_domain:
        observed = behavior((name,), literal)
        assert observed != IDENTITY, f"{name}@{literal} が恒等変換になっている"
        for other in non_k:
            assert observed != behavior((other,), 1), (
                f"{name}@{literal} が {other} と同一の振る舞いになっている"
            )
