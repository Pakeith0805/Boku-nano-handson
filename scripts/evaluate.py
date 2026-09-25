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
| 通常テスト | `data/dataset/test.jsonl` | 問題ごとの新規hidden入力（既定20件）で参照コードと突き合わせる |
| 言い換えテスト | `data/dataset/test_paraphrase.jsonl` | 同上 |
| 組合せ汎化テスト | `data/dataset/test_combination.jsonl` | 同上 |
| 境界値テスト | 上記3つで**既に生成したコード**を再利用 | 全148件のうち`kind=="boundary"`の20件だけで突き合わせ直す |

境界値テストは別ファイルを持たない設計(`data/README.md`参照)——生成済みコードに
境界値入力だけを流し込み直すだけで足りるため、他の3テストとは別に生成をやり直さない。
固定入力148件での合格率も、比較用の別指標として残す。
hidden入力は固定入力と重複せず、`--hidden-seed`と問題文で再現できる。
`--out`指定時は実際のhidden入力も保存する。学習中の評価には使用しない。

pass@1はtemperature=0で1候補、pass@5はtemperature=0.7で別途5候補を生成する。
pass@5は5候補のうち1候補以上が全hidden入力に合格した問題の割合。
貪欲生成の1候補はpass@5に含めず、同じ問題では全6候補を同じhidden入力で判定する。
重複した候補もそのまま数え、生成し直さない。抽出結果は--generation-seedで再現する
（同じモデル・環境・バッチサイズ・問題順序が前提）。

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
from model.generate import batch_generate
from src.probes.behavior_probes import ProbeInput, load_probe_set
from src.probes.hidden_inputs import (
    DEFAULT_HIDDEN_COUNT, DEFAULT_HIDDEN_SEED, HIDDEN_PROTOCOL, hidden_inputs,
)
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

PASS1_TEMPERATURE = 0.0
PASS5_TEMPERATURE = 0.7
PASS5_CANDIDATES = 5


def decoding_protocol() -> dict[str, dict[str, float | int]]:
    """評価時の固定生成条件。hidden入力の生成条件とは別に保存する。"""
    return {
        "pass@1": {"temperature": PASS1_TEMPERATURE, "candidates": 1},
        "pass@5": {"temperature": PASS5_TEMPERATURE, "candidates": PASS5_CANDIDATES},
    }


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
    temperature: float = PASS1_TEMPERATURE,
    generator: torch.Generator | None = None,
) -> list[str]:
    """`records`(instruction, reference_code)の指示文ぶんだけ生成し、コード文字列の列を返す。

    `batch_size`件ずつ、指定温度でバッチ生成する。
    """
    if batch_size < 1:
        raise ValueError("batch_sizeは1以上にしてください")
    codes: list[str] = []
    for start in range(0, len(records), batch_size):
        chunk = records[start : start + batch_size]
        encoded = tokenizer.encode_batch([instruction for instruction, _ in chunk])
        prompts = [[ids.bos, ids.task, *enc.ids, ids.code] for enc in encoded]
        prompt_width = max(len(p) for p in prompts)
        rows = batch_generate(
            model, prompts, eos_id=ids.eos, pad_id=ids.pad, max_new_tokens=max_new_tokens,
            metrics=metrics, temperature=temperature, generator=generator,
        )
        codes.extend(tokenizer.decode(row[prompt_width:], skip_special_tokens=True) for row in rows)
    return codes


