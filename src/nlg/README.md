# src/nlg/

承認済み言い回し（`phrases/ja_phrases_v1.yaml`）から日本語の指示文を組み立てる、日本語の
表層処理。opの意味やop列の妥当性は持たない——それは`src/semantics/`と`src/interp/`の役目。
`src/codegen/`の日本語版にあたり、`codegen.enumerate_candidates`と対になる
`nlgen.enumerate_candidates`を持つ。

## nlgen.py

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `FRAME` | 意味AST→日本語文の書き出し（`"整数を要素に持つリストに対して"`）。`scripts/teacher/op_seeds.yaml`の`frame`と同じ値を複製している（`src/`からYAMLを読めないため） |
| `TRAIN_PHRASE_LIMIT` | 訓練に使う言い回しの番号の上限（10）。`scripts/review_phrases.py`の`TARGET`と同値。現行辞書では全opに1〜10番があり、11番以降は目標超過分。関数自体は件数を保証しない |
| `RULES` | 語尾→連用形の変換規則。長い語尾から順に並んでいる（`える`より先に`る`だけでは見ない） |
| `SentenceCandidate` | 列挙された指示文候補1件を持つdataclass（`phrase_ids`, `text`） |

### 関数

| 関数 | 説明 |
| --- | --- |
| `to_renyou(phrase)` | 終止形の言い回しを連用形に変換する。`RULES`のどれにも合わない語尾は`ValueError` |
| `_concrete(phrase)` | `{k}`プレースホルダを`k`に置き換える内部ヘルパー。生成コードが`k`をパラメータのまま持つため、指示文も具体値に固定しない |
| `_sentence(phrases_in_order)` | 1opにつき1つ選んだ言い回し（AST順）から指示文1本を組み立てる内部ヘルパー。最後のop以外は`to_renyou`で連用形にする |
| `_phrase_index(phrase_id)` | `ge-05`のような言い回しIDから末尾の連番（5）を取り出す内部ヘルパー |
| `split_phrase_pool(phrases, *, train_limit=TRAIN_PHRASE_LIMIT)` | 言い回し辞書を、番号が`train_limit`以下（訓練用）とそれより後（言い換えテスト用）に分ける。番号は承認日時順で、末尾への追加のみなら既存の分割を保てる（過去の承認を削除すると変わり得る）。`train_limit`件しか承認されていないopは言い換えテスト側に出てこない |
| `enumerate_candidates(ast, phrases)` | このASTから作れる日本語指示文を**全部**列挙する（上限なし）。ASTに含まれる各opの承認済み言い回しの直積を取るだけで、間引きは抽出スクリプトの責務。`phrases`は`{op名: {言い回しID: 言い回し文字列}}`の形（依存性注入。呼び出し側がYAMLを読んで渡す）。opが`phrases`に無ければ`KeyError`（`split_phrase_pool`が言い換えテスト側から除いたopを含むASTでは、意図してこの例外が出る） |

### SentenceCandidateのプロパティ

| フィールド | 説明 |
| --- | --- |
| `phrase_ids` | AST順の言い回しIDタプル |
| `text` | 連用形でつないだ指示文 |

不変dataclassで独自メソッドはありません。番号1〜10の存在はこの関数では検証せず、現在の承認済み辞書が満たしている条件です。`RULES` は列挙順に照合する限定的な語尾変換で、日本語全般の活用解析器ではありません。
