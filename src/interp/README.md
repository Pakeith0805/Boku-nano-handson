# src/interp/

参照インタプリタ。「各opが何を計算するか」の**唯一の権威**。`src/semantics/registry.py`は
op名・カテゴリ・値域といったメタデータだけを持ち、実際の計算はすべてここに書く。

## interp.py

### 24個のop実装

いずれも `(xs: Sequence[int], k: int) -> list[int]` というシグネチャ（`OpImpl`型）。

**抽出（10種類）**

| 関数 | 説明 |
| --- | --- |
| `op_even(xs, k)` | 偶数だけを残す。`k`は使わない |
| `op_odd(xs, k)` | 奇数だけを残す。`k`は使わない |
| `op_gt(xs, k)` | `k`より大きい値を残す |
| `op_ge(xs, k)` | `k`以上の値を残す |
| `op_lt(xs, k)` | `k`より小さい値を残す |
| `op_le(xs, k)` | `k`以下の値を残す |
| `op_multiple_of(xs, k)` | `k`の倍数だけを残す |
| `op_positive(xs, k)` | 正の要素を残す。ゼロは含まない。`k`は使わない |
| `op_negative(xs, k)` | 負の要素を残す。ゼロは含まない。`k`は使わない |
| `op_zero(xs, k)` | ゼロの要素を残す。`k`は使わない |

**変換（8種類）**

| 関数 | 説明 |
| --- | --- |
| `op_add_k(xs, k)` | 各要素に`k`を加える |
| `op_sub_k(xs, k)` | 各要素から`k`を引く |
| `op_mul_k(xs, k)` | 各要素に`k`を掛ける |
| `op_double(xs, k)` | 各要素を2倍する。`k`は使わない |
| `op_triple(xs, k)` | 各要素を3倍する。`k`は使わない |
| `op_negate(xs, k)` | 符号を反転する。`k`は使わない |
| `op_abs(xs, k)` | 絶対値を取る。`k`は使わない |
| `op_square(xs, k)` | 二乗する。`k`は使わない |

**並べ替え（3種類）**

| 関数 | 説明 |
| --- | --- |
| `op_asc(xs, k)` | 昇順に並べる。`k`は使わない |
| `op_desc(xs, k)` | 降順に並べる。`k`は使わない |
| `op_reverse(xs, k)` | 現在の並びを逆にする（`op_desc`とは別物、並べ替えではない）。`k`は使わない |

**切り出し（3種類）**

| 関数 | 説明 |
| --- | --- |
| `op_take_first(xs, k)` | 先頭から`k`個。`k > len(xs)`なら全リストを返す |
| `op_take_last(xs, k)` | 末尾から`k`個。`k > len(xs)`なら全リストを返す |
| `op_every_other(xs, k)` | 1個おきに取得する（`xs[::2]`、先頭から）。`k`は使わない |

### `OP_IMPLS: dict[str, OpImpl]`

op名から実装関数への対応。`src.semantics.registry.OP_REGISTRY`とキー集合が一致していなければならない。

### `run(ast, xs, k) -> list[int]`

意味AST（op名の列）を入力`(xs, k)`に適用した結果を返す。操作は列の順に適用する（順序は意味を持つ）。
`xs`を複製してから使うため呼び出し元のリストは変更しない。

- `k`が1〜10の範囲外なら`ValueError`
- `ast`に未知のop名が含まれていれば`KeyError`
- 構造検証（操作数や重複opのチェック）はここでは行わない
