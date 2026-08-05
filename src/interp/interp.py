"""意味ASTの評価。

`run(ast, xs, k)` が意味ASTを左から順に適用する。これが正解の定義であり、
`behavior_hash`も生成コードの検証（改訂版 L352）もこの出力を基準にする。
"""

from collections.abc import Callable, Sequence

from src.limits import K_MAX, K_MIN

OpImpl = Callable[[Sequence[int], int], list[int]]
"""op の実装の型。全opがこのシグネチャに従う。"""


# ---- 抽出（改訂版 L115-128、10種類）----


def op_even(xs: Sequence[int], k: int) -> list[int]:
    """偶数だけを残す（L119）。`k` は使わない。

    `x % 2 == 0` は負数でも正しい。Pythonの `%` は正の除数に対して非負を返すため
    `-2 % 2 == 0` になる。
    """
    return [x for x in xs if x % 2 == 0]


def op_odd(xs: Sequence[int], k: int) -> list[int]:
    """奇数だけを残す（L120）。`k` は使わない。

    `!= 0` を正規形とする（実装計画 §6）。Pythonでは `x % 2 == 1` でも
    L103 の −100〜100 の全整数で同じ結果になる（`-3 % 2 == 1`）。
    `== 1` が負数で崩れるのはC/Javaの挙動であってPythonには当てはまらないが、
    意図が明確な `!= 0` に統一する。
    """
    return [x for x in xs if x % 2 != 0]


def op_gt(xs: Sequence[int], k: int) -> list[int]:
    """`k`より大きい値を残す（L121）。"""
    return [x for x in xs if x > k]


def op_ge(xs: Sequence[int], k: int) -> list[int]:
    """`k`以上の値を残す（L122）。

    `op_gt` との違いは `k` に等しい要素を含むかどうかだけである。固定入力集合は
    この差を分離できなければならない（実装計画 §2.5 の識別力の要件）。
    """
    return [x for x in xs if x >= k]


def op_lt(xs: Sequence[int], k: int) -> list[int]:
    """`k`より小さい値を残す（L123）。

    `k == 1` のとき `x < 1` はゼロを含むため、`op_negative`（`x < 0`）とは異なる。
    この差があるのでリテラル @1 は除外していない（L277）。
    """
    return [x for x in xs if x < k]


def op_le(xs: Sequence[int], k: int) -> list[int]:
    """`k`以下の値を残す（L124）。"""
    return [x for x in xs if x <= k]


def op_multiple_of(xs: Sequence[int], k: int) -> list[int]:
    """`k`の倍数だけを残す（L125）。

    `k >= 1`（L104）なのでゼロ除算は起きないが、前提が崩れたら気づけるよう assert する
    （実装計画 §6）。負数でも `-3 % 3 == 0` となり正しく判定できる。
    ゼロは常に倍数に含まれる（`0 % k == 0`）。
    """
    assert k >= K_MIN, f"multiple_of は k >= {K_MIN} を前提とする（L104）: k={k}"
    return [x for x in xs if x % k == 0]


def op_positive(xs: Sequence[int], k: int) -> list[int]:
    """正の要素を残す（L126）。`k` は使わない。ゼロは含まない。"""
    return [x for x in xs if x > 0]


def op_negative(xs: Sequence[int], k: int) -> list[int]:
    """負の要素を残す（L127）。`k` は使わない。ゼロは含まない。"""
    return [x for x in xs if x < 0]


def op_zero(xs: Sequence[int], k: int) -> list[int]:
    """ゼロの要素を残す（L128）。`k` は使わない。"""
    return [x for x in xs if x == 0]


# ---- 変換（改訂版 L130-141、8種類）----


def op_add_k(xs: Sequence[int], k: int) -> list[int]:
    """各要素に`k`を加える（L134）。"""
    return [x + k for x in xs]


def op_sub_k(xs: Sequence[int], k: int) -> list[int]:
    """各要素から`k`を引く（L135）。"""
    return [x - k for x in xs]


def op_mul_k(xs: Sequence[int], k: int) -> list[int]:
    """各要素に`k`を掛ける（L136）。

    出力は L103 の −100〜100 を超えてよい（L105）。クリップしない。
    """
    return [x * k for x in xs]


def op_double(xs: Sequence[int], k: int) -> list[int]:
    """各要素を2倍する（L137）。`k` は使わない。"""
    return [x * 2 for x in xs]


def op_triple(xs: Sequence[int], k: int) -> list[int]:
    """各要素を3倍する（L138）。`k` は使わない。"""
    return [x * 3 for x in xs]


def op_negate(xs: Sequence[int], k: int) -> list[int]:
    """符号を反転する（L139）。`k` は使わない。ゼロは変わらない。"""
    return [-x for x in xs]


def op_abs(xs: Sequence[int], k: int) -> list[int]:
    """絶対値を取る（L140）。`k` は使わない。

    直前が `square` だとこの操作は恒等になる（L534）。**ここでは特別扱いしない。**
    縮退の検出は `behavior_hash` の仕事である（実装計画 §2.7）。
    """
    return [abs(x) for x in xs]


def op_square(xs: Sequence[int], k: int) -> list[int]:
    """二乗する（L141）。`k` は使わない。

    `x * x` と書く。出力は常に非負であり、L103 の範囲を大きく超え得る（L105）。
    """
    return [x * x for x in xs]


# ---- 並べ替え（改訂版 L143-149、3種類）----


def op_asc(xs: Sequence[int], k: int) -> list[int]:
    """昇順に並べる（L147）。`k` は使わない。"""
    return sorted(xs)


