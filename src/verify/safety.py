"""生成されたPythonソースが、許可された構文だけで出来ているかを検査する。

対象は自分たちの`codegen`が吐くコードだけではない。将来ここを通すのは**学生モデルが
生成した任意のコード**も含む（実装計画のpass@1評価）。したがって**禁止リスト方式は
取らない**——危険な構文・関数を全部列挙するのは原理的に不可能である。代わりに
**許可リスト方式**を取る。許可した構文・関数・属性だけを通し、それ以外は理由を問わず
すべて拒否する。

## 許可リストの根拠

`ALLOWED_NODE_TYPES`・`ALLOWED_CALLS`・`ALLOWED_ATTRS`は、`codegen.enumerate_candidates`が
実際に出力するコード（差分テスト済みの300ASTぶんの全候補）を`ast.walk`で実地に洗い出して
作った。**未知の構文・呼び出しは通さない**（`src/nlg/nlgen.py`の`to_renyou`が未知の語尾を
`ValueError`で落とすのと同じ「静かに通さない」設計）。将来codegenが新しい構文を使うように
なったら、ここも合わせて広げること（`tests/`側で両者の整合を確認するのが望ましい）。
"""

from __future__ import annotations

import ast

ALLOWED_NODE_TYPES: frozenset[type[ast.AST]] = frozenset({
    ast.Module,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.Load,
    ast.Store,
    ast.Return,
    ast.Assign,
    ast.Expr,
    ast.For,
    ast.If,
    ast.List,
    ast.ListComp,
    ast.comprehension,
    ast.Name,
    ast.Constant,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.USub,
    ast.And,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Mod,
    ast.Call,
    ast.Subscript,
    ast.Slice,
    ast.Attribute,
    ast.keyword,
})
"""codegenの出力に実際に現れるASTノード型だけを許可する（網羅的に実地調査した集合）。"""

ALLOWED_CALLS: frozenset[str] = frozenset({"abs", "sorted", "list", "reversed"})
"""`f(...)`の形（`ast.Name`呼び出し）で許可する関数名。"""

ALLOWED_ATTRS: frozenset[str] = frozenset({"append"})
"""`x.attr`の形で許可する属性名。事実上`list.append`専用（forループ版が使う）。

属性アクセスを丸ごと禁止しないのはこのためだが、許可するのは**属性名だけ**であり、
`().__class__`のような属性名自体が許可リストに無いものは弾かれる。
"""


def check(code: str) -> str | None:
    """`code`が許可リストの範囲内だけで出来ているか検査する。

    問題が無ければ`None`、あれば理由の文字列を返す
    （`scripts/teacher/phrase_filters.check`と同じ「例外ではなく理由を返す」形）。

    検査するのは構文と呼び出し・属性の許可リスト、および`def solve(xs, k):`という
    指定シグネチャを守っているかだけである。実際に実行して壊れないかは
    `src/verify/sandbox.py`の担当（役割を混ぜない）。
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"ast.parseに失敗: {e}"

    for node in ast.walk(tree):
        node_type = type(node)
        if node_type not in ALLOWED_NODE_TYPES:
            return f"許可されていない構文: {node_type.__name__}"

        if isinstance(node, ast.Attribute) and node.attr not in ALLOWED_ATTRS:
            return f"許可されていない属性アクセス: .{node.attr}"

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in ALLOWED_CALLS:
                    return f"許可されていない関数呼び出し: {node.func.id}"
            elif not isinstance(node.func, ast.Attribute):
                return "許可されていない呼び出しの形"

    return _check_signature(tree)


def _check_signature(tree: ast.Module) -> str | None:
    """モジュール直下が`def solve(xs, k):`（型注釈の有無は問わない）1つだけであることを確認する。"""
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        return "モジュール直下がsolve関数1つだけではない"

    fn = tree.body[0]
    if fn.name != "solve":
        return f"関数名がsolveではない: {fn.name!r}"

    args = fn.args
    if args.vararg or args.kwarg or args.kwonlyargs or args.posonlyargs or args.defaults:
        return "solve(xs, k)以外の引数の形（*args/**kwargs/キーワード専用引数/既定値など）"

    names = [a.arg for a in args.args]
    if names != ["xs", "k"]:
        return f"引数がxs, kの順で2つではない: {names}"

    return None
