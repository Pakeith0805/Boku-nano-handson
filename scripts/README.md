# scripts/ — 生成・訓練・評価の入口

リポジトリのルートで `python -m scripts.<名前>` と実行します。以下の例は仮想環境のPythonを使う想定です。`uv run python -m ...` でも実行できますが、訓練には `uv run --group train python -m ...` のように必要なグループを指定します。

## 準備と処理順

```bash
uv sync --group dev
source .venv/bin/activate
```

モデル訓練・評価を行う環境は `uv sync --group train`、教師モデルを呼ぶ環境は `uv sync --group teacher` で準備します。両方必要なら両グループを指定します。教師モデルの設定は [teacher/README.md](teacher/README.md) を参照してください。

```text
build_probe_set → build_ast_corpus ──────────────────────────────┐
                       └→ build_bindings（独立した候補台帳）     │
build_phrases ⇄ review_phrases → 承認済み辞書・由来対応表 ───────┤
build_probe_set → 固定入力集合 ─────────────────────────────────┘
                          ↓
                     build_dataset
                          ↓
                     build_tokenizer → visualize_tokenizer
                          ↓
                        train → evaluate / try_generate
```

既存の `phrases/ja_phrases_v1.yaml` と由来対応表を使う場合、教師モデルによる再生成・査読は不要です。`build_dataset` は `bindings.jsonl` を読まず、`k` を引数のまま持つコードと指示文を作ります。

## build_probe_set.py

`main()` は境界値＋乱数の集合を作り、全ASTの挙動を比較して反例を追加し、`probes/behavior_probe_set_v1.jsonl` へ保存します。既存と同じ入力列なら書き換えず、異なれば `--force` なしでは停止します。

| 定数 | 値・役割 |
| --- | --- |
| `VERSION` / `SEED` | `v1` / 0 |
| `RANDOM_COUNT` / `MAX_PROBES` | 最初の乱数入力50件 / 全入力の上限256件 |
| `EXTERNAL_COUNT` / `VERIFY_MAX_DIFFICULTY` | 外部入力200件 / 難易度4までの全267,744 AST |
| `ROOT` / `OUT` | リポジトリルート / 凍結入力の出力先 |

```bash
python -m scripts.build_probe_set
python -m scripts.build_probe_set --force
```

偽の衝突が0件という結果は、使用した外部入力200件上での検査結果です。凍結入力を変更すると挙動ハッシュも変わるため、依存するAST台帳・データセットとの整合を取り直す必要があります。

## build_ast_corpus.py

`main()` は凍結入力を読み、1〜4操作の全ASTを列挙して指紋・統計を計算します。`OUT=data/asts.jsonl` と `MANIFEST_OUT=data/manifest.json` を上書きします。入力のprobe setがなければ停止します。

```bash
python -m scripts.build_ast_corpus
```

列挙と指紋は同じ実装・固定入力で再現できますが、生成時刻 `created_at` は実行ごとに変わります。

## build_bindings.py

`main(cfg)` はAST台帳を読み、各ASTのパラメータ版 `null` と、必要なら全 `k` スロットへ同じ整数を入れるリテラル版を列挙します。Hydra設定は [conf/binding.yaml](../conf/binding.yaml) です。

| 設定 | 既定値 |
| --- | --- |
| `asts_in` | `data/asts.jsonl` |
| `out` / `manifest_out` | `data/bindings.jsonl` / `data/bindings_manifest.json` |
| `binding.include_literal` | `true`。`false` でもパラメータ版は必ず残る |

```bash
python -m scripts.build_bindings
python -m scripts.build_bindings binding.include_literal=false
```

候補台帳を作る処理であり、ここではコードを生成しません。

## try_codegen.py

`main()` は `--ops` または `--ast-id` からASTを決め、`random_style(seed)` で選んだスタイルのコードを1本表示します。学習済みモデルは使いません。`ASTS_PATH=data/asts.jsonl` は `--ast-id` の場合だけ必要です。

