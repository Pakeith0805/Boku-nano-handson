"""診断率が正解率と混ざらず、各段階の失敗を識別することを確認する。"""
import pytest

from src.verify import sandbox
from src.verify.metrics import aggregate, evaluate_code

REFERENCE = 'def solve(xs, k):\n    return xs'
PROBES = [([1], 0), ([], 0)]


def test_independent_static_checks():
    syntax = evaluate_code('def solve(', REFERENCE, PROBES)
    unsafe = evaluate_code('def solve(xs, k):\n    import os\n    return xs', REFERENCE, PROBES)
    signature = evaluate_code('def other(xs, k):\n    return xs', REFERENCE, PROBES)
    assert not syntax['syntax_valid']
    assert unsafe['syntax_valid'] and unsafe['signature_valid'] and not unsafe['safe_ast']
    assert signature['safe_ast'] and not signature['signature_valid']
    assert not unsafe['executable'] and not signature['executable']
    assert aggregate([syntax, unsafe, signature]) == {
        'syntax_valid_rate': 2 / 3, 'safe_ast_rate': 1 / 3,
        'signature_valid_rate': 1 / 3, 'executable_rate': 0,
    }


def test_wrong_answer_is_executable_but_later_exception_is_not():
    wrong = evaluate_code('def solve(xs, k):\n    return []', REFERENCE, PROBES)
    assert wrong['executable'] and not wrong['passed']
    fails_later = evaluate_code('def solve(xs, k):\n    return [xs[0] + 1]', REFERENCE, PROBES)
    assert not fails_later['executable']
    assert 'IndexError' in fails_later['errors']['executable']
    assert evaluate_code(REFERENCE, REFERENCE, PROBES)['passed']


def test_timeout_is_execution_failure(monkeypatch):
    original = sandbox.execute
    code = 'def solve(xs, k):\n    return []'
    def execute(source, xs, k):
        if source == code:
            raise sandbox.ExecutionTimeout('timeout')
        return original(source, xs, k)
    monkeypatch.setattr(sandbox, 'execute', execute)
    result = evaluate_code(code, REFERENCE, PROBES)
    assert not result['executable']
    assert 'ExecutionTimeout' in result['errors']['executable']


def test_empty_inputs():
    assert all(rate == 0 for rate in aggregate([]).values())
    with pytest.raises(ValueError):
        evaluate_code(REFERENCE, REFERENCE, [])


def test_generation_counts_eos_but_not_finished_padding():
    torch = pytest.importorskip('torch')
    from types import SimpleNamespace
    from model.generate import batch_greedy_generate

    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.weight = torch.nn.Parameter(torch.zeros(1))
            self.cfg = SimpleNamespace(max_seq_len=8)
            self.calls = 0

        def forward(self, ids, **kwargs):
            self.calls += 1
            logits = torch.zeros((*ids.shape, 4))
            logits[0, -1, 1] = 1  # 1件目は即EOS。
            logits[1, -1, 1 if self.calls == 3 else 0] = 1
            return logits

    metrics = {}
    for _ in range(2):
        batch_greedy_generate(Model(), [[2], [2]], eos_id=1, pad_id=0,
                              max_new_tokens=4, metrics=metrics)
    # 2件目が実際に生成したpad IDは数え、EOS後の埋め草だけ除外。
    assert metrics['generated_tokens'] == 8
    assert metrics['generation_seconds'] > 0
    assert metrics['generation_tokens_per_second'] == pytest.approx(8 / metrics['generation_seconds'])


def test_category_retains_pass_and_boundary_rates():
    pytest.importorskip('torch')
    from scripts.evaluate import evaluate_category
    report = evaluate_category('test', [('instruction', REFERENCE)],
                               ['def solve(xs, k):\n    return []'],
                               probes_full=PROBES, probes_boundary=[([], 0)])
    assert report['pass_rate'] == 0
    assert report['boundary_pass_rate'] == 1
    assert report['executable_rate'] == 1
