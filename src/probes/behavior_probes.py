"""固定入力集合の生成と読み書き。

`behavior_hash` は境界値と乱数を混ぜた固定の入力集合に対する参照インタプリタの
出力列を連結してハッシュ化する。入力集合は全レコードで共通のものを使う
（内容が変わると全レコードのハッシュが変わるため、一度作ったら凍結する）。

入力は `(xs, k)` の対にする。opが `k` を参照するため、`xs` だけでは意味を同定できない。

## 識別力が要件である

この入力集合の目的は**意味の同定**であって、現実的な入力分布の再現ではない。
「どのopとどのopを分けるために、どんな入力が要るか」から逆算して作る。

分けたい組と、そのために要る条件はこうなる。

| 分けたい組 | 要る条件 |
| --- | --- |
| `gt` と `ge`／`lt` と `le` | `xs` に `k` と等しい値を含む |
| `mul_k` と `double` / `triple` | `k not in {2, 3}` |
| `multiple_of` と `even` | `k != 2` |
| `ge` と `positive` | `k != 1` |
| `lt` と `negative` | `k == 1` かつ `xs` に `0` を含む |
| `take_first` と `take_last` | `len(xs) > k` と `len(xs) < k` の両方 |
| `asc` と `desc` と `reverse` | 未整列で相異なる要素を含む |

これらを満たす境界値を手で書き、乱数で埋めたうえで、単一opのAST24個の出力列が
全て相異なるようになるまで増やす。それでも複合ASTでは分かれないことがあるので、
さらに difficulty 1〜3 の全組み合わせで「入力集合の上では一致するが、集合の外では
食い違う」偽の衝突がなくなるまで育てる（difficulty 4 は255,024件あり全数検証は
現実的でないので、そこは未検証のまま残る）。
"""

import json
import random
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from src.interp.interp import run
from src.limits import ELEM_MAX, ELEM_MIN, K_MAX, K_MIN, XS_LEN_MAX, XS_LEN_MIN
from src.semantics.registry import OP_NAMES

ProbeInput = tuple[tuple[int, ...], int]
"""固定入力集合の1件。`(xs, k)`。`xs` はハッシュ可能にするためタプル。"""

PROBE_SET_VERSION: Final[str] = "v1"
"""既定の固定入力集合の版。`scripts/build_probe_set.py` の凍結先ファイル名と
レコードの `probe_set_version` フィールドの両方がこれを参照する。"""

MAX_PROBES: Final[int] = 256
"""入力集合の上限。識別力が足りなければ増やすが、際限なく増やすと
`behavior_hash` の算出コストが267,744件×入力数に効いてくる。"""

DEFAULT_RANDOM_COUNT: Final[int] = 50
"""乱数で足す件数の初期値。"""

# 境界値20件。上の表の条件を満たすように手で選んである。
# 順序は固定（出力列の順序がハッシュに効くため、あとから並べ替えない）。
_BOUNDARY: Final[tuple[tuple[tuple[int, ...], int, str], ...]] = (
    ((), 1, "空リスト・k下限（長さ0は正当な入力）"),
    ((), 10, "空リスト・k上限"),
    ((0,), 1, "長さ1・ゼロのみ・k=1（lt と negative を分ける）"),
    ((0, 0, 0), 5, "全ゼロ・長さ3"),
    ((5,), 5, "長さ1・x==k（gt と ge を分ける）・len(xs) < k"),
    ((1, 2), 2, "長さ2・x==k・len(xs) == k"),
    ((-1, -2, -3), 1, "全負・長さ3・k=1"),
    ((1, 2, 3), 3, "全正・x==k・len(xs) == k"),
    ((7, 7, 7, 7, 7), 7, "重複値・長さ5・x==k・len(xs) < k"),
    ((-100, 100), 10, "要素の境界・長さ2"),
    ((-100, -50, 0, 50, 100), 5, "正負混在＋ゼロ・長さ5"),
    ((5, 1, 9, 3), 2, "未整列（asc・desc・reverse を分ける）"),
    ((2, 4, 6, 8, 10), 2, "全偶数・k=2（multiple_of が even と一致する側）"),
    ((3, 6, 9, 12), 3, "3の倍数・k=3（mul_k が triple と一致する側）"),
    ((1, 2, 3, 4, 5, 6, 7, 8, 9, 10), 7, "k=7（multiple_of と even を分ける）・len(xs) > k"),
    ((0, 1, -1), 1, "k=1・ゼロ含む（lt と negative を分ける）"),
    ((4, 8, 12, 16), 4, "k=4（mul_k と double/triple を分ける、k not in {2,3}）"),
    ((1, 2, 3), 9, "len(xs) < k・k=9"),
    ((-5, -4, -3, -2, -1), 6, "全負・len(xs) < k・k=6"),
    (
        (10, 20, 30, 40, 50, 60, 70, 80, 90, 100,
         -10, -20, -30, -40, -50, -60, -70, -80, -90, -100),
        8,
        "長さ20（上限）・len(xs) > k・k=8",
    ),
)


