"""データ保存・読み込みで共通に使う、検証済みレコードの採用条件。"""

from collections.abc import Mapping


def is_verified(record: Mapping[str, object]) -> bool:
    """3フラグがすべて真の場合だけ採用する。欠落・不正な型も不合格。"""
    flags = record.get("verification")
    return isinstance(flags, Mapping) and all(
        flags.get(key) is True for key in ("syntax_ok", "ast_safe", "tests_passed")
    )