```bash
python -m scripts.try_codegen --ops asc,take_first
python -m scripts.try_codegen --ast-id ast-000577 --seed 7
```

## build_phrases.py

`main()` は [teacher/op_seeds.yaml](teacher/op_seeds.yaml) と既存の査読判定を読み、opごとにプロンプトを組んで教師モデルを呼びます。形式検査を通った候補も意味が正しいとは限らないため、承認済み辞書にするには人間の査読が必要です。

| 定数 | 既定値・用途 |
| --- | --- |
| `TARGET` | 1opの目標10件。査読履歴があれば承認数、なければ機械採用数で判定 |
| `BASE_ROUNDS` / `MAX_ROUNDS` | 最低5ラウンド / ラウンド番号の上限3,200 |
| `N_PER_REQUEST` / `MAX_NEW_TOKENS` | 要求8行 / 生成上限384トークン |
| `TEMPERATURE` / `TOP_P` | 0.9 / 0.95 |
| `SEED_BASE` | 20260806。各呼び出しは `SEED_BASE + OP_NAMES.index(op) * 100 + round` |
| `MAX_KNOWN_IN_PROMPT` | 既出候補を最大40件掲載 |
| `MAX_REVIEWED_IN_PROMPT` | 承認済み・却下済みをそれぞれ最大24件掲載 |
| `SYSTEM_PROMPT_TEMPLATE` | 種の `frame` を埋める共通指示 |

```bash
python -m scripts.build_phrases --dry-run --ops even reverse
python -m scripts.build_phrases --ops even reverse gt --max-rounds 10
python -m scripts.build_phrases --below-target --max-rounds 20
```

`--dry-run` はモデルをimportせずプロンプトを表示するだけです。通常実行は `phrases_raw.jsonl` に記録済みの `(op, round)` を飛ばして再開します。`--max-rounds` は「今回追加する回数」ではなく通算ラウンド番号の上限です。空のcompletionは候補行が残らないため、そのラウンドの完了を再開時に判定できません。

`--rounds`, `--max-rounds`, `--target`, `-n`, `--temperature` で既定値を上書きできます。`--quiet-prompts` は標準出力へのプロンプト表示だけを省き、ファイルへの記録は残します。査読数は起動時に読み込んだ値なので、実行中の追加承認には追従しません。seedの式はラウンド100以上で別opと同じ値になり得ます。

| 出力 | 内容 |
| --- | --- |
| `data/teacher/phrases_raw.jsonl` | 空でない出力行を採用・棄却の理由とともに追記 |
| `data/teacher/phrases_runs.jsonl` | モデル・ライブラリ・GPU・sampling・引数。開始時に記録し、終了時は同じrunを更新 |
| `data/teacher/prompts.jsonl` | chat template適用後の全文。ハッシュごとに初回だけ追記 |
| `data/teacher/phrases_manifest.json` | 候補全体の統計を上書き |

実際の `-n` や `--target` はrun記録を見る必要があります。manifestの `params.n_per_request` と `params.target` は現行実装ではCLIの上書き値ではなくモジュール定数です。各ファイルのフィールドは [data/README.md](../data/README.md) を参照してください。

## review_phrases.py

`main()` は候補を人間に表示し、判定を保存して、終了時に辞書・manifest・由来対応表を作ります。`--compile` は判定の読み込みと書き出しだけを行います。`termios` を使うUnix系の対話スクリプトです。

| 定数 | 役割 |
| --- | --- |
| `RAW` / `SEEDS_PATH` / `DECISIONS` | 候補、種、`phrases/phrase_decisions.jsonl` のパス |
| `DICT_VERSION` / `TARGET` | 辞書v1 / 1opあたり目標10件 |
| `DICT_OUT` / `MANIFEST_OUT` / `PROVENANCE_OUT` | `phrases/ja_phrases_v1` の辞書・集計・由来対応表 |
| `SIMILAR` / `NON_JA_KANJI` | 類似度0.72以上と簡体字候補を表示で注意喚起 |
| `ORIGIN_FIELDS` | 判定側にも複製する生成由来のフィールド |

