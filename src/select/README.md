# src/select/

生成された候補（AST・コード・指示文）の中から、実際に訓練コーパスへ入れるものを選び、
最終レコードのスキーマへ組み立てる層。`codegen`/`nlgen`が「作れるものを全部列挙する」のに
対し、こちらは「その中から何を・どれだけ採用するか」を決め（`combination`〜`balance`）、
選んだものを1件のレコードにする（`record`）。

処理の順番は次の通り。`combination.py`が一番先——分割の母集団から先に抜いておかないと、
予約したはずの組合せが偶然train側に混ざる。`scripts/build_dataset.py`がこの順で呼び出す。

```
combination.py（組合せ汎化テスト用の隔離）
  → split.py（behavior_hash単位でtrain/val/testに分割）
    → difficulty.py（difficulty 1〜3は全数、4だけ間引く）
      → balance.py（コード形式・日本語テンプレートを貪欲に均す）
        → record.py（選ばれた例1件ずつを最終レコードへ組み立て・検証）
```

## combination.py

組合せ汎化テスト用に、特定のop組合せを訓練/検証から隔離する。

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `RESERVED_PAIRS` | 予約する3組（`{even,desc}`・`{add_k,take_first}`・`{gt,reverse}`）。カテゴリの組合せに変化を持たせている（抽出×並べ替えを2組、変換×切り出しを1組） |
| `CombinationSplit` | 隔離結果を持つdataclass（`remaining`＝通常の分割に回すast_id、`reserved`＝組合せ汎化テスト専用のast_id） |

### 関数

| 関数 | 説明 |
| --- | --- |
| `contains_reserved_pair(ops, pairs)` | `ops`が予約ペアのいずれかを（順序を問わず）両方含むか |
| `carve_out_combinations(records, pairs)` | 予約ペアを1つ以上含むASTを`reserved`へ、それ以外を`remaining`へ振り分ける。単体でのop（`even`単体など）は`remaining`に残る |

### 隔離の考え方

`RESERVED_PAIRS`の3組で全体の6.34%（16,962件）が隔離される（1組あたり5,678件、互いに
重複しない）。予約ペアを**両方揃って**含むASTだけを除外し、単体のopは訓練に残す——
「個々の操作は学習したが、その組合せは見ていない」という状況を作るのが目的で、op自体を
隠すと組合せ汎化のテストにならないため。267,744件で検証済み（train側への漏れ0件）。

## split.py

意味ASTのレコードを`behavior_hash`のグループ単位で訓練/検証/テストに分割する。

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `DEFAULT_RATIOS` | 既定の分割比率（`{"train": 0.8, "val": 0.1, "test": 0.1}`） |
| `Split` | 分割結果を持つdataclass（`train`, `val`, `test`はどれも`ast_id`のタプル）。`bucket_of(ast_id)`でどのsplitに入っているかを引ける |

### 関数

| 関数 | 説明 |
| --- | --- |
| `is_degenerate(record)` | `always_empty`なレコードか。真なら`behavior_hash`グループの原子性を要求しない対象（`is_identity`は2件しか無いため対象外） |
| `_cut(ids, ratios)` | 既にシャッフル済みの列を比率通りに3分割する内部ヘルパー（グループ制約なし版。退化レコード用） |
| `_assign_groups(groups, ratios, rng)` | `behavior_hash`→`ast_id`列のグループを、グループ単位で3バケツへ貪欲に割り当てる内部ヘルパー。サイズの大きいグループから順に「今一番不足しているバケツ」へ入れる |
| `split_corpus(records, *, ratios=DEFAULT_RATIOS, seed=0)` | 全ASTレコードをtrain/val/testに分ける主関数。退化レコードは個別に無作為分割、それ以外は`behavior_hash`グループ単位で分割し、結果を合成する |

### 分割の考え方

