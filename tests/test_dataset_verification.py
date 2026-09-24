"""不正コードが検証されても保存・学習へ流れないことを確認する。"""

import json
from dataclasses import replace

import pytest

from src.select.balance import Example
from src.select.record import _verify
from src.verify.records import is_verified

GOOD = Example(
    ast_id="ast-1", code="def solve(xs, k):\n    return [x * 2 for x in xs]\n",
    code_ops=("double",), code_style=(True, True, False, True, False, False),
    elem_name="x", var_name="result", instruction="2倍する", phrase_ids=(),
)
PROBES = [((1, -2), 3), ((), 1)]


@pytest.mark.parametrize("flags", [None, {}, [], True,
    {"syntax_ok": True, "ast_safe": True},
    {"syntax_ok": True, "ast_safe": True, "tests_passed": False},
    {"syntax_ok": True, "ast_safe": True, "tests_passed": "true"},
])
def test_invalid_verification_never_passes(flags):
    assert not is_verified({"verification": flags})


@pytest.mark.parametrize("code", [
    "def solve(",
    "def solve(xs, k):\n    import os\n    return xs",
    "def solve(xs, k):\n    return xs",
    "def solve(xs, k):\n    return [1 // 0]",
])
def test_real_failures_excluded_before_save(monkeypatch, tmp_path, capsys, code):
    from scripts import build_dataset

    bad = replace(GOOD, code=code)
    assert not is_verified({"verification": _verify(bad, PROBES)})
    monkeypatch.setattr(build_dataset, "_WORKER", {
        "train_phrases": {}, "probes": PROBES, "provenance": {},
    })
    monkeypatch.setattr(build_dataset, "_build_examples_for_ast", lambda *a, **kw: [bad, GOOD])
    ast_record = {"ast_id": "ast-1", "semantic_ast": ["double"],
                  "difficulty": 1, "semantic_hash": "example"}
    records = build_dataset._process_chunk(([ast_record], "train_phrases", 2, 0))
    path = tmp_path / "train.jsonl"
    build_dataset._write(path, records)
    saved = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(saved) == 1
    assert saved[0]["reference_code"] == GOOD.code
    assert is_verified(saved[0])
    assert "検証不合格を除外: 1件" in capsys.readouterr().out


def test_verification_requires_inputs():
    with pytest.raises(ValueError, match="1件以上"):
        _verify(GOOD, [])


def test_loader_excludes_failed_and_unverified_records(tmp_path):
    from model.data import load_records

    good = {"instruction_ja": GOOD.instruction, "reference_code": GOOD.code,
            "verification": _verify(GOOD, PROBES)}
    bad = {**good, "verification": {**good["verification"], "tests_passed": False}}
    missing = {"instruction_ja": "unverified", "reference_code": GOOD.code}
    path = tmp_path / "train.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in [bad, missing, good]))
    with pytest.warns(UserWarning, match="2件を除外"):
        assert load_records(path) == [(GOOD.instruction, GOOD.code)]
    path.write_text(json.dumps(bad))
    with pytest.warns(UserWarning), pytest.raises(ValueError, match="検証済みレコードがありません"):
        load_records(path)
