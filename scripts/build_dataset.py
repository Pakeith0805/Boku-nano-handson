"""意味ASTコーパスから、最終的な訓練/検証/テストデータセットを組み立てる。

```
python -m scripts.build_dataset
python -m scripts.build_dataset --limit-asts 200   # 動作確認用に規模を絞る
python -m scripts.build_dataset --workers 1        # 逐次実行（デバッグ用）
```

処理の順番（`src/select/README.md`の設計と同じ）:

```
combination.py（組合せ汎化テスト用に隔離） → split.py（behavior_hash単位で80/10/10に分割）
  → difficulty.py（split毎にdifficulty 1〜3全数・4だけ間引く） → balance.py（コード形式・
  日本語テンプレートを貪欲に均しつつ選ぶ） → record.py（最終レコードに組み立て・検証）
```

train/val/testに加えて、組合せ汎化テスト・言い換えテストは固定30件ずつの小規模な集合として
別ファイルに書き出す（人が目で見て確認できる規模に留める）。境界値テストは別ファイルを
作らない——`probes/behavior_probe_set_v1.jsonl`に境界値入力が既に含まれており、評価スクリプト
が生成済みコードにそれを流し込むだけで足りるため。

事前に`build_probe_set.py`・`build_ast_corpus.py`・`review_phrases.py --compile`を
実行しておくこと。

## 選抜条件（9項目）のうち、まだ満たしていないもの

「長さ上限を超えない」だけ**未実装**（2026-08-23時点、意図的に先送り）。他8項目
（`ast.parse`成功・許可構文・タイムアウト・参照インタプリタ一致・シグネチャ・完全重複排除・
AST偏りの上限）はこのスクリプトと`src/verify/`・`src/select/`で満たしている。

長さ上限は本来トークン数の話（課題文の目安「1レコード65〜145 tokens」）だが、**トークナイザが
まだ無い**（Phase 2、未着手）ため正確に測れない。文字数ベースの暫定フィルタを今入れる案も
検討したが、トークナイザ完成後にどのみち作り直しになるため、Phase 2でトークナイザができて
から本来の形（トークン数上限）で実装する方針にした。実データでの参考値（文字数）:
`reference_code`は37〜511文字（平均208）、`instruction_ja`は37〜104文字（平均74）で、
現時点で明らかな外れ値は無い。

## 並列化について

1レコードあたりの支配的なコストは`record.build_record`内の`sandbox.execute`（固定入力
148件ぶんの実行）で、AST間に依存が無く並列化しやすい。ASTの列を`--workers`個のチャンクに
ラウンドロビンで分け、`multiprocessing.Pool`のワーカープロセスごとに独立して処理する。

`balance.py`の貪欲な均し（`code_counts`/`phrase_counts`）は、**ワーカーごとに別々の
`Counter`を持つ**（プロセスをまたいだ共有はしない）。全ワーカーを通した完全なグローバル
均しではなくなるが、構造の軸は元々`reverse_style`のように母集団サイズで上限が決まっており
（`src/select/README.md`参照）、単一プロセスでも比率6.86倍程度までしか均せていなかった。
チャンクを難易度が混ざるようラウンドロビンで割ることで、ワーカーごとの偏りも抑えている。

`sandbox.execute`の`signal.setitimer`はプロセスのメインスレッドでしか使えないが、
`multiprocessing`はスレッドではなく別プロセスを起動するため、各ワーカーはそれぞれ自分の
メインスレッドを持ち、制約に抵触しない（`threading`ベースの並列化だとここで壊れる）。
"""

from __future__ import annotations

import argparse
import json
import os
import random
from collections import Counter
from collections.abc import Iterable, Sequence
from multiprocessing import Pool
from pathlib import Path
from typing import Any

import yaml

