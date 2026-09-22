"""生成コードの各検査を独立に記録する（率の分母は全生成件数）。"""
from __future__ import annotations

import ast
from collections.abc import Sequence
from typing import Any

from src.probes.behavior_probes import ProbeInput
from src.verify import safety, sandbox

FLAGS = ("syntax_valid", "safe_ast", "signature_valid", "executable")


def evaluate_code(code: str, reference: str, probes: Sequence[ProbeInput]) -> dict[str, Any]:
    """誤答でも残りの入力を実行し、正解率と実行成功率を区別する。

    構文エラー時は全フラグFalse。Safe-ASTとsignatureは独立に判定する。
    実行は両検査を通ったコードだけ。参照コードの異常は評価自体のエラーとする。
    """
    result: dict[str, Any] = {flag: False for flag in FLAGS}
    result.update(passed=False, errors={})
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        result["errors"]["syntax_valid"] = str(exc)
        return result
    result["syntax_valid"] = True
    for flag, reason in (("safe_ast", safety.check_ast(tree)),
                         ("signature_valid", safety.check_signature(tree))):
        result[flag] = reason is None
        if reason is not None:
            result["errors"][flag] = reason
    if not result["safe_ast"] or not result["signature_valid"]:
        return result
    if not probes:
        raise ValueError("実行評価には1件以上のprobeが必要です")
    matches = True
    for xs, k in probes:
        expected = sandbox.execute(reference, xs, k)
        try:
            got = sandbox.execute(code, xs, k)
        except Exception as exc:
            result["errors"]["executable"] = f"{type(exc).__name__}: {exc}"
            return result
        matches = matches and got == expected
    result["executable"] = True
    result["passed"] = matches
    return result


def aggregate(results: Sequence[dict[str, Any]]) -> dict[str, float]:
    """全生成件数を分母にした率。0件の場合は0.0。"""
    return {f"{flag}_rate": sum(bool(r[flag]) for r in results) / len(results)
            if results else 0.0 for flag in FLAGS}
