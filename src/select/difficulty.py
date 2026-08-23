"""難易度(`difficulty`)による意味ASTの間引き。

## 方針: 均等化ではなく「安いものは全数、高いものだけ間引く」

`difficulty` 1〜4を件数で均等にすると、`difficulty=1`が24種類（学習データのごく一部の
splitではさらに少ない）しか無いことが律速し、コーパス全体が目標トークン数（数千万〜億単位）
に対して2桁以上小さくなってしまう（`difficulty`1〜4全てを24種類相当に切り詰めると、
上限を`for`ループの内包表記や日本語言い回しの組み合わせで最大限まで使い切っても
数千レコード＝数十万トークンにしかならない）。

一方で`difficulty`1〜3は合計しても12,720種類しかなく、これを全数使ってもトークン予算への
影響はわずかである。したがって、**`difficulty`1〜3は全数残し、`difficulty=4`（255,024種類、
全体の95%以上を占める）だけを目標総数に合わせて間引く**方針を取る。これは「難易度を均等に
する」ことを目指すものではない——`difficulty=4`は間引いた後も他の水準より多数派のままである。
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Any


def select_difficulty_thinned(
    records: Sequence[Mapping[str, Any]], *, target_total: int, seed: int = 0
) -> list[str]:
    """difficulty 1〜3は全数、4だけ間引いて目標総AST数に近づける。

    `records`は1つのsplit（例えばtrainだけ）を渡す想定。`target_total`はそのsplit内で
    達成したいAST数。`difficulty`1〜3の合計が`target_total`を超える場合は、間引く対象が
    無い（4の抽出数は0になる）。

    Returns:
        採用する`ast_id`の列（1〜3は全部、4は無作為抽出した分）。
    """
    by_difficulty: dict[int, list[str]] = {}
    for r in records:
        by_difficulty.setdefault(r["difficulty"], []).append(r["ast_id"])

    small = [ast_id for d in (1, 2, 3) for ast_id in by_difficulty.get(d, [])]

    remaining = max(target_total - len(small), 0)
    pool4 = by_difficulty.get(4, [])
    rng = random.Random(seed)
    picked4 = rng.sample(pool4, min(remaining, len(pool4)))

    return small + picked4
