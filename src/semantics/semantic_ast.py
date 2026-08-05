"""意味ASTのデータ構造。

意味ASTは**op名の順序付き列だけ**を表す。`k` の値などの定数は含めない。
定数のバリエーションは今回スコープ外の展開層が吸収する想定。

## この型が持つもの・持たないもの

持つのは**op列とレジストリから一意に決まる値だけ**である
（`difficulty` / `op_set` / `categories` / `canonical_order` / `binding_slots` /
`uses_k`）。

持たないのは次の二種類。

- **評価しないと決まらない値**：`semantic_hash` / `behavior_hash` / `always_empty` /
  `is_identity`。参照インタプリタと固定入力集合が要るので `fingerprint.py` の担当。
- **コーパスに載せるときに決まる値**：`ast_id` / `created_at` / 各 version。
  採番と由来の記録なので、レコード組み立て層の担当。
"""

import json
from dataclasses import dataclass
from itertools import permutations
from typing import Any, Self

from src.semantics.registry import (
    CATEGORY_ORDER,
    MAX_OPS,
    OP_NAMES,
    OP_REGISTRY,
)


@dataclass(frozen=True, slots=True)
class BindingSlot:
    """`k` を参照するopの位置と、そこに入れられるリテラルの値域。

    具体値は持たない。意味ASTは定数を含まないため、ここに置くのは
    「使える範囲」だけである。
    """

    index: int
    """AST内での位置（0始まり）。同じopでも位置が違えば別スロット。"""

    op: str

    literal_domain: tuple[int, ...]
    """このスロットで使えるリテラル。"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "op": self.op,
            "literal_domain": list(self.literal_domain),
        }


@dataclass(frozen=True, slots=True)
class SemanticAST:
    """op名の順序付き列。

    適用順序は自由であり、同じopの集合でも順序が違えば別の意味ASTとして扱う
    （集合ではなく列にしているのはこのため）。
    """

    ops: tuple[str, ...]
    """op名の列。左から順に適用する。"""

    def __post_init__(self) -> None:
        """リストやジェネレータで渡されてもタプルに正規化する。"""
        if not isinstance(self.ops, tuple):
            object.__setattr__(self, "ops", tuple(self.ops))

    # ---- op列から決まる値 ----

    @property
    def difficulty(self) -> int:
        """組み合わせた操作の個数。"""
        return len(self.ops)

    @property
    def op_set(self) -> tuple[str, ...]:
        """順序を落としてソートしたop集合。同一opは重複しない前提なので、
        単に並べ替えるだけでよい。"""
        return tuple(sorted(self.ops))

    @property
    def categories(self) -> tuple[str, ...]:
        """各opのカテゴリを**AST順で**並べたもの。重複し得る。"""
        return tuple(OP_REGISTRY[name].category for name in self.ops)

    @property
    def canonical_order(self) -> bool:
        """カテゴリ順（抽出→変換→並べ替え→切り出し）に従っているか。

        記録するだけで、列挙は制限しない。判定はカテゴリの並びが非減少かどうか。
        同カテゴリ内の順序は問わない。
        """
        ranks = [CATEGORY_ORDER.index(category) for category in self.categories]
        return all(a <= b for a, b in zip(ranks, ranks[1:]))

    @property
    def uses_k(self) -> bool:
        """`k` を参照するopを1つ以上含むか。"""
        return any(OP_REGISTRY[name].uses_k for name in self.ops)

    @property
    def binding_slots(self) -> tuple[BindingSlot, ...]:
        """`k` 参照opの位置と値域をAST順で並べたもの。ここではkには何も代入しないが、kがどこにあるかをここで確認しておくことで、あとの代入に備える。"""
        return tuple(
            BindingSlot(
                index=index,
                op=name,
                literal_domain=OP_REGISTRY[name].literal_domain,
            )
            for index, name in enumerate(self.ops)
            if OP_REGISTRY[name].uses_k
        )

    # ---- 直列化 ----

    def canonical_json(self) -> str:
        """`semantic_hash` の入力になる正準表現。

        op列だけから決まる。由来情報も派生値も入れない
        （入れると再計算のたびに値が変わりうる、あるいは情報が増えないだけになる）。
        """
        return json.dumps(list(self.ops), ensure_ascii=False, separators=(",", ":"))

    def to_dict(self) -> dict[str, Any]:
        """レコード形式のうち、**op列から決まる部分**を返す。

        `semantic_hash` や `ast_id` は含まない。
        """
        return {
            "semantic_ast": list(self.ops),
            "difficulty": self.difficulty,
            "categories": list(self.categories),
            "op_set": list(self.op_set),
            "canonical_order": self.canonical_order,
            "binding_slots": [slot.to_dict() for slot in self.binding_slots],
            "uses_k": self.uses_k,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """`to_dict()` の逆。**`semantic_ast` だけを読み、派生値は再計算する。**

        辞書に派生値が入っていて、それが再計算した値と食い違う場合は `ValueError` にする。
        黙って捨てると、古いコーパスや壊れたレコードを読んでいることに気づけない。

        Raises:
            KeyError: `semantic_ast` が無いとき。
            ValueError: 派生値が再計算した値と食い違うとき。
        """
        ast = cls(tuple(data["semantic_ast"]))

        expected = ast.to_dict()
        for key, value in data.items():
            if key not in expected or key == "semantic_ast":
                continue
            if value != expected[key]:
                raise ValueError(
                    f"派生値 {key!r} がop列と矛盾する: "
                    f"レコード={value!r} 再計算={expected[key]!r}"
                )
        return ast

    def __str__(self) -> str:
        """`[ge, double, asc]` の形。ログと失敗メッセージ用。"""
        return "[" + ", ".join(self.ops) + "]"


# ---- 全数列挙 ----
#
# このコーパスは学習用のサンプリング済みデータではなく**参照台帳**として作る
# （difficulty 1〜4の全267,744件をそのまま持つ）。層化配分や `unrank` は不要で、
# `itertools.permutations` で24個のop名から1〜`MAX_OPS`個を順序付きで選ぶ
# 組み合わせを全て作れば足りる。


def enumerate_all_asts() -> list[SemanticAST]:
    """difficulty 1〜`MAX_OPS` の意味ASTを全て列挙する。

    difficultyの昇順、各difficulty内では `OP_NAMES`（辞書順）を基準にした
    `itertools.permutations` の順（＝辞書順）に並ぶ。同一opの重複は
    `permutations` の性質上そもそも生成されない。
    """
    asts: list[SemanticAST] = []
    for difficulty in range(1, MAX_OPS + 1):
        for ops in permutations(OP_NAMES, difficulty):
            asts.append(SemanticAST(ops))
    return asts
