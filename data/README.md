# data/

生成物置き場。全て`scripts/`配下のスクリプトから再現できる（`probes/behavior_probe_set_v1.jsonl`
と`src/`のコードさえあれば、seedを固定しなくても同じ内容が作れる——乱数を使うのは固定入力集合
の生成だけで、AST列挙もバインディング列挙も決定的なため）。

| ファイル | 件数 | サイズ | 作るスクリプト |
| --- | ---: | ---: | --- |
| `asts.jsonl` | 267,744 | 179MiB | `build_ast_corpus.py` |
| `manifest.json` | — | 1.3KB | `build_ast_corpus.py` |
| `bindings.jsonl` | 2,438,932 | 85MiB | `build_bindings.py` |
| `bindings_manifest.json` | — | 138B | `build_bindings.py` |

## asts.jsonl

意味ASTコーパス本体。difficulty 1〜4の意味AST**全267,744件**（参照台帳、層化サンプリングなし）
を1行1レコードで持つ。フィールドは`src/semantics/schema.json`が定義する。

```json
{"ast_id":"ast-000008","semantic_ast":["ge"],"difficulty":1,"categories":["filter"],"op_set":["ge"],"canonical_order":true,"binding_slots":[{"index":0,"op":"ge","literal_domain":[2,3,4,5,6,7,8,9,10]}],"uses_k":true,"semantic_hash":"...","behavior_hash":"...","always_empty":false,"is_identity":false,"source":"rule","created_at":"...","generator_version":"v0.1","schema_version":1,"registry_version":"ops24-v1","probe_set_version":"v1"}
```

`binding`（`k`をどう具体化するか）はここには**含まれない**。意味ASTは定数を持たない
（op列だけ）という設計のため。それを持つのは`bindings.jsonl`。

## manifest.json

`asts.jsonl`を作った1回分の要約。由来（`created_at`・各version）、difficulty別件数、
op出現頻度、カテゴリ頻度、`canonical_order`比率、`behavior_hash`の衝突統計
（異なり数・衝突グループ数・最大グループ長）、`always_empty`/`is_identity`件数、
出力値の絶対値の最大桁数を持つ。レコードから機械的に集計できる値のみで、`asts.jsonl`と
食い違うことはない。

## bindings.jsonl

`asts.jsonl`の各レコードに対して、`k`をどう具体化するか（バインディング）を列挙したもの。
1行が`{"ast_id": "ast-000008", "binding": 5}`の形（`binding`は`k`に具体化する整数、または
`null`＝パラメータ版）。`semantic_ast`本体は持たないので、使うときは`ast_id`で`asts.jsonl`と
突き合わせる。

- `binding: null` — パラメータ版（`k`は`k`のまま）。**全ASTに必ず1つ存在する**
  （267,744件ちょうど）
- `binding: <int>` — リテラル版（`k`をその値に固定）。`k`参照opを持つASTだけに存在し、
  件数は`uniform_literal_domain`（各`k`参照スロットの値域の共通部分）のサイズ分

`conf/binding.yaml`の`binding.include_literal`（既定`true`）でリテラル版を作るかを切り替えられる。
`false`にすると全ASTがパラメータ版1件だけになり、`asts.jsonl`と同じ267,744件に縮む。

## bindings_manifest.json

`bindings.jsonl`を作った1回分の要約。対象AST数、`include_literal`の設定値、バインディング総数、
パラメータ版/リテラル版それぞれの件数を持つ。

## 追跡しないファイル

`.gitignore`で`asts.jsonl`を除外している（179MiBで、GitHubの1ファイル100MBの上限を超えるため）。
`bindings.jsonl`（85MiB）は上限内だが警告閾値（50MB）は超えているので、リポジトリを軽く保ちたい
なら合わせて除外する選択肢もある。どのファイルも`probes/behavior_probe_set_v1.jsonl`
（凍結済み固定入力集合）と`src/`のコードから再生成できるため、追跡しなくても再現性は失われない。
