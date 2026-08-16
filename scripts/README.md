# scripts/

実際に実行するスクリプト群。`python -m scripts.<ファイル名>`の形で実行する。

依存の順序は次のとおり。左のスクリプトの出力が右の入力になる。

```
build_probe_set  →  build_ast_corpus  →  build_bindings
                    （probe set を読む）  （asts.jsonl を読む）

build_phrases  ⇄  review_phrases
（候補を生成）    （承認して辞書にする。判定は次の生成のプロンプトに戻る）
```

上段（意味AST側）と下段（日本語表現側）は独立していて、どちらを先に流してもよい。
下段だけが教師モデルを使うため`uv sync --group teacher`を要求する。

## build_probe_set.py

固定入力集合（probe set）を生成して`probes/behavior_probe_set_{version}.jsonl`に凍結する。

```
python -m scripts.build_probe_set
python -m scripts.build_probe_set --force   # 既存の凍結ファイルを上書きする
```

### 定数

| 名前 | 説明 |
| --- | --- |
| `VERSION` | 生成する固定入力集合の版（`src.probes.behavior_probes.PROBE_SET_VERSION`を参照） |
| `SEED` | 乱数の種 |
| `RANDOM_COUNT` | 境界値に加えて最初に足す乱数の件数 |
| `MAX_PROBES` | 入力集合の上限 |
| `EXTERNAL_COUNT` | 偽の衝突検証に使う外部入力の件数 |
| `VERIFY_MAX_DIFFICULTY` | 偽の衝突を潰す検証をどのdifficultyまで行うか（4＝全数267,744件対象） |
| `ROOT` / `OUT` | リポジトリルートと凍結ファイルの出力先 |

### 関数

| 関数 | 説明 |
| --- | --- |
| `main()` | ①`build_probe_set`で境界値＋乱数の入力集合を作る、②`enumerate_all_asts`から対象difficultyのop列を取り、`grow_until_no_false_collisions`で偽の衝突が0件になるまで育てる、③結果を報告し、既存の凍結ファイルと違えば`--force`なしでは書き換えずに止める |

## build_ast_corpus.py

意味ASTのコーパス（`data/asts.jsonl`）とその要約（`data/manifest.json`）を生成する。
参照台帳として267,744件（difficulty 1〜4の全数）を作るので、層化配分やseedによる抽出は
行わない。実行前に`build_probe_set.py`で固定入力集合を凍結しておく必要がある。

```
python -m scripts.build_ast_corpus
```

### 定数

| 名前 | 説明 |
| --- | --- |
| `ROOT` | リポジトリルート |
| `OUT` | `asts.jsonl`の出力先（`data/asts.jsonl`） |
| `MANIFEST_OUT` | `manifest.json`の出力先（`data/manifest.json`） |

### 関数

| 関数 | 説明 |
| --- | --- |
| `main()` | 凍結済みの固定入力集合を読み込み、`enumerate_all_asts()`で全ASTを列挙し、`build_records`でレコード化、`build_manifest`で要約を作り、両方をファイルに書き出して結果を報告する |

## build_bindings.py

意味ASTごとに`src.expand.binding.enumerate_bindings`でバインディング（`k`の具体化）を列挙し、
`data/bindings.jsonl`とその要約`data/bindings_manifest.json`を生成する。実行前に
`build_ast_corpus.py`で`data/asts.jsonl`を作っておく必要がある。設定はHydra
（`conf/binding.yaml`）で読み込むため、他の駆動スクリプトと違い`hydra.main`デコレータ経由で
起動する。

```
python -m scripts.build_bindings
python -m scripts.build_bindings binding.include_literal=false   # パラメータ版だけにする
```

### 関数

| 関数 | 説明 |
| --- | --- |
| `main(cfg)` | `cfg.asts_in`（既定`data/asts.jsonl`）を読み、レコードごとに`enumerate_bindings`でバインディングを列挙して`cfg.out`（既定`data/bindings.jsonl`）にJSONLで書き出す。パラメータ版／リテラル版の内訳を`cfg.manifest_out`（既定`data/bindings_manifest.json`）にまとめ、結果を標準出力に報告する |