def generate_pass5_codes(
    model,
    tokenizer: Tokenizer,
    ids: SpecialIds,
    records: list[tuple[str, str]],
    *,
    batch_size: int,
    max_new_tokens: int,
    generator: torch.Generator,
    metrics: dict[str, float | int] | None = None,
) -> list[list[str]]:
    """問題ごとにtemperature=0.7の5候補。重複候補も削除しない。"""
    repeated = [record for record in records for _ in range(PASS5_CANDIDATES)]
    codes = generate_codes(
        model, tokenizer, ids, repeated, batch_size=batch_size,
        max_new_tokens=max_new_tokens, temperature=PASS5_TEMPERATURE,
        generator=generator, metrics=metrics,
    )
    if len(codes) != len(repeated):
        raise ValueError("pass@5の生成件数が問題数×5と一致しません")
    return [codes[i : i + PASS5_CANDIDATES] for i in range(0, len(codes), PASS5_CANDIDATES)]


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
    hidden_count: int = DEFAULT_HIDDEN_COUNT,
    hidden_seed: int = DEFAULT_HIDDEN_SEED,
    sampled_codes: list[list[str]] | None = None,
) -> dict[str, Any]:
    """貪欲1候補と抽出5候補を別々に集計。省略されたpass@5はnull（未評価）。"""
    if len(records) != len(gen_codes):
        raise ValueError("問題数とpass@1の候補数が一致しません")
    if hidden_count < 20:
        raise ValueError("hidden testは問題ごとに20入力以上が必要です")
    if sampled_codes is not None and (
        len(sampled_codes) != len(records)
        or any(len(candidates) != PASS5_CANDIDATES for candidates in sampled_codes)
    ):
        raise ValueError("pass@5には各問題につきちょうど5候補が必要です")
    results = []
    for index, ((instruction, reference_code), gen_code) in enumerate(
        zip(records, gen_codes, strict=True)
    ):
        probes_hidden = hidden_inputs(
            instruction, exclude=probes_full,
            count=hidden_count, seed=hidden_seed,
        )
        def judge(code: str) -> dict[str, Any]:
            return {
                "generated_code": code,
                **evaluate_code(code, reference_code, probes_hidden),
                "fixed_probe_passed": check_pass(code, reference_code, probes_full),
                "boundary_passed": check_pass(code, reference_code, probes_boundary),
            }
        greedy = judge(gen_code)
        candidates = [judge(code) for code in sampled_codes[index]] if sampled_codes is not None else []
        results.append({
            "instruction": instruction,
            "reference_code": reference_code,
            **greedy,
            "hidden_inputs": [{"xs": list(xs), "k": k} for xs, k in probes_hidden],
            "pass@1": greedy["passed"],
            "pass@5": any(c["passed"] for c in candidates) if sampled_codes is not None else None,
            "sampled_candidates": candidates,
        })
    n = len(results)
    n_pass = sum(r["passed"] for r in results)
    n_boundary_pass = sum(r["boundary_passed"] for r in results)
    return {
        **aggregate(results),
        "name": name,
        "n": n,
        "pass_rate": n_pass / n if n else 0.0,
        "pass@1": n_pass / n if n else 0.0,
        "pass@5": (sum(r["pass@5"] for r in results) / n if n else 0.0)
                  if sampled_codes is not None else None,
        "fixed_probe_pass_rate": sum(r["fixed_probe_passed"] for r in results) / n if n else 0.0,
        "evaluation_protocol": HIDDEN_PROTOCOL,
        "hidden_count": hidden_count,
        "hidden_seed": hidden_seed,
        "boundary_pass_rate": n_boundary_pass / n if n else 0.0,
        "fixed_probe_pass_at_5": (
            sum(any(c["fixed_probe_passed"] for c in r["sampled_candidates"]) for r in results) / n
            if n else 0.0
        ) if sampled_codes is not None else None,
        "boundary_pass_at_5": (
            sum(any(c["boundary_passed"] for c in r["sampled_candidates"]) for r in results) / n
            if n else 0.0
        ) if sampled_codes is not None else None,
        "pass5_diagnostics": aggregate([c for r in results for c in r["sampled_candidates"]])
                             if sampled_codes is not None else None,
        "results": results,
    }


