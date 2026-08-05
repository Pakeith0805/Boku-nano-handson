# src/semantics/

意味ASTのデータ構造・opメタデータ・指紋計算・レコード組み立て。opの**意味**（実際の計算）は
持たない——それは`src/interp/`の役目。ここにあるのはopの**メタデータ**と、それを使った
構造的な導出・集計だけ。

## registry.py

24種類のopのメタデータ。**意味を持たない**（lambda・コード文字列・`eval`を一切持たない）。

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `REGISTRY_VERSION` | レジストリの版。op名・カテゴリ・値域を変えたら上げる |
| `MAX_OPS` | 1つの意味ASTに組み合わせる操作数の上限（4） |
| `LITERAL_MIN` / `LITERAL_MAX` | リテラルに使える値の範囲（1〜10、`k`の値域と同一） |
| `Category` | opのカテゴリの型（`"filter" \| "map" \| "order" \| "slice"`） |
| `CATEGORY_ORDER` | `canonical_order`の判定に使うカテゴリの並び（抽出→変換→並べ替え→切り出し） |
| `OpSpec` | 1opのメタデータを持つdataclass（`name`, `category`, `uses_k`, `literal_domain`, `ja_key`, `shadows`, `notes`） |
| `OP_REGISTRY` | 24opのメタデータ辞書（`dict[str, OpSpec]`） |
| `OP_NAMES` | 全op名の辞書順タプル。列挙・全数列挙の添字づけの基準 |
| `N_OPS` | opの総数（24） |

### 関数

| 関数 | 説明 |
| --- | --- |
| `_domain(lowest)` | `lowest`以上`LITERAL_MAX`以下のリテラル値域を作る内部ヘルパー |

## semantic_ast.py

意味ASTのデータ構造と、その全数列挙。

### 型

| 名前 | 説明 |
| --- | --- |
| `BindingSlot` | `k`を参照するopの位置と、そのスロットで使えるリテラル値域を持つdataclass。`to_dict()`を持つ |
| `SemanticAST` | op名の順序付き列を持つdataclass。以下のプロパティ・メソッドを持つ |

**`SemanticAST`のプロパティ**

| プロパティ | 説明 |
| --- | --- |
| `difficulty` | 組み合わせた操作の個数 |
| `op_set` | 順序を落としてソートしたop集合 |
| `categories` | 各opのカテゴリをAST順に並べたもの |
| `canonical_order` | カテゴリ順（抽出→変換→並べ替え→切り出し）に従っているか |
| `uses_k` | `k`を参照するopを1つ以上含むか |
| `binding_slots` | `k`参照opの位置と値域をAST順で並べたもの |

**`SemanticAST`のメソッド**

| メソッド | 説明 |
| --- | --- |
| `canonical_json()` | `semantic_hash`の入力になる正準表現（op列だけのJSON） |
| `to_dict()` | レコード形式のうち、op列から決まる部分を辞書で返す |
| `from_dict(data)` | `to_dict()`の逆。`semantic_ast`だけを読み、派生値は再計算して食い違いを検出する（classmethod） |
| `__str__()` | `[ge, double, asc]`の形の文字列表現 |

### 関数

| 関数 | 説明 |
| --- | --- |
| `enumerate_all_asts()` | difficulty 1〜`MAX_OPS`の意味ASTを全て列挙する（267,744件）。参照台帳として全数を作るため、層化サンプリングは行わず`itertools.permutations`をそのまま使う |

## fingerprint.py

意味ASTの指紋（`semantic_hash`と`behavior_hash`）の計算。op評価（`evaluate`）と固定入力集合
（`probes`）はどちらも呼び出し側が渡す（依存性注入）——このファイル自身はopの意味も
probe setの作り方も知らない。

### 型

| 名前 | 説明 |
| --- | --- |
| `ProbeInput` | 固定入力集合の1件。`(xs, k)` |
| `Evaluate` | op列を`(xs, k)`に適用して出力列を返す関数の型 |
| `Fingerprint` | 1つの意味ASTの指紋一式を持つdataclass（`semantic_hash`, `behavior_hash`, `always_empty`, `is_identity`）。`to_dict()`を持つ |

### 関数

| 関数 | 説明 |
| --- | --- |
| `canonical_json(ops)` | op列だけの正準表現（定数・由来情報は含めない） |
| `semantic_hash(ops)` | op列の正準JSONのハッシュ。順序が違えば別の値になる |
| `behavior_outputs(ops, probes, evaluate)` | 固定入力集合に対する出力列 |
| `behavior_hash_of(outputs)` | 出力列からハッシュを作る |
| `behavior_hash(ops, probes, evaluate)` | 固定入力集合に対する出力列のハッシュ |
| `is_always_empty(outputs)` | 固定入力集合の全入力で出力が空になるか |
| `is_identity_over(probes, outputs)` | 固定入力集合の全入力で入力と同じ出力になるか |
| `fingerprint(ops, probes, evaluate)` | 指紋を一度の評価でまとめて作る |
| `group_by_behavior(op_sequences, probes, evaluate)` | `behavior_hash`ごとにop列をまとめる。衝突グループの報告に使う |

## corpus.py

`asts.jsonl`と`manifest.json`の読み書き。レコードは「op列から決まる値」（`SemanticAST`）＋
「評価しないと決まらない値」（`Fingerprint`）＋「コーパスに載せて決まる値」（この層）の合成。

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `SCHEMA_VERSION` | レコード形式の版。`schema.json`と対応する |
| `SOURCE_RULE` | `source`フィールドの唯一の値（`"rule"`） |
| `AST_ID_DIGITS` | `ast_id`の桁数（6桁） |
| `RecordMeta` | 全レコードに共通で載る由来と版を持つdataclass（`created_at`, `generator_version`, `registry_version`, `probe_set_version`, `schema_version`）。`to_dict()`を持つ |

### 関数

| 関数 | 説明 |
| --- | --- |
| `utc_now_rfc3339()` | 現在時刻をRFC 3339（UTC、秒精度）で返す |
| `format_ast_id(number)` | 連番（1始まり）から`ast_id`（`ast-000001`の形）を作る |
| `build_record(ast, fp, number, meta)` | 1件のレコードを組み立てる |
| `build_records(asts, probes, meta)` | 全レコードと、出力値の絶対値の最大桁数を返す。1つのASTにつき評価は一度だけにする |
| `write_records(path, records)` | JSONLで書き出す（1行1レコード） |
| `read_records(path)` | JSONLを読み戻す |
| `build_manifest(records, probe_count, max_output_digits, meta)` | 1回の生成の要約（difficulty別件数、op出現頻度、behavior_hash衝突統計など）を作る |
| `write_manifest(path, manifest)` | `manifest.json`を書き出す（整形して人が読める形にする） |
| `read_manifest(path)` | `manifest.json`を読む |

## schema.json

`asts.jsonl`の1行（1レコード）のJSON Schema。必須フィールドと型を定義する。関数は持たない。