- **分割の単位は`ast_id`でも`semantic_hash`でもなく`behavior_hash`。** `codegen`が連続filterの条件式を並べ替えるため、別の意味AST（`[even, ge]`と`[ge, even]`など）が生成コードの文字列として一致し得る。この2つは`behavior_hash`が最初から一致しているので、グループを丸ごと同じsplitに入れておけば、別split間でのコード文字列衝突（train/testリーク）を防げる。
- **`always_empty`なレコードだけは例外。** これは`behavior_hash`でグループ化すると267,744件中59,775件（22.3%）が1つの巨大グループに集約されてしまい、80/10/10の構成が成立しなくなる。挙動の多様性がほとんど無いぶん、学習上の価値もどの具体的なop列で実現されていてもほぼ差が無いと判断し、個別に無作為分割する。`is_identity`（2件のみ）はこの特別扱いをせず、通常のグループ単位分割に含める。
- **`split_corpus`が保証するのは「リークが無いこと」と「件数比率が概ね80/10/10になること」だけ。** 難易度・演算子頻度・コード形式・日本語テンプレートを均す層は`difficulty.py`/`balance.py`が担う。

## difficulty.py

`difficulty`（操作数1〜4）による意味ASTの間引き。**均等化はしない。**

### 関数

| 関数 | 説明 |
| --- | --- |
| `select_difficulty_thinned(records, *, target_total, seed=0)` | difficulty 1〜3は全数、4だけ無作為に間引いて目標AST数に近づける。採用する`ast_id`の列を返す |

### 難易度の均し方について

`difficulty`1〜4を件数で均等にすると、`difficulty=1`が24種類（学習データのsplit内ではさらに
少ない）しか無いことが律速し、上限を撤廃してもコーパス全体が目標トークン数（数千万〜億単位）
に対して2桁以上小さくなる（実測: train内の`difficulty=1`全19件・上限なしの絶対天井は
1,860組み合わせ）。一方`difficulty`1〜3は合計12,720種類しかなく、全数使ってもトークン予算
への影響はわずかである。したがって**`difficulty`1〜3は全数残し、`difficulty=4`（全体の95%
以上を占める）だけを目標総数に合わせて間引く**。`difficulty=4`は間引いた後も他の水準より
多数派のままであり、これは「均等化」ではない。

演算子の出現頻度は元々ほぼ均等（全体で最小/最大の比率1.28倍）なので、`difficulty=4`を
無作為に間引くだけで頻度の均等はほぼ保たれる（実測でも間引き後の比率1.276倍とほぼ不変）。
追加の頻度調整は行っていない。

## balance.py

コード形式・日本語テンプレートを、コーパス全体で均等になるよう貪欲に選ぶ。
`codegen.enumerate_candidates`/`nlgen.enumerate_candidates`が返す「作れる候補の全部」から、
コーパス全体を通した採用数を`Counter`で追跡しながらAST 1件ごとに選ぶ。

### 型

| 名前 | 説明 |
| --- | --- |
| `CodeAxisKey` | コード候補1件が持つ構造の軸の値のタプル（内包表記/ループ・一時変数・reverse方式・return形式・注釈・条件式を並べ替えたか）。**変数名は含まない**（均す対象ではないため） |
| `Example` | 選ばれた訓練例1件を持つdataclass（`ast_id`, `code`, `code_ops`, `code_style`, `elem_name`, `var_name`, `instruction`, `phrase_ids`）。最終レコードのスキーマ確定はまだ先なので、再構築に要る最低限の情報だけを持つ |

### 関数

