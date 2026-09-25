"""hidden入力の独立性・再現性と、最終評価への接続を確認する。"""

from pathlib import Path
import json
import sys
from types import SimpleNamespace

import pytest

from src.limits import ELEM_MIN, ELEM_MAX, K_MIN, K_MAX, XS_LEN_MIN, XS_LEN_MAX
from src.probes.behavior_probes import load_probe_set
from src.probes.hidden_inputs import hidden_inputs

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = "def solve(xs, k):\n    return xs"


def test_hidden_inputs_are_unique_in_domain_and_exclude_creation_inputs():
    creation = load_probe_set(ROOT / "probes/behavior_probe_set_v1.jsonl")
    generated = hidden_inputs("問題A", exclude=creation, count=40)
    assert len(generated) == len(set(generated)) == 40
    assert not set(generated) & set(creation)
    for xs, k in generated:
        assert XS_LEN_MIN <= len(xs) <= XS_LEN_MAX
        assert K_MIN <= k <= K_MAX
        assert all(ELEM_MIN <= x <= ELEM_MAX for x in xs)
    # 乱数列に現れる入力も明示的に除外する。
    regenerated = hidden_inputs("問題A", exclude=creation + generated)
    assert not set(regenerated) & set(creation + generated)


def test_problem_and_seed_control_inputs_reproducibly():
    first = hidden_inputs("問題A", exclude=[], seed=42)
    other = hidden_inputs("問題B", exclude=[], seed=42)
    assert first != other
    assert first == hidden_inputs("問題A", exclude=[], seed=42)
    assert first != hidden_inputs("問題A", exclude=[], seed=43)


@pytest.mark.parametrize("count", [-1, 0, 19])
def test_at_least_twenty_inputs(count):
    with pytest.raises(ValueError, match="20入力以上"):
        hidden_inputs("問題", exclude=[], count=count)


def test_final_evaluation_uses_hidden_inputs_and_records_exact_cases():
    from scripts.evaluate import evaluate_category

    # 空入力だけなら誤実装も通るが、独立したhidden入力では落ちる。
    report = evaluate_category(
        "test", [("入力を返す", REFERENCE)], ["def solve(xs, k):\n    return []"],
        probes_full=[((), 1)], probes_boundary=[((), 1)], hidden_seed=123,
    )
    assert report["pass_rate"] == 0
    assert report["fixed_probe_pass_rate"] == 1
    assert report["boundary_pass_rate"] == 1
    row = report["results"][0]
    expected = hidden_inputs("入力を返す", exclude=[((), 1)], seed=123)
    assert row["hidden_inputs"] == [{"xs": list(xs), "k": k} for xs, k in expected]
    assert report["evaluation_protocol"] == "per-problem-random-v1"


def test_inputs_do_not_depend_on_generated_code_or_evaluation_order():
    from scripts.evaluate import evaluate_category

    records = [("問題A", REFERENCE), ("問題B", REFERENCE)]
    kwargs = {"probes_full": [((), 1)], "probes_boundary": [((), 1)]}
    correct = evaluate_category("test", records, [REFERENCE] * 2, **kwargs)
    wrong = evaluate_category("test", records[::-1], ["def solve(xs, k):\n    return []"] * 2, **kwargs)
    assert correct["pass_rate"] == 1
    for a, b in zip(correct["results"], reversed(wrong["results"]), strict=True):
        assert a["hidden_inputs"] == b["hidden_inputs"]
    with pytest.raises(ValueError):
        evaluate_category("test", records, [REFERENCE], **kwargs)


def test_evaluation_cli_saves_hidden_protocol_and_inputs(monkeypatch, tmp_path):
    from scripts import evaluate

    dataset = tmp_path / "test.jsonl"
    dataset.write_text(json.dumps({
        "instruction_ja": "入力を返す", "reference_code": REFERENCE,
        "verification": {"syntax_ok": True, "ast_safe": True, "tests_passed": True},
    }))
    output = tmp_path / "report.json"
    monkeypatch.setattr(evaluate, "CATEGORIES", {"通常テスト": dataset})
    monkeypatch.setattr(evaluate.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(evaluate, "Tokenizer", SimpleNamespace(from_file=lambda p: None))
    monkeypatch.setattr(evaluate, "load_special_ids", lambda t: None)
    monkeypatch.setattr(evaluate, "load_model", lambda *args: (None, 123))
    monkeypatch.setattr(evaluate, "generate_codes", lambda model, tokenizer, ids, records, **kw:
                        [REFERENCE] * len(records))
    monkeypatch.setattr(sys, "argv", ["evaluate", "--checkpoint", "unused.pt",
        "--hidden-count", "25", "--hidden-seed", "42", "--out", str(output)])
    evaluate.main()
    report = json.loads(output.read_text())
    assert report["evaluation_protocol"] == "per-problem-random-v1"
    assert (report["hidden_count"], report["hidden_seed"]) == (25, 42)
    category = report["categories"][0]
    assert category["pass_rate"] == category["fixed_probe_pass_rate"] == 1
    assert len(category["results"][0]["hidden_inputs"]) == 25


def test_cli_rejects_too_few_inputs_before_loading_model(monkeypatch):
    from scripts.evaluate import main

    monkeypatch.setattr(sys, "argv", ["evaluate", "--checkpoint", "missing.pt", "--hidden-count", "19"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
