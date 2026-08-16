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
import hashlib
import json
import uuid
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
DECISIONS = ROOT / "phrases" / "phrase_decisions.jsonl"
"""`review_phrases.py`が書く査読の判定。あれば読み、無ければ無視する。

`data/`ではなく`phrases/`にあるのは、これが生成物ではなく**人間が入れたもの**だからである
（`data/README.md`が「全て再現できる」と宣言しているのに対し、判定は流し直しても再現しない）。
入力として読むファイルという点では`op_seeds.yaml`と同じ立場にある。
"""

RUNS_OUT = ROOT / "data" / "teacher" / "phrases_runs.jsonl"
"""実行1回ぶんの由来。**再現に要るものはすべてここに書く**（1行1実行、追記）。

`phrases_manifest.json`とは役割が違う。あちらは`phrases_raw.jsonl`全体の統計で、実行のたびに
上書きされる——つまり複数回に分けて生成すると、最後の実行の情報しか残らない。由来は
上書きしてはいけないので別ファイルに追記し、各レコードの`run_id`から引けるようにする。
"""


PROMPTS_OUT = ROOT / "data" / "teacher" / "prompts.jsonl"
"""実際にトークナイザへ渡したプロンプトの全文（`prompt_sha256`ごとに1行、追記）。

各レコードの`prompt_sha256`はプロンプトの**同一性**しか保証しない。中身まで復元できなければ
「何を投げたら何が出たか」は結局分からないので、全文をここに残す。ハッシュで重複を除くため、
同じプロンプトを何度投げても1行しか増えない。
"""

# hash生成関数
def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

# プロンプトをprompt.jsonにためていくスクリプト。entryが記録したいデータ、seenが既に記録されているデータのhash値の集合
def record_prompt(entry: dict, seen: set[str]) -> bool:
    """プロンプト全文を追記する。既に同じハッシュを書いていれば何もしない。"""
    if entry["prompt_sha256"] in seen:
        return False
    seen.add(entry["prompt_sha256"])
    PROMPTS_OUT.parent.mkdir(parents=True, exist_ok=True)
    with PROMPTS_OUT.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return True

# この関数を呼び出すと、プロンプトの一覧が得られる。行ごとに分割し、集合として保持
def load_prompt_hashes() -> set[str]:
    if not PROMPTS_OUT.exists():
        return set()
    return {
        json.loads(l)["prompt_sha256"]
        for l in PROMPTS_OUT.read_text(encoding="utf-8").splitlines()
        if l
    }


TARGET = 10
"""1opあたり集めたい採用数の下限。"""

BASE_ROUNDS = 5
"""目標に届いていても必ず回す回数。10個で打ち切らず余分に集めて、承認で落とせる幅を作る。"""

MAX_ROUNDS = 3200
"""目標に届かないopに追加で回す上限。ここで止めないと、うまく言い換えられないopで無限に粘る。

済んだラウンドは飛ばされるので、この値を上げてから流し直せば「続きのラウンド」だけが走る。
"""

MAX_REVIEWED_IN_PROMPT = 24
"""承認済み・却下済みの表現をプロンプトに何件まで載せるか（それぞれの上限）。"""

N_PER_REQUEST = 8
"""1リクエストで要求する個数。

**多く求めるほど質が落ちる。** 15個で試したところ、モデルは良い言い方を出し尽くした後も
数を揃えようとして捏造を始めた——`take_first`に「先頭から{k}個を除く」（正反対）、
`sub_k`に「各要素を{k}引きずる」（日本語として壊れている）、`mul_k`に「各要素に{k}を加える」
（`add_k`の意味）といった具合である。少なく求めてラウンドを増やすほうが、同じ時間で
使える候補が多く集まる。
"""

MAX_NEW_TOKENS = 384
"""8行×約25トークン＋余裕。足りないと最後の行が途中で切れる（正規化では直せない）。"""

TEMPERATURE = 0.9
TOP_P = 0.95
"""貪欲法（`do_sample=False`）は使えない。同じプロンプトから毎回同じ出力しか出ず、
ラウンドを重ねる意味が消えるため。"""

SEED_BASE = 20260806
"""乱数の種の基準値。実際の種は op と round から決まるので、同じ引数なら何度でも再現できる。"""

MAX_KNOWN_IN_PROMPT = 40
"""「これ以外を書け」としてプロンプトに載せる既出表現の上限。全部載せると入力が伸びて遅くなる。"""

