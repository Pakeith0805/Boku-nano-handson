"""op レジストリ：24種類の操作のメタデータ。

改訂版 L113-157 の表が op名の正式な定義であり、このモジュールはその機械可読な写しである。

**意味（各opが何を計算するか）はここに置かない。**
lambda・コード文字列・`eval`・`apply` メソッドを一切持たない。意味は `boku/interp/ops.py`
に手書きする（実装計画 §2.8）。

改訂版 L281-286 は「各意味ASTから、独立した二つのプログラムを作る」（参照インタプリタと
コード生成器）ことを求め、両者の出力をランダムテストで比較してコード生成器のバグを検出する
仕掛けを置いている。レジストリに意味を持たせると両者がそれを共有してしまい、そこにバグが
あった場合に同じように間違えるため、この差分テストが素通りする。それを防ぐための分離である。

レジストリと参照インタプリタの同期は `tests/test_registry_conformance.py` のキー集合一致
テストだけで担保する。このテストが検査するのは「存在と形式」だけであり、「意味が合っているか」
は検査しない。意味の検査は `tests/test_interp_ops.py` と差分ランダムテストの担当である
（実装計画 §2.8）。役割を混ぜないこと。
"""

from dataclasses import dataclass
from typing import Final, Literal

REGISTRY_VERSION: Final[str] = "ops24-v1"
"""レジストリの版。全レコードに記録する（実装計画 §2.3, §4）。

op名・カテゴリ・リテラル値域のいずれかを変えたら上げる。将来 Boku-1B で対象領域を
広げる際は、`OP_REGISTRY` を差し替えてこの版を上げる。
"""

MAX_OPS: Final[int] = 4
"""1つの意味ASTに組み合わせる操作の個数の上限（改訂版 L111「1〜4個」）。

1〜4 で確定しており、実装中に揺れない（実装計画 §8 確認事項①、2026-07-30確定）。
単一定数として置くのは不確定性への保険ではなく、将来 Boku-1B で対象領域を広げる際の
変更点を1箇所に閉じておくためである（実装計画 §2.1）。

この値を下げると意味AST空間が縮み、改訂版 L397 の目標件数 30,000〜100,000 に届かなくなる
（`MAX_OPS = 3` なら空間は 12,720 種類しかない）。変更する場合は L397 の再検討が必要。
"""

LITERAL_MIN: Final[int] = 1
LITERAL_MAX: Final[int] = 10
"""リテラルに使える値の範囲（改訂版 L269）。`k` の値域（L104）と同一。

同一にするのは検証機構を共有するためである。リテラル版のコードは必ず「参照インタプリタを
`k` ＝そのリテラル値で評価した結果」と一致するので、パラメータ版とまったく同じ検証がそのまま
使える。値域外（0や負数）を許すと対応する `k` が存在せず、参照インタプリタで正誤を判定できない。
"""

Category = Literal["filter", "map", "order", "slice"]
"""opのカテゴリ。改訂版の見出し 抽出／変換／並べ替え／切り出し に対応する。"""

CATEGORY_ORDER: Final[tuple[Category, ...]] = ("filter", "map", "order", "slice")
"""`canonical_order` の判定に使うカテゴリの並び（抽出→変換→並べ替え→切り出し）。

改訂版 L115-157 の表の並びである。実装計画 §2.2 のとおり `canonical_order` はこの順に
従っているかどうかを**記録するだけ**で、列挙は制限しない（L297 が順序自由と定めているため）。
"""