```bash
python -m scripts.review_phrases
python -m scripts.review_phrases --ops abs
python -m scripts.review_phrases --include-rejected not_terminal_form
python -m scripts.review_phrases --compile
```

`y`=採用、`n`=却下、`e`=編集して採用、`s`=保留、`u`=直前の判定を取り消し、`q`=終了して辞書を作成。判定は随時保存します。Ctrl-C時は保存済み判定を残して終了し、辞書のコンパイルは行いません。

`compile_dictionary` は重複表現と形式違反があれば書き出さず停止します。目標10件未達は警告のみで、部分辞書も書き出します。IDは承認日時順の連番です。後から承認を末尾へ追加する場合は既存IDを保てますが、過去の承認を削除・変更すると採番や内容が変わり得ます。

## build_dataset.py

`main()` はAST台帳・辞書・由来対応表・凍結入力集合を読み、[src/select/](../src/select/README.md) を呼びます。

| 定数 | 既定値・役割 |
| --- | --- |
| `ASTS_IN` / `PHRASES_IN` / `PROVENANCE_IN` | `data/asts.jsonl`、辞書v1、言い回しIDの由来対応表 |
| `OUT_DIR` | `data/dataset` |
| `TARGET_TOTAL_ASTS` / `CAP` | 通常3split合計の目標65,000 AST / 各AST最大20例 |
| `SPLIT_RATIOS` / `SEED` | train/val/test = 0.8/0.1/0.1 / seed 0 |
| `SPECIAL_TEST_SIZE` | 組合せ・言い換えテストそれぞれ上限30 AST、各1例 |
| `TEACHER_MODEL` / `TEACHER_REVISION` | 辞書v1に対応する教師モデルと固定revision |
| `_SPLIT_SEED_GAP` | 各split・特殊テストの乱数列を10,000ずつずらす |

```bash
python -m scripts.build_dataset
python -m scripts.build_dataset --workers 1 --target-total 65000 --seed 0
```

予約ペア隔離 → 挙動グループ分割 → 難易度4間引き → コード・文の選抜 → 検証結果記録の順です。ASTをワーカー数のチャンクへ分け、採用数の調整はチャンク内だけで行います。結果を合流後、**各出力ファイル内で** `reference_code` の文字列が同じ行を除去し、5ファイルを通した `spec_id` を付け直して保存します。

`--limit-asts 200` は通常3splitのAST数を絞りますが、出力先は通常と同じで既存JSONLを上書きします。特殊テストにはこの上限を適用しません。特殊テストは母集団不足・コード重複排除により30行未満になる場合があります。

同じ生成結果を得るにはseedに加えてワーカー数・コード・辞書・probe setも揃える必要があります。検証結果がfalseの行を除去する処理と、トークン長による選別は未実装です。

## build_tokenizer.py

`main()` は `TRAIN_IN=data/dataset/train.jsonl` の指示文とコードだけを使い、`OUT=data/tokenizer/tokenizer.json` を上書きします。`iter_texts(path)` がJSONLから2種類の文字列を順にyieldします。

| 定数 | 値・意味 |
| --- | --- |
| `VOCAB_SIZE` | 学習時の目標8,192。保存済み現行版の実語彙は1,256 |
| `MAX_TOKEN_LENGTH` | 16。ByteLevel表現上のマージ長を制限。現行語彙の最長は15バイト相当 |
| `SPECIAL_TOKENS` | `<\|pad\|>`, `<\|bos\|>`, `<\|eos\|>`, `<\|task\|>`, `<\|code\|>`, `<\|explanation\|>`。最後は現行学習では未使用 |

```bash
python -m scripts.build_tokenizer
```

ByteLevelの256バイトを基底語彙に含めます。BPEの `byte_fallback` オプションを有効にする方式ではありません。モデル側の語彙行数は別設定（既定4,096）なので、トークナイザを再学習した場合は全IDがモデルの範囲に収まることを確認してください。モデル側は自動調整しません。

