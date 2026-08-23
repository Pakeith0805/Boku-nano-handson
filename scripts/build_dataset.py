"""意味ASTコーパスから、最終的な訓練/検証/テストデータセットを組み立てる。

```
python -m scripts.build_dataset
python -m scripts.build_dataset --limit-asts 200   # 動作確認用に規模を絞る
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
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from collections.abc import Iterable, Sequence
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


def _records_for_asts(
    ast_ids: Sequence[str],
    by_id: dict[str, dict[str, Any]],
    phrases: dict[str, dict[str, str]],
    probes: Sequence[Any],
    provenance: dict[str, dict[str, Any]],
    *,
    cap: int,
    rng: random.Random,
    start_number: int,
) -> tuple[list[dict[str, Any]], int]:
    """`ast_ids`ぶんのレコードを作る。均しの`Counter`はこの呼び出しの中だけで完結する
    （train/val/test間や特殊テスト間で採用数を混ぜない）。
    """
    code_counts: Counter = Counter()
    phrase_counts: Counter = Counter()
    out: list[dict[str, Any]] = []
    number = start_number
    for ast_id in ast_ids:
        rec = by_id[ast_id]
        examples = _build_examples_for_ast(
            ast_id, rec, phrases, cap=cap, code_counts=code_counts, phrase_counts=phrase_counts, rng=rng,
        )
        for ex in examples:
            number += 1
            out.append(
                build_record(
                    number, ex, rec, probes,
                    provenance=provenance,
                    teacher_model=TEACHER_MODEL,
                    teacher_revision=TEACHER_REVISION,
                )
            )
    return out, number


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
    args = parser.parse_args()

    records = read_records(ASTS_IN)
    by_id = {r["ast_id"]: r for r in records}

    phrases_all = yaml.safe_load(PHRASES_IN.read_text(encoding="utf-8"))
    train_phrases, paraphrase_phrases = split_phrase_pool(phrases_all)
    provenance = json.loads(PROVENANCE_IN.read_text(encoding="utf-8"))
    probes = load_probe_set(default_probe_set_path(ROOT, PROBE_SET_VERSION))

    rng = random.Random(args.seed)

    # 手順1-2: 組合せ汎化テスト用に、予約ペアを含むASTを隔離する。
    combo = carve_out_combinations(records, RESERVED_PAIRS)
    remaining_records = [by_id[i] for i in combo.remaining]
    print(f"組合せ汎化テスト用に隔離: {len(combo.reserved):,}件 / 残り{len(remaining_records):,}件")

    # 手順3: 残りをbehavior_hash単位でtrain/val/testに分割する。
    split = split_corpus(remaining_records, seed=args.seed)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    number = 0
    for name, ids in (("train", split.train), ("val", split.val), ("test", split.test)):
        split_records = [by_id[i] for i in ids]
        target = round(args.target_total * SPLIT_RATIOS[name])
        selected = select_difficulty_thinned(split_records, target_total=target, seed=args.seed)
        if args.limit_asts is not None:
            selected = selected[: args.limit_asts]

        out_records, number = _records_for_asts(
            selected, by_id, train_phrases, probes, provenance,
            cap=CAP, rng=rng, start_number=number,
        )
        _write(OUT_DIR / f"{name}.jsonl", out_records)
        print(f"{name}: AST {len(selected):,}件 → レコード {len(out_records):,}件")

    # 組合せ汎化テスト: 隔離したASTから固定件数だけ抽出し、1AST=1例で作る。
    combo_ids = rng.sample(combo.reserved, min(SPECIAL_TEST_SIZE, len(combo.reserved)))
    combo_records, number = _records_for_asts(
        combo_ids, by_id, train_phrases, probes, provenance,
        cap=1, rng=rng, start_number=number,
    )
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
    paraphrase_records, number = _records_for_asts(
        paraphrase_ids, by_id, paraphrase_phrases, probes, provenance,
        cap=1, rng=rng, start_number=number,
    )
    _write(OUT_DIR / "test_paraphrase.jsonl", paraphrase_records)
    print(f"言い換えテスト: AST {len(paraphrase_ids)}件（対象{len(eligible):,}件中） → レコード {len(paraphrase_records)}件")

    print(f"\n合計レコード数: {number:,}")
    print(f"書き出し先: {OUT_DIR}")


if __name__ == "__main__":
    main()
