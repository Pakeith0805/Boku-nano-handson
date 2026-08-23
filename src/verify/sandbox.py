"""検査済みの`solve(xs, k)`コードを、制限時間つきで実際に実行する。

`safety.check()`（構文の許可リスト）と、この`execute()`（実行時の制限時間・ビルトイン制限）の
2段構えにしている。片方だけに頼らない理由は、静的検査は「書かれた構文」しか見られず、
実行時の暴走（無限ループなど）は検査できないため。逆に実行だけに頼ると、`exec()`に
危険なコードをそのまま渡すことになる。

この課題が扱うコードは、`xs`の長さが0〜20の`for`ループ／内包表記だけなので、想定される
実行時間はミリ秒未満である。制限時間は「万一の無限ループを検出する安全弁」であり、
通常は発動しない。
"""

from __future__ import annotations

import signal
from collections.abc import Sequence
from typing import Any

from src.verify import safety

DEFAULT_TIMEOUT_SECONDS: float = 1.0
"""1回の実行に許す制限時間（秒）。この課題の入力規模（xs長さ0〜20）なら十分すぎる余裕。"""

_SAFE_BUILTINS: dict[str, Any] = {"abs": abs, "sorted": sorted, "list": list, "reversed": reversed}
"""`exec()`に渡す`__builtins__`をこれだけに絞る。`safety.ALLOWED_CALLS`と同じ集合——
構文レベルの許可リストと、実行時に実際に使える関数の集合を二重に一致させる。"""


class ExecutionTimeout(Exception):
    """`execute()`が制限時間内に終わらなかったときに送出する。"""


def run_with_timeout(fn: Any, args: tuple[Any, ...], *, seconds: float) -> Any:
    """`fn(*args)`を`seconds`秒の制限時間で実行する。間に合わなければ`ExecutionTimeout`。

    `signal.setitimer`を使うため、Unix系OSでのみ動く（このプロジェクトの実行環境を前提）。
    シグナルハンドラはプロセス全体に対して張るので、**呼び出し元スレッドがメインスレッドで
    あることを前提とする**（`signal`モジュール自体の制約）。
    """
    def _handler(signum: int, frame: Any) -> None:
        raise ExecutionTimeout(f"{seconds}秒以内に実行が終わらなかった")

    old_handler = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn(*args)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)


def execute(
    code: str, xs: Sequence[int], k: int, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> list[int]:
    """`code`（`def solve(xs, k):`を定義するソース）を実行し、`solve(xs, k)`の結果を返す。

    `exec()`する前に必ず`safety.check()`を通す——呼び出し元が検査を怠っても、
    ここが最後の砦になる。`__builtins__`も最小限に絞るため、許可リストを抜けた構文が
    万一あっても、危険な組み込み関数には手が届かない。

    Raises:
        ValueError: `safety.check()`に落ちたとき。
        ExecutionTimeout: 制限時間内に終わらなかったとき。
    """
    reason = safety.check(code)
    if reason is not None:
        raise ValueError(f"安全性検査に落ちたコードは実行しない: {reason}")

    namespace: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}
    exec(compile(code, "<solve>", "exec"), namespace)
    solve = namespace["solve"]
    return run_with_timeout(solve, (list(xs), k), seconds=timeout)
