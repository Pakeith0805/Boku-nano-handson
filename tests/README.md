# tests/

参照インタプリタ、op定義、入力範囲、ASTレコード形式、srcの依存境界を確認するpytest群です。
モデルの学習・生成、データ分割、全生成データの正しさを網羅するテスト群ではありません。

リポジトリルートから実行します。

```bash
uv sync --group dev
uv run pytest
uv run pytest tests/test_interp_ops.py
```

`pyproject.toml` の `pythonpath = ["."]` と `testpaths = ["tests"]` を利用します。
以下のテスト関数はpytestから呼ばれ、通常は値を返さず、失敗時にassertion等を送出します。
引数のあるテストは `pytest.mark.parametrize` で複数ケースに展開されます。

## test_core_has_no_external_deps.py

`src/` のimportを構文木で調べ、外部依存が入り込んでいないか確認します。モジュールをimportして実行する検査ではありません。

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `ROOT / SRC / SOURCE_FILES` | リポジトリルートと `src/**/*.py` の走査結果 |
| `LOCAL_ROOTS` | 自リポジトリのimportとして許す `{"src"}` |

### 関数

| 関数 | 検証内容・役割 |
| --- | --- |
| `imported_roots(path)` | 内部ヘルパー。ファイルをASTで読み、絶対importのトップレベル名を集合で返す。相対importは除外する |
| `test_source_files_were_found()` | 走査対象のPythonファイルが1件以上あることを確認する |
| `test_module_imports_only_stdlib(path)` | 各srcモジュールが標準ライブラリまたはsrcだけをimportしていることを確認する |
| `test_module_does_not_import_the_teacher_stack(path)` | 各srcモジュールにtorch等の教師用スタックへのimportがないことを確認する |

## test_interp_ops.py

各opの結果と `run` の合成処理を、手書きの期待値で検査します。

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `CASES` | op・入力・k・期待値の表。境界値や順序の違いも含む |

### 関数

| 関数 | 検証内容・役割 |
| --- | --- |
| `test_op_computes_the_specified_result(name, xs, k, expected)` | CASESに列挙した入力に対して、各opが手書きの期待値を返すことを確認する |
| `test_every_op_maps_the_empty_list_to_the_empty_list(name)` | 各opが空リストから空リストを返すことを確認する |
| `test_map_ops_preserve_length(name)` | 変換opの適用前後で要素数が変わらないことを確認する |
| `test_order_ops_are_permutations(name)` | 並べ替えopが要素の多重集合を変えないことを確認する |
| `test_desc_and_reverse_are_different_ops()` | 未整列入力でdescとreverseが異なる結果になることを確認する |
| `test_square_output_is_never_negative()` | 検査入力でsquareの出力が全て非負になることを確認する |
| `test_square_then_abs_is_a_degenerate_pair()` | 検査入力でsquareの後のabsが結果を変えないことを確認する |
| `test_run_applies_ops_in_order()` | runがopを指定順に適用することを確認する |
| `test_run_with_an_empty_ast_is_the_identity()` | 空のop列を渡したrunが入力と同じ値を返すことを確認する |
| `test_run_rejects_unknown_op_names()` | 未知のop名でKeyErrorになることを確認する |
| `test_run_does_not_validate_structure()` | runがMAX_OPS超過やop重複を理由に拒否しないことを確認する |
| `test_run_matches_the_uniform_literal_specialization()` | runが同じkを各opへ渡し、一様具体化した計算と一致することを確認する |

## test_limits.py

入力範囲の定数と、`run` が行うkの値域検査を固定します。xsの全入力検証器をテストするものではありません。

### 関数

| 関数 | 検証内容・役割 |
| --- | --- |
| `test_literal_domain_equals_k_domain()` | LITERAL_MIN/MAXとK_MIN/MAXが一致することを確認する |
| `test_limits_match_the_specification()` | 長さ0〜20、要素−100〜100、k=1〜10の定数を確認する |
| `test_empty_list_is_a_valid_input()` | 空リストが正当な入力で、evenを適用しても空であることを確認する |
| `test_run_rejects_k_outside_the_domain(k)` | 値域外のkでrunがValueErrorを出すことを確認する |
| `test_k_lower_bound_is_what_two_ops_depend_on()` | K_MIN=1と、multiple_of/take_lastがk=0をassertで拒否することを確認する |

## test_literal_domains.py

opを定数で具体化するときの値域と、他のopとの振る舞いの衝突を調べます。比較に使う入力は、このファイル内の有限集合です。

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `EXPECTED_DOMAINS` | kを使う10opの期待値域を直接記述した表 |
| `EXCLUSIONS` | 除外した6個の `(op, literal, 衝突相手)` |
| `INPUTS / IDENTITY` | 独自の17入力と、恒等変換なら返す出力列 |

### 関数