@dataclass(frozen=True, slots=True)
class OpSpec:
    """1つのopのメタデータ（実装計画 §2.8）。

    意味を持たない。呼び出せるものを一切フィールドに置かないことがこの型の要件である。
    """

    name: str
    """op名。改訂版 L113-157 の表の正式な識別子。"""

    category: Category
    """カテゴリ。"""

    uses_k: bool
    """引数 `k` を参照するか。

    `literal_domain` の有無と一致しなければならないが、導出せず手で書く。
    二つを独立に書くことで `tests/test_registry_conformance.py` の整合テストが
    意味を持つ（導出すると常に真になり、検査にならない）。
    """

    literal_domain: tuple[int, ...]
    """リテラルに具体化できる値（改訂版 L269-277、実装計画 §2.4）。

    `uses_k=False` なら空タプル。展開層が使う。意味AST自身は定数を持たない（L256）。
    """

    ja_key: str
    """日本語表現辞書の引き当てキー（実装計画 §2.8, §5）。

    現状すべて `name` と同じ値だが、別フィールドとして持つ。辞書は人間が承認した資産
    （L292-293）であり、op名の変更で引き当てが壊れないよう名前空間を分けておく。
    """

    shadows: tuple[str, ...] = ()
    """特定のリテラルに具体化したとき同一になる他のop（実装計画 §2.6）。

    将来コード→ASTパーサを書くときの正準形の宣言に使う。宣言のみで、今回パーサは作らない。
    `literal_domain` の除外によって実際の衝突は消えているので、これは履歴の記録にあたる。

    操作列レベルの縮退（`[square, abs]` が `[square]` と一致するなど）はここに入れない。
    単一opの話ではなく、`behavior_hash` が検出する領域である（実装計画 §2.5）。
    """

    notes: str = ""
    """人間向けの補足。改訂版の該当行と、除外・曖昧性解消の根拠を書く。"""


def _domain(lowest: int) -> tuple[int, ...]:
    """`lowest` 以上 `LITERAL_MAX` 以下のリテラル値域を作る。

    改訂版 L273-277 の除外はすべて値域の**下限側**にある（`ge` の1、`multiple_of` の1と2、
    `mul_k` の1と2と3）。途中に穴があく除外は存在しないため、下限だけで表せる。
    下限側でない除外を持つopが将来加わったら、この補助関数では表せないので明示的な
    タプルを書くこと。

    期待値は `tests/test_literal_domains.py` にこの関数を経由せず直接書いてあり、
    そちらが独立した照合になる。
    """
    return tuple(range(lowest, LITERAL_MAX + 1))


