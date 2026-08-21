"""入力条件そのものと、リテラル値域との一致（`src/limits.py` L29-30）。

`limits.py` は「どんな入力が来るか」、`registry.py` は「どんな操作があるか」を持つ別々の
モジュールだが、`k` の値域とリテラルの値域だけは**同一でなければならない**。同一性は
どちらのファイルにも文章で書かれているだけなので、ここで機械的に固定する。
"""

import pytest

from src.interp.interp import run
from src.limits import (
    ELEM_MAX,
    ELEM_MIN,
    K_MAX,
    K_MIN,
    XS_LEN_MAX,
    XS_LEN_MIN,
)
from src.semantics.registry import LITERAL_MAX, LITERAL_MIN


def test_literal_domain_equals_k_domain():
    """リテラルの値域は `k` の値域と一致する（改訂版 L269）。

    一致していないと、リテラル版のコードを参照インタプリタで検証できなくなる。
    リテラル `v` に固定したコードの正しさは「`run(ast, xs, v)` と一致するか」で判定するが、
    `run` は `k` が L104 の範囲外なら `ValueError` を投げるためである。
    """
    assert (LITERAL_MIN, LITERAL_MAX) == (K_MIN, K_MAX)


def test_limits_match_the_specification():
    """課題文（改訂版 L102-104）が定める値そのもの。

    ここを変えるということは課題の前提を変えるということなので、黙って動かせないよう
    数値を直接書いて固定する。
    """
    assert (XS_LEN_MIN, XS_LEN_MAX) == (0, 20)
    assert (ELEM_MIN, ELEM_MAX) == (-100, 100)
    assert (K_MIN, K_MAX) == (1, 10)


def test_empty_list_is_a_valid_input():
    """`xs` の長さの下限が0であること（L102）。空リストは正当な入力である。

    境界値テストの必須項目（L514）であり、固定入力集合の先頭2件もこれに当たる。
    """
    assert XS_LEN_MIN == 0
    assert run(("even",), (), K_MIN) == []


@pytest.mark.parametrize("k", [K_MIN - 1, 0, -1, K_MAX + 1, 100])
def test_run_rejects_k_outside_the_domain(k):
    """`k` が値域の外なら `ValueError`（L104）。

    リテラル版の検証がこの関数に乗っている以上、値域外を黙って受け付けてはならない。
    """
    with pytest.raises(ValueError):
        run((), (1, 2, 3), k)


def test_k_lower_bound_is_what_two_ops_depend_on():
    """`K_MIN == 1` に二つの実装が依存している（実装計画 §6）。

    `multiple_of` のゼロ除算と、`take_last` の `xs[-k:]` が `k == 0` で全リストを返す罠。
    どちらも op 側で assert しているので、前提が崩れたことをここでも固定しておく。
    """
    assert K_MIN == 1

    from src.interp.interp import op_multiple_of, op_take_last

    with pytest.raises(AssertionError):
        op_multiple_of((1, 2, 3), 0)
    with pytest.raises(AssertionError):
        op_take_last((1, 2, 3), 0)
