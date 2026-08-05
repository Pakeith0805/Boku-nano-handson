# src/probes/

`behavior_hash`の基準となる固定入力集合（probe set）の生成と読み書き。

## behavior_probes.py

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `ProbeInput` | 固定入力集合の1件。`tuple[tuple[int, ...], int]`＝`(xs, k)` |
| `PROBE_SET_VERSION` | 既定の固定入力集合の版（`"v1"`）。凍結ファイル名とレコードの`probe_set_version`が参照する |
| `MAX_PROBES` | 入力集合の上限（256件） |
| `DEFAULT_RANDOM_COUNT` | 乱数で足す件数の初期値（50件） |
| `EXTERNAL_SEED_OFFSET` | 偽の衝突検証に使う外部入力の種のずらし幅。固定入力集合と種を分けるためのもの |
| `_BOUNDARY` | 手書きの境界値20件（内部定数）。opの組を分けるために逆算して選んである |

### 関数

| 関数 | 説明 |
| --- | --- |
| `boundary_inputs()` | 境界値20件を`ProbeInput`のリストで返す |
| `boundary_notes()` | 境界値それぞれの選定意図の説明文を返す |
| `random_input(rng)` | 入力条件の範囲（xs長さ0〜20・要素±100・k 1〜10）から`(xs, k)`を1件ランダムに作る |
| `probe_outputs(ops, probes)` | 意味AST`ops`を入力集合の全件で評価した出力列を返す |
| `single_op_outputs(probes)` | 単一opのAST24個それぞれの出力列を返す |
| `indistinguishable_pairs(probes)` | この入力集合では区別できない単一opの組を返す。空なら識別力が足りている |
| `build_probe_set(seed, random_count, max_probes)` | 境界値＋乱数で入力集合を作り、単一op24個が全て区別できるまで乱数を足して育てる |
| `external_inputs(count, seed, exclude)` | 入力集合に**含まれない**ランダムな`(xs, k)`を作る。偽の衝突を探すための材料 |
| `find_false_collisions(op_sequences, probes, external)` | 入力集合の上では出力が一致するのに`external`のどれかで食い違うASTの組（＝偽の衝突）を探す |
| `grow_until_no_false_collisions(probes, op_sequences, external, max_probes, max_rounds)` | 偽の衝突が見つからなくなるまで、見つかった反例そのものを入力集合に追加し続ける |
| `save_probe_set(path, probes, version, random_count)` | 入力集合をJSONLで保存する。境界値には選定意図の注記を添える |
| `load_probe_set(path)` | 保存した入力集合を順序を保って読み戻す（順序が変わると`behavior_hash`も変わるため） |
| `describe(probes)` | 入力集合の要約統計（件数、`k`の網羅、`xs`の長さ分布など）を返す |
| `default_probe_set_path(root, version)` | 凍結ファイルの既定の置き場所（`probes/behavior_probe_set_{version}.jsonl`）を返す |

### 識別力の設計

固定入力集合の目的は「意味の同定」であって、現実的な入力分布の再現ではない。境界値20件は
以下の組を分けるために逆算して選んである。

| 分けたい組 | 要る条件 |
| --- | --- |
| `gt` と `ge`／`lt` と `le` | `xs` に `k` と等しい値を含む |
| `mul_k` と `double` / `triple` | `k not in {2, 3}` |
| `multiple_of` と `even` | `k != 2` |
| `ge` と `positive` | `k != 1` |
| `lt` と `negative` | `k == 1` かつ `xs` に `0` を含む |
| `take_first` と `take_last` | `len(xs) > k` と `len(xs) < k` の両方 |
| `asc` と `desc` と `reverse` | 未整列で相異なる要素を含む |
