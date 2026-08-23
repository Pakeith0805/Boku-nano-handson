# ファイル地図

どのファイルが何を担っているかの一覧。各ディレクトリの詳しい関数一覧はそれぞれの
`README.md`を見ること。

```
Boku-nano-handson/
├── README.md                       このプロジェクトの方針（全部自分の手で実装する）
├── pyproject.toml                  依存と pytest 設定
├── uv.lock                         依存の固定
├── .python-version                 3.12.13 に固定（3.13系だと教師モデルのTritonが落ちる）
├── build_phrases.log               言い回し生成の実行ログ（投げたプロンプトと出力の記録）
├── build_bindings.log              バインディング生成の実行ログ
│
├── src/                            実装本体
│   ├── README.md                   本ファイル。ファイル地図
│   ├── __init__.py                 generator_version（全レコードに焼き付ける生成器の版）
│   ├── limits.py                   入力条件（xs長さ0〜20・要素±100・k 1〜10）
│   │
│   ├── interp/
│   │   ├── README.md               interp.py の関数一覧
│   │   └── interp.py               参照インタプリタ。24opの意味の唯一の権威
│   │
│   ├── codegen/
│   │   ├── README.md               codegen.py の関数一覧・バリエーション軸・均し方の設計
│   │   └── codegen.py              意味ASTから等価な複数のPython実装を生成する。interp.pyとは独立
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
│   ├── expand/
│   │   ├── README.md               binding.py の関数一覧
│   │   └── binding.py              バインディング（k の具体化）の列挙
│   │
│   ├── nlg/
│   │   ├── README.md               nlgen.py の関数一覧
│   │   └── nlgen.py                意味ASTから日本語指示文を列挙する。codegen.pyの日本語版
│   │
│   ├── verify/
│   │   ├── README.md               safety.py / sandbox.py の関数一覧
│   │   ├── safety.py               生成コードの許可リスト検査（構文・シグネチャ）
│   │   └── sandbox.py              検査済みコードを制限時間つきで実行する
│   │
│   └── select/
│       ├── README.md               各ファイルの関数一覧・処理順
│       ├── combination.py          組合せ汎化テスト用に特定のop組合せを隔離する（最初に実行）
│       ├── split.py                behavior_hashグループ単位でtrain/val/testに分割する
│       ├── difficulty.py           difficulty 1〜3は全数、4だけ間引く
│       ├── balance.py              コード形式・日本語テンプレートを貪欲法で均等に選ぶ
│       └── record.py               選ばれた例1件を最終レコードのスキーマへ組み立てる
│
├── scripts/                        実行の入口
│   ├── README.md                   本ディレクトリの説明
│   ├── build_probe_set.py          固定入力集合を作って凍結する
│   ├── build_ast_corpus.py         意味ASTコーパス（参照台帳）を構築する
│   ├── build_bindings.py           ASTごとのバインディングを列挙する（Hydra駆動）
│   ├── try_codegen.py              1件の意味ASTについて、codegen.pyの出力を1本だけ見る（試験用）
│   ├── build_phrases.py            24opの言い回しを教師モデルに生成させる
│   ├── review_phrases.py           候補を1件ずつ承認して日本語表現辞書を凍結する
│   ├── build_dataset.py            src/select/を順に呼び、最終データセットを組み立てる
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
│   ├── phrase_decisions.jsonl          査読の判定（1行1件。辞書の版をまたいで積み上がる）
│   ├── ja_phrases_v1.yaml              承認済み日本語表現辞書（op → 言い回しの一覧）
│   ├── ja_phrases_v1_manifest.json     辞書の由来（op別採用数・寄与した生成実行のrun_id）
│   └── ja_phrases_v1_provenance.json   言い回しID別の生成由来（run_id・prompt_sha256）
│
└── data/                           スクリプトが書いたものだけ
    ├── README.md                   生成物の一覧と再現方法
    ├── asts.jsonl                  意味ASTコーパス267,744件（参照台帳、全数）
    ├── manifest.json               由来と統計
    ├── bindings.jsonl              ASTごとのバインディング一覧
    ├── bindings_manifest.json      バインディング生成の要約（版・パラメータ/リテラル内訳）
    │
    ├── teacher/
    │   ├── phrases_raw.jsonl       生成された言い回しの候補（棄却分も理由つきで残す）
    │   ├── phrases_runs.jsonl      生成1回ぶんの由来（モデル・ライブラリ版・sampling設定）
    │   ├── prompts.jsonl           実際に投げたプロンプトの全文（ハッシュごとに1行）
    │   └── phrases_manifest.json   候補全体の要約（op別採用数・棄却理由の内訳）
    │
    └── dataset/                    build_dataset.py が書く最終データセット
        ├── train.jsonl              訓練split
        ├── val.jsonl                検証split
        ├── test.jsonl               テストsplit
        ├── test_combination.jsonl   組合せ汎化テスト（隔離した予約ペアAST由来、固定30件）
        └── test_paraphrase.jsonl    言い換えテスト（保留分の言い回しだけで作る、固定30件）
```