## build_phrases.py

24opそれぞれの日本語の言い回しを教師モデル（Qwen3-4B-AWQ）に生成させ、機械的に棄却したうえで
`data/teacher/`に由来つきで書き出す。他の`build_*.py`と違って外部モデルを使うため、
`uv sync --group teacher`が要る（`--dry-run`は不要）。

**出力は辞書ではなく候補である。** 日本語表現辞書は人間が承認した資産であり
（`src/semantics/registry.py`の`ja_key`）、ここが書くのはその手前の材料に過ぎない。承認は
`review_phrases.py`が行う。棄却された行も理由つきで全部残す（どの規則が効いたかが分かれば
プロンプトの直し所が分かるため）。

意味の確定は`scripts/teacher/op_seeds.yaml`（人間が書く種）が持ち、このスクリプトは
「種からプロンプトを組み、生成し、行に割り、弾いて、由来つきで記録する」だけを行う。

```
python -m scripts.build_phrases --dry-run              # プロンプトを表示して終わる（GPU不要）
python -m scripts.build_phrases --ops even reverse gt  # opを絞って試す
python -m scripts.build_phrases                        # 本番（24op×5ラウンド、50分前後）
python -m scripts.build_phrases --below-target         # 査読の承認数が目標未満のopだけ回す
```

途中で落ちても`data/teacher/phrases_raw.jsonl`から済んだ`(op, ラウンド)`を読み戻して再開する。

### 査読との往復

`review_phrases.py`の判定（`phrases/phrase_decisions.jsonl`）があれば読み、承認済みの表現を
**追加の正例**として、却下済みを**反例**としてプロンプトに載せる。機械の検査は形式しか見ないので、
これを読まないと生成側は「何が良い言い回しだったか」を永遠に知らない（`sub_k`は機械が24件通したのに
人間の承認は0件だった、という実例がある）。判定があるときは目標達成の判定も承認数で行う。

### 出力先

| 定数 | ファイル | 何が入るか |
| --- | --- | --- |
| `OUT` | `data/teacher/phrases_raw.jsonl` | 1行1候補。採用も棄却も理由つきで残す（追記） |
| `RUNS_OUT` | `data/teacher/phrases_runs.jsonl` | 1行1実行の由来。**再現に要るものはすべてここ**（追記。開始時に一度書き、終了時に結果を足して差し替える） |
| `PROMPTS_OUT` | `data/teacher/prompts.jsonl` | 実際にトークナイザへ渡したプロンプト全文（`prompt_sha256`ごとに1行） |
| `MANIFEST_OUT` | `data/teacher/phrases_manifest.json` | `phrases_raw.jsonl`全体の統計。**実行のたびに上書きされる** |
| `DECISIONS` | `phrases/phrase_decisions.jsonl` | 入力側。`review_phrases.py`が書く判定。無ければ無視する |

`phrases_manifest.json`と`phrases_runs.jsonl`は役割が違う。前者は全体の統計で上書きされるため、
複数回に分けて生成すると最後の実行の情報しか残らない。由来は上書きしてはいけないので後者に追記し、
各レコードの`run_id`から引けるようにしてある。

#### phrases_raw.jsonl の各行

