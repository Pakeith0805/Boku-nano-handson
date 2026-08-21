"""`run()` と各opが呼び出し元の入力を変更しないこと（`interp.py` L253-255、実装計画 §5）。

`run` は `xs` を複製してから使い、各opも新しいリストを返す。複製は二重の保険にあたるが、
**関数の契約として明示されている**以上、契約のほうを固定する。

破れると被害が静かに広がる。コーパス構築は1つの固定入力集合を267,744件のASTすべてに
使い回すので（`corpus.py` の `build_records`）、どこか1つのopが入力を書き換えると
以降の全レコードの `behavior_hash` が汚染され、しかもハッシュどうしは整合したままになる。
"""

import pytest

from src.interp.interp import OP_IMPLS, run
from src.semantics.registry import OP_NAMES

# 並べ替えが破壊的に実装されていたら（`sorted` ではなく `list.sort`）真っ先に壊れる形。
SAMPLE = [5, 1, 9, 3, -2, 0, 7]


@pytest.mark.parametrize("name", sorted(OP_NAMES))
def test_op_does_not_mutate_its_input_list(name):
    """各opはリストで渡された入力を書き換えない。"""
    xs = list(SAMPLE)
    OP_IMPLS[name](xs, 3)
    assert xs == SAMPLE


@pytest.mark.parametrize("name", sorted(OP_NAMES))
def test_op_returns_a_new_list(name):
    """返り値は入力そのものではない別のリストである。

    `list(xs)` を返さず `xs` をそのまま返す実装だと、呼び出し側が結果を書き換えたときに
    入力まで変わる。同値であることと同一であることは違う。
    """
    xs = list(SAMPLE)
    assert OP_IMPLS[name](xs, 3) is not xs


def test_run_does_not_mutate_its_input_list():
    """`run` に渡したリストは変更されない。"""
    xs = list(SAMPLE)
    run(("asc", "double", "take_first"), xs, 3)
    assert xs == SAMPLE


def test_run_returns_a_copy_even_for_the_empty_ast():
    """空列（恒等）でも複製を返す。呼び出し元と結果が同じ物を指してはいけない。"""
    xs = list(SAMPLE)
    result = run((), xs, 1)
    assert result == SAMPLE
    assert result is not xs

    result.append(999)
    assert xs == SAMPLE


def test_run_accepts_a_tuple_without_complaint():
    """入力はタプルでもよい（固定入力集合は `xs` をタプルで持つ）。

    型注釈は `Sequence[int]` であり、`corpus.py` は `ProbeInput`（`tuple`）を渡す。
    リストを前提にした実装（`xs.sort()` など）に変わっていたらここで落ちる。
    """
    assert run(("asc",), (3, 1, 2), 1) == [1, 2, 3]
