# ファイル地図

どのファイルが何を担っているかの一覧。各ディレクトリの詳しい関数一覧はそれぞれの
`README.md`を見ること。

```
Boku-nano-handson/
├── README.md                       このプロジェクトの方針（全部自分の手で実装する）
├── pyproject.toml                  依存と pytest 設定
├── uv.lock                         依存の固定
│
├── src/                            実装本体
│   ├── README.md                   本ファイル。ファイル地図
│   ├── limits.py                   入力条件（xs長さ0〜20・要素±100・k 1〜10）
│   │
│   ├── interp/
│   │   ├── README.md               interp.py の関数一覧
│   │   └── interp.py               参照インタプリタ。24opの意味の唯一の権威
│   │
│   ├── semantics/
│   │   ├── README.md               このディレクトリの関数一覧
│   │   ├── registry.py             24opのメタデータ。意味は持たない
│   │   ├── semantic_ast.py         SemanticAST / BindingSlot / 全数列挙
│   │   ├── fingerprint.py          semantic_hash / behavior_hash / Fingerprint
│   │   ├── corpus.py               asts.jsonl と manifest.json の読み書き
│   │   └── schema.json             意味ASTレコードの JSON Schema
│   │
│   ├── probes/
│   │   ├── README.md               behavior_probes.py の関数一覧
│   │   └── behavior_probes.py      固定入力集合の生成・偽の衝突つぶし
│   │
│   └── expand/
│       ├── README.md               binding.py の関数一覧
│       └── binding.py              バインディング（k の具体化）の列挙
│
├── scripts/                        実行の入口
│   ├── README.md                   本ディレクトリの説明
│   ├── build_probe_set.py          固定入力集合を作って凍結する
│   ├── build_ast_corpus.py         意味ASTコーパス（参照台帳）を構築する
│   ├── build_bindings.py           ASTごとのバインディングを列挙する（Hydra駆動）
│   ├── build_phrases.py            24opの言い回しを教師モデルに生成させる
│   │
│   └── teacher/                    教師モデル関連。ここだけ teacher グループに依存する
│       ├── README.md               環境構築の手順と分担
│       ├── qwen.py                 Qwen3-4B-AWQ の読み込み・プロンプト組み立て・生成
│       ├── op_seeds.yaml           24opの意味・正例・禁止語（人間が書く資産）
│       └── phrase_filters.py       生成された言い回しの正規化と機械的な棄却
│
├── conf/
│   └── binding.yaml                build_bindings.py 用のHydra設定
│
├── probes/
│   └── behavior_probe_set_v1.jsonl 凍結済み固定入力集合（148件）
│
└── data/
    ├── asts.jsonl                  意味ASTコーパス267,744件（参照台帳、全数）
    ├── manifest.json               由来と統計
    ├── bindings.jsonl              ASTごとのバインディング一覧
    ├── bindings_manifest.json      バインディング生成の要約（版・パラメータ/リテラル内訳）
    │
    └── teacher/
        ├── manifest.json           教師モデルの環境の由来（疎通確認の記録）
        ├── phrases_raw.jsonl       生成された言い回しの候補（棄却分も理由つきで残す）
        └── phrases_manifest.json   生成1回分の要約（op別採用数・棄却理由の内訳）
```

## それぞれのファイルの簡単な説明

**`src/limits.py`**
課題文が定める`solve(xs, k)`の入力の範囲（`xs`の長さ・要素・`k`の値域）。参照インタプリタと
固定入力集合の両方がここを参照する。opのメタデータ（`registry.py`）とは別物として分けてある。

**`src/interp/interp.py`**
24種類のopの実際の計算と、意味ASTを左から順に適用する`run(ast, xs, k)`。「各opが何を計算するか」
の唯一の権威であり、`behavior_hash`もここでの出力を基準にする。

**`src/semantics/registry.py`**
24opのメタデータ（カテゴリ・`k`を使うか・リテラル値域）を持つ辞書`OP_REGISTRY`。opの意味その
ものは持たない（意味は`interp.py`の担当）。

**`src/semantics/semantic_ast.py`**
op名の順序付き列を表す`SemanticAST`と、そこから決まる値（`difficulty`・`categories`・
`binding_slots`など）を導出するプロパティ群。全267,744件を列挙する`enumerate_all_asts()`も
ここにある。

