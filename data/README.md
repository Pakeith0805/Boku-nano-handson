# data/

生成物置き場。`scripts/`配下のスクリプトが書く。

直下の4ファイルは全て再現できる（`probes/behavior_probe_set_v1.jsonl`と`src/`のコードさえあれば、
seedを固定しなくても同じ内容が作れる——乱数を使うのは固定入力集合の生成だけで、AST列挙も
バインディング列挙も決定的なため）。

`teacher/`は再現の意味が弱い。教師モデルの出力なので、同じ種・同じseedでもモデルやライブラリの
版が変われば内容は変わる。だから由来を1実行ごとに記録する（`phrases_runs.jsonl`）。

**人間が入れたものはここには置かない。** 承認済み辞書も査読の判定も`phrases/`にある。
`data/`はスクリプトが書いたものだけの場所であり、消して流し直せる（`teacher/`なら
「同じものは戻らないが、同じ手順で作り直せる」）という性質をこの境界が保っている。

| ファイル | 件数 | サイズ | 作るスクリプト |
| --- | ---: | ---: | --- |
| `asts.jsonl` | 267,744 | 179MiB | `build_ast_corpus.py` |
| `manifest.json` | — | 1.3KB | `build_ast_corpus.py` |
| `bindings.jsonl` | 2,438,932 | 85MiB | `build_bindings.py` |
| `bindings_manifest.json` | — | 138B | `build_bindings.py` |
| `teacher/phrases_raw.jsonl` | 1行1候補 | — | `build_phrases.py` |
| `teacher/phrases_runs.jsonl` | 1行1実行 | — | `build_phrases.py` |
| `teacher/prompts.jsonl` | 1行1プロンプト | — | `build_phrases.py` |
| `teacher/phrases_manifest.json` | — | — | `build_phrases.py` |

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

## teacher/phrases_raw.jsonl

`build_phrases.py`が生成した言い回しの**候補**。1行1候補で、**棄却された行も理由つきで全部残す**
（どの規則がどれだけ効いたかが分かれば、プロンプトのどこを直すべきかも分かる）。

```json
{"op":"gt","round":1,"status":"accepted","reason":null,"phrase":"{k}より大きな値だけを残す","normalized":"7より大きな値だけを残す","raw":"7より大きな値だけを残す  ","run_id":"20260816T102945-45b57224","seed":20261607,"temperature":0.9,"prompt_sha256":"4c59c668...","prompt_version":"v2","registry_version":"ops24-v1","created_at":"2026-08-16T10:43:59+09:00"}
```

`phrase`が後段で使う`{k}`版の形で、採用された行にしか入らない（棄却した行は`{k}`に戻さない）。
`normalized`は具体値のままの検査対象で、重複判定と再開時の突き合わせに使う。`status`が
`rejected`のとき`reason`に`phrase_filters.check`が返した理由が入る（一覧は
`scripts/teacher/README.md`）。

**これは辞書ではない。** 機械の検査が通ったことは形式が整っていることしか意味せず、意味が
合っている保証はまったくない。承認は`review_phrases.py`が行い、結果は`phrases/`に出る。

## teacher/phrases_runs.jsonl

実行1回ぶんの由来。**再現に要るものはすべてここに書く**（1行1実行、追記）。モデルの同一性
（id・revision・量子化・バックエンド・thinkingの有無）、推論スタックの版、GPU、system prompt、
sampling設定と種の決め方、`op_seeds.yaml`の内容ハッシュ（`seeds_sha256`）、引数。
査読の状態（`phrases/phrase_decisions.jsonl`）のハッシュは**持たない**——判定はプロンプトに
展開されて`prompts.jsonl`に全文が残っており、生成の再現にはそちらで足りるためである。
開始時に一度書き、終了時に結果（`finished_at`・`produced`）を足して同じ`run_id`の行を差し替える
（途中で落ちた実行の由来も残るようにするため。`finished_at`が`null`のままなら未完了の実行）。

`phrases_manifest.json`とは役割が違う。あちらは全体の統計で実行のたびに上書きされるので、
複数回に分けて生成すると最後の実行の情報しか残らない。由来は上書きしてはいけないので分けてある。
各候補の`run_id`からこの1行が引ける。

## teacher/prompts.jsonl

実際にトークナイザへ渡したプロンプトの全文（`prompt_sha256`ごとに1行、追記）。各候補の
`prompt_sha256`はプロンプトの**同一性**しか保証しないので、中身まで復元できないと
「何を投げたら何が出たか」は結局分からない。`system_prompt`・`user_prompt`と、chat templateの
記法込みの`templated_text`（＝実際に投げたもの）を持つ。ハッシュで重複を除くため、同じ
プロンプトを何度投げても1行しか増えない。

## teacher/phrases_manifest.json

`phrases_raw.jsonl`**全体**の要約。モデル・パラメータ・op別の採用数とラウンド数・棄却理由の内訳・
目標未達のop、そして`cross_op_duplicates`（複数のopで採用された同一表現）を持つ。最後のものは
自動では落とさない——どちらを残すかは意味の判断なので、承認作業への申し送りとして出す。
**実行のたびに上書きされる**ので、由来を辿るときは`phrases_runs.jsonl`のほうを見ること。

## ここに無いもの

査読の判定（`phrases/phrase_decisions.jsonl`）と承認済み辞書（`phrases/ja_phrases_v1.yaml`）は
人間が入れたものなので`phrases/`にある。`build_phrases.py`が判定を読み返すため入力としても
使われるが、置き場所は「誰が書いたか」で決めている——入力だから`data/`に置く、とはしない
（`op_seeds.yaml`が`scripts/`にあるのと同じ）。

## 追跡しないファイル

`.gitignore`で`asts.jsonl`を除外している（179MiBで、GitHubの1ファイル100MBの上限を超えるため）。
`bindings.jsonl`（85MiB）は上限内だが警告閾値（50MB）は超えているので、リポジトリを軽く保ちたい
なら合わせて除外する選択肢もある。直下の4ファイルは`probes/behavior_probe_set_v1.jsonl`
（凍結済み固定入力集合）と`src/`のコードから再生成できるため、追跡しなくても再現性は失われない。

`teacher/`は追跡しておくほうがよい。同じ手順で作り直せはするが、教師モデルの出力なので
**同じ内容は戻らない**。消すと、承認済み辞書の各表現がどの生成から出たのか（判定の`origin`が
指す先）が辿れなくなる。