| 関数 | 説明 |
| --- | --- |
| `code_axis_key(ast_ops, candidate)` | コード候補1件の`CodeAxisKey`を作る |
| `pick_code_candidates(ast_ops, candidates, *, limit, counts, rng)` | コード候補から`limit`件選ぶ。構造の軸の採用数（`counts`、呼び出し元がAST全件を通して使い回す）が一番少ないものを優先する貪欲法 |
| `pick_sentence_candidates(candidates, *, limit, counts, rng)` | 日本語文候補から`limit`件選ぶ。使っている言い回しID(`phrase_ids`)ごとの採用数の合計が一番少ない候補を優先する |
| `_renamed(candidate, rng)` | 採用が決まったコード候補に、変数名（`elem_name`・`stage_var`/`accum_var`）を無作為に差し込み直し、`generate()`を呼び直して`code`を更新する内部ヘルパー |
| `select_examples(ast_id, ast_ops, code_candidates, sentence_candidates, *, cap, code_counts, phrase_counts, rng)` | 1つのASTについてコードと日本語文をそれぞれ`cap`件まで独立に選び、コード側は`_renamed`で変数名を差し込んでから、シャッフルして位置で対にする。組数はコード・文どちらか少ない方に合わせる |

### 均し方の考え方

候補を1件選ぶたびに、その候補が持つ軸の値の採用数を`Counter`で1つ増やす。次にどの候補を
選ぶかは、現時点で一番採用数が少ない軸の値を持つ候補を優先する（同点はその都度シャッフルして
崩す）。これをAST 1件ずつ繰り返すと、コーパス全体を通して極端に偏った軸の値ができにくい。
呼び出し側（選抜スクリプト）が`Counter`を1つずつ持ち回り、AST全件の処理を通して同じ
インスタンスを使い続けることで、均しが全体に効く。

コード側の軸は、`reverse_style`のように該当opを持つASTにしか存在しない軸があるため、
完全な均等（比率1.0）にはならない（実測で比率6.86倍程度）。これは軸ごとの母集団サイズの
違いによる構造的な上限であり、貪欲法の不具合ではない。日本語の言い回しIDは該当opを持つ
ASTなら基本的にどれでも使えるため、より均等に近づく（実測で比率2.12倍程度）。

## record.py

選ばれた訓練例（`balance.Example`）を、最終レコードのスキーマ（`dict`）へ組み立てる。
スキーマは課題文（改定前）の例をもとに、実際の実装に合わせて調整してある。

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `ProbeInput` | 検証に使う固定入力1件の型エイリアス（`tuple[Sequence[int], int]`＝`(xs, k)`） |

### 関数

| 関数 | 説明 |
| --- | --- |
| `_verify(example, probes)` | `example.code`を検査・実行し、`verification`フィールド（`syntax_ok`/`ast_safe`/`tests_passed`）を作る内部ヘルパー。`safety.check()`に落ちた場合は`ast.parse`自体の失敗かどうかで`syntax_ok`と`ast_safe`を分け、実行はしない。安全なら`probes`の各入力で参照インタプリタ（`interp.run`）の出力と`sandbox.execute()`の出力を比較し、1件でも不一致・例外なら`tests_passed=False` |
| `build_record(number, example, ast_record, probes, *, provenance, teacher_model, teacher_revision)` | 1件の`Example`を最終レコードへ組み立てる主関数。`spec_id`は`number`から`task-{n:06d}`の形で作る。`code_style`は`example.code_style`の6軸に`elem_name`/`var_name`を加えて構造化する。`prompt_hashes`は`example.phrase_ids`を`provenance`（`phrases/ja_phrases_v1_provenance.json`の中身）で引いた`prompt_sha256`の重複無し集合。`tests`は常に空リスト（hidden testは評価フェーズで別途生成するため、訓練レコードには埋め込まない） |

### スキーマ設計の注記

- `teacher_model`/`teacher_revision`は全runで共通の値なので呼び出し側が定数として渡す。
  `prompt_hash`は単数ではなく`prompt_hashes`（複数）にしてある——1レコードの指示文は複数opの
  言い回しを組み合わせて作るため、由来も複数になりうる。
- `verification`は仮の値を置かず、`safety.check()`と`sandbox.execute()`をレコード組み立て時に
  実際に走らせて判定する。
