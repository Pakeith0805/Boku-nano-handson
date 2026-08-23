# src/codegen/

意味ASTから、互いに等価な複数のPython実装を生成する。「各opをどう計算するか」は
`src/interp/interp.py`と**意図的に別々に**書く（`OP_IMPLS`を呼ばない）。参照インタプリタと
コード生成器が同じ実装を共有すると、片方にバグがあっても差分テスト（同じ意味ASTを両方に通し、
乱数入力での出力を突き合わせる）がそれを検出できなくなるため。ただし、opの記述に曖昧さが残る
もの（`every_other`の基準、`desc`と`reverse`の違いなど）は参照インタプリタが確定させた解釈に
そろえる——独立させるのは「計算の書き方」であって、「何を計算するか」の確定ではない。

生成されるコードはいずれも`def solve(xs, k):`（型注釈は`annotate`次第）で、`k`を参照しない
op列でも引数は常に2つ取る（課題の関数シグネチャが固定のため）。

## codegen.py

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `StageKind` | レンダリング単位の種類（`"map" \| "filtergroup" \| "order" \| "slice"`） |
| `Stage` | レンダリング単位1つを持つdataclass（`kind`, `ops`）。連続する`filter` opは`filtergroup`として1つにまとめる |
| `ELEM_NAME_POOL` | 内包表記／forループの要素変数名の候補（`x`, `v`, `n`, `item`） |
| `STAGE_VAR_POOL` | 段階ごとに一時変数を使うとき（`temp_vars=True`）の変数名の接頭辞の候補（`s`, `step`, `tmp`, `part`） |
| `ACCUM_VAR_POOL` | 1本の式に融合するとき（`temp_vars=False`）で複数行形式のときに使う変数名の候補（`result`, `out`, `answer`, `ys`） |
| `Style` | 生成する1本のコードの見た目を決めるフラグ一式（後述の「軸の一覧」を参照）。`xs`・`k`という引数名そのものは変えない |
| `Candidate` | `enumerate_candidates`が返す候補1件。`style`・`ops`（条件式を並べ替えた場合のop列）・`code`を持つ |

### 関数

| 関数 | 説明 |
| --- | --- |
| `_group_stages(ops, *, shuffle_filters, rng)` | op列を`Stage`の列にまとめる。連続filterは1つの`filtergroup`にし、`shuffle_filters=True`ならその中をその場でシャッフルする（`generate`が単発生成のときに使う経路） |
| `_order_expr(op, var, *, reverse_style)` | `asc`/`desc`/`reverse`を式にする。`reverse_style`で`sorted(v, reverse=True)`系と手動逆順系を切り替える |
| `_slice_expr(op, var, k)` | `take_first`/`take_last`/`every_other`を式にする |
| `random_style(seed)` | `seed`から1つの`Style`をランダムに決める（再現可能）。単発でコードを1本見たいとき用 |
| `_comment_for(stage)` | 段階1つぶんの日本語コメントを作る（`annotate=True`のときだけ使う） |
| `_stage_expr(stage, cur, style)` | 段階1つぶんの式（内包表記・組み込み関数）を作る |
| `_stage_loop_lines(stage, cur, dest, style)` | 段階1つぶんの、明示的な`for`ループ版の行を作る |
| `generate(ast, style=Style())` | 意味ASTを1つの`Style`でPythonソース1本にする。**単発生成のための主関数** |
| `_filter_run_spans(ops)` | 連続するfilter opの区間`(start, end)`を列挙する（長さ2以上のみ） |
| `_op_orderings(ops)` | 条件式の順序違いを表す、意味的に同じop列を全パターン列挙する（`itertools.permutations`） |
| `enumerate_candidates(ast)` | このASTから作れる、構造的に異なるコード候補を**全部**列挙する（上限なし、間引きなし）。**抽出（選抜）のための主関数** |

## 生成される7バリエーション軸

