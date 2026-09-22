# ファイル地図

現在の実装・設定・資産を探すための地図です。関数の詳細は各ディレクトリのREADME、実行手順は [scripts/README.md](../scripts/README.md) を参照してください。

`data/asts.jsonl` と `data/dataset/*.jsonl` は生成物、`docs/` はローカルの解説で、現在の `.gitignore` では管理外です。`runs/` のcheckpoint・実験ログ、キャッシュ、仮想環境はツリーから省略しています。

```text
Boku-nano-handson/
├── README.md                              プロジェクトの概要と読み始める場所
├── pyproject.toml                         依存グループとpytest設定
├── uv.lock                                依存の固定
├── .python-version                        Python 3.12.13の指定
├── EXPERIMENTS.md                         訓練実験の履歴と解釈の訂正
├── KNOWLEDGE.md                           人間が書く技術メモ
├── THIRD_PARTY.md                         教師モデルの来歴と記録の状況
├── THIRD_PARTY_LICENSES/
│   └── Qwen3-4B-AWQ-LICENSE.txt           保存済みの教師モデルのLICENSE
├── src/
│   ├── README.md                          本ファイル。全体の地図
│   ├── __init__.py                        生成器の版
│   ├── limits.py                          入力の長さ・整数値域
│   ├── interp/
│   │   ├── interp.py                      24操作の参照実装と順次実行
│   │   └── README.md                      このディレクトリの関数・型の説明
│   ├── codegen/
│   │   ├── codegen.py                     参照実装と独立したPythonコード生成
│   │   └── README.md                      このディレクトリの関数・型の説明
│   ├── semantics/
│   │   ├── registry.py                    24操作のメタデータ
│   │   ├── semantic_ast.py                操作列・派生値・全数列挙
│   │   ├── fingerprint.py                 構造と固定入力上の挙動のハッシュ
│   │   ├── corpus.py                      ASTレコードとmanifestの読み書き
│   │   ├── schema.json                    ASTレコードのJSON Schema
│   │   └── README.md                      このディレクトリの関数・型の説明
│   ├── probes/
│   │   ├── behavior_probes.py             固定入力集合の生成・反例追加・保存
│   │   └── README.md                      このディレクトリの関数・型の説明
│   ├── expand/
│   │   ├── binding.py                     kの具体化候補を列挙
│   │   └── README.md                      このディレクトリの関数・型の説明
│   ├── nlg/
│   │   ├── nlgen.py                       承認済み言い回しから日本語指示を生成
│   │   └── README.md                      このディレクトリの関数・型の説明
│   ├── verify/
│   │   ├── safety.py                      許可構文・呼び出し・シグネチャの検査
│   │   ├── sandbox.py                     同一プロセス内で制限時間つき実行
│   │   └── README.md                      このディレクトリの関数・型の説明
│   └── select/
│       ├── combination.py                 予約した操作ペアを含むASTの隔離
│       ├── split.py                       挙動のグループ単位で分割（退化例は例外）
│       ├── difficulty.py                  難易度4のASTを間引く
│       ├── balance.py                     コードと指示文候補の採用数を調整
│       ├── record.py                      最終レコードの構築と実行検証
│       └── README.md                      このディレクトリの関数・型の説明
├── scripts/
│   ├── README.md                          生成・訓練・評価のコマンド集
│   ├── build_probe_set.py                 固定入力集合を生成して凍結
│   ├── build_ast_corpus.py                全267,744件のAST台帳を生成
│   ├── build_bindings.py                  AST別の具体化候補をJSONLに保存
│   ├── try_codegen.py                     指定ASTのルール生成コードを表示
│   ├── build_phrases.py                   教師モデルで言い回し候補を生成
│   ├── review_phrases.py                  人間の査読と辞書の書き出し
│   ├── build_dataset.py                   選抜・検証・重複排除を経て5つのJSONLを生成
│   ├── build_tokenizer.py                 trainだけからByteLevel BPEを学習
│   ├── visualize_tokenizer.py             トークナイザの可視化JSONを生成
│   ├── train.py                           モデル訓練・定期評価・checkpoint保存
│   ├── evaluate.py                        checkpointを3集合と境界値で評価
│   ├── try_generate.py                    checkpointから1件生成して表示
│   └── teacher/
│       ├── README.md                      教師モデルの設定と関数一覧
│       ├── qwen.py                        教師モデルの読み込み・推論・由来収集
│       ├── phrase_filters.py              候補の正規化と形式検査
│       └── op_seeds.yaml                  操作の意味・例文・禁止語を持つ種
├── model/
│   ├── README.md                          モデルと補助関数のリファレンス
│   ├── __init__.py                        BokuNanoModel・ModelConfigの再公開
│   ├── transformer.py                     GQA・RoPE・RMSNorm・SwiGLUを持つモデル
│   ├── data.py                            JSONLの読み込みと次トークン損失マスク
│   ├── schedule.py                        warmupとcosine学習率
│   ├── generate.py                        左padによるバッチ貪欲生成
│   └── checkpoint.py                      設定と重みから評価用モデルを復元
├── conf/
│   ├── binding.yaml                       具体化候補の入出力とliteral設定
│   ├── train.yaml                         訓練・評価・記録のHydra設定
│   └── model/
│       └── default.yaml                   モデル構造の既定値
├── probes/
│   └── behavior_probe_set_v1.jsonl        凍結入力148件（境界値20件を含む）
├── phrases/
│   ├── phrase_decisions.jsonl             人間の採否・編集と候補の由来
│   ├── ja_phrases_v1.yaml                 承認済み辞書279表現
│   ├── ja_phrases_v1_manifest.json        辞書の集計と寄与した生成run
│   └── ja_phrases_v1_provenance.json      言い回しIDから生成run・promptへの対応
├── data/
│   ├── README.md                          生成物と再現条件の説明
│   ├── asts.jsonl                         全AST台帳（生成物・Git管理外）
│   ├── manifest.json                      AST台帳の統計・時刻・版
│   ├── bindings.jsonl                     パラメータ版とリテラル版の候補
│   ├── bindings_manifest.json             候補件数・設定・内訳
│   ├── teacher/
│   │   ├── phrases_raw.jsonl              形式検査の採用・棄却候補
│   │   ├── phrases_runs.jsonl             生成runごとのモデル・環境・条件
│   │   ├── prompts.jsonl                  実際に渡したプロンプト全文
│   │   └── phrases_manifest.json          候補全体の統計
│   ├── dataset/
│   │   ├── README.md                      Dataset Card
│   │   ├── train.jsonl                    訓練用（生成物・Git管理外）
│   │   ├── val.jsonl                      検証用（生成物・Git管理外）
│   │   ├── test.jsonl                     通常テスト（生成物・Git管理外）
│   │   ├── test_combination.jsonl         組合せテスト（上限30件）
│   │   └── test_paraphrase.jsonl          保留表現による言い換えテスト（上限30件）
│   └── tokenizer/
│       ├── tokenizer.json                 現行v2のトークナイザ本体
│       ├── tokenizerv1.json               v1アーカイブ
│       ├── tokenizerv2.json               v2アーカイブ
│       ├── tokenizer_visualization.json   現行版の可視化
│       └── tokenizer.md                   版ごとの統計と互換性
├── docs/
│   ├── train-walkthrough.md               訓練処理の全体フロー
│   ├── train-prerequisites.md             コードを読むためのPython・Tensorの基礎
│   ├── train-dependencies.md              入出力と設定キーの対応
│   ├── compute-loss-explanation.md        マスクと次トークン損失の位置対応
│   ├── eval-generation-explanation.md     生成・実行結果比較の流れ
│   ├── train-main-explanation.md          mainの起動から保存まで
│   └── norm_weight_decay_comparison.md    RMSNormのweight decay比較の過去記録
└── tests/
    ├── test_core_has_no_external_deps.py  srcの外部依存禁止
    ├── test_interp_ops.py                 24操作の意味とrunの契約
    ├── test_limits.py                     入力とリテラルの値域
    ├── test_literal_domains.py            リテラル除外の根拠
    ├── test_no_mutation.py                入力を変更せず新しいリストを返す契約
    ├── test_record_schema.py              ASTレコードとSchemaの整合
    ├── test_registry_conformance.py       レジストリと実装の名前・形式の整合
    └── README.md                          テストごとの検証範囲と関数一覧
```

