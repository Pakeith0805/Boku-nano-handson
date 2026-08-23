"""意味ASTから、互いに等価な複数のPython実装を生成する。

`src/interp/interp.py`（参照インタプリタ）とは**意図的に独立**して書く。24種のopの
計算をここでも一から書き下ろすのは、`registry.py` のdocstringが述べる分離のためで
ある——参照インタプリタとコード生成器がopの意味を共有してしまうと、片方にバグが
あっても差分テスト（同じ意味ASTを両方に通し、乱数入力での出力を突き合わせる）が
それを検出できなくなる。したがってこのファイルは `src.interp` を一切importしない。

一方で、opの記述に**曖昧さが残る**もの（`every_other` の基準、`desc`と`reverse`の
違いなど）は参照インタプリタが確定させた解釈にそろえる。ここで独立させるのは
「計算の書き方」であって、「何を計算するか」の確定はいずれか片方が担い、参照
インタプリタがそれを担う。

## 生成物の形

いずれのスタイルでも `def solve(xs, k):` （型注釈は`annotate`次第）で、`k`を参照
しないop列でも引数は常に2つ取る（課題の関数シグネチャが固定のため）。
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from typing import Literal

from src.semantics.registry import OP_REGISTRY
from src.semantics.semantic_ast import SemanticAST

StageKind = Literal["map", "filtergroup", "order", "slice"]


@dataclass(frozen=True, slots=True)
class Stage:
    """レンダリング単位。連続する `filter` opはここで1つにまとめる。

    まとめる理由は「条件式の順序変更」バリエーションのため——隣接する2つ以上の
    filterは、同じ要素を独立に判定するだけなので順序を入れ替えても結果は変わらない
    （map/order/sliceはこの性質を持たないため、まとめもシャッフルもしない）。

    `[even, ge]`と`[ge, even]`のように、この並べ替えで別の意味ASTと同一の生成コード
    文字列になり得るが、これらは`behavior_hash`も一致する（挙動が完全に同じ）ため、
    訓練/検証/テスト分割を`behavior_hash`のグループ単位で行う設計のもとでは、
    別split間でこの文字列が衝突することはない（同じグループは常に同じsplitに入る）。
    """

    kind: StageKind
    ops: tuple[str, ...]


def _group_stages(ops: tuple[str, ...], *, shuffle_filters: bool, rng: random.Random) -> list[Stage]:
    stages: list[Stage] = []
    i = 0
    n = len(ops)
    while i < n:
        category = OP_REGISTRY[ops[i]].category
        if category == "filter":
            j = i
            run_ops = []
            while j < n and OP_REGISTRY[ops[j]].category == "filter":
                run_ops.append(ops[j])
                j += 1
            if shuffle_filters and len(run_ops) > 1:
                run_ops = run_ops[:]
                rng.shuffle(run_ops)
            stages.append(Stage("filtergroup", tuple(run_ops)))
            i = j
        else:
            stages.append(Stage(category, (ops[i],)))
            i += 1
    return stages


# ---- opごとの独立実装（式の断片） ----
# interp.py の OP_IMPLS を呼ばず、ここで書き下ろす（分離の理由はモジュールdocstring）。
# ただし挙動はinterp.pyの確定した解釈と一致させる。

_MAP_EXPR: dict[str, "callable[[str, str], str]"] = {
    "abs": lambda e, k: f"abs({e})",
    "add_k": lambda e, k: f"{e} + {k}",
    "sub_k": lambda e, k: f"{e} - {k}",
    "mul_k": lambda e, k: f"{e} * {k}",
    "double": lambda e, k: f"{e} * 2",
    "triple": lambda e, k: f"{e} * 3",
    "negate": lambda e, k: f"-{e}",
    "square": lambda e, k: f"{e} * {e}",
}

_FILTER_COND: dict[str, "callable[[str, str], str]"] = {
    "even": lambda e, k: f"{e} % 2 == 0",
    "odd": lambda e, k: f"{e} % 2 != 0",
    "gt": lambda e, k: f"{e} > {k}",
    "ge": lambda e, k: f"{e} >= {k}",
    "lt": lambda e, k: f"{e} < {k}",
    "le": lambda e, k: f"{e} <= {k}",
    "multiple_of": lambda e, k: f"{e} % {k} == 0",
    "positive": lambda e, k: f"{e} > 0",
    "negative": lambda e, k: f"{e} < 0",
    "zero": lambda e, k: f"{e} == 0",
}

_MAP_COMMENT = {
    "abs": "絶対値にする", "add_k": "kを加える", "sub_k": "kを引く", "mul_k": "kを掛ける",
    "double": "2倍にする", "triple": "3倍にする", "negate": "符号を反転する", "square": "二乗する",
}
_FILTER_COMMENT = {
    "even": "偶数を残す", "odd": "奇数を残す", "gt": "kより大きい値を残す",
    "ge": "k以上の値を残す", "lt": "kより小さい値を残す", "le": "k以下の値を残す",
    "multiple_of": "kの倍数を残す", "positive": "正の値を残す", "negative": "負の値を残す",
    "zero": "ゼロを残す",
}
_ORDER_COMMENT = {"asc": "昇順に並べる", "desc": "降順に並べる", "reverse": "順序を反転する"}
_SLICE_COMMENT = {
    "take_first": "先頭からk個取る", "take_last": "末尾からk個取る", "every_other": "1個おきに取る",
}


def _order_expr(op: str, var: str, *, reverse_style: bool) -> str:
    """`reverse_style` は `reverse=True` と手動での逆順操作を切り替える。

    `desc`（降順に**並べ替える**）と `reverse`（今の並びを**逆にするだけ**）は別opであり、
    ここでも混同しない（`src/interp/interp.py` の `op_desc`/`op_reverse` と同じ区別）。
    """
    if op == "asc":
        return f"sorted({var})"
    if op == "desc":
        return f"sorted({var}, reverse=True)" if not reverse_style else f"sorted({var})[::-1]"
    if op == "reverse":
        return f"{var}[::-1]" if not reverse_style else f"list(reversed({var}))"
    raise ValueError(f"未知のorder op: {op!r}")


def _slice_expr(op: str, var: str, k: str) -> str:
    if op == "take_first":
        return f"{var}[:{k}]"
    if op == "take_last":
        return f"{var}[-{k}:]"
    if op == "every_other":
        return f"{var}[::2]"
    raise ValueError(f"未知のslice op: {op!r}")


ELEM_NAME_POOL: tuple[str, ...] = ("x", "v", "n", "item")
"""内包表記／forループの要素変数名の候補（「変数名の変更」バリエーション用）。"""

STAGE_VAR_POOL: tuple[str, ...] = ("s", "step", "tmp", "part")
"""段階ごとに一時変数を使うとき（`temp_vars=True`）の変数名の接頭辞の候補。"""

ACCUM_VAR_POOL: tuple[str, ...] = ("result", "out", "answer", "ys")
"""1本の式に融合するとき（`temp_vars=False`）で、かつ複数行形式のときに使う変数名の候補。"""


@dataclass(frozen=True, slots=True)
class Style:
    """生成する1本のコードの見た目を決めるフラグ。

    `xs`・`k`という引数名そのものは変えない（課題のシグネチャが固定のため）。
    ここで揺らすのは関数の中身だけである。
    """

    comprehension: bool = True
    """True: 内包表記でmap/filterを書く。False: 明示的な`for`ループ＋`.append`。"""

    temp_vars: bool = True
    """True: 段階ごとに専用の一時変数へ代入する。False: 1本の式に融合する。"""

    shuffle_filters: bool = False
    """隣接する2つ以上のfilterがあるとき、その中の順序を入れ替えるか。"""

    reverse_style: bool = False
    """`desc`/`reverse`の書き方。False: `reverse=True`・`[::-1]`。True: 手動での逆順操作。"""

    one_line_return: bool = True
    """`temp_vars=False`のときだけ効く。False なら `結果 = 式` の次行で `return 結果`。"""

    annotate: bool = True
    """True: 型注釈つきシグネチャ＋各段階に日本語コメント。False: どちらも無し。"""

    elem_name: str = "x"
    stage_var: str = "s"
    accum_var: str = "result"

    seed: int | None = None
    """`shuffle_filters=True` のときの並べ替えの再現性を決める。"""


def random_style(seed: int) -> Style:
    """`seed` から1つのスタイルをランダムに決める（再現可能）。"""
    rng = random.Random(seed)
    return Style(
        comprehension=rng.choice([True, False]),
        temp_vars=rng.choice([True, False]),
        shuffle_filters=rng.choice([True, False]),
        reverse_style=rng.choice([True, False]),
        one_line_return=rng.choice([True, False]),
        annotate=rng.choice([True, False]),
        elem_name=rng.choice(ELEM_NAME_POOL),
        stage_var=rng.choice(STAGE_VAR_POOL),
        accum_var=rng.choice(ACCUM_VAR_POOL),
        seed=seed,
    )


def _comment_for(stage: Stage) -> str:
    if stage.kind == "map":
        return _MAP_COMMENT[stage.ops[0]]
    if stage.kind == "filtergroup":
        return "、".join(_FILTER_COMMENT[op] for op in stage.ops)
    if stage.kind == "order":
        return _ORDER_COMMENT[stage.ops[0]]
    return _SLICE_COMMENT[stage.ops[0]]


def _stage_expr(stage: Stage, cur: str, style: Style) -> str:
    """段階1つぶんの、現在値`cur`から次の値を作る式（内包表記・組み込み関数どちらか）。"""
    e = style.elem_name
    if stage.kind == "map":
        return f"[{_MAP_EXPR[stage.ops[0]](e, 'k')} for {e} in {cur}]"
    if stage.kind == "filtergroup":
        cond = " and ".join(_FILTER_COND[op](e, "k") for op in stage.ops)
        return f"[{e} for {e} in {cur} if {cond}]"
    if stage.kind == "order":
        return _order_expr(stage.ops[0], cur, reverse_style=style.reverse_style)
    return _slice_expr(stage.ops[0], cur, "k")


def _stage_loop_lines(stage: Stage, cur: str, dest: str, style: Style) -> list[str]:
    """段階1つぶんの、`for`ループを使う版（map/filtergroupのみ）。

    `temp_vars=False`だと`dest`が`cur`と同じ変数名になり得る。`{dest} = []`を
    `for ... in {cur}`より先に書くと、その時点で`cur`（＝`dest`）が空リストに
    上書きされてしまい、ループが空の列を回ることになる。そのため一旦は必ず
    別名（`_buf`）へ積み、最後に`dest`へ代入する。
    """
    e = style.elem_name
    lines = ["_buf = []", f"for {e} in {cur}:"]
    if stage.kind == "map":
        lines.append(f"    _buf.append({_MAP_EXPR[stage.ops[0]](e, 'k')})")
    else:  # filtergroup
        cond = " and ".join(_FILTER_COND[op](e, "k") for op in stage.ops)
        lines.append(f"    if {cond}:")
        lines.append(f"        _buf.append({e})")
    lines.append(f"{dest} = _buf")
    return lines


def generate(ast: SemanticAST, style: Style = Style()) -> str:
    """意味AST `ast` を、`style` の見た目でPythonソース1本にする。

    左から順に適用する（`interp.run`と同じ規約）。返り値は`def solve(...):`から
    始まる完全な関数定義の文字列。
    """
    rng = random.Random(style.seed)
    stages = _group_stages(ast.ops, shuffle_filters=style.shuffle_filters, rng=rng)

    sig = (
        "def solve(xs: list[int], k: int) -> list[int]:"
        if style.annotate
        else "def solve(xs, k):"
    )
    body: list[str] = []

    if not style.temp_vars and style.comprehension:
        # 内包表記どうしは式として入れ子にできるので、ここだけ本当に1本の式へ融合できる。
        # `for`ループは文なので式に埋め込めず、この融合はcomprehension=Trueのときだけ成立する。
        expr = "xs"
        for stage in stages:
            expr = _stage_expr(stage, expr, style)
        if style.one_line_return:
            body.append(f"return {expr}")
        else:
            body.append(f"{style.accum_var} = {expr}")
            body.append(f"return {style.accum_var}")
    else:
        # 段階ごとに文を1つ書く。temp_vars=Falseなら全段階が同じ変数名を使い回し、
        # Trueなら段階ごとに専用の変数名を振る。
        cur = "xs"
        for idx, stage in enumerate(stages, start=1):
            dest = f"{style.stage_var}_{idx}" if style.temp_vars else style.accum_var
            if style.annotate:
                body.append(f"# {_comment_for(stage)}")
            if stage.kind in ("map", "filtergroup") and not style.comprehension:
                body.extend(_stage_loop_lines(stage, cur, dest, style))
            else:
                body.append(f"{dest} = {_stage_expr(stage, cur, style)}")
            cur = dest
        body.append(f"return {cur}")

    indented = "\n".join(f"    {line}" for line in body)
    return f"{sig}\n{indented}\n"


def _filter_run_spans(ops: tuple[str, ...]) -> list[tuple[int, int]]:
    """連続するfilter opの区間`(start, end)`（半開区間）を列挙する。長さ2以上のみ返す。

    `MAX_OPS=4`のもとでは、長さ2以上の区間が2つ以上同時に存在することはない
    （区切りに他カテゴリのopが最低1個要るので、2区間なら最低2+1+2=5opsが要る）。
    ただしここでは特定の個数を仮定せず、一般に複数区間があっても正しく動くように書く。
    """
    spans: list[tuple[int, int]] = []
    i = 0
    n = len(ops)
    while i < n:
        if OP_REGISTRY[ops[i]].category == "filter":
            j = i
            while j < n and OP_REGISTRY[ops[j]].category == "filter":
                j += 1
            if j - i > 1:
                spans.append((i, j))
            i = j
        else:
            i += 1
    return spans


def _op_orderings(ops: tuple[str, ...]) -> list[tuple[str, ...]]:
    """条件式の順序違いを表す、意味的に同じop列を全パターン列挙する。

    連続するfilterの区間だけを`itertools.permutations`で並べ替える（filter以外は
    可換ではないので動かさない）。区間が無ければ`[ops]`(元のまま1通り)だけを返す。
    区間が複数あれば、それぞれ独立に並べ替えた直積になる。
    """
    spans = _filter_run_spans(ops)
    if not spans:
        return [ops]
    per_span_perms = [list(itertools.permutations(ops[start:end])) for start, end in spans]
    orderings = []
    for combo in itertools.product(*per_span_perms):
        new_ops = list(ops)
        for (start, end), perm in zip(spans, combo):
            new_ops[start:end] = perm
        orderings.append(tuple(new_ops))
    return orderings


@dataclass(frozen=True, slots=True)
class Candidate:
    """列挙された候補1件。抽出スクリプトが軸の値を見て選べるよう、
    `style`（と、条件式を並べ替えた場合の`ops`）を`code`と一緒に持つ。
    """

    style: Style
    ops: tuple[str, ...]
    code: str


def enumerate_candidates(ast: SemanticAST) -> list[Candidate]:
    """このASTから作れる、構造的に異なるコード候補を**全部**列挙する（上限なし）。

    間引き（何件・どれを採用するか）は行わない——それは抽出スクリプトの責務。
    ここでは次の2つを総当たりする。

    1. 内包表記/ループ・一時変数の有無・reverse方式・return形式・注釈の有無
       （該当opが無い軸は自動的に1択になる）
    2. 条件式の順序（連続filterの区間を`itertools.permutations`で全通り）

    変数名（`elem_name`・`stage_var`/`accum_var`）は含めない。均す対象ではない
    表層的な違いなので、既定値のまま固定する。採用が決まった候補に好きな名前を
    差し込みたい場合は、`Candidate.style`をコピーして`generate()`を呼び直せばよい。

    同一文字列になった候補は重複させない（先に見つかった方を残す）。
    """
    bool_axes = (True, False)
    has_reverse_op = any(op in ("desc", "reverse") for op in ast.ops)
    reverse_choices = bool_axes if has_reverse_op else (False,)

    seen: dict[str, Candidate] = {}
    for ordering in _op_orderings(ast.ops):
        variant = SemanticAST(ordering)
        for comprehension, temp_vars, reverse_style, one_line_return, annotate in itertools.product(
            bool_axes, bool_axes, reverse_choices, bool_axes, bool_axes
        ):
            style = Style(
                comprehension=comprehension,
                temp_vars=temp_vars,
                reverse_style=reverse_style,
                one_line_return=one_line_return,
                annotate=annotate,
            )
            code = generate(variant, style)
            if code not in seen:
                seen[code] = Candidate(style=style, ops=ordering, code=code)

    return list(seen.values())
