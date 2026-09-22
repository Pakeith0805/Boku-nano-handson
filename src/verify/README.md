# src/verify/

生成された`solve(xs, k)`コードが安全かどうかの検査と、制限時間つきの実行。対象は自分たちの
`codegen`が吐くコードだけでなく、`scripts/train.py`・`scripts/evaluate.py` が評価する**学生モデルの生成コード**も含む
（pass@1評価）。禁止リスト方式ではなく**許可リスト方式**を取る——危険な構文を全部列挙するのは
原理的に不可能だが、許可した構文だけを通すのは有限で確認できる。

## safety.py

構文の許可リストと、指定シグネチャ（`def solve(xs, k):`）を守っているかの静的検査。
実際に実行するのは`sandbox.py`の担当（役割を混ぜない）。

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `ALLOWED_NODE_TYPES` | 許可するASTノード型の集合。`codegen.enumerate_candidates`の出力を実地に`ast.walk`して洗い出した |
| `ALLOWED_CALLS` | `f(...)`の形で許可する関数名（`abs`, `sorted`, `list`, `reversed`） |
| `ALLOWED_ATTRS` | `x.attr`の形で許可する属性名（事実上`append`専用） |

### 関数

| 関数 | 説明 |
| --- | --- |
| `check(code)` | `code`が許可リストの範囲内かを検査する。問題が無ければ`None`、あれば理由の文字列を返す（`scripts/teacher/phrase_filters.check`と同じ形） |
| `_check_signature(tree)` | モジュール直下が`def solve(xs, k):`（型注釈の有無は問わない）1つだけであることを確認する内部ヘルパー |

## sandbox.py

`safety.check()`を通った（あるいは未検査の）コードを、制限時間つきで実際に実行する。
静的検査と実行時の制限の2段構え——`exec()`する前に必ず`safety.check()`を呼び直すため、
呼び出し元が検査を怠っても`execute()`が最後の砦になる。`__builtins__`も最小限に絞る。

### 型・定数

| 名前 | 説明 |
| --- | --- |
| `DEFAULT_TIMEOUT_SECONDS` | 1回の実行に許す制限時間（秒、既定1.0）。この課題の入力規模（xs長さ0〜20）なら十分すぎる余裕 |
| `ExecutionTimeout` | 制限時間内に終わらなかったときの例外 |

### 関数

| 関数 | 説明 |
| --- | --- |
| `run_with_timeout(fn, args, *, seconds)` | `fn(*args)`を`seconds`秒の制限時間で実行する。`signal.setitimer`を使うためUnix系OS・メインスレッド限定 |
| `execute(code, xs, k, *, timeout=DEFAULT_TIMEOUT_SECONDS)` | `code`を実行し`solve(xs, k)`の結果を返す。`safety.check()`に落ちれば`ValueError`、制限時間を超えれば`ExecutionTimeout` |

### 実行の範囲

`execute()` は呼び出し元と同じプロセスで動きます。タイマーが囲むのは `solve(list(xs), k)` の呼び出しで、構文検査・`compile`・関数を定義する `exec` はタイマーの外です。OSの隔離やメモリ上限を提供する実装ではありません。

入力リストは複製しますが、返り値の型や値域を検証しているわけではありません。実行中の通常の例外も呼び出し元へ伝播します。型注釈が許可された構文でも、注釈に使う名前が実行名前空間で解決できる保証はありません。