| キー | 中身 | 実例 |
| --- | --- | --- |
| `op` | どのopの候補か | `"abs"` |
| `round` | 何ラウンド目の生成か | `1` |
| `status` | `"accepted"` / `"rejected"` | `"accepted"` |
| `reason` | 棄却理由。通ったら`null` | `null` / `"duplicate"` |
| `phrase` | **辞書に入る形**（`{k}`版）。棄却なら`null` | `"各要素を正の数に変換する"` |
| `normalized` | 正規化後（具体値のまま）。重複判定と再開の突き合わせに使う | `"各要素を正の数に変換する"` |
| `raw` | モデルが出した生の1行（空白込み） | `"各要素を正の数に変換する  "` |
| `run_id` | どの実行か。`phrases_runs.jsonl`への引き当てキー | `"20260816T102945-45b57224"` |
| `seed` | このリクエストの乱数の種 | `20260807` |
| `temperature` | このリクエストの温度 | `0.9` |
| `prompt_sha256` | 投げた全文のハッシュ。`prompts.jsonl`への引き当てキー | `"0bce97d3…"` |
| `prompt_version` | `op_seeds.yaml`の`version` | `"v2"` |
| `registry_version` | `OP_REGISTRY`の版 | `"ops24-v1"` |
| `created_at` | 生成時刻 | `"2026-08-16T10:29:56+09:00"` |

#### prompts.jsonl の各行

`prompt_sha256`ごとに1行で、同じプロンプトを何度投げても増えない。

| キー | 中身 |
| --- | --- |
| `prompt_sha256` | ハッシュ。レコード側と突き合わせる |
| `run_id` / `op` / `round` | このプロンプトを**最初に**使った実行と場所 |
| `system_prompt` | 展開後の全文 |
| `user_prompt` | op固有の部分の全文 |
| `templated_text` | **chat template適用後の全文**（`<\|im_start\|>system`から始まる、トークナイザに渡したそのもの） |
| `created_at` | 記録時刻 |

ハッシュはプロンプトの**同一性**しか保証しない。中身まで復元できなければ「何を投げたら何が出たか」は
分からないので、全文をここに残す。生成の再現に必要なのはこのファイルであり、入力ファイルの
ハッシュではない（だから`decisions_sha256`は持たない）。

#### phrases_runs.jsonl の各行

| キー | 中身 |
| --- | --- |
| `run_id` | 実行の識別子 |
| `started_at` / `finished_at` | 開始・終了時刻（未完了なら`finished_at`が`null`） |
| `model` | `id` / `revision` / `quantization` / `backend` / `thinking_mode` |
| `libraries` | `python` / `torch` / `transformers` / `gptqmodel` |
| `gpu` | `name` / `compute_capability` |
| `system_prompt` | 展開後の全文 |
| `sampling` | `do_sample` / `temperature` / `top_p` / `max_new_tokens` / `n_per_request` / `seed_base` / `seed_formula` |
| `prompt_version` / `registry_version` | 種とレジストリの版 |
| `seeds_sha256` | `op_seeds.yaml`の内容ハッシュ |
| `args` | `ops` / `rounds` / `max_rounds` / `target` / `below_target` |
| `produced` | この実行が生んだ`lines` / `accepted` |

#### phrases_manifest.json

| キー | 中身 |
| --- | --- |
| `model` | `id` / `revision` |
| `params` | `temperature` / `top_p` / `max_new_tokens` / `n_per_request` / `seed_base` / `target` |
| `prompt_version` / `registry_version` | 版 |
| `totals` | `lines` / `accepted` / `rejected` |
| `per_op` | op別の`accepted`と`rounds_run`（24件） |
| `rejection_reasons` | 棄却理由の内訳。どの規則がどれだけ効いたかが分かる |
| `below_target` | 目標未達のop。空なら全op到達 |
| `cross_op_duplicates` | op間で重なった表現。**自動では落とさない**（どちらを残すかは意味の判断なので、査読への申し送りになる） |
| `generated_at` | 作成時刻 |

### 定数