SYSTEM_PROMPT_TEMPLATE = (
    "あなたは日本語のプログラミング課題文を書く担当です。"
    "課題文は必ず「{frame}、」という書き出しで始まり、あなたが書くのはその続きの部分だけです。"
    "この書き出しに自然につながる日本語を書いてください。"
    "書き出しそのものを繰り返してはいけません。"
    "与えられた操作の説明を、意味を変えずに別の日本語の言い方へ書き換えてください。"
    "説明や前置きは書かず、求められた行だけを出力してください。"
)
"""system prompt の雛形。`{frame}` は `op_seeds.yaml` の書き出しで埋める。

書き出しは24op・全ラウンドを通じて不変なので、opごとに変わる指示（意味・正例・禁止語）とは
置き場所を分ける。恒常的な役割の宣言は system 側に置くのが素直であり、ユーザープロンプトに
混ぜると「今回だけの指示」と見分けがつかない。

「書き出しそのものを繰り返してはいけない」を明示するのは、書き出しを見せ始めた副作用で
「整数を要素に持つリストに対して、各要素を7で減らす」のように枠ごと復唱する行が
出るようになったためである。
"""

# op_seedsってのが、プロンプトの種。registryと食い違ってないか判定し、大丈夫ならseedを返す。seedっていうのは、それさえあればプロンプトを組み立てられる辞書型変数。
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
    literal = str(seeds["literal_probe"]) # literal_probeは、{k}に入れる具体値。qwenに{k}を出させるとバグりやすい

    # registoryと比較して過不足ないか判定。会ったらエラー
    missing = set(OP_REGISTRY) - set(ops)
    extra = set(ops) - set(OP_REGISTRY)
    if missing or extra:
        raise ValueError(f"op_seeds.yaml が OP_REGISTRY と一致しない: 不足={missing} 余分={extra}")

    # {k}の代わりに仮で入れておく数字が例文にそのまま残ってたり、kが存在するはずなのになかったり、逆にkがないはずなのにあったりしたらエラー
    for name, spec in OP_REGISTRY.items():
        # 「例文にkが含まれているか」と、「kを含むopか」が不一致ならエラー
        for example in ops[name]["examples"]:
            if ("{k}" in example) != spec.uses_k:
                raise ValueError(
                    f"{name}: uses_k={spec.uses_k} なのに例文の {{k}} の有無が食い違う: {example!r}"
                )
        # probe_literal(7)がそのまま残ってたらエラー
        if literal in ops[name]["meaning"] or any(literal in e for e in ops[name]["examples"]):
            raise ValueError(
                f"{name}: 種に検査用リテラル {literal} が裸で書かれている。{{k}} を使うこと"
            )

    return seeds

# 人間の査読結果を返す。
def load_review() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """査読の結果（`review_phrases.py`が書く判定）をop別に読む。無ければ空を返す。

    機械の検査は形式しか見ないので、これを読まないと生成側は「何が良い言い回しだったか」を
    永遠に知らない。実際、`sub_k`は機械が24件通したのに人間の承認は0件だった——
    助詞を誤った「各要素を{k}で引く」ばかりが並んでいて、機械にはその誤りが見えていない。
    """
    approved: dict[str, list[str]] = defaultdict(list)
    rejected: dict[str, list[str]] = defaultdict(list)
    if not DECISIONS.exists():
        return approved, rejected
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        d = json.loads(line)
        (approved if d["decision"] == "approved" else rejected)[d["op"]].append(d["phrase"])
    return approved, rejected

