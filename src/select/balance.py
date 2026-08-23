"""コード形式・日本語テンプレートを、コーパス全体で均等になるよう貪欲に選ぶ。

`codegen.enumerate_candidates`/`nlgen.enumerate_candidates`は、あるASTから作れる候補を
**全部**返すだけで、どれを採用するかは決めない（両者のREADME参照）。ここでは「コーパス
全体を通した採用数」を`Counter`で追跡しながら、AST 1件ごとに候補を選ぶ。

## 貪欲法の考え方

候補を1件選ぶたびに、その候補が持つ軸の値の採用数を1つ増やす。次にどの候補を選ぶかは、
**現時点で一番採用数が少ない軸の値を持つ候補を優先する**（同点はその都度シャッフルして崩す）。
これをAST 1件ずつ繰り返すと、コーパス全体を通して極端に偏った軸の値ができにくい。

コード側の軸（内包表記/ループ等の構造6軸）と、日本語側の軸（採用した言い回しID）は別物
なので、別々の`Counter`で独立に均す。呼び出し側（選抜スクリプト）が`Counter`を1つずつ
持ち回り、AST全件の処理を通して同じインスタンスを使い続けることで、均しが全体に効く。
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace

from src.codegen.codegen import (
    ACCUM_VAR_POOL,
    ELEM_NAME_POOL,
    STAGE_VAR_POOL,
    Candidate,
    generate,
)
from src.nlg.nlgen import SentenceCandidate
from src.semantics.semantic_ast import SemanticAST

CodeAxisKey = tuple[bool, bool, bool, bool, bool, bool]
"""(comprehension, temp_vars, reverse_style, one_line_return, annotate, 条件式を並べ替えたか)。"""


def code_axis_key(ast_ops: tuple[str, ...], candidate: Candidate) -> CodeAxisKey:
    """候補1件が持つ構造の軸の値。コーパス全体の`Counter`のキーに使う。"""
    s = candidate.style
    return (
        s.comprehension,
        s.temp_vars,
        s.reverse_style,
        s.one_line_return,
        s.annotate,
        candidate.ops != ast_ops,
    )


def pick_code_candidates(
    ast_ops: tuple[str, ...],
    candidates: Sequence[Candidate],
    *,
    limit: int,
    counts: Counter[CodeAxisKey],
    rng: random.Random,
) -> list[Candidate]:
    """コード候補から`limit`件選ぶ。構造の軸の採用数が一番少ないものを優先する。

    候補数が`limit`に満たなければ、あるだけ返す（水増ししない。`codegen.enumerate_candidates`
    のdocstringにある方針と同じ）。
    """
    pool = list(candidates)
    rng.shuffle(pool)
    pool.sort(key=lambda c: counts[code_axis_key(ast_ops, c)])

    picked = pool[:limit]
    for c in picked:
        counts[code_axis_key(ast_ops, c)] += 1
    return picked


def pick_sentence_candidates(
    candidates: Sequence[SentenceCandidate],
    *,
    limit: int,
    counts: Counter[str],
    rng: random.Random,
) -> list[SentenceCandidate]:
    """日本語文候補から`limit`件選ぶ。

    使っている言い回しID(`phrase_ids`)ごとの採用数の**合計**が一番少ない候補を優先する。
    こうすると、特定の言い回し（例えば`ge-01`ばかり）に偏らず、opごとの言い回しが
    コーパス全体で均等に使われる。
    """
    pool = list(candidates)
    rng.shuffle(pool)
    pool.sort(key=lambda c: sum(counts[pid] for pid in c.phrase_ids))

    picked = pool[:limit]
    for c in picked:
        for pid in c.phrase_ids:
            counts[pid] += 1
    return picked


def _renamed(candidate: Candidate, rng: random.Random) -> Candidate:
    """採用が決まったコード候補に、変数名のバリエーションを差し込み直す。

    `codegen.enumerate_candidates`は変数名を意図的に既定値（`x`/`s`/`result`）のまま
    固定して返す（均す対象ではない表層的な違いのため、そのdocstring参照）。「採用が決まった
    候補にだけ好きな名前を差し込む」設計だったので、ここがその仕上げにあたる。
    """
    style = replace(
        candidate.style,
        elem_name=rng.choice(ELEM_NAME_POOL),
        stage_var=rng.choice(STAGE_VAR_POOL),
        accum_var=rng.choice(ACCUM_VAR_POOL),
    )
    code = generate(SemanticAST(candidate.ops), style)
    return replace(candidate, style=style, code=code)


@dataclass(frozen=True, slots=True)
class Example:
    """選ばれた訓練例1件。最終レコードのスキーマ確定はまだ先なので、ここでは
    再構築に要る最低限の情報だけを持つ。
    """

    ast_id: str
    code: str
    code_ops: tuple[str, ...]
    code_style: CodeAxisKey
    elem_name: str
    var_name: str
    instruction: str
    phrase_ids: tuple[str, ...]


def select_examples(
    ast_id: str,
    ast_ops: tuple[str, ...],
    code_candidates: Sequence[Candidate],
    sentence_candidates: Sequence[SentenceCandidate],
    *,
    cap: int,
    code_counts: Counter[CodeAxisKey],
    phrase_counts: Counter[str],
    rng: random.Random,
) -> list[Example]:
    """1つのASTについて、コードと日本語文をそれぞれ`cap`件まで均等に選び、対にする。

    コード側・日本語文側を独立に選んでから位置で対にする（`i`番目のコードと`i`番目の文を
    組み合わせる）ので、対にする前にもう一度シャッフルし、「採用順位の高いコードは採用順位の
    高い文とばかり組む」という余計な相関を生まないようにする。組の数は、コード・文どちらか
    少ない方に合わせる（`enumerate_candidates`が候補を水増ししない設計を踏襲する）。

    構造の軸（`code_counts`）はまだ既定の変数名のまま選ぶ——変数名は均す対象ではないため、
    軸の採用数に影響させない。選ばれた後で`_renamed`が変数名を差し込む。
    """
    codes = pick_code_candidates(ast_ops, code_candidates, limit=cap, counts=code_counts, rng=rng)
    codes = [_renamed(c, rng) for c in codes]
    sentences = pick_sentence_candidates(sentence_candidates, limit=cap, counts=phrase_counts, rng=rng)
    rng.shuffle(codes)
    rng.shuffle(sentences)

    n = min(len(codes), len(sentences))
    return [
        Example(
            ast_id=ast_id,
            code=codes[i].code,
            code_ops=codes[i].ops,
            code_style=code_axis_key(ast_ops, codes[i]),
            elem_name=codes[i].style.elem_name,
            var_name=codes[i].style.stage_var if codes[i].style.temp_vars else codes[i].style.accum_var,
            instruction=sentences[i].text,
            phrase_ids=sentences[i].phrase_ids,
        )
        for i in range(n)
    ]
