"""生成された言い回しの候補を1件ずつ承認し、日本語表現辞書として凍結する。

    python -m scripts.review_phrases              # 続きから査読する
    python -m scripts.review_phrases --ops abs    # opを絞る
    python -m scripts.review_phrases --compile    # 査読はせず、今の判定から辞書だけ書き直す

`data/teacher/phrases_raw.jsonl`（機械が形式だけ検査した候補）を読み、キー入力で1件ずつ
採用・却下していく。判定は`phrases/phrase_decisions.jsonl`に随時書き出すので、
`q`でいつ中断しても続きから再開できる。最後に`phrases/ja_phrases_v1.yaml`を書く。

**ここが「意味の検査」を行う唯一の場所である。** `phrase_filters`が通したことは形式が
整っていることしか意味しない。実際、機械が通した候補には`abs`に対する「負の値を除去する」
（それは`positive`）のような誤りが相当数混ざっている。判定基準を見失わないよう、
opごとに`op_seeds.yaml`の`meaning`を画面に出し続ける。

判定も辞書も`data/`でなく`phrases/`に置く。`data/README.md`が「全て`scripts/`配下から
再現できる」と宣言しているのに対し、どちらも人間の判断が入っていて再現できないためである。
`probes/behavior_probe_set_v1.jsonl`と同じ「凍結された資産」の扱いにする。
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
import termios
import tty
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scripts.teacher import phrase_filters
from src.semantics.registry import OP_NAMES, OP_REGISTRY, REGISTRY_VERSION

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "teacher" / "phrases_raw.jsonl"
SEEDS_PATH = ROOT / "scripts" / "teacher" / "op_seeds.yaml"
DECISIONS = ROOT / "phrases" / "phrase_decisions.jsonl"
"""査読の判定。

`DICT_OUT`と違って版を付けないのは、判定が辞書の版をまたいで積み上がる記録だからである。
`DICT_VERSION`を上げても捨てずに引き継ぎ、そこから各版の辞書を組み直す。
"""

DICT_VERSION = "v1"
DICT_OUT = ROOT / "phrases" / f"ja_phrases_{DICT_VERSION}.yaml"
MANIFEST_OUT = ROOT / "phrases" / f"ja_phrases_{DICT_VERSION}_manifest.json"

TARGET = 10
"""1opあたり集めたい採用数の下限。`build_phrases.py`と同じ値。"""

SIMILAR = 0.72
"""「採用済みのこれと似ている」と警告する類似度の閾値（`difflib`の比）。

1件ずつ見ていくと、直前に採用したものとほぼ同じ候補に気づけない。`各要素に{k}を足す`を
採用した直後の`要素に{k}を足す`のような、間引くべき候補を取りこぼさないための補助である。
"""

NON_JA_KANJI = "值变顺减乘并个后头负绝对组转换选择删过滤计输长为从将应该间义"
"""日本語では使わない字体（簡体字）。含まれていたら警告する。

教師モデルは稀に中国語の字体を混ぜてくる（実際に`絶対值`＝U+503C が出た。`値`はU+5024）。
見た目がほとんど同じで目視では気づけないので機械に指摘させる。**却下はしない**——
網羅的な一覧ではなく取りこぼしがあるため、あくまで注意喚起に留める。
"""

KEYS = "y=採用  n=却下  e=編集して採用  s=保留  u=取り消し  q=中断して保存"


# ---- 入力 ----------------------------------------------------------------


def read_key() -> str:
    """1文字だけ読む（Enter不要）。

    数百件を1件ずつ捌くので、1件につきEnterまで押させると倍のキーストロークになる。
    端末でないとき（パイプ経由など）は行単位の読み込みに落とす。
    """
    if not sys.stdin.isatty():
        line = sys.stdin.readline()
        return (line.strip()[:1] or "q").lower()

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    if ch in ("\x03", "\x04"):  # Ctrl-C / Ctrl-D
        raise KeyboardInterrupt
    return ch.lower()


def edit_text(text: str) -> str:
    """元の文字列を入れた状態で編集させる。

    「惜しい」候補（`絶対値を置き換える`→`絶対値に置き換える`）を捨てずに直せるようにする。
    却下してやり直すより、1文字直すほうが辞書は早く育つ。
    """
    import readline

    readline.set_startup_hook(lambda: readline.insert_text(text))
    try:
        return input("  編集> ").strip()
    finally:
        readline.set_startup_hook()


# ---- 候補の読み込みと並べ方 ------------------------------------------------


ORIGIN_FIELDS = ("run_id", "round", "seed", "prompt_sha256", "prompt_version", "created_at")
"""判定に焼き付ける、候補を生んだ生成の由来。

