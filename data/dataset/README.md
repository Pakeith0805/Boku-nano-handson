# Dataset Card: Boku-nano synthetic dataset

`scripts/build_dataset.py`が生成する、日本語指示→Python関数の合成データセット。
「Boku-nano」（限定されたPython関数を生成するSmall Language Model）を、ランダム初期値から
学習させるための訓練/検証/テストデータである。

## Dataset Summary

固定シグネチャ`def solve(xs: list[int], k: int) -> list[int]:`を持つPython関数を対象に、
24種類の基本操作（`even`・`ge`・`add_k`・`asc`・`take_first`など、抽出・変換・並べ替え・
切り出しの4カテゴリ）を1〜4個組み合わせた問題を、日本語の指示文とその正解コードのペアとして
機械的に生成したデータセット。指示文・正解コードのどちらも人手では書かず、ルールベースの
生成器（`src/codegen/`・`src/nlg/`）と、参照インタプリタ（`src/interp/`）による全件実行検証を
通したものだけを採用している。

| 項目 | 値 |
| --- | --- |
| レコード総数 | 1,010,707件 |
| 対象タスク | 日本語指示からのコード生成（instruction-to-code） |
| 言語 | 指示文: 日本語 / コード: Python 3 |
| ライセンス | 生成器・コードは本リポジトリのライセンスに従う。指示文の言い回しの一部は教師モデル（`Qwen/Qwen3-4B-AWQ`、Apache License 2.0）由来。詳細は`THIRD_PARTY.md`参照 |

## Supported Tasks

- **instruction-to-code**: 日本語の指示文（`instruction_ja`）を入力し、`solve(xs, k)`の
  実装（`reference_code`）を出力する。評価は文字列一致ではなく、固定入力集合に対する
  実行結果の一致で行う想定（`verification.tests_passed`と同じ基準）。

## Dataset Structure

### Splits

| split | ファイル | 件数 | サイズ |
| --- | --- | ---: | ---: |
| train | `train.jsonl` | 820,763 | 約1.12 GiB |
| validation | `val.jsonl` | 95,164 | 約132 MiB |
| test（通常テスト） | `test.jsonl` | 94,720 | 約131 MiB |
| test（組合せ汎化テスト） | `test_combination.jsonl` | 30 | — |
| test（言い換えテスト） | `test_paraphrase.jsonl` | 30 | — |

分割は`ast_id`単位ではなく**`behavior_hash`単位**で行っている（`src/select/split.py`）。
連続するfilterの条件式は順序を入れ替えても結果が同じなため、別の意味ASTが同一の挙動・
同一のコード文字列になり得る（`[even, ge]`と`[ge, even]`など）。この2つが別splitに
分かれるとリークになるため、`behavior_hash`が同じASTのグループは必ず同じsplitへ丸ごと
割り当てている。

**組合せ汎化テスト**（`test_combination.jsonl`）は、`{even,desc}`・`{add_k,take_first}`・
`{gt,reverse}`の3組を両方揃って含む意味ASTを訓練・検証から完全に除外し（16,962件、全体の
6.3%）、その中から30件をhidden testとして使う。単体のop（`even`単体など）は訓練に残して
いるため、「個々の操作は学習したが、その組合せは見ていない」場合の汎化を測れる。

**言い換えテスト**（`test_paraphrase.jsonl`）は、日本語の言い回し辞書のうち承認日時が
11番目以降（`TRAIN_PHRASE_LIMIT=10`）の、訓練に一度も使っていない言い回しだけを使って
作った30件。

### Fields

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `spec_id` | str | レコード通番（`task-000001`形式、ファイル内で一意） |
| `ast_id` | str | 元になった意味AST（`data/asts.jsonl`）への引き当てキー |
| `semantic_ast` | list[str] | 操作列（例: `["ge", "positive", "lt"]`）。定数は含まない |
| `instruction_ja` | str | 日本語の指示文 |
| `reference_code` | str | 正解コード全文（`def solve(...):`から） |
| `phrase_ids` | list[str] | 指示文の組み立てに使った言い回しID（例: `["ge-02", ...]`）。`phrases/ja_phrases_v1.yaml`への引き当てキー |
| `tests` | list | 常に空。hidden testは評価時に別途生成する想定（訓練データに埋め込むと「隠し」でなくなるため） |
| `difficulty` | int | 組み合わせた操作の個数（1〜4） |
| `code_style` | dict | コードの見た目の軸7つ（`comprehension`・`temp_vars`・`reverse_style`・`one_line_return`・`annotate`・`reordered`・`elem_name`・`var_name`） |
| `semantic_hash` | str | 操作列の正準表現のSHA-256 |
| `text_hash` | str | `instruction_ja`のSHA-256 |
| `teacher_model` / `teacher_revision` | str | 言い回し生成に使った教師モデルの同一性 |
| `prompt_hashes` | list[str] | `phrase_ids`それぞれの生成プロンプトのSHA-256（複数opぶんの言い回しを組み合わせるため複数になりうる） |
| `verification` | dict | `syntax_ok`・`ast_safe`・`tests_passed`（本データセットは全件`true`） |

### Data Instance（例）