from src.codegen.codegen import enumerate_candidates as code_candidates
from src.nlg.nlgen import enumerate_candidates as nl_candidates
from src.nlg.nlgen import split_phrase_pool
from src.probes.behavior_probes import PROBE_SET_VERSION, default_probe_set_path, load_probe_set
from src.select.balance import Example, select_examples
from src.select.combination import RESERVED_PAIRS, carve_out_combinations
from src.select.difficulty import select_difficulty_thinned
from src.select.record import build_record
from src.select.split import split_corpus
from src.semantics.corpus import read_records, write_records
from src.semantics.semantic_ast import SemanticAST

ROOT = Path(__file__).resolve().parents[1]
ASTS_IN = ROOT / "data" / "asts.jsonl"
PHRASES_IN = ROOT / "phrases" / "ja_phrases_v1.yaml"
PROVENANCE_IN = ROOT / "phrases" / "ja_phrases_v1_provenance.json"
OUT_DIR = ROOT / "data" / "dataset"

TEACHER_MODEL = "Qwen/Qwen3-4B-AWQ"
TEACHER_REVISION = "74d4bd2bd4bff9cafc9345221320bffb08b406a3"
"""`data/teacher/phrases_runs.jsonl`の全run共通の値（`review_phrases.py --compile`実行時に
確認済み）。ここで固定値として持つのは、この辞書の生成に使った教師モデルが1種類だけであり、
レコードごとに変わる情報ではないため。"""

CAP = 20
"""1つの意味ASTにつき採用する例数の上限。課題文の「最大20例」と同じ。"""

TARGET_TOTAL_ASTS = 65_000
"""train+val+testで目標とする意味ASTの総数（課題文の目安の中央値）。"""

SPLIT_RATIOS = {"train": 0.8, "val": 0.1, "test": 0.1}

SPECIAL_TEST_SIZE = 30
"""組合せ汎化テスト・言い換えテストそれぞれの件数。人が目で見て確認できる規模に留める。"""

SEED = 0

_SPLIT_SEED_GAP = 10_000
"""`_run_parallel`の呼び出し（train/val/test/combination/paraphrase）ごとにseedをずらす間隔。

`_run_parallel`はチャンクiに`seed + i`を渡すため、複数の呼び出しに同じ`seed`を渡すと、
train・val・test・組合せ汎化・言い換えの「チャンク0」同士が同一の乱数列から始まってしまい、
`rng.shuffle`によるコード形式・変数名選びが呼び出しをまたいで相関する。間隔は
実運用のworker数（chunk数の上限）を十分上回る大きさにしてあり、呼び出し間で
seed空間が重ならないようにしている。"""


# ---- ワーカープロセスの内部状態 ----
# Pool(initializer=...)で1ワーカーにつき1回だけ読み込み、チャンクごとの再読込を避ける。

_WORKER: dict[str, Any] = {}


def _init_worker(phrases_path: str, provenance_path: str, probe_path: str) -> None:
    phrases_all = yaml.safe_load(Path(phrases_path).read_text(encoding="utf-8"))
    train_phrases, paraphrase_phrases = split_phrase_pool(phrases_all)
    _WORKER["train_phrases"] = train_phrases
    _WORKER["paraphrase_phrases"] = paraphrase_phrases
    _WORKER["provenance"] = json.loads(Path(provenance_path).read_text(encoding="utf-8"))
    _WORKER["probes"] = load_probe_set(Path(probe_path))


def _build_examples_for_ast(
    ast_id: str,
    ast_record: dict[str, Any],
    phrases: dict[str, dict[str, str]],
    *,
    cap: int,
    code_counts: Counter,
    phrase_counts: Counter,
    rng: random.Random,
) -> list[Example]:
    ast = SemanticAST.from_dict(ast_record)
    codes = code_candidates(ast)
    sentences = nl_candidates(ast, phrases)
    return select_examples(
        ast_id, ast.ops, codes, sentences,
        cap=cap, code_counts=code_counts, phrase_counts=phrase_counts, rng=rng,
    )


