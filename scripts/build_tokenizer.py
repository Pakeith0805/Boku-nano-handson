"""訓練データ（`data/dataset/train.jsonl`）だけを使って、バイト単位BPEトークナイザを学習する。

```
python -m scripts.build_tokenizer
```

**val/testは使わない。** トークナイザ自体が学習データ由来の統計（どの部分文字列が頻出するか）
を語彙に焼き込むため、val/testを混ぜるとトークナイザ自身がリークの経路になる
（「フルスクラッチ学習」の定義③「トークナイザも本課題の訓練データだけから作成する」）。

学習アルゴリズムは自前実装ではなく、Hugging Faceの`tokenizers`ライブラリを使う。BPEの
学習（頻出ペアの逐次併合）は数十万種類の語を相手にすると素朴な実装ではO(語彙数×語数)規模で
遅くなり（実際に手で書いて試したところ、ヒープ最適化を入れても実用時間に収まらなかった）、
Rust実装の`tokenizers`はこれを高速に解く。モデル本体にPyTorch/Transformersの既存部品を
使ってよい、という課題文の方針と同じ扱いにしている（トークナイザの学習アルゴリズムという
「道具」を借りるだけで、学習データそのものは全て本課題のものだけを使う）。

**byte fallback**は`ByteLevel`前処理（バイト単位でパースし、基底アルファベットに256バイト
全部を含める）で実現する。未知の文字が来ても、常に既知のバイトの並びとして表現できる。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from tokenizers import Tokenizer, decoders, pre_tokenizers, trainers
from tokenizers.models import BPE

ROOT = Path(__file__).resolve().parents[1]
TRAIN_IN = ROOT / "data" / "dataset" / "train.jsonl"
OUT = ROOT / "data" / "tokenizer" / "tokenizer.json"

VOCAB_SIZE = 8_192
"""課題文の推奨語彙数。"""

MAX_TOKEN_LENGTH = 16
"""1トークンの最大バイト長。これを小さくすることで、1トークンの大きさが小さくなる"""

SPECIAL_TOKENS: list[str] = [
    "<|pad|>",
    "<|bos|>",
    "<|eos|>",
    "<|task|>",
    "<|code|>",
    "<|explanation|>",
]


def iter_texts(path: Path) -> Iterator[str]:
    """`train.jsonl`から、指示文とコードのテキストだけを取り出す（他のフィールドは学習に使わない）。"""
    with path.open(encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            yield record["instruction_ja"]
            yield record["reference_code"]


def main() -> None:
    tokenizer = Tokenizer(BPE(unk_token=None))
    # unk_token=None: ByteLevel前処理により未知バイトが原理的に発生しないため、
    # 通常のBPEが使う<unk>フォールバックは不要（byte fallbackそのものが代わりを果たす）。
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tokenizer.decoder = decoders.ByteLevel()

    trainer = trainers.BpeTrainer(
        vocab_size=VOCAB_SIZE,
        special_tokens=SPECIAL_TOKENS,
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
        max_token_length=MAX_TOKEN_LENGTH,
        show_progress=True,
    )
    tokenizer.train_from_iterator(iter_texts(TRAIN_IN), trainer=trainer)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tokenizer.save(str(OUT))

    print(f"vocab_size: {tokenizer.get_vocab_size()}")
    print(f"書き出し先: {OUT}")


if __name__ == "__main__":
    main()