# ここでプロンプト全文を組み上げる。
def build_user_prompt(
    name: str,
    seeds: dict,
    known: list[str],
    n: int,
    good: list[str] = (),
    bad: list[str] = (),
) -> str:
    """1op・1ラウンド分のプロンプトを組む。

    `known`（既に採用済みの言い回し）を載せて「それ以外」と言うのが、ラウンドを重ねたときの
    重複を減らす一番効く手である。載せないと2回目以降も同じ表現が並び、採用数が伸びない。

    `good`/`bad`は人間の査読を通った表現と落とされた表現。種の正例だけでは足りないopが
    あるので、承認済みを追加の正例として、却下済みを反例として見せる。
    """
    spec = seeds["ops"][name]
    literal = str(seeds["literal_probe"])
    render = lambda s: s.replace("{k}", literal)  # noqa: E731

    frame = seeds["frame"]
    lines = [
        "次の操作を、同じ意味のまま別の日本語で言い換えてください。",
        "",
        f"操作の意味: {render(spec['meaning'])}",
        "",
        # 書き出しを毎回見せる。単独で完結した文を書かせると対象を言い直してしまい
        # （「リストを並べる」）、実際に組み上げた文で重複する。
        f"言い換えは必ず「{frame}、」に続く形で使われます。その続きの部分だけを書いてください。",
        "",
        f"言い換えの例（いずれも「{frame}、」に続く部分）:",
    ]
    lines += [f"- {render(e)}" for e in spec["examples"]]
    if good:
        lines += [f"- {render(g)}" for g in good[-MAX_REVIEWED_IN_PROMPT:]]

    if bad:
        lines += ["", "次はいずれも誤りとして退けられた言い方です。同じ型を繰り返さないでください:"]
        lines += [f"- {render(b)}" for b in bad[-MAX_REVIEWED_IN_PROMPT:]]

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
    run_id: str,
    system_prompt: str,
    prompt_hashes: set[str],
    echo_prompt: bool,
    good: list[str] = (),
    bad: list[str] = (),
) -> tuple[list[dict], float]:
    """1op・1ラウンド分を生成して、行ごとのレコードに割る。"""
    from scripts.teacher import qwen

    literal = str(seeds["literal_probe"])
    spec = seeds["ops"][name]
    uses_k = OP_REGISTRY[name].uses_k
    seed = SEED_BASE + OP_NAMES.index(name) * 100 + round_no

    # 査読済みなら good/bad がそのまま既出の一覧になるので、`known` は載せない
    # （同じ内容を二度見せてもプロンプトが伸びるだけ）。
    shown_known = [] if (good or bad) else known
    user = build_user_prompt(name, seeds, shown_known, n, good=good, bad=bad)
    text = qwen.build_prompt(tokenizer, user, system=system_prompt)
    prompt_hash = sha256(text)

    record_prompt(
        {
            "prompt_sha256": prompt_hash,
            "run_id": run_id,
            "op": name,
            "round": round_no,
            "system_prompt": system_prompt,
            "user_prompt": user,
            # トークナイザに渡した全文。chat template の記法込みで、これが実際に投げたもの。
            "templated_text": text,
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        },
        prompt_hashes,
    )
    if echo_prompt:
        print(f"\n{'─' * 72}\n[{name} round {round_no}] prompt {prompt_hash[:12]}\n{'─' * 72}")
        print(user)
        print("─" * 72)

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
                # 再現に要るもの。run_id から phrases_runs.jsonl の1行（モデル・量子化・
                # ライブラリ版・system prompt・sampling設定）が引ける。
                "run_id": run_id,
                "seed": seed,
                "temperature": temperature,
                # 実際にトークナイザに渡した全文のハッシュ。chat template も system prompt も
                # 査読由来の正例・反例も含んだ、まさに投げた文字列そのものを指す。
                "prompt_sha256": prompt_hash,
                "prompt_version": seeds["version"],
                "registry_version": REGISTRY_VERSION,
                "created_at": now,
            }
        )
    return records, elapsed


def write_run(run: dict) -> None:
    """実行1件の由来を追記する（既にあれば同じ`run_id`の行を差し替える）。

    開始時に一度書き、終了時に結果を足して書き直す。開始時に書くのは、途中で落ちた実行の
    由来も残すためである（レコードだけあって由来が無い、という状態を作らない）。
    """
    RUNS_OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if RUNS_OUT.exists():
        rows = [json.loads(l) for l in RUNS_OUT.read_text(encoding="utf-8").splitlines() if l]
    rows = [r for r in rows if r["run_id"] != run["run_id"]] + [run]
    RUNS_OUT.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )


