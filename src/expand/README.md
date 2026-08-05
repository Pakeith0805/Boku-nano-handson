# src/expand/

意味ASTごとの「バインディング」（`k`を参照するopの具体化）を列挙する。ASTそのものの構造
（`src/semantics/`）や実際の計算（`src/interp/`）には触れず、「1つのASTから何通りの実体化を
作るか」だけを扱う。

## binding.py

`k`を参照するopを持つ意味ASTは、全スロットを`k`のまま残す**パラメータ版**（`None`）か、
全スロットを同一の値に固定する**リテラル版**（`int`）のどちらかでしか実体化できない。
スロットごとに違う値を入れる混在は型（`Binding = int | None`）として表現できないようにしてある。
opに焼き付いた定数（`double`の`2`など）は`k`と無関係なので、そもそもバインディングの対象に
ならない（`binding_slots`が0個のop）。

### 型

| 名前 | 説明 |
| --- | --- |
| `Binding` | `k`の具体化を表す型エイリアス（`int \| None`）。`None`＝パラメータ版、`int`＝その値に固定したリテラル版 |

### 関数

| 関数 | 説明 |
| --- | --- |
| `uniform_literal_domain(binding_slots)` | 全スロットを同一の値に具体化できるリテラルの集合（各スロットの`literal_domain`の共通部分）をソート済みタプルで返す。スロットが無ければ空タプル |
| `enumerate_bindings(binding_slots, include_literal)` | 1つの意味ASTに対して作るバインディングの一覧。パラメータ版（`None`）は常に含み、`include_literal`が`True`かつ`k`参照opがあれば`uniform_literal_domain`の各値をリテラル版として追加する |

`binding_slots`はどちらの関数も`SemanticAST.to_dict()`/コーパスレコードの`binding_slots`と
同じ形（各要素が`{"index":..., "op":..., "literal_domain":[...]}`の辞書）を受け取る。