## visualize_tokenizer.py

`main()` は `TOKENIZER_IN=data/tokenizer/tokenizer.json` から語彙とマージを読み、`OUT=data/tokenizer/tokenizer_visualization.json` を上書きします。`_readable(decoder, raw)` がByteLevel表記を可読テキストへ戻します。日本語1文字の途中のバイトだけを持つトークンは、単独表示すると `�` になる場合があります。

```bash
python -m scripts.visualize_tokenizer
```

## train.py

`main(cfg)` は設定と入力を読み、`BokuNanoModel` を初期化してAdamWで更新します。モデル構造は [conf/model/default.yaml](../conf/model/default.yaml)、その他は [conf/train.yaml](../conf/train.yaml) です。

```bash
python -m scripts.train
python -m scripts.train train.target_real_tokens=100_000_000
python -m scripts.train optim.max_lr=1e-4 eval.interval=100
```

| 設定・型 | 既定値・意味 |
| --- | --- |
| `Record` | パディング前の `(トークンID列, loss_mask列)` |
| `train.global_batch_sequences` | 128系列を一度に処理。勾配累積なし |
| `train.target_real_tokens` | 200,000,000。pad以外のトークン予算の目安 |
| `optim.*` | max_lr=3e-4、betas=(0.9,0.95)、eps=1e-8、weight_decay=0.1、warmup_ratio=0.03、min_lr_ratio=0.1、grad_clip=1.0 |
| `eval.interval` / `eval.n_batches` | 200step間隔 / 8バッチのlossを平均 |
| `eval.generation.n_samples` / `max_new_tokens` | 固定seedで16件 / 最大192新規トークン |
| `checkpoint.interval` | step 0を除く500step間隔と最終stepに保存 |
| `mlflow.experiment` / `tracking_db` | `boku-nano` / `runs/mlflow.db` |

1レコード1系列で右padし、次トークン予測を行います。モデルの順伝播をBF16 autocastで計算し、cross entropyはFP32です。パラメータはFP32で、RMSNormも含めて全パラメータに同じweight decayを設定します。

学習step数は `floor(target_real_tokens / (系列数 × 平均トークン長))` で事前に決めます。実測累計で停止する方式ではありません。長さ見積もりは上限で丸めていますが、データイテレータは長すぎるレコードを切り詰めず例外にします。

損失マスクは入力位置側に合わせます。EOS予測のほか、右padのある行ではEOSから最初のpadへの予測も含む現行挙動については [model/README.md](../model/README.md) を参照してください。

検証lossはイテレータを進めて得た8バッチの単純平均です。生成評価の16件は毎回同じseedで選び、構文検査と固定入力全件の出力一致で合格を数えます。`eval.generation.temperature` は設定ファイルにありますが、コードは参照せず貪欲生成に固定されています。

checkpointは `runs/checkpoints/<run_id>/step_NNNNNN.pt`、metricsはSQLite、トークナイザ本体はMLflow artifactへ保存します。artifactの配置はMLflow側の設定に従います。checkpointから訓練を再開するCLIはありません。

## try_generate.py

`main()` はcheckpointからモデルを復元し、1件の日本語指示に対してコードを表示します。`TOKENIZER_PATH` と `VAL_PATH` はリポジトリ内の現行tokenizerと `val.jsonl` に固定されています。

以下の `RUN_ID` とstep番号は、保存済みcheckpointの実際の値に置き換えます。

```bash
python -m scripts.try_generate --checkpoint runs/checkpoints/RUN_ID/step_006000.pt --random-val --seed 3
python -m scripts.try_generate --checkpoint runs/checkpoints/RUN_ID/step_006000.pt \
    --instruction '整数を要素に持つリストに対して、偶数だけを残すsolve関数を書いてください。'
```

`--instruction` と `--random-val` はどちらか1つが必須です。前者は構文検査まで、後者は固定入力全件で参照コードと比較してPASS/FAILを表示します。`--max-new-tokens` は既定192です。checkpointと同じトークナイザを使ってください。対応版の自動検査やtokenizer指定オプションはありません。