`phrases/`は、まだ査読を1件も通していなければ存在しない。

## それぞれのファイルの簡単な説明

**`src/__init__.py`**
`BOKU_GENERATOR_VERSION`（現在`v0.1`）だけを持つ。全レコードの`generator_version`に載る値で、
手で上げる。**参照インタプリタを直したときも上げること**——`behavior_hash`はその実装に依存する
のに、`registry_version`も`probe_set_version`もインタプリタの変更では動かないため、この定数だけが
唯一の記録になる。

**`src/limits.py`**
課題文が定める`solve(xs, k)`の入力の範囲（`xs`の長さ・要素・`k`の値域）。参照インタプリタと
固定入力集合の両方がここを参照する。opのメタデータ（`registry.py`）とは別物として分けてある。

**`src/interp/interp.py`**
24種類のopの実際の計算と、意味ASTを左から順に適用する`run(ast, xs, k)`。「各opが何を計算するか」
の唯一の権威であり、`behavior_hash`もここでの出力を基準にする。

**`src/codegen/codegen.py`**
意味ASTから、互いに等価な複数のPython実装を生成する`generate(ast, style)`と、あるASTから
作れる構造的に異なるコード候補を全部列挙する`enumerate_candidates(ast)`。`interp.py`とは
opの計算を意図的に別々に書く（差分テストが意味を持つように）。内包表記/ループ・一時変数・
reverse方式・return形式・注釈・条件式の順序という6つの構造の軸を持ち、変数名は含めない
（抽出スクリプト側でコーパス全体を均しながら選び、仕上げに差し込む想定）。

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

**`src/nlg/nlgen.py`**
意味ASTから、承認済み日本語表現辞書（`phrases/ja_phrases_v1.yaml`）を使って指示文を組み立てる
`enumerate_candidates(ast, phrases)`。`codegen.py`の日本語版で、opごとに複数ある承認済み
言い回しの直積を全部列挙する（間引きはしない）。複数opは連用形連結（C方式）で1文にまとめ、
そのための活用変換`to_renyou()`（語尾の変換規則`RULES`を長い語尾から順に試す。知らない語尾は
`ValueError`）も持つ。辞書自体は読み込まず、呼び出し側が渡す（依存性注入。`yaml`は`src/`から
使えないため）。

**`src/verify/safety.py`**
生成コードが許可リストの範囲内かを検査する`check(code)`。禁止リスト方式ではなく許可リスト
方式（危険な構文を全部列挙するのは不可能なため）。許可する構文・関数・属性の集合は、
`codegen.enumerate_candidates`の実際の出力を`ast.walk`して実地に洗い出した。指定シグネチャ
（`def solve(xs, k):`）を守っているかもここで見る。対象は自分たちのcodegenの出力だけでなく、
将来ここを通す学生モデル生成コードも含む。

