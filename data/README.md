# data/ — 生成物と来歴

データ生成スクリプトの出力を置きます。承認済み辞書と人間の査読判定は `phrases/`、凍結した固定入力は `probes/`、訓練結果は `runs/` です。このREADMEやDataset Cardは生成物を説明する文書です。

## ファイル一覧

件数・サイズは2026-09-22に手元のファイルを確認した値です。再生成時の設定や入力によって変わります。

| ファイル | 件数・規模 | 作るスクリプト |
| --- | --- | --- |
| `asts.jsonl` | 267,744 AST | `build_ast_corpus.py` |
| `manifest.json` | AST台帳の統計・時刻・版 | 同上 |
| `bindings.jsonl` | 2,438,932候補 | `build_bindings.py` |
| `bindings_manifest.json` | パラメータ267,744件、リテラル2,171,188件 | 同上 |
| `teacher/phrases_raw.jsonl` | 1行1候補（棄却分を含む） | `build_phrases.py` |
| `teacher/phrases_runs.jsonl` | 1行1生成run | 同上 |
| `teacher/prompts.jsonl` | 1行1プロンプトハッシュ | 同上 |
| `teacher/phrases_manifest.json` | 候補全体の集計 | 同上 |
| `dataset/train.jsonl` | 820,763行、約1.09 GiB | `build_dataset.py` |
| `dataset/val.jsonl` | 95,164行、約132 MiB | 同上 |
| `dataset/test.jsonl` | 94,720行、約131 MiB | 同上 |
| `dataset/test_combination.jsonl` | 30行 | 同上 |
| `dataset/test_paraphrase.jsonl` | 30行 | 同上 |
| `tokenizer/tokenizer.json` | 実語彙1,256、約83 KiB | `build_tokenizer.py` |
| `tokenizer/tokenizer_visualization.json` | 約214 KiB | `visualize_tokenizer.py` |

## asts.jsonl / manifest.json

ASTは定数を持たない操作名の列です。24操作から重複なく1〜4個を選び、順序も区別した全数を保存します。1行の形式は [src/semantics/schema.json](../src/semantics/schema.json) です。

| 情報 | 主なフィールド |
| --- | --- |
| 操作列から導出 | `semantic_ast`, `difficulty`, `categories`, `op_set`, `canonical_order`, `binding_slots`, `uses_k` |
| 指紋・有限入力上の特徴 | `semantic_hash`, `behavior_hash`, `always_empty`, `is_identity` |
| 採番・由来 | `ast_id`, `source`, `created_at`, `generator_version`, `schema_version`, `registry_version`, `probe_set_version` |

`semantic_hash` は操作列だけから計算します。`behavior_hash` と退化フラグには固定入力全件での参照出力を使います。`manifest.json` は難易度別件数・操作頻度・衝突統計などを集計し、出力の最大桁数は実行結果から計算します。すべてがレコードだけから再計算できるわけではありません。

同じコードと凍結入力を使えば列挙順・ID・ハッシュは再現できます。`created_at` は実行時刻なので、ファイル全体のバイト一致はしません。

## bindings.jsonl / bindings_manifest.json

```json
{"ast_id":"ast-000008","binding":5}
```

`binding=null` は全スロットで `k` を引数のまま使う候補で、全ASTに1件あります。整数なら `k` を参照する全スロットを同じ値で具体化する候補です。許される値は各スロットの値域の共通部分です。

`conf/binding.yaml` の `binding.include_literal=false` でパラメータ候補だけにできます。manifestは対象AST数・設定・候補数の内訳で、版や時刻は持ちません。現在の `build_dataset.py` はこれらを入力に使いません。

## teacher/phrases_raw.jsonl

形式検査を通った候補も落ちた候補も残します。`accepted` は機械的な形式検査の結果であり、人間の承認ではありません。

| フィールド | 意味 |
| --- | --- |
| `op`, `round` | 操作と生成ラウンド |
| `status`, `reason` | `accepted` / `rejected` と棄却理由 |
| `phrase` | 採用候補の `{k}` 版。棄却なら `null` |
| `normalized`, `raw` | 正規化後の具体値版と、モデルの元の1行 |
| `run_id`, `seed`, `temperature` | 生成runと各呼び出しの条件 |
| `prompt_sha256` | 実際に渡したプロンプト全文のハッシュ |
| `prompt_version`, `registry_version`, `created_at` | 種・レジストリの版と生成時刻 |

## teacher/phrases_runs.jsonl

モデルID・固定revision・量子化・バックエンド・thinking設定、ライブラリ版、GPU、sampling条件、CLI引数、種のハッシュをrun単位で記録します。開始時の `finished_at` は `null`、終了時は同じ `run_id` の行を更新し、終了時刻と生成件数を加えます。

再現条件を辿るには、この記録に加えてプロンプト全文と対応するコード・依存環境が必要です。seedだけで異なる環境の出力まで同一になる保証はありません。

## teacher/prompts.jsonl

`prompt_sha256` ごとに `system_prompt`, `user_prompt`, `templated_text` を保存します。最後がchat template適用後の全文で、ハッシュの入力です。同じハッシュは1回だけ記録し、`run_id` / `op` / `round` はそのプロンプトを最初に記録した呼び出しを指します。

## teacher/phrases_manifest.json

候補全体の件数、op別の機械採用数とラウンド数、棄却理由、目標未達、op間の重複表現を集計し、実行終了時に上書きします。過去runの実行条件を復元するファイルではありません。

現行コードでは `params.n_per_request` と `params.target` は定数値なので、CLIで変更した実際の値は `phrases_runs.jsonl` の `sampling.n_per_request` / `args.target` を参照します。

## dataset/

[Dataset Card](dataset/README.md) に最終レコードの形式と選抜・分割の制約をまとめています。組合せ・言い換えテストは上限30件ずつです。境界値専用のJSONLはなく、評価時に同じ生成コードを固定入力の境界値20件でも判定します。

再生成にはコード、AST台帳、凍結入力、承認済み辞書と由来対応表、seed、ワーカー数が必要です。ワーカー数を変えると乱数列と採用数の集計単位も変わります。

## tokenizer/

| ファイル | 内容 |
| --- | --- |
| `tokenizer.json` | 現行v2。訓練・評価が読むトークナイザ |
| `tokenizerv1.json` | 旧版。実語彙1,809、マージ長制限なし |
| `tokenizerv2.json` | 現行版と同一の保存コピー |
| `tokenizer_visualization.json` | 語彙とマージを可読化した副産物。モデルは読まない |
| `tokenizer.md` | 版別の統計とcheckpointとの対応 |

スクリプトは現行版を上書きしますが、v1/v2のアーカイブを自動更新しません。現行版とコピーの同一性は、この確認時点のものです。詳しくは [tokenizer.md](tokenizer/tokenizer.md) を参照してください。

## 保存と再生成の区別

現在の `.gitignore` は `data/asts.jsonl` と `data/dataset/*.jsonl` を除外しています。`bindings.jsonl`、manifest、教師の生成記録、トークナイザはこの除外規則の対象ではありません。

教師の記録は同じ出力を再取得できる保証がなく、辞書から `run_id` / `prompt_sha256` で参照されます。通常の再生成可能な台帳と同じ扱いで消すと、元の生成条件や全文への参照を失います。