## evaluate.py

`main()` はモデルを読み、通常・言い換え・組合せの3集合で生成・判定し、同じ生成結果を境界値入力だけでも再評価します。`CATEGORIES` が3つのファイルパスを定義します。

```bash
python -m scripts.evaluate --checkpoint runs/checkpoints/RUN_ID/step_006000.pt
python -m scripts.evaluate --checkpoint runs/checkpoints/RUN_ID/step_006000.pt --limit 500 --out report.json
python -m scripts.evaluate --checkpoint runs/checkpoints/RUN_ID/step_006000.pt --limit 0
```

| オプション・定数 | 既定値・動作 |
| --- | --- |
| `DEFAULT_LIMIT` / `--limit` | 通常テスト200件。0以下、または全件数以上なら全件 |
| `--seed` | 通常テストの抽出seed 0 |
| `--batch-size` | 一度に生成する件数64 |
| `--max-new-tokens` | 192。モデルの残り系列長も上限になる |
| `--out` | 省略時は標準出力のみ。指定時は生成コードと個別合否を含むJSONを書き出す |
| `TOKENIZER_PATH` / `PROBES_PATH` | 現行tokenizerと凍結入力v1の固定パス |

言い換え・組合せは全件を使い、通常テストだけを抽出します。生成コードは構文検査と全148入力の参照出力一致で合格です。境界値の合格率は20入力だけで判定した各例の合否を、評価した3集合の**件数で加重して**集計します。

存在しないデータファイルはスキップします。`--out` の親ディレクトリは自動作成しません。EOSを出したかどうかは合格条件に含まれません。これらの評価は新しいhidden入力の生成ではなく、データ構築にも使った凍結probe setの再利用です。

### 評価指標と性能計測

学習中の生成評価と単独評価の両方で、次の率を記録します。分母はすべて評価した生成コードの全件数です。

| キー | 判定 |
| --- | --- |
| `syntax_valid_rate` | `ast.parse` に成功 |
| `safe_ast_rate` | 構文・呼び出し・属性の許可リストに適合 |
| `signature_valid_rate` | モジュール直下に `solve(xs, k)` を正しく定義 |
| `executable_rate` | 安全性とシグネチャの検査を通り、全probeでtimeout・例外なく実行 |

構文エラーの場合は4項目とも失敗です。Safe-ASTとシグネチャは独立に判定します。Executableは出力の正しさを問いません。誤答が出ても後続probeの実行を続けます。単独評価のJSONには各生成コードの判定フラグと `errors`（検査失敗・実行例外の理由）も保存します。

Validation lossは従来どおり学習時の `val_loss` として記録します。組合せ汎化率は従来の組合せカテゴリの `pass_rate` に加え、単独評価JSONの `combination_generalization_rate` にも保存します。組合せデータが無い場合は `null` です。固定probeによる既存の合格判定を使います。

- `train_tokens_per_second`: padを除いた累計学習トークン数 / 累計学習step時間。データ取得・バッチ化・forward・backward・更新を含み、検証・ログ・checkpoint保存は除外します。
- `generation_tokens_per_second`: 生成したトークン数 / 生成処理時間。EOSを含み、EOS後の埋め草padとプロンプトは除外します。生成処理内のテンソル準備とCPUへの結果転送を含み、tokenize・decode・コード検査は除外します。単独評価ではカテゴリごと、学習時は生成評価ごとに計測します。`generated_tokens` と `generation_seconds` も保存します。
- `max_gpu_memory_bytes`: 実行開始時にピーク統計をリセットした後のPyTorch CUDA allocatedメモリの最大値（bytes）。モデルのロード・学習・評価を含みます。予約済みメモリや他プロセスの使用量は含みません。CPUでは単独評価JSONは `null`、MLflowにはこのキーを記録しません。

CUDAでは時間計測の前後に同期します。学習指標はコンソールとMLflow、単独評価指標はコンソールと `--out` 指定時のJSONに記録します。
