"""意味ASTのレコードを、`behavior_hash`のグループ単位で訓練/検証/テストに分割する。

## なぜ`ast_id`や`semantic_hash`ではなく`behavior_hash`が分割の単位か

`codegen`は連続するfilterの条件式を並べ替える（`shuffle_filters`）ため、`[even, ge]`と
`[ge, even]`のように**別の意味AST（別の`ast_id`・別の`semantic_hash`）が、生成コードの
文字列としては一致し得る**。この2つは`behavior_hash`が最初から一致している（挙動が完全に
同じ）ので、`behavior_hash`のグループを丸ごと同じsplitに入れておけば、別split間でこの
文字列が衝突する（＝train/testリークになる）ことはない。`ast_id`や`semantic_hash`単位で
素朴に分割すると、このリークを防げない。

## なぜ退化レコード（`always_empty`）だけ特別扱いするか

`behavior_hash`でグループ化すると、「常に空リストを返す」という挙動だけで267,744件中
59,775件（22.3%）が1つの巨大グループに集約されてしまう（`[abs, negative]`も`[even, odd]`も
挙動は同じ）。これを他と同じにグループ単位でsplitに割り当てると、コーパスの5分の1強が
丸ごとどれか1つのsplitに寄ってしまい、80/10/10の構成が成立しなくなる。

一方で、「常に空リストを返す」という挙動は、どの具体的なop列で実現されていても学習上の
価値にほとんど差が無い（1例見せれば十分学べる）。したがって`always_empty`なレコードだけ
`behavior_hash`のグループ制約を外し、レコード単位で無作為に分割してよいと判断する。

`is_identity`（`[add_k, sub_k]`と`[sub_k, add_k]`の2件のみ）はこの特別扱いをしない。
2件しかなく、巨大グループ化の問題が起きないため、他と同じ通常のグループ単位分割に含める
（この2件は元々`behavior_hash`が一致するので、1つのグループとして丸ごと同じsplitに入る）。
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_RATIOS: dict[str, float] = {"train": 0.8, "val": 0.1, "test": 0.1}
"""既定の分割比率。課題文の推奨構成（訓練80%・検証10%・テスト10%）と同じ。"""


@dataclass(frozen=True, slots=True)
class Split:
    """分割結果。値は`ast_id`の列（レコードそのものではない）。"""

    train: tuple[str, ...]
    val: tuple[str, ...]
    test: tuple[str, ...]

    def bucket_of(self, ast_id: str) -> str | None:
        """`ast_id`がどのsplitに入っているかを返す。見つからなければ`None`。"""
        for name in ("train", "val", "test"):
            if ast_id in getattr(self, name):
                return name
        return None


def is_degenerate(record: Mapping[str, Any]) -> bool:
    """常に空リストを返すレコードか。

    真なら、挙動の多様性がほとんど無いので`behavior_hash`グループの原子性を要求しない
    （`split_corpus`が個別に無作為分割する）。`is_identity`はここに含めない——2件しか無く
    巨大グループ化の問題が起きないため、通常のグループ単位分割に任せる。
    """
    return bool(record["always_empty"])


def _cut(ids: Sequence[str], ratios: Mapping[str, float]) -> Split:
    """既にシャッフル済みの`ids`を、比率通りに3分割する（グループ制約なし版）。"""
    n = len(ids)
    n_train = round(n * ratios["train"])
    n_val = round(n * ratios["val"])
    return Split(
        train=tuple(ids[:n_train]),
        val=tuple(ids[n_train : n_train + n_val]),
        test=tuple(ids[n_train + n_val :]),
    )


def _assign_groups(
    groups: Mapping[str, Sequence[str]], ratios: Mapping[str, float], rng: random.Random
) -> Split:
    """`behavior_hash` → `ast_id`列 のグループを、グループ単位で3つのバケツへ貪欲に割り当てる。

    サイズの大きいグループから順に、「現在の割合が目標比率から一番不足しているバケツ」へ
    入れる（bin-packingの Longest-Processing-Time-First と同じ発想）。グループサイズは
    1〜数千まで幅があるため、単純にグループ数やランダムな割り当てで切ると実際の件数比率が
    80/10/10から大きくズレる。大きいグループから優先的に「今一番足りないところ」へ埋めると
    ズレが小さく抑えられる。

    同サイズのグループの順序はタイブレークになるため、事前に`rng`でシャッフルしてから
    サイズ降順で安定ソートする（再現性を保ちつつ、常に同じ順で偏らないようにする）。
    """
    items = list(groups.items())
    rng.shuffle(items)
    items.sort(key=lambda kv: len(kv[1]), reverse=True)

    total = sum(len(ids) for _, ids in items)
    counts = {name: 0 for name in ratios}
    buckets: dict[str, list[str]] = {name: [] for name in ratios}

    for _, ids in items:
        deficit = {
            name: (counts[name] / total if total else 0.0) - ratios[name] for name in ratios
        }
        target = min(deficit, key=lambda name: deficit[name])
        buckets[target].extend(ids)
        counts[target] += len(ids)

    return Split(train=tuple(buckets["train"]), val=tuple(buckets["val"]), test=tuple(buckets["test"]))


def split_corpus(
    records: Sequence[Mapping[str, Any]],
    *,
    ratios: Mapping[str, float] = DEFAULT_RATIOS,
    seed: int = 0,
) -> Split:
    """全ASTレコードをtrain/val/testに分ける。

    退化レコード（`is_degenerate`）は`behavior_hash`を無視して個別に無作為分割する。
    それ以外は`behavior_hash`のグループを丸ごとどれか1つのsplitへ割り当てる
    （同じ挙動を持つASTがsplitを跨いで現れることによるリークを防ぐ）。

    両者を別々に分割してから結果を合成する（片方が偏っても、もう片方の比率には
    影響しないようにするため）。
    """
    rng = random.Random(seed)

    degenerate_ids = [r["ast_id"] for r in records if is_degenerate(r)]
    rng.shuffle(degenerate_ids)
    degenerate_split = _cut(degenerate_ids, ratios)

    groups: dict[str, list[str]] = {}
    for r in records:
        if not is_degenerate(r):
            groups.setdefault(r["behavior_hash"], []).append(r["ast_id"])
    normal_split = _assign_groups(groups, ratios, rng)

    return Split(
        train=degenerate_split.train + normal_split.train,
        val=degenerate_split.val + normal_split.val,
        test=degenerate_split.test + normal_split.test,
    )
