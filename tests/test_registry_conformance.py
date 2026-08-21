"""レジストリと参照インタプリタの同期（`registry.py` L14-17、`interp.py` L239-243）。

**検査するのは「存在と形式」だけである。** 「`op_even` が本当に偶数を残すか」は見ない。
意味の検査は `test_interp_ops.py` の担当であり、役割を混ぜないこと。

レジストリに意味を持たせない設計（改訂版 L281-286）のせいで、op名の一覧は
`OP_REGISTRY` と `OP_IMPLS` の2箇所に書かれている。その二重化を照合するのがこのファイルで、
ここが無いとレジストリと実装は黙って食い違える。
"""

import pytest

from src.interp.interp import OP_IMPLS
from src.semantics.registry import (
    CATEGORY_ORDER,
    LITERAL_MAX,
    LITERAL_MIN,
    MAX_OPS,
    N_OPS,
    OP_NAMES,
    OP_REGISTRY,
)

# 改訂版 L115-157 の表の内訳。カテゴリごとの個数を直接書いて、
# opの取りこぼしと入れ違いを両方捕まえる。
EXPECTED_CATEGORY_COUNTS = {"filter": 10, "map": 8, "order": 3, "slice": 3}


def test_registry_and_interpreter_have_the_same_ops():
    """キー集合の一致。**レジストリと参照インタプリタを同期させる唯一の仕掛け**。

    レジストリにあって実装が無いとコーパス構築が `KeyError` で落ちるが、逆向き
    （実装にあってレジストリに無い）は**何も起きずにopが1つ欠落する**。後者を捕まえる
    ためにも、片側の包含ではなく集合の一致で見る。
    """
    assert set(OP_REGISTRY) == set(OP_IMPLS)


def test_op_count_is_24():
    """改訂版 L111 の24。意味AST空間の基数になる。"""
    assert N_OPS == len(OP_REGISTRY) == len(OP_IMPLS) == 24


def test_max_ops_is_4():
    """改訂版 L111「1〜4個」。

    下げると意味AST空間が縮み、L397 の目標件数 30,000〜100,000 に届かなくなる
    （3 なら 12,720 種類しかない）。
    """
    assert MAX_OPS == 4


def test_op_names_is_the_sorted_registry():
    """`OP_NAMES` は列挙の添字づけの基準なので、辞書順で安定していなければならない。

    並びが変わると同じ `i` が別のASTを指す。`OP_REGISTRY` の記述順（改訂版の表順）を
    後から編集しても添字が動かないよう、辞書順に正規化してある。
    """
    assert OP_NAMES == tuple(sorted(OP_REGISTRY))
    assert list(OP_NAMES) == sorted(OP_NAMES)


@pytest.mark.parametrize("name", sorted(OP_REGISTRY))
def test_spec_name_matches_its_key(name):
    """辞書のキーと `OpSpec.name` の一致。写し間違いを捕まえる。"""
    assert OP_REGISTRY[name].name == name


@pytest.mark.parametrize("name", sorted(OP_REGISTRY))
def test_uses_k_agrees_with_literal_domain(name):
    """`uses_k` と `literal_domain` の有無の一致（`registry.py` L77-79）。

    二つを**独立に手で書いている**ので、この照合が成立する（片方から導出すると常に真に
    なって検査にならない）。ズレると `binding_slots` はスロットを作るのに値域が空になり、
    そのopのリテラル版が静かに消える。
    """
    spec = OP_REGISTRY[name]
    assert spec.uses_k == bool(spec.literal_domain), (
        f"{name}: uses_k={spec.uses_k} なのに literal_domain={spec.literal_domain}"
    )


@pytest.mark.parametrize("name", sorted(OP_REGISTRY))
def test_literal_domain_is_a_sorted_subset_of_the_allowed_range(name):
    """値域は昇順・重複なしで、`LITERAL_MIN`〜`LITERAL_MAX` に収まる。

    値そのもの（どこを除外したか）は `test_literal_domains.py` が見る。ここは形式だけ。
    """
    domain = OP_REGISTRY[name].literal_domain
    assert list(domain) == sorted(set(domain))
    assert all(LITERAL_MIN <= v <= LITERAL_MAX for v in domain)


@pytest.mark.parametrize("name", sorted(OP_REGISTRY))
def test_category_is_known(name):
    """カテゴリは `CATEGORY_ORDER` の4種類のいずれか。

    未知の値が入ると `canonical_order` の判定（`CATEGORY_ORDER.index`）が `ValueError` で
    落ちる。列挙時ではなくここで気づけるようにする。
    """
    assert OP_REGISTRY[name].category in CATEGORY_ORDER


def test_category_counts_match_the_specification():
    """カテゴリ別の個数が改訂版 L115-157 の表と一致する。"""
    counts: dict[str, int] = {}
    for spec in OP_REGISTRY.values():
        counts[spec.category] = counts.get(spec.category, 0) + 1
    assert counts == EXPECTED_CATEGORY_COUNTS


def test_ja_keys_are_unique_and_non_empty():
    """日本語表現辞書の引き当てキーは一意でなければならない。

    現状すべて `name` と同じ値だが、**一致は要求しない**——別フィールドとして持つ目的が
    「op名の変更で辞書の引き当てが壊れないよう名前空間を分ける」ことなので、
    等しさを固定すると分離した意味が消える。要るのは一意性のほうである。
    """
    keys = [spec.ja_key for spec in OP_REGISTRY.values()]
    assert all(keys)
    assert len(set(keys)) == len(keys)


@pytest.mark.parametrize("name", sorted(OP_REGISTRY))
def test_shadows_reference_real_ops(name):
    """`shadows` に挙げた相手は実在するop名で、自分自身ではない。

    衝突が本当に起きるか（`ge@1` が `positive` と一致するか）は振る舞いの話なので
    `test_literal_domains.py` の担当。
    """
    spec = OP_REGISTRY[name]
    for other in spec.shadows:
        assert other in OP_REGISTRY, f"{name}.shadows に未知のop: {other}"
        assert other != name


@pytest.mark.parametrize("name", sorted(OP_IMPLS))
def test_impl_is_callable_with_the_op_signature(name):
    """実装は `(xs, k) -> list[int]` として呼べる。**中身の正しさは見ない。**"""
    result = OP_IMPLS[name]((1, 2, 3), 1)
    assert isinstance(result, list)
    assert all(isinstance(v, int) for v in result)
