"""ASTコーパスの読み書き。

`asts.jsonl`（1行1レコード）と `manifest.json`（1回の生成の要約）を扱う。

## レコードは3つの層の合成

| 層 | 出どころ | 何を足すか |
| --- | --- | --- |
| op列から決まる値 | `SemanticAST.to_dict()` | `semantic_ast` `difficulty` `binding_slots` など |
| 評価しないと決まらない値 | `Fingerprint` | `semantic_hash` `behavior_hash` `always_empty` `is_identity` |
| コーパスに載せて決まる値 | この層 | `ast_id` と由来3項目、各 version |

## 由来3項目

- `source` — AST層では常に `"rule"`。教師モデル由来・開発支援AI由来の意味ASTは
  存在してはいけない。
- `created_at` — 各ハッシュと `ast_id` の入力に含めない。含めると同一入力での
  再実行が別物になり、再現性の確認ができなくなる。
- `generator_version` — 手で上げる。参照インタプリタを直したときも上げること
  （`behavior_hash` が変わるため）。

## `ast_id` は実行をまたぐキーではない

列挙順で振る連番。実行をまたいで同一性を見るときは `semantic_hash` を使う。
"""

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from src import BOKU_GENERATOR_VERSION
from src.interp.interp import run
from src.probes.behavior_probes import PROBE_SET_VERSION, ProbeInput
from src.semantics.fingerprint import (
    Fingerprint,
    behavior_hash_of,
    behavior_outputs,
    is_always_empty,
    is_identity_over,
    semantic_hash,
)
from src.semantics.registry import MAX_OPS, REGISTRY_VERSION
from src.semantics.semantic_ast import SemanticAST

SCHEMA_VERSION: Final[int] = 1
"""レコード形式の版。`schema.json` と対応する。フィールドの追加・削除・意味の変更で上げる。"""

SOURCE_RULE: Final[str] = "rule"
"""AST層の `source` の唯一の値。"""

AST_ID_DIGITS: Final[int] = 6
"""`ast_id` の桁数。`schema.json` の `^ast-[0-9]{6}$` と対応する。267,744件は6桁で表せる。"""


def utc_now_rfc3339() -> str:
    """現在時刻をRFC 3339（UTC、秒精度）で返す。この値はハッシュにも `ast_id` にも入らない。"""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_ast_id(number: int) -> str:
    """連番から `ast_id` を作る（1始まり）。"""
    if number < 1:
        raise ValueError(f"ast_id の連番は1以上: {number}")
    return f"ast-{number:0{AST_ID_DIGITS}d}"


@dataclass(frozen=True, slots=True)
class RecordMeta:
    """全レコードに共通で載る由来と版。"""

    created_at: str
    generator_version: str = BOKU_GENERATOR_VERSION
    registry_version: str = REGISTRY_VERSION
    probe_set_version: str = PROBE_SET_VERSION
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """レコードに載せる形。`source` は常に `"rule"`。"""
        return {
            "source": SOURCE_RULE,
            "created_at": self.created_at,
            "generator_version": self.generator_version,
            "schema_version": self.schema_version,
            "registry_version": self.registry_version,
            "probe_set_version": self.probe_set_version,
        }


def build_record(
    ast: SemanticAST, fp: Fingerprint, number: int, meta: RecordMeta
) -> dict[str, Any]:
    """1件のレコードを組み立てる。"""
    return {
        "ast_id": format_ast_id(number),
        **ast.to_dict(),
        **fp.to_dict(),
        **meta.to_dict(),
    }


def build_records(
    asts: Sequence[SemanticAST], probes: Sequence[ProbeInput], meta: RecordMeta
) -> tuple[list[dict[str, Any]], int]:
    """全レコードと、出力値の絶対値の最大桁数を返す。

    指紋の算出はコーパス構築で最も重い処理（AST数 × 入力数の評価）なので、
    **1つのASTにつき評価は一度だけ**にして、そこから指紋と桁数の両方を得る。
    `fingerprint()` を経由せず個々の関数を直接呼ぶのはこのため
    （経由すると出力列がその中に閉じてしまい、桁数が取れない）。

    Returns:
        `(レコード列, 出力値の絶対値の最大桁数)`。桁数はトークナイザ設計への
        申し送りとして `manifest.json` に載せる。
    """
    records: list[dict[str, Any]] = []
    max_digits = 0
    for number, ast in enumerate(asts, start=1):
        outputs = behavior_outputs(ast.ops, probes, run)
        fp = Fingerprint(
            semantic_hash=semantic_hash(ast.ops),
            behavior_hash=behavior_hash_of(outputs),
            always_empty=is_always_empty(outputs),
            is_identity=is_identity_over(probes, outputs),
        )
        for output in outputs:
            for value in output:
                max_digits = max(max_digits, len(str(abs(value))))
        records.append(build_record(ast, fp, number, meta))
    return records, max_digits


def write_records(path: Path, records: Iterable[dict[str, Any]]) -> None:
    """JSONLで書き出す（1行1レコード）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            )


def read_records(path: Path) -> list[dict[str, Any]]:
    """JSONLを読み戻す。順序を保つ。"""
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def build_manifest(
    records: Sequence[dict[str, Any]],
    *,
    probe_count: int,
    max_output_digits: int,
    meta: RecordMeta,
) -> dict[str, Any]:
    """1回の生成の要約。

    参照台帳（全数）として作るので、層化サンプリングの「計画 vs 実績」のような
    対比は不要。レコードから導ける値はレコードから数える（二重に持つと食い違う
    余地ができるため、`max_output_digits` だけを外から受け取る。出力そのものは
    レコードに載らないため）。
    """
    by_difficulty = Counter(record["difficulty"] for record in records)
    op_frequency = Counter(op for record in records for op in record["semantic_ast"])
    category_frequency = Counter(
        category for record in records for category in record["categories"]
    )
    slot_distribution = Counter(len(record["binding_slots"]) for record in records)

    behavior_groups = Counter(record["behavior_hash"] for record in records)
    collision_groups = {
        digest: size for digest, size in behavior_groups.items() if size > 1
    }

    canonical = sum(1 for record in records if record["canonical_order"])

    return {
        "created_at": meta.created_at,
        "generator_version": meta.generator_version,
        "registry_version": meta.registry_version,
        "probe_set_version": meta.probe_set_version,
        "schema_version": meta.schema_version,
        "probe_count": probe_count,
        "record_count": len(records),
        "by_difficulty": {
            str(d): by_difficulty.get(d, 0) for d in range(1, MAX_OPS + 1)
        },
        "op_frequency": dict(sorted(op_frequency.items())),
        "category_frequency": dict(sorted(category_frequency.items())),
        "canonical_order_ratio": round(canonical / len(records), 6) if records else 0.0,
        "k_slot_distribution": {
            str(slots): slot_distribution.get(slots, 0) for slots in range(MAX_OPS + 1)
        },
        "behavior_hash": {
            "distinct": len(behavior_groups),
            "collision_groups": len(collision_groups),
            "largest_group": max(behavior_groups.values()) if behavior_groups else 0,
            "asts_in_collisions": sum(collision_groups.values()),
        },
        "always_empty_count": sum(1 for r in records if r["always_empty"]),
        "is_identity_count": sum(1 for r in records if r["is_identity"]),
        "max_output_abs_digits": max_output_digits,
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """`manifest.json` を書き出す（人が読むので整形する）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def read_manifest(path: Path) -> dict[str, Any]:
    """`manifest.json` を読む。"""
    return json.loads(path.read_text(encoding="utf-8"))
