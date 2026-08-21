"""24opの**意味**の検査（`registry.py` L16、`interp.py` L242）。

`test_registry_conformance.py` が見るのは存在と形式だけなので、「`op_even` が本当に偶数を
残すか」を確かめるのはこのファイルである。参照インタプリタは意味の唯一の権威であり、
`behavior_hash` も `data/asts.jsonl` の267,744件もこの実装が正しいという前提の上に立つ。
ハッシュは「同じ間違い」を検出できないので、ここが唯一の防波堤になる。

期待値は改訂版 L115-157 の表と実装計画 §6 の曖昧性解消から**手で書く**。実装を呼んで
得た値を期待値にしてはならない（それは実装が実装と一致することしか言わない）。
"""

import pytest

from src.interp.interp import OP_IMPLS, run
from src.semantics.registry import OP_NAMES

# (op名, xs, k, 期待する出力)
CASES: list[tuple[str, tuple[int, ...], int, list[int]]] = [
    # ---- 抽出（L115-128）----
    # 負数でも正しく判定する。Pythonの % は正の除数に対して非負を返すため
    # `-2 % 2 == 0` / `-3 % 2 == 1` になる（C/Javaの挙動とは違う）。
    ("even", (-2, -1, 0, 1, 2, 3), 1, [-2, 0, 2]),
    ("even", (1, 3, 5), 1, []),
    ("odd", (-3, -2, -1, 0, 1, 2), 1, [-3, -1, 1]),
    ("odd", (0, 2, 4), 1, []),
    # gt と ge の違いは k に等しい要素を含むかどうかだけ。
    ("gt", (4, 5, 6), 5, [6]),
    ("ge", (4, 5, 6), 5, [5, 6]),
    ("lt", (4, 5, 6), 5, [4]),
    ("le", (4, 5, 6), 5, [4, 5]),
    # lt@1 はゼロを含む。これが negative（x < 0）と違うので @1 を除外していない（L277）。
    ("lt", (-1, 0, 1), 1, [-1, 0]),
    ("negative", (-1, 0, 1), 1, [-1]),
    # ゼロは常に倍数に含まれる（0 % k == 0）。負数も正しく判定する。
    ("multiple_of", (-6, -3, 0, 3, 4, 9), 3, [-6, -3, 0, 3, 9]),
    ("multiple_of", (1, 2, 4, 5), 3, []),
    # positive / negative はどちらもゼロを含まない。
    ("positive", (-1, 0, 1), 1, [1]),
    ("zero", (-1, 0, 1, 0), 1, [0, 0]),
    # ---- 変換（L130-141）----
    ("add_k", (1, -1, 0), 3, [4, 2, 3]),
    ("sub_k", (1, -1, 0), 3, [-2, -4, -3]),
    # 出力は L103 の −100〜100 を超えてよい（L105）。クリップしない。
    ("mul_k", (100, -100, 0), 10, [1000, -1000, 0]),
    ("double", (3, -3, 0), 1, [6, -6, 0]),
    ("triple", (3, -3, 0), 1, [9, -9, 0]),
    ("negate", (3, -3, 0), 1, [-3, 3, 0]),
    ("abs", (-3, 0, 3), 1, [3, 0, 3]),
    ("square", (-3, 0, 2, 100), 1, [9, 0, 4, 10000]),
    # ---- 並べ替え（L143-149）----
    ("asc", (5, 1, 9, 3), 1, [1, 3, 5, 9]),
    ("desc", (5, 1, 9, 3), 1, [9, 5, 3, 1]),
    # reverse は「並べ替え」ではなく「現在の並びを逆にするだけ」。desc と混同しない。
    ("reverse", (5, 1, 9, 3), 1, [3, 9, 1, 5]),
    ("asc", (2, 2, 1), 1, [1, 2, 2]),
    ("desc", (1, 2, 2), 1, [2, 2, 1]),
    # ---- 切り出し（L151-157）----
    ("take_first", (1, 2, 3, 4, 5), 2, [1, 2]),
    ("take_last", (1, 2, 3, 4, 5), 2, [4, 5]),
    # k > len(xs) は全リストを返す（Pythonスライス準拠、実装計画 §6）。
    ("take_first", (1, 2), 5, [1, 2]),
    ("take_last", (1, 2), 5, [1, 2]),
    ("take_first", (1, 2, 3), 1, [1]),
    ("take_last", (1, 2, 3), 1, [3]),
    # 「1個おき」は xs[::2]（先頭から、添字が偶数）に確定する。xs[1::2] ではない。
    ("every_other", (1, 2, 3, 4, 5), 1, [1, 3, 5]),
    ("every_other", (1, 2, 3, 4), 1, [1, 3]),
    ("every_other", (7,), 1, [7]),
]


