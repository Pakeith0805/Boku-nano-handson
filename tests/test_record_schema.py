"""レコード形式と `schema.json` の一致（`corpus.py` L50, L56）。

`schema.json` はレコードの形を**2箇所目に**書いたものである。`build_record()` が実際に出す
辞書が正であり、スキーマはその写しに過ぎないが、写しである以上ズレうる。

`jsonschema` は使わない。依存を増やさずに済むうえ、ここで見たいのは「バリデータが通るか」
ではなく「**2つの記述が同じことを言っているか**」だからである。スキーマが緩ければ
バリデータは通ってしまう（実際 `uniform_literal_domain` は宣言だけあって誰も出していないが、
`required` ではないので検証は通る）。
"""

import json
from pathlib import Path

import pytest

from src.semantics.corpus import (
    AST_ID_DIGITS,
    SCHEMA_VERSION,
    RecordMeta,
    build_record,
    utc_now_rfc3339,
)
from src.semantics.fingerprint import Fingerprint
from src.semantics.registry import CATEGORY_ORDER, LITERAL_MAX, LITERAL_MIN, MAX_OPS
from src.semantics.semantic_ast import SemanticAST

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "semantics" / "schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

# 宣言はあるが `build_record()` が出していないプロパティ。
# `uniform_literal_domain` は、この値の置き場所がAST層から `src/expand/` へ移った名残である
# （`binding.uniform_literal_domain()` が持つ）。`required` に無いので検証は通るが、
# 増えたら気づけるようここに固定しておく。
KNOWN_UNUSED_PROPERTIES = {"uniform_literal_domain"}


def sample_record() -> dict:
    """代表的なレコードを1件組み立てる。

    ファイル（`data/asts.jsonl`）は読まない。あれは生成物で、`.gitignore` で追跡外に
    してあるうえ、古い版が残っていると検査が過去を見ることになるためである。
    """
    ast = SemanticAST(("ge", "double", "asc"))
    fp = Fingerprint(
        semantic_hash="0" * 64,
        behavior_hash="1" * 64,
        always_empty=False,
        is_identity=False,
    )
    return build_record(ast, fp, 1, RecordMeta(created_at=utc_now_rfc3339()))


def test_record_keys_are_exactly_the_required_fields():
    """実レコードのキー集合が `required` と一致する。

    スキーマは `additionalProperties: false` なので、レコードに増えたフィールドは
    宣言されていなければ契約違反になる。逆に `required` にあって出していなければ
    レコードが不完全である。
    """
    assert set(sample_record()) == set(SCHEMA["required"])


def test_every_record_key_is_a_declared_property():
    """`additionalProperties: false` の下で、全キーが宣言済みであること。"""
    assert set(sample_record()) <= set(SCHEMA["properties"])


def test_declared_but_unused_properties_are_the_known_ones():
    """宣言だけあって誰も出していないプロパティが増えていない。

    スキーマがレコードより先に育つと、書いたつもりのフィールドが実は存在しない、
    という食い違いが静かに溜まる。
    """
    unused = set(SCHEMA["properties"]) - set(sample_record())
    assert unused == KNOWN_UNUSED_PROPERTIES


@pytest.mark.parametrize("field", ["semantic_ast", "categories", "op_set"])
def test_schema_op_list_bounds_match_max_ops(field):
    """op列の長さの上限が `MAX_OPS` と一致する。"""
    assert SCHEMA["properties"][field]["maxItems"] == MAX_OPS


def test_schema_difficulty_bounds_match_max_ops():
    """`difficulty` の範囲が 1〜`MAX_OPS`。"""
    difficulty = SCHEMA["properties"]["difficulty"]
    assert (difficulty["minimum"], difficulty["maximum"]) == (1, MAX_OPS)


def test_schema_binding_slot_bounds_match_max_ops():
    """スロット数の上限と `index` の範囲が `MAX_OPS` と整合する。"""
    slots = SCHEMA["properties"]["binding_slots"]
    assert slots["maxItems"] == MAX_OPS
    index = slots["items"]["properties"]["index"]
    assert (index["minimum"], index["maximum"]) == (0, MAX_OPS - 1)


def test_schema_literal_domain_bounds_match_the_registry():
    """スキーマが書いているリテラルの範囲が `LITERAL_MIN`/`LITERAL_MAX` と一致する。"""
    item = SCHEMA["properties"]["binding_slots"]["items"]["properties"]["literal_domain"]["items"]
    assert (item["minimum"], item["maximum"]) == (LITERAL_MIN, LITERAL_MAX)


def test_schema_categories_enum_matches_the_registry():
    """カテゴリの enum が `CATEGORY_ORDER` と一致する。"""
    assert set(SCHEMA["properties"]["categories"]["items"]["enum"]) == set(CATEGORY_ORDER)


def test_schema_ast_id_pattern_matches_the_digit_count():
    """`ast_id` の桁数がスキーマの正規表現と一致する。"""
    assert SCHEMA["properties"]["ast_id"]["pattern"] == f"^ast-[0-9]{{{AST_ID_DIGITS}}}$"


def test_sample_record_satisfies_the_declared_patterns_and_types():
    """代表レコードが、宣言どおりの型・パターンに収まっている。

    バリデータの代わりに、要点だけを手で見る。
    """
    import re

    record = sample_record()
    assert re.fullmatch(SCHEMA["properties"]["ast_id"]["pattern"], record["ast_id"])
    for field in ("semantic_hash", "behavior_hash"):
        assert re.fullmatch(SCHEMA["properties"][field]["pattern"], record[field])
    assert record["source"] == SCHEMA["properties"]["source"]["const"]
    assert record["schema_version"] == SCHEMA_VERSION
    assert 1 <= record["difficulty"] <= MAX_OPS
