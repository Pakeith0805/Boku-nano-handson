# src/select/ — 分割・候補選抜・最終レコード

候補を作る `codegen` / `nlg` に対し、この層は「どれを採用するか」と最終形式への組み立てを担当します。駆動は [scripts/build_dataset.py](../../scripts/build_dataset.py) です。

```text
combination（予約ペアの隔離）
  → split（残りをtrain/val/testへ）
    → difficulty（各splitで難易度4を間引く）
      → balance（コードと指示文を選ぶ）
        → record（形式を整えて検証結果を記録）
```

## combination.py

予約した操作の組を一度も見せずに、その組合せの生成を評価するための分離です。

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `RESERVED_PAIRS` | `{even, desc}`, `{add_k, take_first}`, `{gt, reverse}` の3組 |
| `CombinationSplit` | 隔離結果を持つ不変dataclass |

### CombinationSplitのプロパティ

| フィールド | 説明 |
| --- | --- |
| `remaining` | 予約ペアを含まないASTのIDタプル |
| `reserved` | 予約ペアを1つ以上含むASTのIDタプル |

### 関数

| 関数 | 説明 |
| --- | --- |
| `contains_reserved_pair(ops, pairs)` | 順序を問わず、いずれかの予約ペアを両方含むか返す |
| `carve_out_combinations(records, pairs)` | ASTレコードを走査し、2群のIDを `CombinationSplit` で返す |

全267,744 ASTのうち16,962件を隔離します。1ペアは5,678件に含まれ、**ペアのop自体は重ならなくても、4操作ASTには2ペアを同時に含められます**。その重複72件を引いて `3 × 5,678 − 72 = 16,962` です。

これは操作ペアの隔離です。別の操作列が同じ挙動になる場合まで隔離する処理ではありません。単体opをこの条件で除去することはありませんが、最終的な訓練splitへの採用を個別に保証するわけではありません。

## split.py

予約ペアを除いた母集団を、固定入力上の挙動ハッシュでグループ化して分けます。

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `DEFAULT_RATIOS` | train/val/testの目標比率0.8/0.1/0.1 |
| `Split` | 分割結果の不変dataclass |

### Splitのプロパティ

| フィールド | 説明 |
| --- | --- |
| `train`, `val`, `test` | 各splitのAST IDタプル |

### Splitのメソッド

| メソッド | 説明 |
| --- | --- |
| `bucket_of(ast_id)` | IDが属するsplit名を返し、どこにもなければ `None` |

### 関数

| 関数 | 説明 |
| --- | --- |
| `is_degenerate(record)` | `always_empty` を真偽値で返す。`is_identity` は含めない |
| `_cut(ids, ratios)` | 内部ヘルパー。シャッフル済みのIDを件数比率で3分割 |
| `_assign_groups(groups, ratios, rng)` | 内部ヘルパー。大きい挙動グループから、全体比率に対する不足が最大のsplitへ割り当てる |
| `split_corpus(records, *, ratios=DEFAULT_RATIOS, seed=0)` | 通常ASTは挙動グループ単位、`always_empty` は個別に分割し、合成した `Split` を返す |

通常ASTでは同じ `behavior_hash` が通常3splitを跨ぎません。ただし `always_empty` は全台帳中59,775件が同じ挙動に集まるため例外で、同じ挙動・同じコードがsplitを跨ぐ可能性があります。組合せ汎化テストとの横断的な挙動重複も検査しません。「全データでリーク0」を保証する関数ではありません。

比率はグループのサイズに左右されます。後段の候補数・重複排除もあるため、最終レコード数が厳密に80/10/10になる保証はありません。

## difficulty.py

### 関数

| 関数 | 説明 |
| --- | --- |
| `select_difficulty_thinned(records, *, target_total, seed=0)` | 難易度1〜3の全IDと、難易度4から不足分を無作為抽出したIDを返す |

低難易度だけで `target_total` を超える場合も1〜3は残します。難易度別の均等化ではありません。操作頻度を直接調整する処理もありません。全AST台帳では各opは44,069回ずつ出現しますが、予約ペア隔離・分割・選抜後には偏り得ます。

## balance.py

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `CodeAxisKey` | 構造フラグ6個のタプル。内包表記、一時変数、逆順方式、return形式、注釈、filter並べ替え有無 |
| `Example` | コードと日本語文を対にした不変dataclass |

### Exampleのプロパティ

| フィールド | 説明 |
| --- | --- |
| `ast_id` | 元のAST ID |
| `code` / `code_ops` | コード本文と、filter並べ替えを反映した操作列 |
| `code_style` | `CodeAxisKey` |
| `elem_name` / `var_name` | 要素変数名と段階変数の接頭辞または結果変数名 |
| `instruction` / `phrase_ids` | 日本語指示文とAST順の言い回しID |

### 関数

| 関数 | 説明 |
| --- | --- |
| `code_axis_key(ast_ops, candidate)` | 候補の構造フラグ6個を返す。条件式の変更は元の操作列との不一致で表す |
| `pick_code_candidates(ast_ops, candidates, *, limit, counts, rng)` | 構造タプル全体の採用数が少ない候補を最大 `limit` 件選び、呼び出し側の `counts` を更新する |
| `pick_sentence_candidates(candidates, *, limit, counts, rng)` | 言い回しIDの採用数の合計が少ない候補を最大 `limit` 件選び、`counts` を更新する |
| `_renamed(candidate, rng)` | 内部ヘルパー。候補の変数名を乱数で選び直してコードを再生成 |
| `select_examples(ast_id, ast_ops, code_candidates, sentence_candidates, *, cap, code_counts, phrase_counts, rng)` | 両側を独立に最大 `cap` 件選び、変数名を変え、シャッフルして短い側の件数だけ対にする |

コード側の集計キーは6軸の**組全体**であり、各軸のTrue/Falseを別々に均す方式ではありません。候補プールを一度ソートしてまとめて選び、その後でカウンタを更新するため、同じAST内で1件採るたびに順位を計算し直すわけでもありません。

`build_dataset.py` は各チャンクで独立したカウンタを作ります。全ワーカー共有ではなく、余った候補や後の重複排除で消えた候補も集計から差し引きません。採用数の偏りを抑えるための近似です。

## record.py

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `ProbeInput` | 検証入力 `(xs, k)` の型エイリアス |

### 関数

| 関数 | 説明 |
| --- | --- |
| `_verify(example, probes)` | 内部ヘルパー。構文検査と参照インタプリタへの実行結果照合から3つの検証フラグを返す |
| `build_record(number, example, ast_record, probes, *, provenance, teacher_model, teacher_revision)` | 例・ASTの情報・言い回しの由来・検証結果を最終レコードの辞書にまとめる |

構文が不正なら実行せず、実行例外や不一致は `tests_passed=False` にします。正解は `example.code_ops` の参照実行です。**検証フラグを記録する処理であり、falseのレコードを除外する処理はありません。**

`tests` は常に空リストです。現在の評価は [scripts/evaluate.py](../../scripts/evaluate.py) が外部の凍結probe setを読み、新規hidden入力は生成しません。`prompt_hashes` は由来が見つかった言い回しのハッシュだけを重複除去して並べるため、由来の完全性を検証するフィールドではありません。

データ生成時のトークン長フィルタは未実装です。トークナイザは既にあり、訓練用の `model.data.iter_padded_records` は系列長超過で例外を送出します。最終フィールドの一覧は [Dataset Card](../../data/dataset/README.md) を参照してください。
