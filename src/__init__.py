"""Boku-nano データ生成パイプライン。"""

from typing import Final

BOKU_GENERATOR_VERSION: Final[str] = "v0.1"
"""生成器の版。全レコードの `generator_version` に記録する。

手で上げる。上げるべき変更は「同じ入力から出るレコードの内容が変わる」ものすべてであり、
特に**参照インタプリタの修正を含む**。`behavior_hash` の値は参照インタプリタの実装に依存するが、
`registry_version` も `probe_set_version` もインタプリタの変更では動かないため、
この定数だけが唯一の記録になる。インタプリタを直したらここも上げること。
"""