def _process_chunk(
    chunk: tuple[list[dict[str, Any]], str, int, int],
) -> list[dict[str, Any]]:
    """1ワーカーが1チャンクぶんのASTレコードを処理する。`Pool.imap`から渡される。

    `code_counts`/`phrase_counts`はこのチャンク（＝このワーカー）の中だけで完結する
    （モジュールdocstringの「並列化について」を参照）。`spec_id`はまだ仮の値（0）のまま
    返す——最終的な通し番号は、全チャンクを集めた後にメインプロセス側で振り直す。
    """
    ast_records, phrase_pool_name, cap, seed = chunk
    phrases = _WORKER[phrase_pool_name]
    probes = _WORKER["probes"]
    provenance = _WORKER["provenance"]

    rng = random.Random(seed)
    code_counts: Counter = Counter()
    phrase_counts: Counter = Counter()
    out: list[dict[str, Any]] = []
    for rec in ast_records:
        examples = _build_examples_for_ast(
            rec["ast_id"], rec, phrases, cap=cap, code_counts=code_counts, phrase_counts=phrase_counts, rng=rng,
        )
        for ex in examples:
            out.append(
                build_record(
                    0, ex, rec, probes,
                    provenance=provenance,
                    teacher_model=TEACHER_MODEL,
                    teacher_revision=TEACHER_REVISION,
                )
            )
    return out


def _round_robin_chunks(items: Sequence[Any], n: int) -> list[list[Any]]:
    """`items`を`n`個のチャンクにラウンドロビンで分ける。難易度順に並んだ列でも、
    各チャンクに難易度の混ざりが生まれるようにするため（`_process_chunk`の均しが
    チャンク内で完結するので、1チャンクが単一難易度に偏ると軸の多様性が狭まる）。
    """
    chunks: list[list[Any]] = [[] for _ in range(n)]
    for i, item in enumerate(items):
        chunks[i % n].append(item)
    return [c for c in chunks if c]


def _run_parallel(
    ast_ids: Sequence[str],
    by_id: dict[str, dict[str, Any]],
    phrase_pool_name: str,
    *,
    cap: int,
    seed: int,
    pool: Pool,
    workers: int,
) -> list[dict[str, Any]]:
    chunks = _round_robin_chunks(
        [by_id[i] for i in ast_ids], workers,
    )
    tasks = [
        (chunk, phrase_pool_name, cap, seed + idx)
        for idx, chunk in enumerate(chunks)
    ]
    results = pool.map(_process_chunk, tasks)
    merged = [record for chunk_out in results for record in chunk_out]
    return _dedup_by_code(merged)


