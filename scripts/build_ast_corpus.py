"""意味ASTのコーパス（`asts.jsonl`）とその要約（`manifest.json`）を生成する。

```
python -m scripts.build_ast_corpus
```

参照台帳として267,744件（difficulty 1〜4の全数）を作る。学習用のサンプリング済み
データではないので、層化配分やseedによる抽出は行わない。事前に
`python -m scripts.build_probe_set` で固定入力集合を凍結しておくこと。
"""

from pathlib import Path

from src.probes.behavior_probes import PROBE_SET_VERSION, default_probe_set_path, load_probe_set
from src.semantics.corpus import (
    RecordMeta,
    build_manifest,
    build_records,
    utc_now_rfc3339,
    write_manifest,
    write_records,
)
from src.semantics.semantic_ast import enumerate_all_asts

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "asts.jsonl"
MANIFEST_OUT = ROOT / "data" / "manifest.json"


def main() -> None:
    probe_path = default_probe_set_path(ROOT, PROBE_SET_VERSION)
    if not probe_path.exists():
        raise SystemExit(
            f"固定入力集合がない: {probe_path}\n"
            "  先に `python -m scripts.build_probe_set` を実行すること"
        )
    probes = load_probe_set(probe_path)

    asts = enumerate_all_asts()
    print(f"意味AST: {len(asts):,} 件")

    meta = RecordMeta(created_at=utc_now_rfc3339())
    records, max_digits = build_records(asts, probes, meta)

    manifest = build_manifest(
        records, probe_count=len(probes), max_output_digits=max_digits, meta=meta
    )

    write_records(OUT, records)
    write_manifest(MANIFEST_OUT, manifest)

    print(f"レコード数         : {manifest['record_count']:,}")
    print(f"difficulty別       : {manifest['by_difficulty']}")
    print(f"behavior_hash異なり: {manifest['behavior_hash']['distinct']:,}")
    print(f"衝突グループ数     : {manifest['behavior_hash']['collision_groups']:,}")
    print(f"衝突に関与するAST  : {manifest['behavior_hash']['asts_in_collisions']:,}")
    print(f"always_empty       : {manifest['always_empty_count']:,} 件")
    print(f"is_identity        : {manifest['is_identity_count']:,} 件")
    print(f"出力の最大桁数     : {manifest['max_output_abs_digits']} 桁")
    print(f"\n書き出し: {OUT}")
    print(f"          {MANIFEST_OUT}")


if __name__ == "__main__":
    main()