def print_report(
    reports: list[dict[str, Any]], boundary_overall: float, boundary_n: int,
    boundary_pass5_overall: float,
) -> None:
    print()
    print("hidden判定: pass@1=temperature 0 ×1 / pass@5=temperature 0.7 ×5（別途生成）")
    print(f"{'テスト':16s} {'問題数':>8s} {'pass@1':>10s} {'pass@5':>10s}")
    for r in reports:
        print(f"{r['name']:16s} {r['n']:8d} {r['pass@1']:9.1%} {r['pass@5']:9.1%}")
        print(f"  固定probe（比較用）: pass@1={r['fixed_probe_pass_rate']:.1%} "
              f"pass@5={r['fixed_probe_pass_at_5']:.1%}")
        print(f"  境界値: pass@1={r['boundary_pass_rate']:.1%} pass@5={r['boundary_pass_at_5']:.1%}")
        print("  pass@1候補: " + " ".join(f"{key}={r[key]:.1%}" for key in (
            "syntax_valid_rate", "safe_ast_rate", "signature_valid_rate", "executable_rate"
        )))
        print("  pass@5候補（全5n候補が分母）: " + " ".join(
            f"{key}={value:.1%}" for key, value in r["pass5_diagnostics"].items()
        ))
        print(f"  generation_tokens/s={r['generation_tokens_per_second']:.1f}")
    print()
    print(f"境界値テスト(3カテゴリ合算 {boundary_n}問): "
          f"pass@1={boundary_overall:.1%} pass@5={boundary_pass5_overall:.1%}")


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
    parser.add_argument("--hidden-count", type=int, default=DEFAULT_HIDDEN_COUNT,
                        help="問題ごとのhidden入力数（20以上）")
    parser.add_argument("--hidden-seed", type=int, default=DEFAULT_HIDDEN_SEED,
                        help="hidden入力専用の再現用seed")
    parser.add_argument("--generation-seed", type=int, default=0,
                        help="pass@5の温度0.7サンプリング専用のseed")
    parser.add_argument("--batch-size", type=int, default=64, help="1回のforwardにまとめる件数")
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument("--out", help="結果(1件ごとの生成コード込み)をJSONで書き出す先")
    args = parser.parse_args()
    if args.hidden_count < 20:
        parser.error("--hidden-count は20以上にしてください")
    if args.batch_size < 1 or args.max_new_tokens < 1:
        parser.error("--batch-size と --max-new-tokens は1以上にしてください")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    generator = torch.Generator(device=device).manual_seed(args.generation_seed)
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    tokenizer = Tokenizer.from_file(str(TOKENIZER_PATH))
    ids = load_special_ids(tokenizer)
    model, step = load_model(Path(args.checkpoint), device)
    print(f"checkpoint: {args.checkpoint} (step {step}, device={device})")

    probes_full = load_probe_set(PROBES_PATH)
    probes_boundary = load_boundary_probes(PROBES_PATH)
    print(f"probe set: 全{len(probes_full)}件(うちboundary {len(probes_boundary)}件)")
    print(f"hidden test: 問題ごとに{args.hidden_count}件、seed={args.hidden_seed}")
    print(f"pass@1: temperature=0 ×1 / pass@5: temperature=0.7 ×5、seed={args.generation_seed}")

    reports = []
    for name, path in CATEGORIES.items():
        if not path.exists():
            print(f"[skip] {name}: {path} が無い")
            continue
        limit = args.limit if name == "通常テスト" else 0
        records = sample_records(path, limit, args.seed)
        print(f"{name}: {len(records)}問 ×（貪欲1候補＋抽出5候補）を生成中...")
        greedy_performance: dict[str, float | int] = {}
        sampled_performance: dict[str, float | int] = {}
        gen_codes = generate_codes(
            model, tokenizer, ids, records, batch_size=args.batch_size, max_new_tokens=args.max_new_tokens,
            metrics=greedy_performance, temperature=PASS1_TEMPERATURE,
        )
        sampled_codes = generate_pass5_codes(
            model, tokenizer, ids, records, batch_size=args.batch_size, max_new_tokens=args.max_new_tokens,
            generator=generator, metrics=sampled_performance,
        )
        report = evaluate_category(
            name, records, gen_codes, probes_full=probes_full, probes_boundary=probes_boundary,
            hidden_count=args.hidden_count, hidden_seed=args.hidden_seed,
            sampled_codes=sampled_codes,
        )
        seconds = sum(p.get("generation_seconds", 0.0) for p in (greedy_performance, sampled_performance))
        tokens = sum(p.get("generated_tokens", 0) for p in (greedy_performance, sampled_performance))
        report.update({
            "decoding": decoding_protocol(),
            "generation_seed": args.generation_seed,
            "generation_seconds": seconds,
            "generated_tokens": tokens,
            "generation_tokens_per_second": tokens / seconds if seconds else 0.0,
            "generation_by_metric": {"pass@1": greedy_performance, "pass@5": sampled_performance},
        })
        reports.append(report)

    total_boundary_pass = sum(r["boundary_pass_rate"] * r["n"] for r in reports)
    total_n = sum(r["n"] for r in reports)
    boundary_overall = total_boundary_pass / total_n if total_n else 0.0
    boundary_pass5_overall = (
        sum(r["boundary_pass_at_5"] * r["n"] for r in reports) / total_n if total_n else 0.0
    )

    peak = torch.cuda.max_memory_allocated(device) if device.type == "cuda" else None
    combination_rate = next((r["pass_rate"] for r in reports
                             if r["name"] == "組合せ汎化テスト"), None)
    print_report(reports, boundary_overall, total_n, boundary_pass5_overall)
    print(f"最大GPUメモリ (allocated bytes): {peak if peak is not None else 'N/A (CPU)'}")

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(
            json.dumps(
                {
                    "checkpoint": str(args.checkpoint),
                    "step": step,
                    "device": str(device),
                    "evaluation_protocol": HIDDEN_PROTOCOL,
                    "hidden_count": args.hidden_count,
                    "hidden_seed": args.hidden_seed,
                    "decoding": decoding_protocol(),
                    "generation_seed": args.generation_seed,
                    "batch_size": args.batch_size,
                    "max_new_tokens": args.max_new_tokens,
                    "record_sample_seed": args.seed,
                    "record_limit": args.limit,
                    "max_gpu_memory_bytes": peak,
                    "combination_generalization_rate": combination_rate,
                    "categories": reports,
                    "boundary_pass_rate_overall": boundary_overall,
                    "boundary_pass_at_5_overall": boundary_pass5_overall,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"詳細レポート: {out_path}")


if __name__ == "__main__":
    main()