def _dedup_by_code(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`reference_code`が完全に一致するレコードを、最初に出てきたもの以外落とす。

    `code_counts`/`phrase_counts`によるバランスの均しはチャンク（＝ワーカー）ごとに
    独立している（モジュールdocstring参照）。そのため、`behavior_hash`が同じ別AST
    （例: `[even,ge]`と`[ge,even]`）が別々のチャンクに割り振られると、互いを知らないまま
    同じコード文字列を選んでしまうことがある。チャンクを合流させた**この時点**でしか
    横断的に検出できないので、ここで一括して弾く。
    """
    seen: set[str] = set()
    out = []
    for r in records:
        code = r["reference_code"]
        if code in seen:
            continue
        seen.add(code)
        out.append(r)
    return out


def _renumber(records: list[dict[str, Any]], start: int) -> int:
    """`records`の`spec_id`を`start+1`から通し番号で振り直す。返り値は最後の通番。"""
    number = start
    for r in records:
        number += 1
        r["spec_id"] = f"task-{number:06d}"
    return number


def _write(path: Path, records: Iterable[dict[str, Any]]) -> None:
    write_records(path, records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit-asts", type=int, default=None,
        help="動作確認用。train/val/testそれぞれで使うAST数の上限を絞る（既定は絞らない）",
    )
    parser.add_argument("--target-total", type=int, default=TARGET_TOTAL_ASTS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--workers", type=int, default=os.cpu_count() or 1,
        help="並列ワーカー数（既定はCPUの論理コア数）。1で逐次実行になる",
    )
    args = parser.parse_args()

    records = read_records(ASTS_IN)
    by_id = {r["ast_id"]: r for r in records}

    probe_path = default_probe_set_path(ROOT, PROBE_SET_VERSION)
    provenance = json.loads(PROVENANCE_IN.read_text(encoding="utf-8"))
    phrases_all = yaml.safe_load(PHRASES_IN.read_text(encoding="utf-8"))
    _, paraphrase_phrases = split_phrase_pool(phrases_all)

    rng = random.Random(args.seed)

    # 手順1-2: 組合せ汎化テスト用に、予約ペアを含むASTを隔離する。
    combo = carve_out_combinations(records, RESERVED_PAIRS)
    remaining_records = [by_id[i] for i in combo.remaining]
    print(f"組合せ汎化テスト用に隔離: {len(combo.reserved):,}件 / 残り{len(remaining_records):,}件")

    # 手順3: 残りをbehavior_hash単位でtrain/val/testに分割する。
    split = split_corpus(remaining_records, seed=args.seed)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    number = 0

    with Pool(
        processes=args.workers,
        initializer=_init_worker,
        initargs=(str(PHRASES_IN), str(PROVENANCE_IN), str(probe_path)),
    ) as pool:
        for split_idx, (name, ids) in enumerate(
            (("train", split.train), ("val", split.val), ("test", split.test))
        ):
            split_records = [by_id[i] for i in ids]
            target = round(args.target_total * SPLIT_RATIOS[name])
            selected = select_difficulty_thinned(split_records, target_total=target, seed=args.seed)
            if args.limit_asts is not None:
                selected = selected[: args.limit_asts]

            out_records = _run_parallel(
                selected, by_id, "train_phrases",
                cap=CAP, seed=args.seed + split_idx * _SPLIT_SEED_GAP, pool=pool, workers=args.workers,
            )
            number = _renumber(out_records, number)
            _write(OUT_DIR / f"{name}.jsonl", out_records)
            print(f"{name}: AST {len(selected):,}件 → レコード {len(out_records):,}件")

        # 組合せ汎化テスト: 隔離したASTから固定件数だけ抽出し、1AST=1例で作る。
        combo_ids = rng.sample(combo.reserved, min(SPECIAL_TEST_SIZE, len(combo.reserved)))
        combo_records = _run_parallel(
            combo_ids, by_id, "train_phrases",
            cap=1, seed=args.seed + 3 * _SPLIT_SEED_GAP, pool=pool, workers=args.workers,
        )
        number = _renumber(combo_records, number)
        _write(OUT_DIR / "test_combination.jsonl", combo_records)
        print(f"組合せ汎化テスト: AST {len(combo_ids)}件 → レコード {len(combo_records)}件")

        # 言い換えテスト: test split のASTのうち、全opに言い換え保留分の言い回しがあるものから
        # 固定件数を抽出し、その保留分の辞書だけを使ってレコードを作る。
        eligible = [
            i for i in split.test
            if all(op in paraphrase_phrases for op in by_id[i]["semantic_ast"])
        ]
        rng.shuffle(eligible)
        paraphrase_ids = eligible[:SPECIAL_TEST_SIZE]
        paraphrase_records = _run_parallel(
            paraphrase_ids, by_id, "paraphrase_phrases",
            cap=1, seed=args.seed + 4 * _SPLIT_SEED_GAP, pool=pool, workers=args.workers,
        )
        number = _renumber(paraphrase_records, number)
        _write(OUT_DIR / "test_paraphrase.jsonl", paraphrase_records)
        print(f"言い換えテスト: AST {len(paraphrase_ids)}件（対象{len(eligible):,}件中） → レコード {len(paraphrase_records)}件")

    print(f"\n合計レコード数: {number:,}")
    print(f"書き出し先: {OUT_DIR}")


if __name__ == "__main__":
    main()