def write_manifest(records: list[dict], seeds: dict, temperature: float) -> None:
    """`phrases_raw.jsonl`全体の統計を書く。**実行のたびに上書きする**。

    由来は`RUNS_OUT`の担当であってこちらではない。ここが持つのは「今ファイルに何件あるか」
    だけで、それは常に最新の1枚でよい（過去の統計は残っているレコードから数え直せる）。
    """
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
        "--below-target",
        action="store_true",
        help="承認数が目標未満のopだけを対象にする（査読の判定を読む）",
    )
    parser.add_argument(
        "--quiet-prompts",
        action="store_true",
        help="投げたプロンプトを標準出力に出さない（data/teacher/prompts.jsonl には必ず残る）",
    )
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

    approved, rejected = load_review()
    if args.below_target:
        if not approved and not rejected:
            raise SystemExit(f"査読の判定がない: {DECISIONS}")
        args.ops = [n for n in args.ops if len(approved[n]) < args.target]
        print(f"承認数が{args.target}件未満のop（{len(args.ops)}個）: {args.ops}")

    # 書き出しは24op共通なので system 側で宣言する。生成のたびに実際に投げた全文を
    # 由来に記録するので、雛形ではなくこの展開後の文字列を持ち回る。
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(frame=seeds["frame"])

    if args.dry_run:
        print("─" * 72)
        print("[system]")
        print(system_prompt)
        for name in args.ops:
            print("=" * 72)
            print(f"[{name}]  uses_k={OP_REGISTRY[name].uses_k}  承認済み {len(approved[name])} 件")
            print("=" * 72)
            print(
                build_user_prompt(
                    name, seeds, known=[], n=args.n, good=approved[name], bad=rejected[name]
                )
            )
            print()
        return

    records, done, accepted = load_existing()
    if done:
        print(f"再開: 済み {len(done)} ラウンド / 既存レコード {len(records)} 件")

    # 目標の判定は、査読があればその承認数で行う。機械が通した数で測ると、
    # `sub_k`（機械24件・承認0件）のようなopが「達成済み」と見なされて1ラウンドも回らない。
    def progress(name: str) -> int:
        return len(approved[name]) if (approved or rejected) else len(accepted[name])

    from scripts.teacher import qwen

    run_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    run = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "finished_at": None,
        **qwen.provenance(),
        "system_prompt": system_prompt,
        "sampling": {
            "do_sample": args.temperature is not None,
            "temperature": args.temperature,
            "top_p": TOP_P,
            "max_new_tokens": MAX_NEW_TOKENS,
            "n_per_request": args.n,
            "seed_base": SEED_BASE,
            "seed_formula": "SEED_BASE + OP_NAMES.index(op) * 100 + round",
        },
        "prompt_version": seeds["version"],
        "registry_version": REGISTRY_VERSION,
        # 種は人間が書く資産なので、変更を追える形で残す。
        # 査読の状態（phrase_decisions.jsonl）はハッシュを取らない——プロンプトの中身は
        # data/teacher/prompts.jsonl に全文が残っており、生成の再現にはそれで足りるため。
        "seeds_sha256": sha256(SEEDS_PATH.read_text(encoding="utf-8")),
        "args": {
            "ops": list(args.ops),
            "rounds": args.rounds,
            "max_rounds": args.max_rounds,
            "target": args.target,
            "below_target": args.below_target,
        },
    }
    write_run(run)
    prompt_hashes = load_prompt_hashes()
    print(f"run_id: {run_id}")

    print(f"モデル読み込み中: {qwen.MODEL_ID} @ {qwen.REVISION[:8]}")
    model, tokenizer = qwen.load()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as fp:
        for name in args.ops:
            round_no = 1
            while round_no <= args.max_rounds:
                # 既定ラウンドを終えたら、目標に届いていないopだけ追加で回す。
                if round_no > args.rounds and progress(name) >= args.target:
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
                    run_id=run_id,
                    system_prompt=system_prompt,
                    prompt_hashes=prompt_hashes,
                    echo_prompt=not args.quiet_prompts,
                    good=approved[name],
                    bad=rejected[name],
                )
                for r in new_records:
                    fp.write(json.dumps(r, ensure_ascii=False) + "\n")
                fp.flush()
                records += new_records

                n_ok = sum(1 for r in new_records if r["status"] == "accepted")
                print(
                    f"{name:<12} round {round_no}: "
                    f"採用 {n_ok:>2}/{len(new_records):>2}  "
                    f"新候補 {len(accepted[name]):>2} / 承認済み {progress(name):>2}"
                    f"  ({elapsed:.0f}秒)"
                )
                round_no += 1

    run["finished_at"] = datetime.now(timezone.utc).astimezone().isoformat()
    run["produced"] = {
        "lines": sum(1 for r in records if r.get("run_id") == run_id),
        "accepted": sum(
            1 for r in records if r.get("run_id") == run_id and r["status"] == "accepted"
        ),
    }
    write_run(run)

    write_manifest(records, seeds, args.temperature)

    below = [n for n in args.ops if progress(n) < args.target]
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
