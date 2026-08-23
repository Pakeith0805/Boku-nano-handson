"""1件の意味ASTから、コード生成器`src/codegen/codegen.py`の出力を1本だけ見る。

```
python -m scripts.try_codegen --ast-id ast-000577
python -m scripts.try_codegen --ast-id ast-000577 --seed 7
python -m scripts.try_codegen --ops asc,take_first
```

バッチ処理（`data/asts.jsonl`全267,744件への一括生成）はまだ行わない。生成器の
設計を固めるための、1件ずつ確認する足場。
"""

import argparse
from pathlib import Path

from src.codegen.codegen import Style, generate, random_style
from src.semantics.corpus import read_records
from src.semantics.semantic_ast import SemanticAST

ROOT = Path(__file__).resolve().parents[1]
ASTS_PATH = ROOT / "data" / "asts.jsonl"


def _find_by_ast_id(ast_id: str) -> SemanticAST:
    for record in read_records(ASTS_PATH):
        if record["ast_id"] == ast_id:
            return SemanticAST.from_dict(record)
    raise SystemExit(f"{ASTS_PATH} に {ast_id} が無い")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--ast-id", help="data/asts.jsonl から引く（例: ast-000577）")
    source.add_argument("--ops", help="op名をカンマ区切りで直接指定する（例: asc,take_first）")
    parser.add_argument("--seed", type=int, default=0, help="スタイルの乱数シード")
    args = parser.parse_args()

    ast = _find_by_ast_id(args.ast_id) if args.ast_id else SemanticAST(tuple(args.ops.split(",")))

    style = random_style(args.seed)
    print(f"# semantic_ast = {list(ast.ops)}")
    print(f"# style = {style}")
    print()
    print(generate(ast, style))


if __name__ == "__main__":
    main()