def op_desc(xs: Sequence[int], k: int) -> list[int]:
    """降順に並べる（L148）。`k` は使わない。

    `op_reverse`（並びを逆にするだけ）とは別物であり、潰さない（実装計画 §6）。
    `[asc, reverse]` と振る舞いは同一になるが、それは操作列レベルの縮退なので
    `behavior_hash` が拾う（実装計画 §2.6）。
    """
    return sorted(xs, reverse=True)


def op_reverse(xs: Sequence[int], k: int) -> list[int]:
    """逆順にする（L149）。`k` は使わない。

    並べ替えではなく、**現在の並びを逆にするだけ**である。`op_desc` と混同しないこと
    （実装計画 §6）。
    """
    return list(xs[::-1])


# ---- 切り出し（改訂版 L151-157、3種類）----


def op_take_first(xs: Sequence[int], k: int) -> list[int]:
    """先頭から`k`個（L155）。

    `k > len(xs)` のときは全リストを返す（Pythonスライス準拠、実装計画 §6）。
    切り詰めもエラーもしない。
    """
    return list(xs[:k])


def op_take_last(xs: Sequence[int], k: int) -> list[int]:
    """末尾から`k`個（L156）。

    `xs[-k:]` は **`k == 0` のとき全リストを返す**（`xs[-0:]` は `xs[0:]` と同じ）。
    L104 により `k >= 1` なのでこの罠は踏まないが、前提が崩れたら気づけるよう
    assert する（実装計画 §6）。

    `k > len(xs)` のときは全リストを返す（Pythonスライス準拠）。
    """
    assert k >= K_MIN, f"take_last は k >= {K_MIN} を前提とする（L104）: k={k}"
    return list(xs[-k:])


def op_every_other(xs: Sequence[int], k: int) -> list[int]:
    """1個おきに取得する（L157）。`k` は使わない。

    **「1個おき」の曖昧性を `xs[::2]`（先頭から、添字が偶数の要素）に確定する**
    （実装計画 §6）。`xs[1::2]`（2番目から）ではない。
    要素が1個なら、その1個を返す。
    """
    return list(xs[::2])


OP_IMPLS: dict[str, OpImpl] = {
    # 抽出（10）
    "even": op_even,
    "odd": op_odd,
    "gt": op_gt,
    "ge": op_ge,
    "lt": op_lt,
    "le": op_le,
    "multiple_of": op_multiple_of,
    "positive": op_positive,
    "negative": op_negative,
    "zero": op_zero,
    # 変換（8）
    "add_k": op_add_k,
    "sub_k": op_sub_k,
    "mul_k": op_mul_k,
    "double": op_double,
    "triple": op_triple,
    "negate": op_negate,
    "abs": op_abs,
    "square": op_square,
    # 並べ替え（3）
    "asc": op_asc,
    "desc": op_desc,
    "reverse": op_reverse,
    # 切り出し（3）
    "take_first": op_take_first,
    "take_last": op_take_last,
    "every_other": op_every_other,
}
"""op名から実装への対応。

`boku.semantics.registry.OP_REGISTRY` とキー集合が一致しなければならない。それを検査するのが
`tests/test_registry_conformance.py` であり、レジストリと参照インタプリタを同期させる唯一の
仕掛けである。ただし検査するのは**存在と形式だけ**で、意味が合っているかは見ない
（実装計画 §2.8）。意味の検査は `tests/test_interp_ops.py` の担当。
"""



def run(ast: Sequence[str], xs: Sequence[int], k: int) -> list[int]:
    """意味AST `ast` を入力 `(xs, k)` に適用した結果を返す。

    操作は**列の順に**適用する。順序は意味を持つ（改訂版 L297-302）。
    `[asc, take_first]` と `[take_first, asc]` は別の関数である。

    引数 `xs` は複製してから使うため、**呼び出し元のリストは変更されない**
    （実装計画 §5、`tests/test_no_mutation.py`）。各opも新しいリストを返すので
    複製は二重の保険にあたるが、この関数の契約として明示しておく。

    `k` は各opにそのまま渡す。ASTは定数を持たないため（改訂版 L256）、
    `k` を解決する処理は要らない（実装計画 §5）。

    リテラルに具体化したコードの検証にもこの関数を使う。リテラル `v` に一様具体化した版は
    `run(ast, xs, v)` と一致する（L269、実装計画 §2.4 の一様具体化の制約）。

    Args:
        ast: op名の列。空列を渡すと恒等（`xs` の複製）を返す。
        xs: 入力リスト。長さは L102 の 0〜20、要素は L103 の −100〜100 を想定する。
        k: L104 の 1〜10 の整数。

    Returns:
        評価結果の新しいリスト。要素は L103 の範囲を超えてよい（L105）。

    Raises:
        ValueError: `k` が L104 の範囲外のとき。
        KeyError: `ast` に未知のop名が含まれるとき。

    Note:
        **構造検証はここでは行わない。** 操作数が 1〜`MAX_OPS` か、同一opの重複がないかは
        `boku.semantics.validate` の担当である（実装計画 §2.7）。この関数は「渡された列を
        順に適用する」ことだけに責任を持つ。役割を混ぜると、権威である評価器に検証の都合が
        混ざる。
    """
    if not (K_MIN <= k <= K_MAX):
        raise ValueError(f"k は {K_MIN}〜{K_MAX} の整数（改訂版 L104）: k={k}")

    current = list(xs)
    for op_name in ast:
        impl = OP_IMPLS.get(op_name)
        if impl is None:
            raise KeyError(f"未知のop名: {op_name!r}")
        current = impl(current, k)
    return current
