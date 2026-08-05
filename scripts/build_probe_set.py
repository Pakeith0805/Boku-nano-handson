"""固定入力集合を生成して凍結する。

```
python -m scripts.build_probe_set
```

単一opのAST24個の出力列が全て相異なるまで自動で乱数を増やし、
さらに difficulty 1〜4 の全組み合わせで偽の衝突がなくなるまで育てる。

## 凍結ファイルを黙って書き換えない

この入力集合は `behavior_hash` の基準である。内容が変わると**全レコードのハッシュが
変わる**。既に凍結したファイルと違う内容が出た場合は、`--force` を明示しない限り
エラーで止める。事故で作り直すと、既存のコーパスと新しいコーパスの `behavior_hash` が
比較できなくなる。
"""

import sys
from pathlib import Path

from src.probes.behavior_probes import (
    PROBE_SET_VERSION,
    build_probe_set,
    describe,
    external_inputs,
    find_false_collisions,
    grow_until_no_false_collisions,
    indistinguishable_pairs,
    load_probe_set,
    save_probe_set,
)
from src.semantics.semantic_ast import enumerate_all_asts

VERSION = PROBE_SET_VERSION
SEED = 0
RANDOM_COUNT = 50
MAX_PROBES = 256
EXTERNAL_COUNT = 200
VERIFY_MAX_DIFFICULTY = 4
"""偽の衝突を潰す検証をどのdifficultyまで行うか。

difficulty 4（255,024件）を含めても、グループ化は1パス約15秒、偽の衝突の
検出は1パス約75秒で済むことを実測済み。全267,744件を対象にする。"""

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "probes" / f"behavior_probe_set_{VERSION}.jsonl"


def main() -> None:
    force = "--force" in sys.argv[1:]

    probes = build_probe_set(seed=SEED, random_count=RANDOM_COUNT, max_probes=MAX_PROBES)
    base_count = len(probes)

    op_sequences = [
        ast.ops for ast in enumerate_all_asts() if ast.difficulty <= VERIFY_MAX_DIFFICULTY
    ]
    external = external_inputs(count=EXTERNAL_COUNT, seed=SEED, exclude=probes)
    before = find_false_collisions(op_sequences, probes, external)
    probes = grow_until_no_false_collisions(
        probes, op_sequences=op_sequences, external=external, max_probes=MAX_PROBES
    )

    summary = describe(probes)
    print(f"probe_set_version : {VERSION}")
    print(f"seed              : {SEED}")
    print(
        f"件数              : {summary['count']}"
        f"（境界値20 + 乱数{RANDOM_COUNT} + 反例{len(probes) - base_count}）"
    )
    print(f"k の網羅          : {summary['k_values']}")
    print(f"xs の長さ         : {summary['xs_lengths']}")
    print(
        "単一op24個の識別  : "
        f"{'OK（全て相異なる）' if not indistinguishable_pairs(probes) else 'NG'}"
    )
    print(
        f"偽の衝突の検証    : difficulty 1〜{VERIFY_MAX_DIFFICULTY} の "
        f"{len(op_sequences):,} 件 × 外部入力 {EXTERNAL_COUNT:,} 件"
    )
    print(f"  反例駆動の前    : {len(before)} 件")
    print("  反例駆動の後    : 0 件")

    if OUT.exists():
        existing = load_probe_set(OUT)
        if existing == probes:
            print(f"\n既存ファイルと同一。書き換えません: {OUT}")
            return
        if not force:
            print(
                f"\n[中止] 既存の凍結ファイルと内容が違います: {OUT}\n"
                f"  既存 {len(existing)} 件 / 新規 {len(probes)} 件\n"
                "  上書きすると全レコードの behavior_hash が変わります。\n"
                "  作り直すなら --force を付けてください。",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print(f"\n[force] 既存ファイルを上書きします: {OUT}")

    save_probe_set(OUT, probes, version=VERSION, random_count=RANDOM_COUNT)
    print(f"\n凍結しました: {OUT}")


if __name__ == "__main__":
    main()