def boundary_inputs() -> list[ProbeInput]:
    """手書きの境界値（20件）。"""
    return [(xs, k) for xs, k, _ in _BOUNDARY]


def boundary_notes() -> list[str]:
    """境界値それぞれの意図。保存時にファイルへ残す。"""
    return [note for _, _, note in _BOUNDARY]


def random_input(rng: random.Random) -> ProbeInput:
    """入力条件の範囲から `(xs, k)` を1件引く。"""
    length = rng.randint(XS_LEN_MIN, XS_LEN_MAX)
    xs = tuple(rng.randint(ELEM_MIN, ELEM_MAX) for _ in range(length))
    return xs, rng.randint(K_MIN, K_MAX)


def probe_outputs(
    ops: Sequence[str], probes: Sequence[ProbeInput]
) -> tuple[tuple[int, ...], ...]:
    """意味AST `ops` を入力集合の全件で評価した出力列。"""
    return tuple(tuple(run(ops, xs, k)) for xs, k in probes)


def single_op_outputs(
    probes: Sequence[ProbeInput],
) -> dict[str, tuple[tuple[int, ...], ...]]:
    """単一opのAST24個それぞれの出力列。"""
    return {name: probe_outputs((name,), probes) for name in OP_NAMES}


def indistinguishable_pairs(probes: Sequence[ProbeInput]) -> list[tuple[str, str]]:
    """この入力集合では区別できない単一opの組を返す。空なら識別力が足りている。"""
    outputs = single_op_outputs(probes)
    names = sorted(outputs)
    return [
        (left, right)
        for i, left in enumerate(names)
        for right in names[i + 1:]
        if outputs[left] == outputs[right]
    ]


def build_probe_set(
    seed: int,
    random_count: int = DEFAULT_RANDOM_COUNT,
    max_probes: int = MAX_PROBES,
) -> list[ProbeInput]:
    """境界値＋乱数で入力集合を作り、単一op24個が区別できるまで乱数を足す。

    Raises:
        RuntimeError: 上限まで増やしても単一opを区別できないとき。
    """
    rng = random.Random(seed)
    probes = boundary_inputs()
    seen = set(probes)

    def add_random(count: int) -> None:
        added = 0
        attempts = 0
        while added < count and len(probes) < max_probes:
            attempts += 1
            if attempts > count * 1000:
                raise RuntimeError("乱数入力が重複ばかりで増やせない")
            candidate = random_input(rng)
            if candidate in seen:
                continue
            seen.add(candidate)
            probes.append(candidate)
            added += 1

    add_random(random_count)

    while indistinguishable_pairs(probes):
        if len(probes) >= max_probes:
            pairs = indistinguishable_pairs(probes)
            raise RuntimeError(f"上限 {max_probes} 件でも単一opを区別できない: {pairs}")
        add_random(min(10, max_probes - len(probes)))

    return probes


EXTERNAL_SEED_OFFSET: Final[int] = 1
"""検証用の外部入力に使う種のずらし幅。固定入力集合そのものとは別の種を使う。
同じ種で引くと、検証に使う入力が入力集合と重なって「自分で自分を検証する」ことになる。"""


def external_inputs(
    count: int, seed: int, exclude: Sequence[ProbeInput]
) -> list[ProbeInput]:
    """入力集合に**含まれない**ランダムな `(xs, k)` を作る。

    偽の衝突（固定入力集合では同じ指紋なのに、実際は別の関数）を探すために使う。
    入力集合の外から見ないと、識別力の不足そのものが見えない。
    """
    rng = random.Random(seed + EXTERNAL_SEED_OFFSET)
    excluded = set(exclude)
    found: list[ProbeInput] = []
    while len(found) < count:
        candidate = random_input(rng)
        if candidate not in excluded:
            found.append(candidate)
    return found


