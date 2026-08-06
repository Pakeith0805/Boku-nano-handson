"""24opそれぞれの日本語の言い回しを、教師モデル（Qwen）に増やさせる。

    uv sync --group teacher
    python -m scripts.build_phrases --dry-run    # プロンプトだけ見る（GPU不要）
    python -m scripts.build_phrases              # 本番（実測で40分前後）

種は`scripts/teacher/op_seeds.yaml`（人間が書く資産）で、意味の確定はそちらが持つ。
ここがやるのは「種からプロンプトを組み、生成し、行に割り、機械的に弾いて、由来つきで
記録する」ことだけ。

他の`build_*.py`と同じくここは駆動スクリプトであり、教師モデルに実際に触るコードは
`scripts/teacher/qwen.py`に閉じたままである（`scripts/teacher/README.md`の分離方針）。
`--dry-run`が`torch`無しで動くのはそのため——`qwen`の import は使う直前まで遅らせてある。

**出力は辞書ではなく候補である。** `registry.py`の`ja_key`が言うとおり日本語表現辞書は
人間が承認した資産であり、ここが書く`data/teacher/phrases_raw.jsonl`はその手前の材料に
過ぎない。承認済み辞書は別ファイルとして人が選ぶ。`check`が通ったことは形式が整っている
ことしか意味せず、意味が合っている保証はまったくない。

棄却された行も理由つきで全部残す。どの規則がどれだけ効いたかが分かればプロンプトの
どこを直すべきかが分かるためで、`--dry-run`と合わせてプロンプトを育てる材料になる。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scripts.teacher import phrase_filters
from src.semantics.registry import OP_NAMES, OP_REGISTRY, REGISTRY_VERSION

ROOT = Path(__file__).resolve().parents[1]
SEEDS_PATH = ROOT / "scripts" / "teacher" / "op_seeds.yaml"
OUT = ROOT / "data" / "teacher" / "phrases_raw.jsonl"
MANIFEST_OUT = ROOT / "data" / "teacher" / "phrases_manifest.json"

TARGET = 10
"""1opあたり集めたい採用数の下限。"""

BASE_ROUNDS = 3
"""目標に届いていても必ず回す回数。10個で打ち切らず余分に集めて、承認で落とせる幅を作る。"""

MAX_ROUNDS = 6
"""目標に届かないopに追加で回す上限。ここで止めないと、うまく言い換えられないopで無限に粘る。"""

N_PER_REQUEST = 15
"""1リクエストで要求する個数。多く求めるほど後半が崩れるので、採用率と合わせて調整する。"""

MAX_NEW_TOKENS = 640
"""15行×約25トークン＋余裕。足りないと最後の行が途中で切れる（正規化では直せない）。"""

TEMPERATURE = 0.9
TOP_P = 0.95
"""貪欲法（`do_sample=False`）は使えない。同じプロンプトから毎回同じ出力しか出ず、
ラウンドを重ねる意味が消えるため。"""

SEED_BASE = 20260806
"""乱数の種の基準値。実際の種は op と round から決まるので、同じ引数なら何度でも再現できる。"""

MAX_KNOWN_IN_PROMPT = 40
"""「これ以外を書け」としてプロンプトに載せる既出表現の上限。全部載せると入力が伸びて遅くなる。"""

SYSTEM_PROMPT = (
    "あなたは日本語のプログラミング課題文を書く担当です。"
    "与えられた操作の説明を、意味を変えずに別の日本語の言い方へ書き換えます。"
    "説明や前置きは書かず、求められた行だけを出力します。"
)


def load_seeds() -> dict:
    """`op_seeds.yaml`を読み、`OP_REGISTRY`と食い違っていないかを検査する。

    検査は2つ。opのキー集合が完全一致すること（24個の取りこぼしと綴り間違いを防ぐ）と、
    例文に`{k}`があることと`uses_k`が一致することである。

    後者を種の側に`uses_k: true`と書かせず例文から見るのは、そのほうが検査になるからである
    （`registry.py`が`uses_k`と`literal_domain`を二重に書いているのと同じ考え方——
    片方から導出すると常に真になって検査の役に立たない）。
    """
    seeds = yaml.safe_load(SEEDS_PATH.read_text(encoding="utf-8"))
    ops = seeds["ops"]
    literal = str(seeds["literal_probe"])

    missing = set(OP_REGISTRY) - set(ops)
    extra = set(ops) - set(OP_REGISTRY)
    if missing or extra:
        raise ValueError(f"op_seeds.yaml が OP_REGISTRY と一致しない: 不足={missing} 余分={extra}")

    for name, spec in OP_REGISTRY.items():
        for example in ops[name]["examples"]:
            if ("{k}" in example) != spec.uses_k:
                raise ValueError(
                    f"{name}: uses_k={spec.uses_k} なのに例文の {{k}} の有無が食い違う: {example!r}"
                )
        if literal in ops[name]["meaning"] or any(literal in e for e in ops[name]["examples"]):
            raise ValueError(
                f"{name}: 種に検査用リテラル {literal} が裸で書かれている。{{k}} を使うこと"
            )

    return seeds


def build_user_prompt(name: str, seeds: dict, known: list[str], n: int) -> str:
    """1op・1ラウンド分のプロンプトを組む。

    `known`（既に採用済みの言い回し）を載せて「それ以外」と言うのが、ラウンドを重ねたときの
    重複を減らす一番効く手である。載せないと2回目以降も同じ表現が並び、採用数が伸びない。
    """
    spec = seeds["ops"][name]
    literal = str(seeds["literal_probe"])
    render = lambda s: s.replace("{k}", literal)  # noqa: E731

    lines = [
        "次の操作を、同じ意味のまま別の日本語で言い換えてください。",
        "",
        f"操作の意味: {render(spec['meaning'])}",
        "",
        "言い換えの例:",
    ]
    lines += [f"- {render(e)}" for e in spec["examples"]]
    lines += ["", "守ること:"]
    lines += [f"- {rule}" for rule in seeds["style"]]

    if spec["forbid"]:
        lines.append("- 次の語は使わないでください: " + "、".join(spec["forbid"]))
    if known:
        shown = known[-MAX_KNOWN_IN_PROMPT:]
        lines.append("- 次はすでに集めた言い方です。これらとは違う言い方にしてください:")
        lines += [f"  - {p}" for p in shown]

    lines += [
        "",
        f"{n}個の言い換えを、1行に1つずつ出力してください。"
        "番号・記号・前置き・説明は書かないでください。",
    ]
    return "\n".join(lines)


def load_existing() -> tuple[list[dict], set[tuple[str, int]], dict[str, list[str]]]:
    """途中まで書かれた`phrases_raw.jsonl`を読み戻す。

    24op×3ラウンドで40分前後かかるので、落ちたときに最初からやり直さずに済むようにする。
    済んだ`(op, round)`は飛ばし、採用済みの言い回しは次のプロンプトの`known`として引き継ぐ。
    """
    if not OUT.exists():
        return [], set(), defaultdict(list)

    records = [json.loads(line) for line in OUT.read_text(encoding="utf-8").splitlines() if line]
    done = {(r["op"], r["round"]) for r in records}
    accepted: dict[str, list[str]] = defaultdict(list)
    for r in records:
        if r["status"] == "accepted":
            accepted[r["op"]].append(r["normalized"])
    return records, done, accepted


def run_round(
    model,
    tokenizer,
    *,
    name: str,
    round_no: int,
    seeds: dict,
    known: list[str],
    n: int,
    temperature: float,
) -> tuple[list[dict], float]:
    """1op・1ラウンド分を生成して、行ごとのレコードに割る。"""
    from scripts.teacher import qwen

    literal = str(seeds["literal_probe"])
    spec = seeds["ops"][name]
    uses_k = OP_REGISTRY[name].uses_k
    seed = SEED_BASE + OP_NAMES.index(name) * 100 + round_no

    user = build_user_prompt(name, seeds, known, n)
    text = qwen.build_prompt(tokenizer, user, system=SYSTEM_PROMPT)
    completion, _, elapsed = qwen.generate(
        model,
        tokenizer,
        text,
        max_new_tokens=MAX_NEW_TOKENS,
        seed=seed,
        temperature=temperature,
        top_p=TOP_P,
    )

    now = datetime.now(timezone.utc).astimezone().isoformat()
    seen = set(known)
    records = []
    for raw in completion.splitlines():
        if not raw.strip():
            continue
        normalized = phrase_filters.normalize(raw, literal)
        reason = phrase_filters.check(
            normalized,
            uses_k=uses_k,
            literal=literal,
            forbid=spec["forbid"],
            seen=seen,
        )
        accepted = reason is None
        if accepted:
            seen.add(normalized)
            known.append(normalized)
        records.append(
            {
                "op": name,
                "round": round_no,
                "status": "accepted" if accepted else "rejected",
                "reason": reason,
                # `phrase`（{k}版）が後段で使う形。`normalized`は具体値のままの検査対象で、
                # 重複判定と再開時の突き合わせに使う。棄却した行は {k} に戻さない。
                "phrase": phrase_filters.to_placeholder(normalized, literal) if accepted else None,
                "normalized": normalized,
                "raw": raw,
                "seed": seed,
                "temperature": temperature,
                "prompt_version": seeds["version"],
                "registry_version": REGISTRY_VERSION,
                "created_at": now,
            }
        )
    return records, elapsed


def write_manifest(records: list[dict], seeds: dict, temperature: float) -> None:
    """1回分の由来と統計を書く。`data/teacher/manifest.json`（環境の正本）とは別物。"""
    from scripts.teacher import qwen

    accepted = [r for r in records if r["status"] == "accepted"]
    per_op = {
        name: {
            "accepted": sum(1 for r in accepted if r["op"] == name),
            "rounds_run": len({r["round"] for r in records if r["op"] == name}),
        }
        for name in OP_NAMES
    }

    by_phrase: dict[str, set[str]] = defaultdict(set)
    for r in accepted:
        by_phrase[r["phrase"]].add(r["op"])

    MANIFEST_OUT.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_OUT.write_text(
        json.dumps(
            {
                "model": {"id": qwen.MODEL_ID, "revision": qwen.REVISION},
                "params": {
                    "temperature": temperature,
                    "top_p": TOP_P,
                    "max_new_tokens": MAX_NEW_TOKENS,
                    "n_per_request": N_PER_REQUEST,
                    "seed_base": SEED_BASE,
                    "target": TARGET,
                },
                "prompt_version": seeds["version"],
                "registry_version": REGISTRY_VERSION,
                "totals": {
                    "lines": len(records),
                    "accepted": len(accepted),
                    "rejected": len(records) - len(accepted),
                },
                "per_op": per_op,
                "rejection_reasons": dict(
                    Counter(r["reason"] for r in records if r["reason"]).most_common()
                ),
                "below_target": [n for n in OP_NAMES if per_op[n]["accepted"] < TARGET],
                # 同じ言い回しが複数のopで採用されると、その文からopを一意に決められない。
                # 自動では落とさない（どちらを残すかは意味の判断なので）。承認作業への申し送り。
                "cross_op_duplicates": {
                    p: sorted(ops) for p, ops in by_phrase.items() if len(ops) > 1
                },
                "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ops", nargs="*", default=list(OP_NAMES), help="対象のop（既定は24個全部）")
    parser.add_argument("--rounds", type=int, default=BASE_ROUNDS)
    parser.add_argument("--max-rounds", type=int, default=MAX_ROUNDS)
    parser.add_argument("--target", type=int, default=TARGET)
    parser.add_argument("-n", type=int, default=N_PER_REQUEST)
    parser.add_argument("--temperature", type=float, default=TEMPERATURE)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="プロンプトを表示して終わる。モデルを読み込まないのでGPUも teacher グループも要らない",
    )
    args = parser.parse_args()

    seeds = load_seeds()
    unknown = set(args.ops) - set(OP_NAMES)
    if unknown:
        raise SystemExit(f"知らないop: {sorted(unknown)}")

    if args.dry_run:
        for name in args.ops:
            print("=" * 72)
            print(f"[{name}]  uses_k={OP_REGISTRY[name].uses_k}")
            print("=" * 72)
            print(build_user_prompt(name, seeds, known=[], n=args.n))
            print()
        return

    records, done, accepted = load_existing()
    if done:
        print(f"再開: 済み {len(done)} ラウンド / 既存レコード {len(records)} 件")

    from scripts.teacher import qwen

    print(f"モデル読み込み中: {qwen.MODEL_ID} @ {qwen.REVISION[:8]}")
    model, tokenizer = qwen.load()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as fp:
        for name in args.ops:
            round_no = 1
            while round_no <= args.max_rounds:
                # 既定ラウンドを終えたら、目標に届いていないopだけ追加で回す。
                if round_no > args.rounds and len(accepted[name]) >= args.target:
                    break
                if (name, round_no) in done:
                    round_no += 1
                    continue

                new_records, elapsed = run_round(
                    model,
                    tokenizer,
                    name=name,
                    round_no=round_no,
                    seeds=seeds,
                    known=accepted[name],
                    n=args.n,
                    temperature=args.temperature,
                )
                for r in new_records:
                    fp.write(json.dumps(r, ensure_ascii=False) + "\n")
                fp.flush()
                records += new_records

                n_ok = sum(1 for r in new_records if r["status"] == "accepted")
                print(
                    f"{name:<12} round {round_no}: "
                    f"採用 {n_ok:>2}/{len(new_records):>2}  "
                    f"累計 {len(accepted[name]):>2}  ({elapsed:.0f}秒)"
                )
                round_no += 1

    write_manifest(records, seeds, args.temperature)

    below = [n for n in args.ops if len(accepted[n]) < args.target]
    print(f"\n記録: {OUT}")
    print(f"      {MANIFEST_OUT}")
    print(f"採用合計: {sum(1 for r in records if r['status'] == 'accepted')} 件")
    if below:
        print(f"目標{args.target}件に未達のop: {below}")
        print("プロンプト（op_seeds.yaml の meaning / examples）を見直して再実行すること。")
    else:
        print(f"全opが目標{args.target}件に到達。")


if __name__ == "__main__":
    main()
