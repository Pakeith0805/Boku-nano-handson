"""選ばれた訓練例（`balance.Example`）を、最終レコードのスキーマへ組み立てる。

スキーマは課題文（改定前）の例をもとに、実際の実装に合わせて調整してある。

- `teacher_model`/`teacher_revision`/`prompt_hash`は残すが、1レコードの指示文は複数opの
  言い回しを組み合わせて作るため、由来が複数になりうる。`prompt_hash`は`prompt_hashes`
  （複数）にする。`teacher_model`/`teacher_revision`は全run共通なので定数として渡せばよい。
- `code_style`は文字列1つではなく、実際に持っている7軸（内包表記/ループ・一時変数・
  reverse方式・return形式・注釈・条件式の順序・変数名）をそのまま構造化する。
- `tests`は空のままにする。hidden testは評価フェーズ（Phase 5）で新しく生成するものであり、
  訓練レコードに先に埋め込むと、後で評価用に使い回したときにもう「隠し」ではなくなる。
- `verification`は仮の値ではなく、`safety.check()`と`sandbox.execute()`を実際に走らせて
  その場で判定する。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.interp.interp import run
from src.select.balance import Example
from src.semantics.fingerprint import sha256
from src.verify import safety, sandbox

ProbeInput = tuple[Sequence[int], int]


def _verify(example: Example, probes: Sequence[ProbeInput]) -> dict[str, bool]:
    """`example.code`を検査・実行し、`verification`フィールドを作る。

    `safety.check()`に落ちた場合、`ast.parse`自体に失敗したのかそれ以外の理由かで
    `syntax_ok`と`ast_safe`を分ける。安全でなければ実行しない（`tests_passed`も`False`）。
    """
    if not probes:
        raise ValueError("検証には1件以上の入力が必要です")
    reason = safety.check(example.code)
    if reason is not None:
        return {
            "syntax_ok": not reason.startswith("ast.parseに失敗"),
            "ast_safe": False,
            "tests_passed": False,
        }

    tests_passed = True
    for xs, k in probes:
        expected = run(example.code_ops, xs, k)
        try:
            got = sandbox.execute(example.code, xs, k)
        except Exception:
            tests_passed = False
            break
        if got != expected:
            tests_passed = False
            break

    return {"syntax_ok": True, "ast_safe": True, "tests_passed": tests_passed}


def build_record(
    number: int,
    example: Example,
    ast_record: Mapping[str, Any],
    probes: Sequence[ProbeInput],
    *,
    provenance: Mapping[str, Mapping[str, Any]],
    teacher_model: str,
    teacher_revision: str,
) -> dict[str, Any]:
    """1件の`Example`を最終レコード（`dict`）へ組み立てる。

    `provenance`は`phrases/ja_phrases_v1_provenance.json`を読み込んだ形
    （`{言い回しID: {"run_id":..., "prompt_sha256":...}}`）。`example.phrase_ids`から
    引いた`prompt_sha256`の重複無し集合を`prompt_hashes`にする。

    Args:
        number: レコード通番（1始まり）。`spec_id`に使う。
        example: `balance.select_examples`が選んだ訓練例1件。
        ast_record: `data/asts.jsonl`の対応するレコード（`difficulty`・`semantic_hash`用）。
        probes: 検証に使う固定入力集合。
    """
    comprehension, temp_vars, reverse_style, one_line_return, annotate, reordered = (
        example.code_style
    )
    prompt_hashes = sorted(
        {
            provenance[pid]["prompt_sha256"]
            for pid in example.phrase_ids
            if pid in provenance and provenance[pid].get("prompt_sha256")
        }
    )

    return {
        "spec_id": f"task-{number:06d}",
        "ast_id": example.ast_id,
        "semantic_ast": list(ast_record["semantic_ast"]),
        "instruction_ja": example.instruction,
        "reference_code": example.code,
        "phrase_ids": list(example.phrase_ids),
        "tests": [],
        "difficulty": ast_record["difficulty"],
        "code_style": {
            "comprehension": comprehension,
            "temp_vars": temp_vars,
            "reverse_style": reverse_style,
            "one_line_return": one_line_return,
            "annotate": annotate,
            "reordered": reordered,
            "elem_name": example.elem_name,
            "var_name": example.var_name,
        },
        "semantic_hash": ast_record["semantic_hash"],
        "text_hash": sha256(example.instruction),
        "teacher_model": teacher_model,
        "teacher_revision": teacher_revision,
        "prompt_hashes": prompt_hashes,
        "verification": _verify(example, probes),
    }