| 関数 | 検証内容・役割 |
| --- | --- |
| `behavior(ops, k)` | 内部ヘルパー。指定したop列とkをINPUTS全件に適用した出力タプルを返す |
| `test_expected_domains_cover_every_k_op()` | 期待値の表がkを使う10opを過不足なく含むことを確認する |
| `test_literal_domain_matches_the_expected_value(name)` | 各opのliteral_domainが手書きの期待値と一致することを確認する |
| `test_non_k_ops_have_no_literal_domain(name)` | kを使わないopのliteral_domainが空であることを確認する |
| `test_domain_is_contiguous_up_to_the_maximum(name)` | 各値域が下限から10までの連続値であることを確認する |
| `test_excluded_literals_really_do_collide(name, literal, collides_with)` | 除外値の具体化が、INPUTS上で記載のopまたは恒等変換と一致することを確認する |
| `test_excluded_literals_are_outside_the_domain(name, literal, collides_with)` | 衝突の理由で除外した値がliteral_domainに含まれないことを確認する |
| `test_kept_literals_are_not_equivalent_to_any_single_op(name)` | 残した値の具体化が、INPUTS上で恒等変換やk不要の単一opと異なることを確認する |

## test_no_mutation.py

opと `run` が入力を変更せず、新しいリストを返すことを検査します。

### 関数

| 関数 | 検証内容・役割 |
| --- | --- |
| `test_op_does_not_mutate_its_input_list(name)` | 各opが渡されたリストの内容を書き換えないことを確認する |
| `test_op_returns_a_new_list(name)` | 各opの戻り値が入力リストとは別オブジェクトであることを確認する |
| `test_run_does_not_mutate_its_input_list()` | runが渡されたリストを書き換えないことを確認する |
| `test_run_returns_a_copy_even_for_the_empty_ast()` | 空のop列でもrunが入力の複製を返すことを確認する |
| `test_run_accepts_a_tuple_without_complaint()` | runがtuple入力も受け付けることを確認する |

## test_record_schema.py

その場で組み立てたASTレコードを `src/semantics/schema.json` の記述と照合します。保存済みのasts.jsonl全件の検証や、JSON Schemaバリデータによる完全検証ではありません。

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `SCHEMA_PATH / SCHEMA` | 読み込むschema.jsonのパスと辞書 |
| `KNOWN_UNUSED_PROPERTIES` | schemaに宣言されるが現行レコードにはない `uniform_literal_domain` |

### 関数

| 関数 | 検証内容・役割 |
| --- | --- |
| `sample_record()` | 内部ヘルパー。代表ASTとダミーのhashからレコードを1件作る。生成済みコーパスは読まない |
| `test_record_keys_are_exactly_the_required_fields()` | レコードのキー集合とschemaのrequiredが一致することを確認する |
| `test_every_record_key_is_a_declared_property()` | レコードの全キーがschemaのpropertiesに宣言されていることを確認する |
| `test_declared_but_unused_properties_are_the_known_ones()` | 未出力の宣言がKNOWN_UNUSED_PROPERTIESだけであることを確認する |
| `test_schema_op_list_bounds_match_max_ops(field)` | op関連リストのmaxItemsがMAX_OPSと一致することを確認する |
| `test_schema_difficulty_bounds_match_max_ops()` | difficultyの範囲が1〜MAX_OPSであることを確認する |
| `test_schema_binding_slot_bounds_match_max_ops()` | binding_slotsの件数上限とindexの範囲を確認する |
| `test_schema_literal_domain_bounds_match_the_registry()` | schema上のliteral_domainの範囲をレジストリと照合する |
| `test_schema_categories_enum_matches_the_registry()` | schemaのカテゴリ列挙とCATEGORY_ORDERの集合が一致することを確認する |
| `test_schema_ast_id_pattern_matches_the_digit_count()` | ast_idの正規表現とAST_ID_DIGITSが一致することを確認する |
| `test_sample_record_satisfies_the_declared_patterns_and_types()` | 代表レコードのID・hashの形式と、source・schema_version・difficultyを確認する |

## test_registry_conformance.py

レジストリとインタプリタのop集合、件数、メタデータの形式を照合します。各opの具体的な計算結果はtest_interp_ops.pyの担当です。

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `EXPECTED_CATEGORY_COUNTS` | filter=10、map=8、order=3、slice=3 |

### 関数

| 関数 | 検証内容・役割 |
| --- | --- |
| `test_registry_and_interpreter_have_the_same_ops()` | OP_REGISTRYとOP_IMPLSのキー集合が一致することを確認する |
| `test_op_count_is_24()` | レジストリ・実装・N_OPSが24件で一致することを確認する |
| `test_max_ops_is_4()` | MAX_OPSが4であることを確認する |
| `test_op_names_is_the_sorted_registry()` | OP_NAMESがレジストリのキーを辞書順に並べたtupleであることを確認する |
| `test_spec_name_matches_its_key(name)` | OpSpec.nameと辞書のキーが一致することを確認する |
| `test_uses_k_agrees_with_literal_domain(name)` | uses_kとliteral_domainの有無が一致することを確認する |
| `test_literal_domain_is_a_sorted_subset_of_the_allowed_range(name)` | 値域が昇順・重複なしでLITERAL_MIN/MAX内にあることを確認する |
| `test_category_is_known(name)` | カテゴリがCATEGORY_ORDERのいずれかであることを確認する |
| `test_category_counts_match_the_specification()` | カテゴリ別件数がEXPECTED_CATEGORY_COUNTSと一致することを確認する |
| `test_ja_keys_are_unique_and_non_empty()` | 日本語辞書キーが空でなく、一意であることを確認する |
| `test_shadows_reference_real_ops(name)` | shadowsが自分以外の実在opを指すことを確認する |
| `test_impl_is_callable_with_the_op_signature(name)` | 各実装が(xs, k)で呼べ、整数のlistを返すことを確認する |
