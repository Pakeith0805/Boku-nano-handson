"""生成された言い回しの正規化と、機械的に判定できる棄却。

**このモジュールは意味の正しさを判定しない。** 「`even`の表現として偶数の話をしているか」は
文字列からは分からない。ここが見るのは形式だけ——文型・長さ・使用禁止語・`k`の出現回数・重複。
意味の検査は人間の承認か、後段（生成文→コード→参照インタプリタ照合）の担当である。

`qwen.py`に依存しない（`torch`も`gptqmodel`も import しない）。GPU無しで単体テストできる
ようにするためで、この境界は崩さないこと。

`MIN_LEN`/`MAX_LEN`と終止形の規則は`op_seeds.yaml`の`style`と対になっている。あちらは
モデルへの指示、こちらは検査であり、二重に書いているのは意図的である
（`registry.py`が`uses_k`と`literal_domain`を二重に書いているのと同じ理由——導出すると
検査が常に真になって意味を失う）。片方を変えたらもう片方も直すこと。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Container, Sequence

MIN_LEN = 5
MAX_LEN = 40
"""言い回しの長さ（`{k}`を具体値に展開した状態での文字数）。`op_seeds.yaml`の`style`と対。"""

TERMINAL_KANA = frozenset("うくぐすずつぬふぶむゆる")
"""動詞の終止形の末尾になりうるかな（う段）。

「〜する」だけを見て『る』で判定すると「残**す**」「取り出**す**」「足**す**」が全部落ちる。
う段の集合で見るのが正しい。体言止め（「〜の抽出」）や連用形（「〜して」）はここで落ちる。
"""

POLITE_SUFFIXES = ("です", "ます", "ください", "ましょう", "でしょう")
"""丁寧形の語尾。`style`が求める終止形（普通体）ではないので落とす。

これは文体の統一のためだけでなく、**前置きを落とす罠**として効く。モデルは指示しても
「以下が言い換えです」のような1行を先頭に付けることがあり、これは う段（す）で終わるうえに
かなも含むので、他の検査を素通りしてしまう。
"""

BAD_CHAR = re.compile(r"[A-Za-z{}\[\]()<>=|@#$%^&*_\\/+~`;]")
"""日本語の言い回しに出てはいけない文字。

ラテン文字を一律で弾くのが効く。これ1つで `xs` `lambda` `def` `return` といったコード片も、
英語のop名をそのまま書いた行も、英語で答えてしまった行もまとめて落ちる。
`-`（マイナス）と`×``÷`は除外していない——「-1を掛ける」「×2する」は日本語として通るため。
"""

KANA = re.compile(r"[ぁ-ゟ゠-ヿ]")
DIGIT_RUN = re.compile(r"\d+")

_LEADING_MARKER = re.compile(r"^\s*(?:[-*・‐–—]+|\d+[.)．、:：]|[（(]\d+[）)])\s*")
_TRAILING_PAREN = re.compile(r"[（(][^（()）]*[）)]\s*$")
_EDGE_PUNCT = "。．.、,・:：;；!！?？ \t"
_QUOTE_CHARS = "「」『』\"'“”‘’【】〈〉《》"


def normalize(line: str, literal: str) -> str:
    """1行を比較・検査できる形に均す。

    モデルは指示しても箇条書きの記号や番号、鉤括弧、末尾の句点、補足の括弧書きを付けてくる。
    それらは言い回しの違いではないので、ここで落としてから重複判定にかける。落とさないと
    「偶数だけを残す」と「- 偶数だけを残す。」が別物として2件に数えられてしまう。

    `{k}`をそのまま書いてきた行は`literal`に展開する。プロンプトは具体値で書けと指示するが、
    例示から`{k}`を写してくることがあり、以降の検査を1本に保つためここで形を揃える。
    """
    s = unicodedata.normalize("NFKC", line)
    s = s.replace("{k}", literal)
    s = _LEADING_MARKER.sub("", s, count=1)
    # 括弧書きを落とすと新しい末尾が出てくる（「…残す」。→ …残す」）ので、括弧書きの
    # 除去を挟んで前後2回削る。1回だけだと鉤括弧と句点が同時に付いた行を均せない。
    s = s.strip(_EDGE_PUNCT + _QUOTE_CHARS)
    s = _TRAILING_PAREN.sub("", s)
    s = s.strip(_EDGE_PUNCT + _QUOTE_CHARS)
    s = re.sub(r"\s+", "", s)
    return s


def to_placeholder(phrase: str, literal: str) -> str:
    """具体値で書かれた言い回しを`{k}`版に戻す。

    数字の並びが`literal`と**完全に一致する**ものだけを置き換える。単純な文字列置換だと
    「17より大きい」が「1{k}より大きい」になる。`check`が`k_missing`/`k_multiple`で
    そういう行を先に落としているが、ここでも桁単位で見て二重に守る。
    """
    return DIGIT_RUN.sub(lambda m: "{k}" if m.group() == literal else m.group(), phrase)


def _literal_count(phrase: str, literal: str) -> int:
    """`literal`とちょうど一致する数字の並びが何個あるか。"""
    return sum(1 for m in DIGIT_RUN.finditer(phrase) if m.group() == literal)


def check(
    phrase: str,
    *,
    uses_k: bool,
    literal: str,
    forbid: Sequence[str],
    seen: Container[str],
) -> str | None:
    """`normalize`済みの言い回しを検査する。通れば`None`、弾くなら理由の文字列を返す。

    理由は`data/teacher/phrases_raw.jsonl`にそのまま記録して集計する。どの規則がどれだけ
    効いたかが分かれば、プロンプトのどこを直すべきかも分かる（棄却が`forbidden:*`に偏るなら
    禁止語の指示が伝わっていない、`not_terminal_form`に偏るなら文型の指示が弱い、など）。
    棄却された行も捨てずに残すのはそのためである。
    """
    if not phrase:
        return "empty"
    if len(phrase) < MIN_LEN:
        return "too_short"
    if len(phrase) > MAX_LEN:
        return "too_long"
    if BAD_CHAR.search(phrase):
        return "bad_char"
    if not KANA.search(phrase):
        return "no_kana"
    if phrase.endswith(POLITE_SUFFIXES):
        return "polite_form"
    if phrase[-1] not in TERMINAL_KANA:
        return "not_terminal_form"

    n_literal = _literal_count(phrase, literal)
    if uses_k:
        if n_literal == 0:
            return "k_missing"
        if n_literal > 1:
            return "k_multiple"
    elif n_literal > 0:
        # k を取らないopなのに検査用リテラルが出た。`double`が「7倍する」と言うような
        # 取り違えなので落とす。この値が日常的な数として紛れ込みにくいことが
        # `op_seeds.yaml`で 7 を選んだ理由でもある。
        return "unexpected_literal"

    for word in forbid:
        if word in phrase:
            return f"forbidden:{word}"

    if phrase in seen:
        return "duplicate"

    return None