## ファイル間の関係

- **`src/interp/interp.py` と `src/codegen/codegen.py`**：操作の意味を参照インタプリタで定義し、コード生成器では同じ計算を独立して書きます。両者の出力比較で片側の誤りを検出するための分離です。
- **`src/semantics/registry.py` と `semantic_ast.py`**：レジストリはメタデータ、ASTは操作列と派生値です。全数列挙は重複のない1〜4操作を生成しますが、`SemanticAST` のコンストラクタ自体は操作数や重複を検証しません。
- **`src/semantics/fingerprint.py` と `corpus.py`**：前者は構造のハッシュと有限入力上の挙動のハッシュ、後者はその値に採番・時刻・版を足して保存します。構造ハッシュに評価器は不要です。挙動の一致は全入力での等価性の証明ではありません。
- **`src/semantics/schema.json`**：AST台帳用の形式です。最終訓練レコードの形式は `src/select/record.py` が定義します。
- **`src/probes/behavior_probes.py`**：境界値と乱数に反例を追加します。`scripts/build_probe_set.py` は難易度1〜4の全ASTを対象に、固定した外部入力200件に対する偽の衝突を調べます。
- **`src/expand/binding.py` と `scripts/build_bindings.py`**：`k` の具体化候補を列挙して台帳に保存します。現在のコード・指示文生成は `k` を引数のまま使い、`build_dataset.py` はこの台帳を読みません。
- **`src/nlg/nlgen.py`**：渡された辞書の直積から指示文を作ります。辞書の読み込みは外部依存を扱えるスクリプト側の仕事です。
- **`src/verify/safety.py` と `sandbox.py`**：前者が構文とシグネチャを調べ、後者が再検査後にコードを実行します。タイマーは `solve` 呼び出しを囲み、モジュール定義を実行する `exec` はタイマーの外です。
- **`src/select/combination.py` と `split.py`**：予約ペアを含むASTを先に隔離し、残りを挙動ハッシュで分割します。`always_empty` は個別分割の例外です。組合せ集合との挙動重複や退化例のsplit横断重複は除去しません。
- **`src/select/difficulty.py`**：各通常splitで難易度1〜3を残し、4だけを目標数に合わせます。難易度別の件数を均等にする処理ではありません。
- **`src/select/balance.py` と `record.py`**：候補を選んで組み合わせ、検証結果をレコードに記録します。`build_dataset.py` の均しはチャンクごと、コード重複排除は出力ファイルごとです。検証結果がfalseの行を落とす処理はありません。
- **`scripts/build_phrases.py` と `review_phrases.py`**：教師モデルが出すのは短い言い換え候補です。人間の判定から辞書を作り、その判定を次の生成の正例・反例として読み返します。
- **`scripts/teacher/qwen.py`・`phrase_filters.py`・`op_seeds.yaml`**：それぞれ教師推論、機械的な形式検査、プロンプトの種を担当します。形式検査だけで日本語の意味は確認できません。
- **`scripts/build_dataset.py`**：AST・承認済み辞書・由来対応表・固定入力集合を結び、通常3splitと特殊テスト2集合を書きます。特殊テストは上限30件で、候補不足・重複排除により減る場合があります。
- **`scripts/build_tokenizer.py` と `visualize_tokenizer.py`**：trainの指示文とコードだけでBPEを学習し、別途人間用の可視化を作ります。可視化JSONはモデルの入力ではありません。
- **`scripts/train.py` と `model/data.py`**：データ側は1件のトークン列・マスク、訓練側は右padしたバッチと最適化を担当します。現在は128系列を一度に処理し、勾配累積はしません。
- **`model/transformer.py` と `model/__init__.py`**：前者がモデル・設定型を定義し、後者が再公開します。アーキテクチャの既定値は `conf/model/default.yaml` から読みます。
- **`model/schedule.py`**：予定step数に対する学習率を計算します。`train.target_real_tokens` を変えると予定step数とcosineの進み方も変わります。
- **`model/generate.py` と `model/checkpoint.py`**：前者が左padを使う貪欲生成、後者がモデルの復元です。checkpointはトークナイザを含みません。
- **`scripts/evaluate.py` と `try_generate.py`**：前者は集合単位、後者は1件単位でモデルを確認します。`scripts/try_codegen.py` は学習モデルを使わずルール生成器を見る別の入口です。
- **`conf/train.yaml`・`conf/model/default.yaml`・`conf/binding.yaml`**：訓練設定、モデル構造、具体化候補の生成設定に分かれます。Hydraの上書きは `key=value` 形式です。
- **`phrases/` と `data/teacher/`**：前者は人間の判断を含む辞書資産、後者は生成候補とその来歴です。辞書のIDは承認日時順で採番するため、過去の承認を削除すると変わり得ます。
- **`data/` の台帳・データセット・トークナイザ**：作り直せる条件は [data/README.md](../data/README.md) にまとめています。生成日時まで含めたバイト一致は保証しません。
- **`tests/`**：参照実装・レジストリ・値域・ASTレコード形式・依存境界を確認します。モデル訓練や全パイプラインの網羅的なテストではありません。
- **`docs/` と `EXPERIMENTS.md`**：前者は現行コードの解説、後者は過去の測定記録です。過去の設定名や実験時の推測を、そのまま現行の仕様と解釈しないでください。
- **`KNOWLEDGE.md`**：人間が書く技術メモです。ファイル冒頭の編集方針を維持しています。
- **`THIRD_PARTY.md` と保存済みLICENSE**：教師モデルの来歴を記録します。教師モデルのLICENSEと、このリポジトリ独自のコード・データのライセンスは別です。

## src直下の定数

### __init__.py

| 名前 | 説明 |
| --- | --- |
| `BOKU_GENERATOR_VERSION` | 現在 `v0.1`。ASTレコードの `generator_version` に記録する生成器の版 |

### limits.py

| 名前 | 説明 |
| --- | --- |
| `XS_LEN_MIN` / `XS_LEN_MAX` | 入力リストの想定長0〜20 |
| `ELEM_MIN` / `ELEM_MAX` | 入力要素の想定範囲−100〜100。出力は範囲外でもよい |
| `K_MIN` / `K_MAX` | パラメータ `k` の範囲1〜10 |

これらは入力条件の定義です。`interp.run()` が実行時に検査するのは `k` の範囲であり、`xs` の長さ・要素の型や範囲を一括検証する関数ではありません。