| 名前 | 説明 |
| --- | --- |
| `TARGET` | 1opあたり集めたい採用数の下限（10） |
| `BASE_ROUNDS` / `MAX_ROUNDS` | 目標に届いていても必ず回す回数（5）と、未達opに追加で回す上限（16） |
| `N_PER_REQUEST` | 1リクエストで要求する言い換えの個数（8）。**多く求めるほど質が落ちる**（15個で試すとモデルが数合わせに捏造を始めた） |
| `MAX_NEW_TOKENS` | 1リクエストの生成上限（384）。足りないと最後の行が途中で切れる |
| `TEMPERATURE` / `TOP_P` | サンプリングの設定。貪欲法は使えない（毎回同じ出力になり、ラウンドを重ねる意味が消える） |
| `SEED_BASE` | 乱数の種の基準値。実際の種は`SEED_BASE + OP_NAMES.index(op) * 100 + round`で決まり再現できる |
| `MAX_KNOWN_IN_PROMPT` | 「これ以外を書け」としてプロンプトに載せる既出表現の上限（40） |
| `MAX_REVIEWED_IN_PROMPT` | 査読由来の正例・反例をプロンプトに載せる上限（それぞれ24件） |
| `SYSTEM_PROMPT_TEMPLATE` | system promptの雛形。`{frame}`を`op_seeds.yaml`の書き出しで埋める。書き出しは24op・全ラウンドで不変なのでopごとの指示とは置き場所を分ける |
| `SEEDS_PATH` | 種（`scripts/teacher/op_seeds.yaml`）の場所 |

### 関数

| 関数 | 説明 |
| --- | --- |
| `sha256(text)` | UTF-8文字列のSHA-256（16進）。内部ヘルパー |
| `record_prompt(entry, seen)` | プロンプト全文を`prompts.jsonl`に追記する。同じハッシュを既に書いていれば何もしない |
| `load_prompt_hashes()` | `prompts.jsonl`に既に載っている`prompt_sha256`の集合を読む |
| `load_seeds()` | `op_seeds.yaml`を読み、opのキー集合が`OP_REGISTRY`と一致すること・例文の`{k}`の有無が`uses_k`と一致すること・種に検査用リテラルが裸で書かれていないことを検査する。破れていれば`ValueError` |
| `load_review()` | `phrase_decisions.jsonl`から承認済み／却下済みの表現をop別に読む。無ければ空を返す |
| `build_user_prompt(name, seeds, known, n, good, bad)` | 1op・1ラウンド分のユーザープロンプトを組む。`known`（採用済み）を載せて「それ以外」と指示するのがラウンド間の重複を減らす一番効く手。`good`/`bad`は査読を通った表現と落とされた表現 |
| `load_existing()` | 途中まで書かれた`phrases_raw.jsonl`を読み戻し、`(全レコード, 済んだ(op, ラウンド)の集合, op別の採用済み表現)`を返す |
| `run_round(model, tokenizer, *, ...)` | 1op・1ラウンド分を生成し、行ごとに`phrase_filters`で正規化・棄却してレコードに割る。プロンプト全文の記録もここで行う。`(レコード列, 所要秒数)`を返す |
| `write_run(run)` | 実行1件の由来を`phrases_runs.jsonl`に追記する（同じ`run_id`の行があれば差し替える） |
| `write_manifest(records, seeds, temperature)` | モデル・パラメータ・op別採用数・棄却理由の内訳・目標未達のop・op間で重複した言い回しをまとめて書く |
| `main()` | 種を検査し、査読の判定を読み、opごとにラウンドを回してJSONLに追記し、最後に要約を報告する |

### 主なオプション

| オプション | 説明 |
| --- | --- |
| `--dry-run` | プロンプトを表示して終わる。モデルを読み込まないのでGPUも teacher グループも要らない |
| `--ops` | 対象のop（既定は24個全部） |
| `--below-target` | 承認数が目標未満のopだけを対象にする。査読の判定が無ければエラーで止まる |
| `--rounds` / `--max-rounds` / `--target` / `-n` / `--temperature` | 同名の定数を上書きする |
| `--quiet-prompts` | 投げたプロンプトを標準出力に出さない（`prompts.jsonl`には必ず残る） |

## review_phrases.py

`build_phrases.py`が集めた候補を1件ずつ承認し、日本語表現辞書
`phrases/ja_phrases_v1.yaml`として凍結する。キー入力で採用・却下していく対話スクリプト。

