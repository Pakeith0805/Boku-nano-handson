"""入力条件（改訂版 L100-107）。

課題文が定める `solve(xs, k)` の入力の範囲。参照インタプリタと固定入力集合の両方が使う。
op のメタデータ（`boku.semantics.registry`）とは別物なので分けてある。こちらは
「どんな入力が来るか」であり、あちらは「どんな操作があるか」である。
"""

from typing import Final

XS_LEN_MIN: Final[int] = 0
XS_LEN_MAX: Final[int] = 20
"""`xs` の長さの範囲（改訂版 L102「長さ0〜20の整数リスト」）。

下限が0なので、**空リストは正当な入力**である。境界値テストの必須項目（L514）。
"""

ELEM_MIN: Final[int] = -100
ELEM_MAX: Final[int] = 100
"""`xs` の各要素の範囲（改訂版 L103「−100以上100以下の整数」）。"""

K_MIN: Final[int] = 1
K_MAX: Final[int] = 10
"""`k` の範囲（改訂版 L104「1以上10以下の整数」）。

下限が1であることに二つの実装が依存している。`multiple_of` のゼロ除算が起きないこと、
`take_last` の `xs[-k:]` が `k == 0` のとき全リストを返す罠を踏まないこと
（実装計画 §6）。どちらも `boku/interp/ops.py` で assert している。

リテラルの値域（`boku.semantics.registry.LITERAL_MIN` / `LITERAL_MAX`）はこれと同一である。
同一にする根拠は L269 にあり、`tests/test_limits.py` で一致を機械的に固定している。
"""

# 出力側には範囲の制約がない。改訂版 L105 は「二乗などの変換により、出力要素は
# −100〜100の範囲を超えてよい」と明記している。したがって参照インタプリタは出力を
# クリップしない。実際に到達する桁数は manifest.json に記録する（実装計画 §6）。