OP_REGISTRY: Final[dict[str, OpSpec]] = {
    # ---- 抽出（改訂版 L115-128、10種類）----
    "even": OpSpec(
        name="even", category="filter", uses_k=False, literal_domain=(), ja_key="even",
        notes="偶数だけを残す（L119）",
    ),
    "odd": OpSpec(
        name="odd", category="filter", uses_k=False, literal_domain=(), ja_key="odd",
        notes="奇数だけを残す（L120）",
    ),
    "gt": OpSpec(
        name="gt", category="filter", uses_k=True, literal_domain=_domain(1), ja_key="gt",
        notes="`k`より大きい値を残す（L121）。除外なし",
    ),
    "ge": OpSpec(
        name="ge", category="filter", uses_k=True, literal_domain=_domain(2), ja_key="ge",
        shadows=("positive",),
        notes="`k`以上の値を残す（L122）。@1 は要素が整数なので `positive` と同一のため除外（L275）",
    ),
    "lt": OpSpec(
        name="lt", category="filter", uses_k=True, literal_domain=_domain(1), ja_key="lt",
        notes=(
            "`k`より小さい値を残す（L123）。@1（x < 1）は `negative`（x < 0）とゼロの扱いが"
            "違うため除外しない（L277）"
        ),
    ),
    "le": OpSpec(
        name="le", category="filter", uses_k=True, literal_domain=_domain(1), ja_key="le",
        notes="`k`以下の値を残す（L124）。除外なし",
    ),
    "multiple_of": OpSpec(
        name="multiple_of", category="filter", uses_k=True, literal_domain=_domain(3),
        ja_key="multiple_of", shadows=("even",),
        notes="`k`の倍数だけを残す（L125）。@1 は恒真、@2 は `even` と同一のため除外（L274-275）",
    ),
    "positive": OpSpec(
        name="positive", category="filter", uses_k=False, literal_domain=(), ja_key="positive",
        notes="正の要素を残す（L126）。ゼロを含まない",
    ),
    "negative": OpSpec(
        name="negative", category="filter", uses_k=False, literal_domain=(), ja_key="negative",
        notes="負の要素を残す（L127）。ゼロを含まない",
    ),
    "zero": OpSpec(
        name="zero", category="filter", uses_k=False, literal_domain=(), ja_key="zero",
        notes="ゼロの要素を残す（L128）",
    ),
    # ---- 変換（改訂版 L130-141、8種類）----
    "add_k": OpSpec(
        name="add_k", category="map", uses_k=True, literal_domain=_domain(1), ja_key="add_k",
        notes="各要素に`k`を加える（L134）。@0 は値域外なので除外規定を要しない（L277）",
    ),
    "sub_k": OpSpec(
        name="sub_k", category="map", uses_k=True, literal_domain=_domain(1), ja_key="sub_k",
        notes="各要素から`k`を引く（L135）。@0 は値域外なので除外規定を要しない（L277）",
    ),
    "mul_k": OpSpec(
        name="mul_k", category="map", uses_k=True, literal_domain=_domain(4), ja_key="mul_k",
        shadows=("double", "triple"),
        notes=(
            "各要素に`k`を掛ける（L136）。@1 は恒等変換、@2 は `double`、@3 は `triple` と"
            "同一のため除外（L273-275）"
        ),
    ),
    "double": OpSpec(
        name="double", category="map", uses_k=False, literal_domain=(), ja_key="double",
        notes="各要素を2倍する（L137）",
    ),
    "triple": OpSpec(
        name="triple", category="map", uses_k=False, literal_domain=(), ja_key="triple",
        notes="各要素を3倍する（L138）",
    ),
    "negate": OpSpec(
        name="negate", category="map", uses_k=False, literal_domain=(), ja_key="negate",
        notes="符号を反転する（L139）",
    ),
    "abs": OpSpec(
        name="abs", category="map", uses_k=False, literal_domain=(), ja_key="abs",
        notes="絶対値を取る（L140）",
    ),
    "square": OpSpec(
        name="square", category="map", uses_k=False, literal_domain=(), ja_key="square",
        notes=(
            "二乗する（L141）。二乗は常に非負なので後続の `abs` が恒等になる（L534）。"
            "インタプリタ側で特別扱いはせず、`behavior_hash` に縮退として検出させる"
            "（実装計画 §2.7, §6）"
        ),
    ),
    # ---- 並べ替え（改訂版 L143-149、3種類）----
    "asc": OpSpec(
        name="asc", category="order", uses_k=False, literal_domain=(), ja_key="asc",
        notes="昇順に並べる（L147）",
    ),
    "desc": OpSpec(
        name="desc", category="order", uses_k=False, literal_domain=(), ja_key="desc",
        notes=(
            "降順に並べる（L148）。`[asc, reverse]` と振る舞いが同一だがパース衝突ではないため"
            "`shadows` には入れない。`behavior_hash` が拾う（実装計画 §2.6）"
        ),
    ),
    "reverse": OpSpec(
        name="reverse", category="order", uses_k=False, literal_domain=(), ja_key="reverse",
        notes="逆順にする（L149）。`desc`（降順整列）とは別opであり、潰さない（実装計画 §6）",
    ),
    # ---- 切り出し（改訂版 L151-157、3種類）----
    "take_first": OpSpec(
        name="take_first", category="slice", uses_k=True, literal_domain=_domain(1),
        ja_key="take_first",
        notes="先頭から`k`個（L155）。除外なし",
    ),
    "take_last": OpSpec(
        name="take_last", category="slice", uses_k=True, literal_domain=_domain(1),
        ja_key="take_last",
        notes="末尾から`k`個（L156）。除外なし",
    ),
    "every_other": OpSpec(
        name="every_other", category="slice", uses_k=False, literal_domain=(),
        ja_key="every_other",
        notes=(
            "1個おきに取得する（L157）。「1個おき」の曖昧性は `xs[::2]`（先頭から）に確定する"
            "（実装計画 §6）"
        ),
    ),
}
"""24種類のopのメタデータ。記述順は改訂版 L115-157 の表と同じ（目視照合のため）。

添字づけには使わない。列挙が使う並びは `OP_NAMES` である。
"""

OP_NAMES: Final[tuple[str, ...]] = tuple(sorted(OP_REGISTRY))
"""全op名の辞書順タプル。**列挙の添字づけの基準**（実装計画 §2.2 の unrank）。

`unrank(r, i)` は24個のopに固定した番号を与えて意味ASTを復元するため、この並びが変わると
同じ `i` が別のASTを指す。したがって並びは安定でなければならない。

辞書順にするのは、`OP_REGISTRY` の記述順（改訂版の表順）を後から編集しても添字が動かない
ようにするためである。並びを変えても `semantic_hash` は op名から計算するので不変であり、
影響を受けるのは `ast_id` の採番と、`--seed` を固定したときの difficulty 4 の抽出結果だけである。
"""

N_OPS: Final[int] = len(OP_NAMES)
"""opの総数。改訂版 L111 の24。意味AST空間の計算（実装計画 §2.2）の基数になる。"""
