"""指定したcheckpointを、課題指定の4種類のテストで評価する。

```
python -m scripts.evaluate --checkpoint runs/checkpoints/<run_id>/step_XXXXXX.pt
python -m scripts.evaluate --checkpoint ... --limit 500      # 通常テストの件数を絞る(既定200)
python -m scripts.evaluate --checkpoint ... --limit 0        # 通常テスト全94,720件(時間がかかる)
python -m scripts.evaluate --checkpoint ... --out report.json  # 結果をJSONにも書く
```

## 4種類のテストと、それぞれのデータの出所

| テスト | データ | 判定方法 |
| --- | --- | --- |
| 通常テスト | `data/dataset/test.jsonl` | 生成コードを固定入力集合**全148件**で参照コードと突き合わせる |
| 言い換えテスト | `data/dataset/test_paraphrase.jsonl` | 同上 |
| 組合せ汎化テスト | `data/dataset/test_combination.jsonl` | 同上 |
| 境界値テスト | 上記3つで**既に生成したコード**を再利用 | 全148件のうち`kind=="boundary"`の20件だけで突き合わせ直す |

境界値テストは別ファイルを持たない設計(`data/README.md`参照)——生成済みコードに
境界値入力だけを流し込み直すだけで足りるため、他の3テストとは別に生成をやり直さない。

## 判定基準

各例について、`src.verify.safety.check`(許可リスト構文検査)を通り、かつ対象の入力
すべてで参照コード(`reference_code`)と実行結果が一致すれば合格。文字列一致ではなく
実行結果の一致で見る(データセット自体の検証・`scripts/train.py`の生成評価と同じ基準。
このデータセットは同じ意味のコードに複数の書き方がありうる設計のため)。
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

import torch
from tokenizers import Tokenizer

from model.checkpoint import load_model
from model.data import SpecialIds, load_records, load_special_ids
from model.generate import batch_greedy_generate
from src.probes.behavior_probes import ProbeInput, load_probe_set
from src.verify import safety, sandbox
from src.verify.metrics import aggregate, evaluate_code

ROOT = Path(__file__).resolve().parents[1]
TOKENIZER_PATH = ROOT / "data" / "tokenizer" / "tokenizer.json"
PROBES_PATH = ROOT / "probes" / "behavior_probe_set_v1.jsonl"

DATASET_DIR = ROOT / "data" / "dataset"
CATEGORIES: dict[str, Path] = {
    "通常テスト": DATASET_DIR / "test.jsonl",
    "言い換えテスト": DATASET_DIR / "test_paraphrase.jsonl",
    "組合せ汎化テスト": DATASET_DIR / "test_combination.jsonl",
}

DEFAULT_LIMIT = 200
"""通常テスト(94,720件)をそのまま全件回すと非常に時間がかかるための既定の間引き数。
言い換え・組合せ汎化テストは元々30件しか無いので間引かない。`--limit 0`で無効化できる。"""


def load_boundary_probes(path: Path) -> list[ProbeInput]:
    """probe setのうち`kind == "boundary"`の入力だけを取り出す。"""
    probes: list[ProbeInput] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["kind"] == "boundary":
                probes.append((row["xs"], row["k"]))
    return probes


def sample_records(path: Path, limit: int, seed: int) -> list[tuple[str, str]]:
    """`load_records`で読み、`limit`件を(`limit<=0`なら全件)乱数で抽出する。"""
    records = load_records(path)
    if limit <= 0 or limit >= len(records):
        return records
    return random.Random(seed).sample(records, limit)


def generate_codes(
    model,
    tokenizer: Tokenizer,
    ids: SpecialIds,
    records: list[tuple[str, str]],
    *,
    batch_size: int,
    max_new_tokens: int,
    metrics: dict[str, float | int] | None = None,
) -> list[str]:
    """`records`(instruction, reference_code)の指示文ぶんだけ生成し、コード文字列の列を返す。

    `batch_size`件ずつ`batch_greedy_generate`にまとめる(1件ずつより速い)。
    """
    codes: list[str] = []
    for start in range(0, len(records), batch_size):
        chunk = records[start : start + batch_size]
        encoded = tokenizer.encode_batch([instruction for instruction, _ in chunk])
        prompts = [[ids.bos, ids.task, *enc.ids, ids.code] for enc in encoded]
        prompt_width = max(len(p) for p in prompts)
        rows = batch_greedy_generate(
            model, prompts, eos_id=ids.eos, pad_id=ids.pad, max_new_tokens=max_new_tokens,
            metrics=metrics
        )
        codes.extend(tokenizer.decode(row[prompt_width:], skip_special_tokens=True) for row in rows)
    return codes


def check_pass(gen_code: str, reference_code: str, probes: list[ProbeInput]) -> bool:
    """`gen_code`が安全性検査を通り、`probes`全部で`reference_code`と実行結果が一致するか。"""
    if safety.check(gen_code) is not None:
        return False
    for xs, k in probes:
        try:
            expected = sandbox.execute(reference_code, xs, k)
            got = sandbox.execute(gen_code, xs, k)
        except Exception:
            return False
        if got != expected:
            return False
    return True


def evaluate_category(
    name: str,
    records: list[tuple[str, str]],
    gen_codes: list[str],
    *,
    probes_full: list[ProbeInput],
    probes_boundary: list[ProbeInput],
) -> dict[str, Any]:
    """1カテゴリぶんの結果をまとめる。全148件での合否と、境界値20件だけでの合否を両方持つ。"""
    results = []
    for (instruction, reference_code), gen_code in zip(records, gen_codes):
        results.append(
            {
                "instruction": instruction,
                "generated_code": gen_code,
                "reference_code": reference_code,
                **evaluate_code(gen_code, reference_code, probes_full),
                "boundary_passed": check_pass(gen_code, reference_code, probes_boundary),
            }
        )
    n = len(results)
    n_pass = sum(r["passed"] for r in results)
    n_boundary_pass = sum(r["boundary_passed"] for r in results)
    return {
        **aggregate(results),
        "name": name,
        "n": n,
        "pass_rate": n_pass / n if n else 0.0,
        "boundary_pass_rate": n_boundary_pass / n if n else 0.0,
        "results": results,
    }


def print_report(reports: list[dict[str, Any]], boundary_overall: float, boundary_n: int) -> None:
    print()
    print(f"{'テスト':16s} {'件数':>8s} {'pass_rate':>10s} {'boundary内訳':>12s}")
    for r in reports:
        print(f"{r['name']:16s} {r['n']:8d} {r['pass_rate']:9.1%} {r['boundary_pass_rate']:11.1%}")
        print("  " + " ".join(f"{key}={r[key]:.1%}" for key in (
            "syntax_valid_rate", "safe_ast_rate", "signature_valid_rate", "executable_rate"
        )))
        print(f"  generation_tokens/s={r['generation_tokens_per_second']:.1f}")
    print()
    print(f"境界値テスト(3カテゴリ合算 {boundary_n}件、probe20件で判定): {boundary_overall:.1%}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--checkpoint", required=True, help="scripts/train.pyが書いたcheckpoint(.pt)")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"通常テストの件数を絞る(既定{DEFAULT_LIMIT}件、0で全件)。言い換え・組合せ汎化は常に全件",
    )
    parser.add_argument("--seed", type=int, default=0, help="通常テストの間引きに使う乱数シード")
    parser.add_argument("--batch-size", type=int, default=64, help="1回のforwardにまとめる件数")
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument("--out", help="結果(1件ごとの生成コード込み)をJSONで書き出す先")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    tokenizer = Tokenizer.from_file(str(TOKENIZER_PATH))
    ids = load_special_ids(tokenizer)
    model, step = load_model(Path(args.checkpoint), device)
    print(f"checkpoint: {args.checkpoint} (step {step}, device={device})")

    probes_full = load_probe_set(PROBES_PATH)
    probes_boundary = load_boundary_probes(PROBES_PATH)
    print(f"probe set: 全{len(probes_full)}件(うちboundary {len(probes_boundary)}件)")

    reports = []
    for name, path in CATEGORIES.items():
        if not path.exists():
            print(f"[skip] {name}: {path} が無い")
            continue
        limit = args.limit if name == "通常テスト" else 0
        records = sample_records(path, limit, args.seed)
        print(f"{name}: {len(records)}件を生成中...")
        performance: dict[str, float | int] = {
            "generation_seconds": 0.0, "generated_tokens": 0,
            "generation_tokens_per_second": 0.0,
        }
        gen_codes = generate_codes(
            model, tokenizer, ids, records, batch_size=args.batch_size, max_new_tokens=args.max_new_tokens,
            metrics=performance,
        )
        report = evaluate_category(
            name, records, gen_codes, probes_full=probes_full, probes_boundary=probes_boundary
        )
        report.update(performance)
        reports.append(report)

    total_boundary_pass = sum(r["boundary_pass_rate"] * r["n"] for r in reports)
    total_n = sum(r["n"] for r in reports)
    boundary_overall = total_boundary_pass / total_n if total_n else 0.0

    peak = torch.cuda.max_memory_allocated(device) if device.type == "cuda" else None
    combination_rate = next((r["pass_rate"] for r in reports
                             if r["name"] == "組合せ汎化テスト"), None)
    print_report(reports, boundary_overall, total_n)
    print(f"最大GPUメモリ (allocated bytes): {peak if peak is not None else 'N/A (CPU)'}")

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(
            json.dumps(
                {
                    "checkpoint": str(args.checkpoint),
                    "step": step,
                    "device": str(device),
                    "max_gpu_memory_bytes": peak,
                    "combination_generalization_rate": combination_rate,
                    "categories": reports,
                    "boundary_pass_rate_overall": boundary_overall,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"詳細レポート: {out_path}")


if __name__ == "__main__":
    main()