**ここが「意味の検査」を行う唯一の場所である。** `phrase_filters`が通したことは形式が整っている
ことしか意味しない（実際、機械が通した候補には`abs`に対する「負の値を除去する」＝それは`positive`、
のような誤りが相当数混ざっている）。判定基準を見失わないよう、opごとに`op_seeds.yaml`の`meaning`を
画面に出し続ける。

辞書を`data/`でなく`phrases/`に置くのは、`data/README.md`が「全て`scripts/`配下から再現できる」と
宣言しているのに対し、承認済み辞書は人間の判断が入っていて再現できないため。
`probes/behavior_probe_set_v1.jsonl`と同じ「版つきで凍結された資産」の扱いにする。

```
python -m scripts.review_phrases                              # 続きから査読する
python -m scripts.review_phrases --ops abs                    # opを絞る
python -m scripts.review_phrases --include-rejected not_terminal_form  # 機械が落とした行も候補に戻す
python -m scripts.review_phrases --compile                    # 査読はせず、今の判定から辞書だけ書き直す
```

判定は1件ごとに`phrases/phrase_decisions.jsonl`へ書き出すので、`q`でいつ中断しても続きから
再開できる。判定には候補を生んだ生成の由来（`run_id`など）を焼き付ける——承認済み辞書は生成物より
長く生きる資産なので、`phrases_raw.jsonl`との突き合わせに頼らない。

### キー操作

`y`=採用　`n`=却下　`e`=編集して採用　`s`=保留（記録せず次回また聞く）　`u`=直前の判定を取り消す　`q`=中断して保存

### 定数

| 名前 | 説明 |
| --- | --- |
| `RAW` / `DECISIONS` | 候補（`data/teacher/phrases_raw.jsonl`）と判定の置き場所 |
| `DICT_VERSION` | 辞書の版（`v1`）。`DICT_OUT`・`MANIFEST_OUT`のファイル名に入る |
| `DICT_OUT` / `MANIFEST_OUT` | `phrases/ja_phrases_v1.yaml` と `phrases/ja_phrases_v1_manifest.json` |
| `TARGET` | 1opあたり集めたい採用数の下限（10）。`build_phrases.py`と同じ値 |
| `SIMILAR` | 「採用済みのこれと似ている」と警告する類似度の閾値（0.72、`difflib`の比） |
| `NON_JA_KANJI` | 日本語では使わない字体（簡体字）。含まれていたら警告するが**却下はしない**（網羅的な一覧ではないため） |
| `ORIGIN_FIELDS` | 判定に焼き付ける生成の由来のフィールド名 |

### 関数

| 関数 | 説明 |
| --- | --- |
| `read_key()` | 1文字だけ読む（Enter不要）。端末でないときは行単位の読み込みに落とす |
| `edit_text(text)` | 元の文字列を入れた状態で編集させる。「惜しい」候補を捨てずに直せるようにする |
| `load_candidates(include_rejected)` | `phrases_raw.jsonl`からop別の候補とその由来を読む。`include_rejected`に棄却理由を渡すと、その理由で落ちた行も候補に戻す |
| `chain_order(phrases)` | 似た候補が隣り合うように並べ替える。最短のものから始め、直前に一番似ているものを繋いでいく |
| `load_decisions()` / `save_decisions(decisions)` | 判定の読み書き。保存は毎回まるごと書き直す（`u`＝取り消しを素直に実装するため） |
| `show_header(op, meaning, approved, n_done, n_total)` | opの見出し（意味・採用数・採用済み一覧）を出す |
| `show_candidate(phrase, approved, index, total)` | 候補1件と、類似警告・字体警告・キー一覧を出す |
| `compile_dictionary(decisions, seeds)` | 判定から辞書を組み、検証して書き出す。op間で表現が重複していれば、または`phrase_filters.check`に反する表現があれば、**書かずに止めて人に返す** |
| `main()` | 判定を読み、opごとに候補を並べて1件ずつ捌き、最後に`compile_dictionary`を呼ぶ |
