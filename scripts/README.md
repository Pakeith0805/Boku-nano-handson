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
