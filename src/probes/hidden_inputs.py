"""最終評価専用の、問題ごとに再現可能なランダム入力。"""

import hashlib
import json
import random
from collections.abc import Sequence

from src.probes.behavior_probes import ProbeInput, random_input

DEFAULT_HIDDEN_COUNT = 20
DEFAULT_HIDDEN_SEED = 1_000_003
HIDDEN_PROTOCOL = "per-problem-random-v1"


def hidden_inputs(
    problem_key: str,
    *,
    exclude: Sequence[ProbeInput],
    count: int = DEFAULT_HIDDEN_COUNT,
    seed: int = DEFAULT_HIDDEN_SEED,
) -> list[ProbeInput]:
    """既存probeと重複しない入力を20件以上作る。生成コードには依存しない。

    seedと問題キーから乱数列を決めるため、評価順や抽出件数に左右されない。
    同じ問題内の重複も除き、既存の固定入力集合には書き戻さない。
    """
    if count < 20:
        raise ValueError("hidden testは問題ごとに20入力以上必要です")
    material = json.dumps([HIDDEN_PROTOCOL, seed, problem_key], ensure_ascii=False)
    rng = random.Random(int.from_bytes(hashlib.sha256(material.encode()).digest(), "big"))
    seen = {(tuple(xs), k) for xs, k in exclude}
    result: list[ProbeInput] = []
    for _ in range(count * 1000):
        candidate = random_input(rng)
        if candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
        if len(result) == count:
            return result
    raise RuntimeError("重複しないhidden入力を必要数生成できませんでした")