**`src/verify/sandbox.py`**
検査済みコードを制限時間つきで実行する`execute(code, xs, k)`。`exec()`する前に必ず
`safety.check()`を呼び直す（呼び出し元が検査を怠っても最後の砦になる）。`__builtins__`も
最小限に絞り、`signal.setitimer`で制限時間（既定1秒）を超えたら`ExecutionTimeout`にする。

**`src/select/combination.py`**
組合せ汎化テスト用に、`RESERVED_PAIRS`（`{even,desc}`・`{add_k,take_first}`・`{gt,reverse}`の
3組）を両方揃って含むASTを`carve_out_combinations()`で隔離する`src/select/`の最初の処理。
単体のopは訓練に残す。267,744件中16,962件（6.34%）が隔離され、`split.py`はこれを除いた
残りだけを対象に分割する。

**`src/select/split.py`**
意味ASTのレコードを`behavior_hash`のグループ単位でtrain/val/testに分割する`split_corpus()`。
`codegen`が連続filterの条件式を並べ替えるため、別の意味ASTが生成コードの文字列として
一致し得る（`[even,ge]`と`[ge,even]`など）——この2つは`behavior_hash`が一致しているので、
グループを丸ごと同じsplitに入れることでリークを防ぐ。`always_empty`なレコード（22.3%が
1つの巨大グループに集約される）だけは例外的にグループ制約を外し、個別に無作為分割する。
267,744件で検証済み（比率80.0/10.0/10.0%、リーク0件）。

**`src/select/difficulty.py`**
`select_difficulty_thinned()`。`difficulty`1〜3は全数、`difficulty=4`（全体の95%以上）だけ
無作為に間引いて目標AST数に近づける。均等化はしない——`difficulty=1`(24種類)に他を揃えると
上限を撤廃してもコーパスが目標トークン数に対して2桁以上小さくなるため。演算子の出現頻度は
元々ほぼ均等なので、間引きだけで頻度の均等も保たれる（実測比率1.28倍→1.276倍）。

**`src/select/balance.py`**
`select_examples()`。コード形式（内包表記/ループ等の構造6軸）と日本語テンプレート（言い回し
ID）を、コーパス全体を通した採用数`Counter`を見ながら貪欲法で選ぶ。`codegen`/`nlgen`の
`enumerate_candidates`が返す全候補から、AST 1件ごとに一番採用数が少ない軸の値を優先して
選び、コードと文をそれぞれ`cap`件まで選んでから対にする。300ASTの実データで検証済み
（4,783例、sandbox経由で0エラー）。

**`src/select/record.py`**
選ばれた訓練例（`balance.Example`）を最終レコードのスキーマへ組み立てる`build_record()`。
`code_style`は実際に持っている7軸（内包表記/ループ・一時変数・reverse方式・return形式・
注釈・条件式の順序・変数名）をそのまま構造化し、`prompt_hashes`は`phrases/`の由来対応表
（`ja_phrases_v1_provenance.json`）から引く（1レコードの指示文は複数opの言い回しを組み合わせる
ため複数になりうる）。`verification`は仮の値を置かず、`safety.check()`と`sandbox.execute()`を
その場で走らせて`syntax_ok`/`ast_safe`/`tests_passed`を判定する。`tests`は常に空リスト
（hidden testは評価フェーズで別途生成するものであり、訓練レコードに先に埋め込むと後で使い回した
ときにもう「隠し」ではなくなるため）。

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

**`scripts/try_codegen.py`**
`data/asts.jsonl`から`--ast-id`で1件引く（または`--ops`でop名を直接指定する）か`--seed`で
スタイルを選び、`codegen.generate()`の出力を1本だけ標準出力に印字する試験用スクリプト。
`data/asts.jsonl`全267,744件への一括生成はまだ行わない。

