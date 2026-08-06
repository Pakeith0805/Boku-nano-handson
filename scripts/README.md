# scripts/

実際に実行するスクリプト群。`python -m scripts.<ファイル名>`の形で実行する。

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
`data/teacher/phrases_raw.jsonl`と`data/teacher/phrases_manifest.json`に書き出す。他の
`build_*.py`と違って外部モデルを使うため、`uv sync --group teacher`が要る（`--dry-run`は不要）。

**出力は辞書ではなく候補である。** 日本語表現辞書は人間が承認した資産であり
（`src/semantics/registry.py`の`ja_key`）、ここが書くのはその手前の材料に過ぎない。
棄却された行も理由つきで全部残す（どの規則が効いたかが分かればプロンプトの直し所が分かるため）。

意味の確定は`scripts/teacher/op_seeds.yaml`（人間が書く種）が持ち、このスクリプトは
「種からプロンプトを組み、生成し、行に割り、弾いて、由来つきで記録する」だけを行う。

```
python -m scripts.build_phrases --dry-run              # プロンプトを表示して終わる（GPU不要）
python -m scripts.build_phrases --ops even reverse gt  # opを絞って試す
python -m scripts.build_phrases                        # 本番（24op×3ラウンド、40分前後）
```

途中で落ちても`data/teacher/phrases_raw.jsonl`から済んだ`(op, ラウンド)`を読み戻して再開する。

### 定数

| 名前 | 説明 |
| --- | --- |
| `TARGET` | 1opあたり集めたい採用数の下限（10） |
| `BASE_ROUNDS` / `MAX_ROUNDS` | 必ず回す回数と、未達opに追加で回す上限 |
| `N_PER_REQUEST` | 1リクエストで要求する言い換えの個数 |
| `MAX_NEW_TOKENS` | 1リクエストの生成上限。足りないと最後の行が途中で切れる |
| `TEMPERATURE` / `TOP_P` | サンプリングの設定。貪欲法は使えない（毎回同じ出力になる） |
| `SEED_BASE` | 乱数の種の基準値。実際の種はopとラウンドから決まり再現できる |
| `MAX_KNOWN_IN_PROMPT` | 「これ以外を書け」としてプロンプトに載せる既出表現の上限 |
| `SEEDS_PATH` / `OUT` / `MANIFEST_OUT` | 種と2つの出力先 |

### 関数

| 関数 | 説明 |
| --- | --- |
| `load_seeds()` | `op_seeds.yaml`を読み、opのキー集合が`OP_REGISTRY`と一致すること・例文の`{k}`の有無が`uses_k`と一致すること・種にリテラル値が裸で書かれていないことを検査する |
| `build_user_prompt(name, seeds, known, n)` | 1op・1ラウンド分のプロンプトを組む。`known`（採用済みの言い回し）を載せて「それ以外」と指示することで、ラウンドを重ねたときの重複を減らす |
| `load_existing()` | 途中まで書かれた`phrases_raw.jsonl`を読み戻し、済んだ`(op, ラウンド)`と採用済みの言い回しを返す |
| `run_round(...)` | 1op・1ラウンド分を生成し、行ごとに`phrase_filters`で正規化・棄却してレコードに割る |
| `write_manifest(records, seeds, temperature)` | モデル・パラメータ・op別採用数・棄却理由の内訳・目標未達のop・op間で重複した言い回しをまとめて書く |
| `main()` | 種を検査し、opごとにラウンドを回してJSONLに追記し、最後に要約を報告する |