```json
{
  "spec_id": "task-000419",
  "ast_id": "ast-004458",
  "semantic_ast": ["ge", "positive", "lt"],
  "instruction_ja": "整数を要素に持つリストに対して、k以上のもののみを抽出し、正の値を残し、kよりも小さな値を残すsolve関数を書いてください。",
  "reference_code": "def solve(xs, k):\n    _buf = []\n    for item in xs:\n        if item >= k and item < k and item > 0:\n            _buf.append(item)\n    ys = _buf\n    return ys\n",
  "phrase_ids": ["ge-02", "positive-01", "lt-09"],
  "tests": [],
  "difficulty": 3,
  "code_style": {
    "comprehension": false, "temp_vars": false, "reverse_style": false,
    "one_line_return": true, "annotate": false, "reordered": true,
    "elem_name": "item", "var_name": "ys"
  },
  "semantic_hash": "43783d1e...",
  "text_hash": "19c8e9ca...",
  "teacher_model": "Qwen/Qwen3-4B-AWQ",
  "teacher_revision": "74d4bd2bd4bff9cafc9345221320bffb08b406a3",
  "prompt_hashes": ["05df4401...", "9ecf6526...", "e463f302..."],
  "verification": {"syntax_ok": true, "ast_safe": true, "tests_passed": true}
}
```

## Dataset Creation

### 生成手順

```
combination.py（組合せ汎化テスト用に隔離）
  → split.py（behavior_hash単位でtrain/val/testに80/10/10分割）
    → difficulty.py（difficulty 1〜3は全数、4だけ間引く。65,000AST相当に調整）
      → balance.py（コード形式7軸・日本語言い回しを貪欲法で均等に選ぶ、1ASTにつき最大20例）
        → record.py（最終レコードへ組み立て・全件検証）
```

詳細な設計判断は`src/select/README.md`を参照。

### Source Data

- **意味ASTの構造**: 24opから1〜4個を順序付きで選ぶ全267,744通りのうち、上記の間引きを
  経て52,000（train）+6,500（val）+6,500（test）+16,962（組合せ汎化テスト母集団）＝
  約82,000種類を使用。難易度分布はtrainで`{1: 180件, 2: 6,486件, 3: 153,693件, 4: 660,404件}`
  （AST単位ではなくレコード単位）。演算子の出現頻度は元の母集団が均等（1.28倍以内）なため
  追加調整なしでほぼ均等（train内で最小102,005〜最大161,626）。
- **正解コード**: `src/codegen/codegen.py`（ルールベース、参照インタプリタとは独立実装）。
  内包表記/forループ・一時変数の有無・変数名・条件式の順序・reverse方式・return形式・
  コメント/型注釈の有無、という7軸の組み合わせで生成する。train内の実測でcomprehension
  True/False比は491,747/329,016、annotate True/False比は410,349/410,414とほぼ半々。
- **日本語指示文**: `src/nlg/nlgen.py`が、教師モデル（`Qwen/Qwen3-4B-AWQ`）に生成させ
  人間が査読・承認した言い回し辞書（`phrases/ja_phrases_v1.yaml`、279件）から、opごとの
  言い回しを連用形連結で1文に組み立てる。教師モデルは短い言い換え候補の生成にしか使わず、
  正解コードにも意味ASTの構造にも一切関与しない（詳細は`THIRD_PARTY.md`）。

### Annotations / Verification

人手のアノテーションは無い（全件が生成器の出力）。品質保証は実行検証で行う。

- `ast.parse`に成功するか
- 許可リスト方式の構文検査（`src/verify/safety.py`。import・属性アクセス・ファイル操作は
  構造的に生成し得ない）
- 指定シグネチャ（`solve(xs, k)`）を守っているか
- 制限時間内に実行できるか（`src/verify/sandbox.py`）
- 参照インタプリタ（`src/interp/interp.py`）の出力と、固定入力集合148件**全部**で一致するか
- コード完全重複が無いか（split内でSHA256照合）

**このデータセットは上記全てを通過したレコードだけを含む**（`verification`フィールドは
全件`{"syntax_ok": true, "ast_safe": true, "tests_passed": true}`）。

## Considerations for Using the Data

### 既知の限界

- **長さ上限は未適用**。トークナイザがまだ無く（Phase 2、本データセット作成時点では未着手）、
  課題の目安（1レコード65〜145 tokens）通りの検査ができないため先送りにしている。文字数の
  実測は`reference_code`が37〜511文字（平均208）、`instruction_ja`が37〜104文字（平均74）で、
  明らかな外れ値は無い。
- **既存コードとの長い一致検査は未実施**。生成コードが使える構文・関数はごく少数
  （`abs`/`sorted`/`list`/`reversed`と`.append`のみ）に絞られているため、偶発的な一致が
  起きるとしても短い定型句程度と考えられるが、実際の検査スクリプトはまだ無い。
- **train内のコード完全重複は除去済みだが、意味的な重複は残る**。`behavior_hash`が一致する
  別々の意味AST（`[even,ge]`と`[ge,even]`など）が同じsplit内に混在するのは意図した設計
  （リーク防止のため同じsplitへ丸ごと入れている）であり、文字列としては異なるが機能的には
  同一のコードが訓練データ内に複数存在しうる。

### ライセンス・由来

指示文の言い回しの一部は`Qwen/Qwen3-4B-AWQ`（Apache License 2.0）の出力を人間が査読して
採用したもの。詳細な来歴（LICENSE原文の所在・revision・使用範囲）は`THIRD_PARTY.md`を
参照。正解コード・生成器のソースはこのリポジトリのライセンスに従う。

## Additional Information

- **再現方法**: `python -m scripts.build_probe_set` → `python -m scripts.build_ast_corpus` →
  （`python -m scripts.build_phrases`と`python -m scripts.review_phrases`で辞書を作成済みで
  あること）→ `python -m scripts.build_dataset`。乱数のseedは固定（既定0）だが、教師モデルの
  言い換え候補生成自体は再現性が弱い（`data/README.md`参照）ため、辞書を作り直すと指示文の
  表現は変わりうる。
- **関連ドキュメント**: `src/select/README.md`（選抜パイプラインの設計）、
  `src/codegen/README.md`（コード生成の7軸）、`src/nlg/README.md`（日本語文生成）、
  `THIRD_PARTY.md`（教師モデルの来歴）。