def find_false_collisions(
    op_sequences: Sequence[Sequence[str]],
    probes: Sequence[ProbeInput],
    external: Sequence[ProbeInput],
) -> list[tuple[tuple[str, ...], tuple[str, ...], ProbeInput]]:
    """偽の衝突を探す。

    入力集合の上では出力列が一致するのに、`external` のどれかで食い違うASTの組を返す。
    3つ目の要素が**それを分ける入力**であり、そのまま入力集合に足せば次からは分かれる。
    """
    groups: dict[tuple[tuple[int, ...], ...], list[tuple[str, ...]]] = {}
    for ops in op_sequences:
        groups.setdefault(probe_outputs(ops, probes), []).append(tuple(ops))

    found: list[tuple[tuple[str, ...], tuple[str, ...], ProbeInput]] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        base = members[0]
        for other in members[1:]:
            for xs, k in external:
                if run(base, xs, k) != run(other, xs, k):
                    found.append((base, other, (xs, k)))
                    break
    return found


def grow_until_no_false_collisions(
    probes: Sequence[ProbeInput],
    op_sequences: Sequence[Sequence[str]],
    external: Sequence[ProbeInput],
    max_probes: int = MAX_PROBES,
    max_rounds: int = 50,
) -> list[ProbeInput]:
    """偽の衝突がなくなるまで、**反例そのもの**を入力集合に足す。

    見つかった食い違いの入力を足せば、次の回ではその組が分かれる。

    Returns:
        育てた入力集合。元の並びは保ち、追加分を末尾に足す。

    Raises:
        RuntimeError: 上限または巡回数の上限に達しても収束しないとき。
    """
    grown = list(probes)
    for _ in range(max_rounds):
        found = find_false_collisions(op_sequences, grown, external)
        if not found:
            return grown
        for _, _, probe in found:
            if probe not in grown:
                if len(grown) >= max_probes:
                    raise RuntimeError(
                        f"上限 {max_probes} 件でも偽の衝突が消えない（残り {len(found)} 件）"
                    )
                grown.append(probe)
    raise RuntimeError(f"{max_rounds} 巡しても偽の衝突が消えない")


def save_probe_set(
    path: Path,
    probes: Sequence[ProbeInput],
    version: str,
    random_count: int = DEFAULT_RANDOM_COUNT,
) -> None:
    """入力集合をJSONLで保存する（1行1件）。

    境界値には意図の説明を添える。`kind` は3種類で、並びは
    boundary → random → counterexample の順になる。
    """
    notes = boundary_notes()
    lines = []
    for index, (xs, k) in enumerate(probes):
        if index < len(notes):
            kind = "boundary"
        elif index < len(notes) + random_count:
            kind = "random"
        else:
            kind = "counterexample"
        record: dict[str, object] = {
            "index": index,
            "xs": list(xs),
            "k": k,
            "kind": kind,
            "probe_set_version": version,
        }
        if index < len(notes):
            record["note"] = notes[index]
        lines.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_probe_set(path: Path) -> list[ProbeInput]:
    """保存した入力集合を**順序を保って**読み戻す。

    順序が変わると出力列も変わり、`behavior_hash` が全件変わってしまう。
    帰り値はprobe_set(参照コードと生成コードが一致しているか確かめるためのリストと数値の集合)
    """
    probes: list[ProbeInput] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        probes.append((tuple(record["xs"]), record["k"]))
    return probes


def describe(probes: Sequence[ProbeInput]) -> dict[str, object]:
    """入力集合の要約。ビルド時の報告と `manifest.json` に使う。"""
    items = list(probes)
    lengths = sorted({len(xs) for xs, _ in items})
    ks = sorted({k for _, k in items})
    return {
        "count": len(items),
        "k_values": ks,
        "k_covers_full_range": ks == list(range(K_MIN, K_MAX + 1)),
        "xs_lengths": lengths,
        "has_empty_xs": 0 in lengths,
        "has_max_length_xs": XS_LEN_MAX in lengths,
        "has_x_equal_to_k": any(k in xs for xs, k in items),
        "has_len_greater_than_k": any(len(xs) > k for xs, k in items),
        "has_len_less_than_k": any(len(xs) < k for xs, k in items),
    }


def default_probe_set_path(root: Path, version: str) -> Path:
    """凍結ファイルの既定の置き場所。"""
    return root / "probes" / f"behavior_probe_set_{version}.jsonl"
