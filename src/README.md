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
│   ├── review_phrases.py           候補を1件ずつ承認して日本語表現辞書を凍結する
│   │
│   └── teacher/                    教師モデル関連。ここだけ teacher グループに依存する
│       ├── README.md               環境構築の手順と、このディレクトリの関数一覧
│       ├── qwen.py                 Qwen3-4B-AWQ の読み込み・プロンプト組み立て・生成・由来
│       ├── op_seeds.yaml           24opの意味・正例・禁止語（人間が書く資産）
│       └── phrase_filters.py       生成された言い回しの正規化と機械的な棄却
│
├── conf/
│   └── binding.yaml                build_bindings.py 用のHydra設定
│
├── probes/
│   └── behavior_probe_set_v1.jsonl 凍結済み固定入力集合（148件）
│
├── phrases/                        人間が入れたもの。再現できないので data/ には置かない
│   ├── phrase_decisions.jsonl      査読の判定（1行1件。辞書の版をまたいで積み上がる）
│   ├── ja_phrases_v1.yaml          承認済み日本語表現辞書（op → 言い回しの一覧）
│   └── ja_phrases_v1_manifest.json 辞書の由来（op別採用数・寄与した生成実行のrun_id）
│
└── data/                           スクリプトが書いたものだけ
    ├── README.md                   生成物の一覧と再現方法
    ├── asts.jsonl                  意味ASTコーパス267,744件（参照台帳、全数）
    ├── manifest.json               由来と統計
    ├── bindings.jsonl              ASTごとのバインディング一覧
    ├── bindings_manifest.json      バインディング生成の要約（版・パラメータ/リテラル内訳）
    │
    └── teacher/
        ├── phrases_raw.jsonl       生成された言い回しの候補（棄却分も理由つきで残す）
        ├── phrases_runs.jsonl      生成1回ぶんの由来（モデル・ライブラリ版・sampling設定）
        ├── prompts.jsonl           実際に投げたプロンプトの全文（ハッシュごとに1行）
        └── phrases_manifest.json   候補全体の要約（op別採用数・棄却理由の内訳）
```

`phrases/`は、まだ査読を1件も通していなければ存在しない。

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
`review_phrases.py`の判定があればそれも読み、承認済みを追加の正例・却下済みを反例として
プロンプトに載せる（機械の検査は形式しか見ないので、これを読まないと生成側は
「何が良い言い回しだったか」を永遠に知らない）。

**`scripts/review_phrases.py`**
候補を1件ずつキー入力で承認・却下し、`phrases/ja_phrases_v1.yaml`を書き出す対話スクリプト。
**意味の検査を行う唯一の場所**であり、`phrase_filters`が通したことは形式が整っていることしか
意味しない。判定は`phrases/phrase_decisions.jsonl`に随時書くので中断・再開できる。
出力を`data/`でなく`phrases/`に置くのは、人間の判断が入っていて再生成できないためである。

**`scripts/teacher/qwen.py`**
教師モデルに実際に触る唯一のファイル。revision固定・`BACKEND.TORCH`・非thinkingモードという
疎通確認で通った構成を、読み込み・プロンプト組み立て・生成の3関数にしたもの。
プロンプトの中身も出力のパースも持たない。生成物に焼き付ける由来（モデルの同一性と
推論スタックの版）を**呼び出し時点の実測値として**返す`provenance()`もここにある。

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

**`data/teacher/`**
`build_phrases.py`の出力一式。候補そのもの（`phrases_raw.jsonl`）と、それを再現するのに要る
由来を3つのファイルに分けて持つ。`phrases_manifest.json`は全体の統計で**実行のたびに
上書きされる**ので、上書きしてはいけない由来は`phrases_runs.jsonl`に追記し、投げた
プロンプトの全文は`prompts.jsonl`に残す（ハッシュは同一性しか保証しないため）。各候補の
`run_id`と`prompt_sha256`がこの2つへの引き当てキーになる。

**`phrases/phrase_decisions.jsonl`**
`review_phrases.py`が書く査読の判定。1行1件で、`source`（画面に出た候補）・`phrase`（実際に
採用した形。`e`で編集すると違う値になる）・`decision`・`origin`を持つ。`origin`には候補を生んだ
生成の由来（`run_id`・`seed`・`prompt_sha256`など）を**複製してある**——判定は単体で意味を
持たなければならず、`phrases_raw.jsonl`との突き合わせは生成物を消した瞬間に切れるためである。
2方向に使われ、`review_phrases.py --compile`が読んで辞書を組み、`build_phrases.py`が読んで
承認済みを正例・却下済みを反例としてプロンプトに載せる。版を付けないのは、辞書の版をまたいで
積み上がる記録だからである。

**`phrases/ja_phrases_v1.yaml` / `phrases/ja_phrases_v1_manifest.json`**
`review_phrases.py`が承認済みの判定から組んだ日本語表現辞書と、その由来。生成物ではなく
**人間が承認した資産**なので、流し直しても同じものは再現されない。`data/`ではなくここに
置くのはそのためで、`probes/behavior_probe_set_v1.jsonl`と同じ「版つきで凍結された資産」に
あたる。書き出す前にop間の重複と`phrase_filters`の規則を検査し、破れていれば書かずに止まる。