| 軸 | `Style`のフィールド | 効くstage |
| --- | --- | --- |
| 内包表記 / `for`ループ | `comprehension` | map, filtergroup（要素ごとに処理するstageのみ。order/sliceは常に同じ式） |
| 一時変数の有無 | `temp_vars` | 全stage共通 |
| 変数名の変更 | `elem_name` / `stage_var` / `accum_var` | `elem_name`はmap/filtergroupのみ。`stage_var`は`temp_vars=True`時、`accum_var`は`temp_vars=False`時 |
| 条件式の順序変更 | （`Style`ではなくop列そのもの。後述） | 連続filterの区間のみ |
| `reverse=True` / 逆順操作 | `reverse_style` | order stageのうち`desc`と`reverse`だけ（`asc`には効かない。該当opが無いASTでは完全に無効） |
| 1行`return` / 複数行形式 | `one_line_return` | `temp_vars=False`かつ`comprehension=True`（1本の式に完全融合できたとき）だけ |
| コメント・型注釈の有無 | `annotate` | シグネチャ全体＋全stage |

## 条件式の順序変更の仕組み

「隣接する2つ以上のfilterは、同じ要素を独立に判定するだけなので順序を入れ替えても結果が
変わらない」という性質を使い、`_op_orderings`が**op列というタプルそのものを並べ替えて**
別の（挙動は同じ）`SemanticAST`を作り、それを普通の`generate()`にそのまま渡している。
`generate()`側に「シャッフルモード」のような特別扱いは無く、渡された`variant`を他の意味ASTと
区別せずに処理するだけである。

対象になるのは次の条件を両方満たす区間だけ。

- **filterカテゴリのopであること**（map/order/sliceは対象外。可換ではないため）
- **連続していること**（間にmap/order/sliceが1つでも挟まると、そこで区間が切れる）

例えば`even, add_k, ge`は両方filterだが`add_k`で分断されているため並べ替えの対象外
（`ge`の判定基準が「元の値」か「kを足した後の値」かで意味が変わってしまう）。
`MAX_OPS=4`のもとでは、長さ2以上の区間が同時に2つ存在することはない（区切りに他カテゴリの
opが最低1個要るので、2区間なら最低2+1+2=5opsが要る）ので、区間は多くとも1つ、最大でも
4連続（`4!=24`通り）にしかならない。

`[even, ge]`と`[ge, even]`のように、この並べ替えで**別の意味AST（別の`ast_id`）と同一の
生成コード文字列になり得る**。これは意図的に許容している——この2つは`behavior_hash`も
一致する（挙動が完全に同じ）ため、訓練/検証/テスト分割を`behavior_hash`のグループ単位で
行う設計のもとでは、同じグループは常に同じsplitに入るので、別split間でこの文字列が衝突する
ことはない。

## 均し方の設計（抽出スクリプト向け）

`enumerate_candidates`はASTから作れる候補を全部返すだけで、**何件・どれを実際に採用するかは
一切決めない**。それは`scripts/`側の抽出スクリプトの責務であり、次の2段構えを想定している。

1. **構造の軸（6つ）をコーパス全体で均す** — `comprehension`・`temp_vars`・`reverse_style`・
   `one_line_return`・`annotate`・条件式の順序（`Candidate.ops`が元の`ast.ops`と同じか、
   どう並び替わっているか）を、コーパス全体を跨いだ`Counter`で今の採用数を見ながら、
   一番不足している軸の値を持つ候補を優先して選ぶ貪欲法を想定している。
   `Candidate.style`だけを見ても条件式の順序は分からない点に注意（`Candidate.ops`を見る）。
2. **変数名（2つ）は均さず、選ばれた候補にラウンドロビンで仕上げる** — `elem_name`・
   `stage_var`/`accum_var`は表層的な違いでしかないので、コーパス全体で均等にする価値が薄い。
   ①で選ばれた`Candidate`に対して、`Candidate.style`をコピーして好きな名前を差し込み、
   `generate(SemanticAST(candidate.ops), 名前入りstyle)`を呼び直せば済む。

`enumerate_candidates`が変数名を含めずに列挙しているのは、この2段構えを前提にしている
ためである（変数名まで総当たりすると件数が膨らみ、①の集計が数えにくくなる）。