@pytest.mark.parametrize(
    ("name", "xs", "k", "expected"),
    CASES,
    ids=[f"{name}@k={k}:{xs}" for name, xs, k, _ in CASES],
)
def test_op_computes_the_specified_result(name, xs, k, expected):
    """各opが改訂版の表どおりに計算する。"""
    assert OP_IMPLS[name](xs, k) == expected


@pytest.mark.parametrize("name", sorted(OP_NAMES))
def test_every_op_maps_the_empty_list_to_the_empty_list(name):
    """空リストはどのopでも空リストになる。空リストは正当な入力（L102）。"""
    assert OP_IMPLS[name]((), 1) == []


@pytest.mark.parametrize("name", ["double", "triple", "square", "abs", "negate"])
def test_map_ops_preserve_length(name):
    """変換は要素数を変えない。抽出・切り出しと取り違えていないことの確認。"""
    xs = (-3, -1, 0, 1, 3)
    assert len(OP_IMPLS[name](xs, 1)) == len(xs)


@pytest.mark.parametrize("name", ["asc", "desc", "reverse"])
def test_order_ops_are_permutations(name):
    """並べ替えは要素の多重集合を変えない。"""
    xs = (5, 1, 9, 3, 1)
    assert sorted(OP_IMPLS[name](xs, 1)) == sorted(xs)


def test_desc_and_reverse_are_different_ops():
    """`desc`（降順整列）と `reverse`（並びを逆に）は別物であり、潰さない（実装計画 §6）。

    未整列の入力でだけ差が出るので、整列済みの入力で確かめても意味がない。
    """
    xs = (5, 1, 9, 3)
    assert OP_IMPLS["desc"](xs, 1) != OP_IMPLS["reverse"](xs, 1)


def test_square_output_is_never_negative():
    """二乗は常に非負。この性質のせいで後続の `abs` が恒等になる（L534）。

    インタプリタ側では特別扱いせず、縮退の検出は `behavior_hash` に任せる。
    """
    assert all(v >= 0 for v in OP_IMPLS["square"]((-100, -1, 0, 1, 100), 1))


def test_square_then_abs_is_a_degenerate_pair():
    """`[square, abs]` が `[square]` と同じ結果になること自体は正しい振る舞いである。

    これは実装の誤りではなく操作列レベルの縮退であり、除去せず記録する（実装計画 §2.7）。
    """
    xs = (-3, 0, 4)
    assert run(("square", "abs"), xs, 1) == run(("square",), xs, 1)


# ---- run() の契約 --------------------------------------------------------


def test_run_applies_ops_in_order():
    """操作は列の順に適用する。順序は意味を持つ（L297-302）。"""
    xs = (3, 1, 2)
    assert run(("asc", "take_first"), xs, 2) == [1, 2]
    assert run(("take_first", "asc"), xs, 2) == [1, 3]


def test_run_with_an_empty_ast_is_the_identity():
    """空列は恒等（`xs` の複製）を返す。"""
    xs = (3, 1, 2)
    assert run((), xs, 1) == [3, 1, 2]


def test_run_rejects_unknown_op_names():
    """未知のop名は `KeyError`。黙って読み飛ばさない。"""
    with pytest.raises(KeyError):
        run(("even", "no_such_op"), (1, 2), 1)


def test_run_does_not_validate_structure():
    """**構造検証は行わない**（`interp.py` L275-279）。

    操作数が `MAX_OPS` を超えていても、同一opが重複していても、この関数は黙って適用する。
    それは別の層の責任であり、権威である評価器に検証の都合を混ぜないための線引きである。
    ここが `ValueError` を投げるようになったら、責務が混ざった合図。
    """
    assert run(("even", "even", "even", "even", "even"), (1, 2, 4), 1) == [2, 4]


def test_run_matches_the_uniform_literal_specialization():
    """リテラル `v` に一様具体化した版は `run(ast, xs, v)` と一致する（L269、§2.4）。

    リテラル版の検証機構がこの等式に乗っている。`k` を各opにそのまま渡していることの確認。
    """
    xs = (1, 5, 7, 12)
    assert run(("ge", "add_k"), xs, 5) == [x + 5 for x in xs if x >= 5]
