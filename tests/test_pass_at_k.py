"""課題のpass@1/pass@5定義と、温度0/0.7の別生成を固定する。GPU・checkpoint不要。"""

import json
import sys
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")

from model.data import SpecialIds
from model.generate import batch_generate, batch_greedy_generate
from scripts import evaluate

REFERENCE = "def solve(xs, k):\n    return xs"
WRONG = "def solve(xs, k):\n    return []"
FIXED = [((), 1)]


class TinyModel(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.zeros(1))
        self.cfg = SimpleNamespace(max_seq_len=20)
        self.calls = 0

    def forward(self, ids, **kwargs):
        assert not self.training
        self.calls += 1
        return torch.arange(4, dtype=torch.float).expand(*ids.shape, 4)


def test_temperature_zero_uses_argmax_without_sampling(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("temperature=0 must not sample")

    monkeypatch.setattr(torch, "multinomial", forbidden)
    model = TinyModel()
    result = batch_greedy_generate(model, [[2], [2, 2]], eos_id=1, pad_id=0, max_new_tokens=2)
    assert result == [[0, 2, 3, 3], [2, 2, 3, 3]]
    assert model.training


def test_temperature_point_seven_scales_logits_and_uses_generator(monkeypatch):
    generator = torch.Generator().manual_seed(17)
    calls = []

    def sample(probabilities, num_samples, *, generator):
        calls.append(generator)
        expected = torch.softmax(torch.arange(4, dtype=torch.float) / 0.7, dim=-1)
        assert torch.allclose(probabilities, expected.expand_as(probabilities))
        assert num_samples == 1
        return torch.full((probabilities.shape[0], 1), 2, dtype=torch.long)

    monkeypatch.setattr(torch, "multinomial", sample)
    model = TinyModel()
    metrics = {}
    rows = batch_generate(model, [[2], [3]], eos_id=1, pad_id=0, max_new_tokens=2,
                          temperature=0.7, generator=generator, metrics=metrics)
    assert rows == [[2, 2, 2], [3, 2, 2]]  # argmaxの3ではない。
    assert calls == [generator, generator]
    assert model.training
    assert metrics["generated_tokens"] == 4


def test_sampling_seed_reproducibility_and_context_budget():
    def generate(seed):
        model = TinyModel()
        model.eval()
        rows = batch_generate(model, [[2]] * 3, eos_id=99, pad_id=0, max_new_tokens=100,
                              temperature=0.7, generator=torch.Generator().manual_seed(seed))
        assert not model.training
        assert all(len(row) == 20 for row in rows)
        return rows

    assert generate(42) == generate(42)
    assert generate(42) != generate(43)


def test_sampling_eos_finished_padding_and_token_count(monkeypatch):
    selections = iter([[[1], [2]], [[3], [1]]])
    monkeypatch.setattr(torch, "multinomial", lambda *args, **kwargs: torch.tensor(next(selections)))
    metrics = {}
    model = TinyModel()
    rows = batch_generate(model, [[2], [2]], eos_id=1, pad_id=0, max_new_tokens=10,
                          temperature=0.7, metrics=metrics)
    assert rows == [[2, 1, 0], [2, 2, 1]]
    assert model.calls == 2
    assert metrics["generated_tokens"] == 3


@pytest.mark.parametrize("temperature", [-0.1, float("nan"), float("inf")])
def test_invalid_temperatures(temperature):
    with pytest.raises(ValueError, match="temperature"):
        batch_generate(TinyModel(), [[2]], eos_id=1, pad_id=0, max_new_tokens=1,
                       temperature=temperature)


def test_generate_codes_forwards_temperature_and_strips_left_padding(monkeypatch):
    calls = []
    generator = torch.Generator().manual_seed(5)
    ids = SpecialIds(pad=0, bos=1, eos=2, task=3, code=4)
    tokenizer = SimpleNamespace(
        encode_batch=lambda texts: [SimpleNamespace(ids=[7] * len(text)) for text in texts],
        decode=lambda tokens, **kwargs: str(tokens),
    )

    def generate(model, prompts, **kwargs):
        calls.append(kwargs)
        width = max(map(len, prompts))
        return [[0] * (width - len(prompt)) + prompt + [9, 2] for prompt in prompts]

    monkeypatch.setattr(evaluate, "batch_generate", generate)
    result = evaluate.generate_codes(None, tokenizer, ids, [("a", REFERENCE), ("long", REFERENCE)],
                                     batch_size=2, max_new_tokens=10, temperature=0.7,
                                     generator=generator)
    assert result == ["[9, 2]", "[9, 2]"]
    assert calls[0]["temperature"] == 0.7
    assert calls[0]["generator"] is generator


def test_pass5_generates_exactly_five_per_problem_without_deduplication(monkeypatch):
    records = [("A", REFERENCE), ("B", REFERENCE)]
    generator = torch.Generator().manual_seed(9)

    def generate(model, tokenizer, ids, repeated, **kwargs):
        assert repeated == [records[0]] * 5 + [records[1]] * 5
        assert kwargs["temperature"] == 0.7
        assert kwargs["generator"] is generator
        return [WRONG] * 10

    monkeypatch.setattr(evaluate, "generate_codes", generate)
    assert evaluate.generate_pass5_codes(None, None, None, records, batch_size=3, max_new_tokens=10,
                                         generator=generator) == [[WRONG] * 5, [WRONG] * 5]


def test_pass_rates_are_per_problem_and_use_separate_candidate_sets():
    records = [("A", REFERENCE), ("B", REFERENCE), ("C", REFERENCE)]
    sampled = [[WRONG] * 5, [WRONG] * 4 + [REFERENCE], [REFERENCE] * 5]
    report = evaluate.evaluate_category(
        "test", records, [REFERENCE, WRONG, WRONG], sampled_codes=sampled,
        probes_full=FIXED, probes_boundary=FIXED,
    )
    assert report["pass@1"] == report["pass_rate"] == 1 / 3
    assert report["pass@5"] == 2 / 3  # 6/15という候補単位の率ではない。
    assert [(r["pass@1"], r["pass@5"]) for r in report["results"]] == [
        (True, False), (False, True), (False, True),
    ]
    assert report["fixed_probe_pass_at_5"] == report["boundary_pass_at_5"] == 1
    for row in report["results"]:
        assert len(row["hidden_inputs"]) >= 20
        assert all(case != {"xs": [], "k": 1} for case in row["hidden_inputs"])
        assert len(row["sampled_candidates"]) == 5


def test_one_candidate_must_pass_every_hidden_input(monkeypatch):
    hidden = [((n,), 1) for n in range(20)]
    calls = []

    def inputs(instruction, **kwargs):
        calls.append(instruction)
        return hidden

    monkeypatch.setattr(evaluate, "hidden_inputs", inputs)
    original = evaluate.evaluate_code
    checked = []

    def judge(code, reference, probes):
        checked.append(probes)
        return original(code, reference, probes)

    monkeypatch.setattr(evaluate, "evaluate_code", judge)
    even = "def solve(xs, k):\n    return [x for x in xs if x % 2 == 0]"
    odd = "def solve(xs, k):\n    return [x for x in xs if x % 2 != 0]"
    report = evaluate.evaluate_category(
        "test", [("A", REFERENCE)], [REFERENCE], sampled_codes=[[even, odd, even, odd, even]],
        probes_full=FIXED, probes_boundary=FIXED,
    )
    assert report["pass@5"] == 0  # 異なる候補の正解入力を寄せ集めてはいけない。
    assert calls == ["A"]
    assert len(checked) == 6 and all(p is hidden for p in checked)


@pytest.mark.parametrize("codes", [[], [[REFERENCE] * 4], [[REFERENCE] * 6], [[REFERENCE] * 5] * 2])
def test_rejects_missing_or_extra_candidates(codes):
    with pytest.raises(ValueError, match="ちょうど5候補"):
        evaluate.evaluate_category("test", [("A", REFERENCE)], [REFERENCE], sampled_codes=codes,
                                   probes_full=FIXED, probes_boundary=FIXED)


def test_unmeasured_pass5_is_not_reported_as_zero():
    report = evaluate.evaluate_category("test", [], [], probes_full=FIXED, probes_boundary=FIXED)
    assert report["pass@1"] == 0
    assert report["pass@5"] is None
    measured = evaluate.evaluate_category("test", [], [], sampled_codes=[],
                                          probes_full=FIXED, probes_boundary=FIXED)
    assert measured["pass@5"] == 0


def test_cli_records_temperatures_candidates_seeds_and_combination_pass1(monkeypatch, tmp_path, capsys):
    dataset = tmp_path / "test.jsonl"
    dataset.write_text(json.dumps({
        "instruction_ja": "入力を返す", "reference_code": REFERENCE,
        "verification": {"syntax_ok": True, "ast_safe": True, "tests_passed": True},
    }))
    output = tmp_path / "report.json"
    monkeypatch.setattr(evaluate, "CATEGORIES", {name: dataset for name in evaluate.CATEGORIES})
    monkeypatch.setattr(evaluate.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(evaluate, "Tokenizer", SimpleNamespace(from_file=lambda p: None))
    monkeypatch.setattr(evaluate, "load_special_ids", lambda t: None)
    monkeypatch.setattr(evaluate, "load_model", lambda *args: (None, 123))
    calls = []

    def generate(model, tokenizer, ids, records, **kwargs):
        calls.append((kwargs["temperature"], len(records)))
        kwargs["metrics"].update(generation_seconds=2.0, generated_tokens=10,
                                 generation_tokens_per_second=5.0)
        if kwargs["temperature"] == 0:
            return [WRONG] * len(records)
        assert kwargs["generator"].initial_seed() == 77
        return [WRONG] * 4 + [REFERENCE]

    monkeypatch.setattr(evaluate, "generate_codes", generate)
    monkeypatch.setattr(sys, "argv", ["evaluate", "--checkpoint", "unused.pt",
        "--generation-seed", "77", "--hidden-count", "25", "--hidden-seed", "42",
        "--out", str(output)])
    evaluate.main()
    report = json.loads(output.read_text())
    assert calls == [(0.0, 1), (0.7, 5)] * 3
    assert report["decoding"] == {
        "pass@1": {"temperature": 0.0, "candidates": 1},
        "pass@5": {"temperature": 0.7, "candidates": 5},
    }
    assert report["generation_seed"] == 77
    assert report["combination_generalization_rate"] == 0
    for category in report["categories"]:
        assert category["pass@1"] == 0 and category["pass@5"] == 1
        assert category["generated_tokens"] == 20
        assert category["generation_tokens_per_second"] == 5
        row = category["results"][0]
        assert len(row["hidden_inputs"]) == 25
        assert [c["generated_code"] for c in row["sampled_candidates"]] == [WRONG] * 4 + [REFERENCE]
    text = capsys.readouterr().out
    assert "pass@1" in text and "pass@5" in text