**`scripts/build_phrases.py`**
`scripts/teacher/op_seeds.yaml`の種から24opぶんのプロンプトを組み、教師モデル（Qwen3-4B-AWQ）に
日本語の言い回しを生成させ、`phrase_filters`で弾いて`data/teacher/phrases_raw.jsonl`に
由来つきで記録する駆動スクリプト。出力は辞書ではなく**候補**であり、承認は人間が行う。
`review_phrases.py`の判定があればそれも読み、承認済みを追加の正例・却下済みを反例として
プロンプトに載せる（機械の検査は形式しか見ないので、これを読まないと生成側は
「何が良い言い回しだったか」を永遠に知らない）。

**`scripts/review_phrases.py`**
候補を1件ずつキー入力で承認・却下し、`phrases/ja_phrases_v1.yaml`と、言い回しIDごとの生成由来
をまとめた`phrases/ja_phrases_v1_provenance.json`を書き出す対話スクリプト。**意味の検査を行う
唯一の場所**であり、`phrase_filters`が通したことは形式が整っていることしか意味しない。判定は
`phrases/phrase_decisions.jsonl`に随時書くので中断・再開できる。出力を`data/`でなく`phrases/`
に置くのは、人間の判断が入っていて再生成できないためである。

**`scripts/build_dataset.py`**
`src/select/`の5ファイルをこの順（`combination`→`split`→`difficulty`→`balance`→`record`）で
呼び出し、意味ASTコーパスから最終的な訓練/検証/テストデータセット（`data/dataset/*.jsonl`）を
組み立てる駆動スクリプト。実行前に`build_probe_set.py`・`build_ast_corpus.py`・
`review_phrases.py --compile`が済んでいる必要がある。train/val/testに加えて、組合せ汎化テスト
（隔離した予約ペアAST由来）・言い換えテスト（保留分の言い回しだけで作る）を固定30件ずつ別ファイル
に書き出す（人が目で見て確認できる規模に留める）。境界値テストは別ファイルを作らない——
`probes/behavior_probe_set_v1.jsonl`の境界値入力を評価スクリプトが生成済みコードに流し込むだけで
足りるため。均しの`Counter`（`code_counts`・`phrase_counts`）はtrain/val/test・特殊テスト間で
混ぜず、split単位で完結させる。`--limit-asts`で動作確認用に規模を絞れる。

**`scripts/teacher/qwen.py`**
教師モデルに実際に触る唯一のファイル。revision固定・`BACKEND.AWQ_GEMM_TRITON`・非thinkingモード
という構成を、読み込み・プロンプト組み立て・生成の3関数にしたもの（バックエンドの選択は生成速度を
5.6倍変えるので、既定の自動選択に任せない）。
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

**`data/dataset/`**
`build_dataset.py`の出力一式。`train.jsonl`/`val.jsonl`/`test.jsonl`が本体で、
`test_combination.jsonl`（組合せ汎化テスト）・`test_paraphrase.jsonl`（言い換えテスト）は
それぞれ固定30件の小規模な集合として別ファイルに分けてある。各行は`src/select/record.py`の
`build_record()`が組み立てた最終レコード（`spec_id`・`instruction_ja`・`reference_code`・
`verification`など）。境界値テストは別ファイルを作らない——`probes/behavior_probe_set_v1.jsonl`
に境界値入力が既に含まれているため。

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

**`phrases/ja_phrases_v1_provenance.json`**
`review_phrases.py`が辞書と同時に書く、言い回しID（`ge-05`など）ごとの生成由来
（`run_id`・`prompt_sha256`・`decided_at`）。`ja_phrases_v1.yaml`のIDは承認日時順の連番であり、
`phrase_decisions.jsonl`はこのIDを持たない（`phrase`本文をキーにしている）ため、1レコードの
指示文が複数opの言い回しを組み合わせて作られても、`src/select/record.py`の`build_record()`が
`example.phrase_ids`からこのファイルを引いて`prompt_hashes`を復元できるようにしている。
