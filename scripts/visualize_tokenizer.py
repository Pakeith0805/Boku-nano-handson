"""学習済みトークナイザ（`data/tokenizer/tokenizer.json`）を、人が読める形のJSONにする。

```
python -m scripts.visualize_tokenizer
```

`tokenizer.json`自体はモデルが読む内部形式で、`ByteLevel`前処理によりUTF-8の1バイトずつを
印字可能などこかの文字に置き換えて保存している（`ãĤĴ`が「を」の3バイトを表す、など）。
これは正しい仕組みだが人間が目で見て確認するには向かないため、**可視化専用**に、
`decoders.ByteLevel`で元のテキストへ戻したものを添えて別ファイルへ書き出す。

学習やモデルはこのファイルを読まない——あくまで人が中身を確認するための副産物であり、
`tokenizer.json`と二重管理にならないよう、情報源は常に`tokenizer.json`側に置く。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tokenizers import Tokenizer, decoders

from scripts.build_tokenizer import SPECIAL_TOKENS

ROOT = Path(__file__).resolve().parents[1]
TOKENIZER_IN = ROOT / "data" / "tokenizer" / "tokenizer.json"
OUT = ROOT / "data" / "tokenizer" / "tokenizer_visualization.json"


def _readable(decoder: decoders.ByteLevel, raw: str) -> str:
    """`ByteLevel`表記の1トークンを、元のテキストへ戻す。

    不完全なバイト列（マージ途中で、多バイト文字の一部だけを表すトークン）は正しい文字に
    ならないことがあるが、`ByteLevel`デコーダは`�`（U+FFFD）で埋めて壊れずに返す。
    """
    return decoder.decode([raw])


def main() -> None:
    tokenizer = Tokenizer.from_file(str(TOKENIZER_IN))
    decoder = decoders.ByteLevel()

    vocab = tokenizer.get_vocab()  # {token文字列: id}
    special = set(SPECIAL_TOKENS)
    tokens: list[dict[str, Any]] = []
    for raw, token_id in sorted(vocab.items(), key=lambda kv: kv[1]):
        is_special = raw in special
        tokens.append({
            "id": token_id,
            "raw": raw,
            "text": raw if is_special else _readable(decoder, raw),
            "is_special": is_special,
        })

    model = json.loads(TOKENIZER_IN.read_text(encoding="utf-8"))["model"]
    merges = []
    for left, right in model.get("merges", []):
        merges.append({
            "left": _readable(decoder, left),
            "right": _readable(decoder, right),
            "result": _readable(decoder, left + right),
        })

    payload = {
        "vocab_size": tokenizer.get_vocab_size(),
        "tokens": tokens,
        "merges": merges,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"トークン {len(tokens):,}件・マージ {len(merges):,}件")
    print(f"書き出し先: {OUT}")


if __name__ == "__main__":
    main()
