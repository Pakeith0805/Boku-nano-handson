"""意味ASTごとにバインディング（`k`の具体化）を列挙し、`data/bindings.jsonl`を書く。

```
python -m scripts.build_bindings
python -m scripts.build_bindings binding.include_literal=false
```

パラメータ版（`k`は`k`のまま）は常に作る。リテラル版（`k`を具体的な値に固定）を
追加で作るかは`binding.include_literal`で切り替えられる（既定はtrue、両方作る）。
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import hydra
from omegaconf import DictConfig

from src.expand.binding import enumerate_bindings
from src.semantics.corpus import read_records


@hydra.main(config_path="../conf", config_name="binding", version_base=None)
def main(cfg: DictConfig) -> None:
    root = Path(hydra.utils.get_original_cwd())
    asts_in = root / cfg.asts_in
    out = root / cfg.out
    manifest_out = root / cfg.manifest_out
    include_literal = bool(cfg.binding.include_literal)

    if not asts_in.exists():
        raise SystemExit(
            f"意味ASTコーパスがない: {asts_in}\n"
            "  先に `python -m scripts.build_ast_corpus` を実行すること"
        )
    records = read_records(asts_in)
    print(f"意味AST               : {len(records):,} 件")
    print(f"binding.include_literal: {include_literal}")

    rows: list[dict[str, Any]] = []
    for record in records:
        for binding in enumerate_bindings(record["binding_slots"], include_literal):
            rows.append({"ast_id": record["ast_id"], "binding": binding})

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    by_kind = Counter("parameter" if r["binding"] is None else "literal" for r in rows)
    manifest = {
        "ast_count": len(records),
        "include_literal": include_literal,
        "binding_count": len(rows),
        "parameter_count": by_kind["parameter"],
        "literal_count": by_kind["literal"],
    }
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"バインディング総数    : {manifest['binding_count']:,}")
    print(f"  パラメータ版        : {manifest['parameter_count']:,}")
    print(f"  リテラル版          : {manifest['literal_count']:,}")
    print(f"\n書き出し: {out}")
    print(f"          {manifest_out}")


if __name__ == "__main__":
    main()