判定レコードは単体で意味を持たなければならない。`(op, 表現)`で`phrases_raw.jsonl`を引けば
辿れるとはいえ、その突き合わせは生成物を消した瞬間に切れる——承認済み辞書は生成物より
長く生きる資産なので、由来は判定の側にも複製しておく。
"""


def load_candidates(
    include_rejected: list[str],
) -> tuple[dict[str, list[str]], dict[tuple[str, str], dict]]:
    """`phrases_raw.jsonl`からop別の候補と、その由来を読む。

    既定では機械の検査を通った行だけを対象にする。`include_rejected`に棄却理由を渡すと、
    その理由で落ちた行も候補に戻す（`not_terminal_form`のように、言い方としては妥当なのに
    文型だけ外れた行を人が救えるようにするため）。
    """
    if not RAW.exists():
        raise SystemExit(f"候補がない: {RAW}（先に build_phrases.py を流すこと）")

    out: dict[str, list[str]] = defaultdict(list)
    origins: dict[tuple[str, str], dict] = {}
    for line in RAW.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        r = json.loads(line)
        if r["status"] == "accepted":
            phrase = r["phrase"]
        elif r["reason"] in include_rejected:
            phrase = r["normalized"]
        else:
            continue
        if (r["op"], phrase) in origins:
            continue
        origins[(r["op"], phrase)] = {k: r.get(k) for k in ORIGIN_FIELDS}
        out[r["op"]].append(phrase)
    return out, origins


def chain_order(phrases: list[str]) -> list[str]:
    """似た候補が隣り合うように並べ替える。

    1件ずつ見る形式では、似たものが離れていると「さっき採ったあれと同じでは」と思い出せない。
    最も短いもの（＝素直な言い方）から始めて、直前に一番似ているものを繋いでいく。
    候補はopあたり数十件なので、総当たりで足りる。
    """
    remaining = sorted(phrases, key=lambda s: (len(s), s))
    ordered = [remaining.pop(0)] if remaining else []
    while remaining:
        last = ordered[-1]
        i = max(
            range(len(remaining)),
            key=lambda j: difflib.SequenceMatcher(None, last, remaining[j]).ratio(),
        )
        ordered.append(remaining.pop(i))
    return ordered


# ---- 判定の永続化 ----------------------------------------------------------


def load_decisions() -> list[dict]:
    if not DECISIONS.exists():
        return []
    return [json.loads(l) for l in DECISIONS.read_text(encoding="utf-8").splitlines() if l]


def save_decisions(decisions: list[dict]) -> None:
    """毎回まるごと書き直す。

    追記でなく上書きなのは`u`（取り消し）を素直に実装するためである。数百行なので
    書き直しの費用は無視できる。1件ごとに書くので、いつ落としても判定は残る。
    """
    DECISIONS.parent.mkdir(parents=True, exist_ok=True)
    DECISIONS.write_text(
        "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in decisions), encoding="utf-8"
    )


# ---- 画面 ------------------------------------------------------------------


def show_header(op: str, meaning: str, approved: list[str], n_done: int, n_total: int) -> None:
    print("\n" + "═" * 78)
    print(f"  [{op}]  {meaning}")
    print(f"  採用 {len(approved)} 件 / 判定済み {n_done} / 候補 {n_total}")
    if approved:
        print("  採用済み: " + " ／ ".join(approved))
    print("═" * 78)


def show_candidate(phrase: str, approved: list[str], index: int, total: int) -> None:
    print(f"\n  ({index}/{total})  \033[1m{phrase}\033[0m")

    near = [(difflib.SequenceMatcher(None, phrase, a).ratio(), a) for a in approved]
    if near:
        ratio, best = max(near)
        if ratio >= SIMILAR:
            print(f"    \033[33m≈ 採用済みの「{best}」と似ている（{ratio:.2f}）\033[0m")

    bad = sorted({ch for ch in phrase if ch in NON_JA_KANJI})
    if bad:
        print(f"    \033[33m⚠ 日本語で使わない字体: {' '.join(bad)}\033[0m")

    print(f"    {KEYS}")


# ---- 辞書の書き出し --------------------------------------------------------


def compile_dictionary(decisions: list[dict], seeds: dict) -> None:
    """判定から辞書を組み、検証して書き出す。

    手で編集できる以上、検証なしには通せない。ここで見るのは形式だけだが、形式の破れは
    機械にしか見つけられない（`{k}`を消してしまった、他のopと同じ表現になった、など）。
    """
    literal = str(seeds["literal_probe"])
    approved: dict[str, list[str]] = defaultdict(list)
    for d in decisions:
        if d["decision"] == "approved":
            approved[d["op"]].append(d["phrase"])

    problems: list[str] = []

    owner: dict[str, list[str]] = defaultdict(list)
    for op, phrases in approved.items():
        for p in phrases:
            owner[p].append(op)
    for phrase, ops in sorted(owner.items()):
        if len(ops) > 1:
            # 同じ表現が2つのopにあると、その文からopを一意に決められない。
            # 意味の判断なのでどちらを残すかは機械には決められず、止めて人に返すしかない。
            problems.append(f"op間で重複: {phrase!r} が {sorted(ops)} の両方にある")

    for op, phrases in approved.items():
        spec = OP_REGISTRY[op]
        for p in phrases:
            concrete = p.replace("{k}", literal)
            reason = phrase_filters.check(
                concrete,
                uses_k=spec.uses_k,
                literal=literal,
                forbid=seeds["ops"][op]["forbid"],
                seen=(),
            )
            if reason is not None:
                problems.append(f"{op}: {p!r} が規則に反する（{reason}）")

    below = [op for op in OP_NAMES if len(approved.get(op, [])) < TARGET]

    if problems:
        print("\n\033[31m辞書を書けない。次を直してから再実行すること:\033[0m")
        for p in problems:
            print(f"  - {p}")
        print(f"\n判定は {DECISIONS} に残っている。")
        raise SystemExit(1)

    body = {op: sorted(approved[op]) for op in OP_NAMES if approved.get(op)}
    header = (
        f"# 承認済み日本語表現辞書 {DICT_VERSION}\n"
        f"# 引き当てキーは OP_REGISTRY の ja_key。`{{k}}` は k 参照opのスロット。\n"
        f"# 生成物ではなく人間が承認した資産である。`scripts/review_phrases.py` で作るが、\n"
        f"# 中身を決めているのは判定した人間であり、流し直しても同じものは再現されない。\n"
        f"# registry_version: {REGISTRY_VERSION}\n\n"
    )
    DICT_OUT.parent.mkdir(parents=True, exist_ok=True)
    DICT_OUT.write_text(
        header + yaml.safe_dump(body, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )

    edited = sum(1 for d in decisions if d["decision"] == "approved" and d["edited"])
    MANIFEST_OUT.write_text(
        json.dumps(
            {
                "dictionary_version": DICT_VERSION,
                "registry_version": REGISTRY_VERSION,
                "prompt_version": seeds["version"],
                "target_per_op": TARGET,
                "totals": {
                    "reviewed": len(decisions),
                    "approved": sum(len(v) for v in approved.values()),
                    "rejected": sum(1 for d in decisions if d["decision"] == "rejected"),
                    "edited_on_approval": edited,
                },
                "per_op": {op: len(approved.get(op, [])) for op in OP_NAMES},
                "below_target": below,
                # この辞書に寄与した生成実行。data/teacher/phrases_runs.jsonl の該当行に
                # モデル・量子化・ライブラリ版・system prompt・sampling設定がある。
                "source_runs": sorted(
                    {
                        d["origin"]["run_id"]
                        for d in decisions
                        if d["decision"] == "approved" and d.get("origin", {}).get("run_id")
                    }
                ),
                "compiled_at": datetime.now(timezone.utc).astimezone().isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"\n辞書: {DICT_OUT}（{sum(len(v) for v in body.values())} 件 / {len(body)} op）")
    print(f"要約: {MANIFEST_OUT}")
    if below:
        print(f"\n\033[33m{TARGET}件に未達のop（{len(below)}個）: {below}\033[0m")
        print("build_phrases.py でラウンドを足すか、op_seeds.yaml を見直すこと。")


# ---- 本体 ------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ops", nargs="*", default=list(OP_NAMES), help="査読するop（既定は全部）")
    parser.add_argument(
        "--include-rejected",
        nargs="*",
        default=[],
        metavar="理由",
        help="機械が落とした行も候補に戻す（例: not_terminal_form）",
    )
    parser.add_argument("--compile", action="store_true", help="査読せず、今の判定から辞書を書く")
    args = parser.parse_args()

    seeds = yaml.safe_load(SEEDS_PATH.read_text(encoding="utf-8"))
    literal = str(seeds["literal_probe"])
    decisions = load_decisions()

    if args.compile:
        compile_dictionary(decisions, seeds)
        return

    candidates, origins = load_candidates(args.include_rejected)
    decided = {(d["op"], d["source"]) for d in decisions}
    approved: dict[str, list[str]] = defaultdict(list)
    for d in decisions:
        if d["decision"] == "approved":
            approved[d["op"]].append(d["phrase"])

    print(f"候補 {sum(len(v) for v in candidates.values())} 件 / 判定済み {len(decisions)} 件")
    print(f"表示は具体値でなく `{{k}}` のまま（検査用リテラルは {literal}）。{KEYS}")

    quit_now = False
    for op in args.ops:
        if quit_now:
            break
        queue = [p for p in chain_order(candidates.get(op, [])) if (op, p) not in decided]
        if not queue:
            continue

        show_header(op, seeds["ops"][op]["meaning"], approved[op], len(decisions), len(queue))

        i = 0
        while i < len(queue):
            phrase = queue[i]
            show_candidate(phrase, approved[op], i + 1, len(queue))
            key = read_key()

            if key == "q":
                quit_now = True
                break
            if key == "u":
                if not decisions:
                    print("    取り消せる判定がない。")
                    continue
                last = decisions.pop()
                if last["decision"] == "approved":
                    approved[last["op"]].remove(last["phrase"])
                decided.discard((last["op"], last["source"]))
                save_decisions(decisions)
                print(f"    取り消し: {last['source']}")
                if last["op"] == op and last["source"] in queue:
                    i = queue.index(last["source"])
                continue
            if key == "s":
                # 保留は記録しない。次回の実行でもう一度聞かれる。
                i += 1
                continue
            if key == "e":
                text = edit_text(phrase)
                reason = phrase_filters.check(
                    text.replace("{k}", literal),
                    uses_k=OP_REGISTRY[op].uses_k,
                    literal=literal,
                    forbid=seeds["ops"][op]["forbid"],
                    seen=[a.replace("{k}", literal) for a in approved[op]],
                )
                if reason is not None:
                    print(f"    \033[31m規則に反するので採用しない（{reason}）\033[0m")
                    continue
                final, edited = phrase_filters.to_placeholder(text, literal), True
            elif key == "y":
                final, edited = phrase, False
            elif key == "n":
                final, edited = phrase, False
            else:
                print(f"    {KEYS}")
                continue

            decision = "rejected" if key == "n" else "approved"
            decisions.append(
                {
                    "op": op,
                    "source": phrase,
                    "phrase": final,
                    "decision": decision,
                    "edited": edited,
                    "decided_at": datetime.now(timezone.utc).astimezone().isoformat(),
                    # 候補を生んだ生成の由来（run_id からモデル・量子化・ライブラリ版・
                    # system prompt・sampling設定が引ける）。判定を単体で意味のある記録にする。
                    "origin": origins.get((op, phrase), {}),
                }
            )
            decided.add((op, phrase))
            if decision == "approved":
                approved[op].append(final)
            save_decisions(decisions)
            i += 1

        remaining = [p for p in queue if (op, p) not in decided]
        if not quit_now:
            print(f"\n  [{op}] 完了。採用 {len(approved[op])} 件"
                  + (f"（保留 {len(remaining)} 件）" if remaining else ""))

    print(f"\n判定 {len(decisions)} 件を {DECISIONS} に記録した。")
    compile_dictionary(decisions, seeds)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n中断した。判定は保存済み。")