**`src/semantics/fingerprint.py`**
op列の正準表現から作る`semantic_hash`と、固定入力集合での出力列から作る`behavior_hash`。
op評価とprobe setはどちらも呼び出し側から渡す（依存性注入）ので、標準ライブラリ以外に依存しない。

**`src/semantics/corpus.py`**
`SemanticAST`の値・`Fingerprint`の値・由来情報（`ast_id`・`created_at`・各version）を1つの
レコードに合成し、`asts.jsonl`と`manifest.json`として読み書きする層。

**`src/semantics/schema.json`**
`asts.jsonl`の1行が満たすべきJSON Schema。必須フィールドと型を定義する。

**`src/probes/behavior_probes.py`**
`behavior_hash`の基準になる固定入力集合（境界値20件＋乱数＋偽の衝突をつぶすための反例）を
作り、JSONLで凍結・読み戻す。

**`src/expand/binding.py`**
`k`を参照するopを持つ意味ASTを、パラメータ版（`k`のまま）とリテラル版（`k`を具体値に固定）
のどちらかで実体化するための列挙。混在は型（`Binding = int | None`）として表現できないように
してあり、opに焼き付いた定数（`double`の`2`など）はそもそも対象にならない。

**`scripts/build_probe_set.py`**
`behavior_probes.py`を使って固定入力集合を生成し、`probes/behavior_probe_set_{version}.jsonl`
に凍結する駆動スクリプト。

**`scripts/build_ast_corpus.py`**
凍結済みの固定入力集合を読み、全ASTを列挙・レコード化して`data/asts.jsonl`と
`data/manifest.json`を書き出す駆動スクリプト。

**`scripts/build_bindings.py`**
`data/asts.jsonl`の各レコードに対して`enumerate_bindings`でバインディングを列挙し、
`data/bindings.jsonl`と`data/bindings_manifest.json`を書き出す駆動スクリプト。設定は
Hydra（`conf/binding.yaml`）経由で読む。

**`scripts/build_phrases.py`**
`scripts/teacher/op_seeds.yaml`の種から24opぶんのプロンプトを組み、教師モデル（Qwen3-4B-AWQ）に
日本語の言い回しを生成させ、`phrase_filters`で弾いて`data/teacher/phrases_raw.jsonl`に
由来つきで記録する駆動スクリプト。出力は辞書ではなく**候補**であり、承認は人間が行う。

**`scripts/teacher/qwen.py`**
教師モデルに実際に触る唯一のファイル。revision固定・`BACKEND.TORCH`・非thinkingモードという
疎通確認で通った構成を、読み込み・プロンプト組み立て・生成の3関数にしたもの。
プロンプトの中身も出力のパースも持たない。

**`scripts/teacher/op_seeds.yaml`**
24opそれぞれの意味・言い換えの正例2つ・使ってはいけない語。**人間が書く資産**であり、
opの意味の確定はここが持つ（教師モデルに意味を推測させない）。`k`参照opの表現は`{k}`を含む。

**`scripts/teacher/phrase_filters.py`**
生成された行の正規化（記号・番号・鉤括弧・句点・括弧書きの除去）と、機械的に判定できる棄却
（文型・長さ・使用禁止語・`k`の出現回数・重複）。**意味の正しさは判定しない。**
教師モデルにも`torch`にも依存しないので、GPU無しで単体テストできる。

**`conf/binding.yaml`**
`build_bindings.py`のHydra設定。入出力パスと、リテラル版も作るか（`binding.include_literal`、
既定true）を持つ。作業ディレクトリを`outputs/...`に移さないための`hydra.job.chdir: false`も
ここで指定している。

**`probes/behavior_probe_set_v1.jsonl`**
`build_probe_set.py`が生成した凍結済みの固定入力集合。境界値20件＋乱数50件＋偽の衝突をつぶす
ための反例で構成され、difficulty 1〜4の全267,744件で偽の衝突が0件になるまで育ててある。

**`data/asts.jsonl` / `data/manifest.json`**
`build_ast_corpus.py`が生成した意味ASTコーパス本体（267,744件、参照台帳として全数）と、
その由来・統計の要約。

**`data/bindings.jsonl` / `data/bindings_manifest.json`**
`build_bindings.py`が生成した、ASTごとのバインディング一覧（`{"ast_id":..., "binding":...}`の
JSONL）と、パラメータ版／リテラル版の内訳を含む要約。
