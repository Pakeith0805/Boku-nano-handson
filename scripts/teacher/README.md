# scripts/teacher/ — 教師モデル（Qwen）環境構築の手順

教師モデルの役目は**日本語表現を増やすことだけ**（`document_EXPAND.md §2.7`）。正解の意味構造・
コードはルールベースで作る（`src/`）。教師にコードや正解を書かせない。

この手順は`/home/s6323004/Boku-nano`（同じマシン）で2026-08-05に検証済みの構成をそのまま
なぞる。試行錯誤済みなので、ここに書いた通りにやれば一発で通るはず。**うまくいかない場合は
「環境の再現に失敗している」ということなので、下の「詰まりやすい点」を先に疑うこと。**

## 0. 前提（このマシンで確認済み・2026-08-05時点）

| | |
| --- | --- |
| GPU | NVIDIA GeForce RTX 5090 |
| VRAM | 32,607 MiB |
| ドライバ | 595.84 |
| compute capability | **12.0（sm_120、Blackwell）** |

`nvidia-smi`で変わっていないか確認しておく。

```bash
nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version --format=csv
```

**GPUは共有されている可能性がある。** 空きVRAMが少なければ他プロセスが使っている。
Qwen3-4B-AWQは読み込み後で約2.5GiBしか使わないので、通常は問題にならない。

## 1. Pythonのバージョンを固定する

このリポジトリの`.venv`は現状Python 3.13系でできているが、**3.13系だとビルド時に
`Python.h`（開発ヘッダ）が無くてTritonのランタイムコンパイルが落ちる**（主プロジェクトで
実際に踏んだ問題。AWQ/bf16どちらでも起きる、Pythonのバージョンの問題であってモデルの問題ではない）。

`.python-version`を`3.12.13`に固定済み（このマシンには既に`uv python install`で入っている）。
`uv sync`すると自動的にこのバージョンで`.venv`が作り直される。

## 2. 依存関係を入れる

```bash
uv sync --group teacher
```

`pyproject.toml`の`teacher`グループ（`torch` `transformers` `accelerate` `huggingface-hub`
`gptqmodel` `torchvision`）が入る。**これは巨大な依存なので既定では入れない。**
`src/`や他の`scripts/`には絶対にこの依存を持ち込まないこと
（教師モデルを触るコードは`scripts/teacher/`の中に閉じる）。

## 3. 疎通確認スクリプトを書いて実行する

自分で`scripts/teacher/check_env.py`を書く。やることは3つ。

1. GPUとcompute capabilityを確認する（`torch.cuda.get_device_capability()`が`(12, 0)`）
2. `Qwen/Qwen3-4B-AWQ`を読み込み、1プロンプトだけ生成して日本語が返ることを確認する
3. 版・量子化方式などを`data/teacher/manifest.json`に記録する

**このスクリプトは一度通したら消してよい**（実際に消してある）。役目は「その時点の環境が
条件を満たしていたことを確かめて記録に残す」ことであり、成果物は残った
`data/teacher/manifest.json`のほうだからである。環境を疑う事態になったら、この手順に
沿って書き直して流し直すこと。読み込み方そのものは`scripts/teacher/qwen.py`に残っている。

### 3-1. モデルの読み込み方（詰まりやすい点を先に潰す）

**`autoawq`は使わない。** 0.2.9で更新が止まっていて（Blackwell以前のGPU向け）、
`transformers`5.x系はAWQの読み込みに`gptqmodel`を要求する。

**バックエンドは`BACKEND.TORCH`を明示する。** `gptqmodel`の既定（自動選択）は
`AwqMarlinLinear`を選ぶが、そのJITビルドが`CUDA_HOME`（nvcc）を要求して失敗する
（このマシンにCUDA toolkitは入っていない）。`BACKEND.TORCH`はコンパイル不要で、
「24opぶんのプロンプトを1回ずつ流す」程度の用途には十分な速度が出る。

```python
from gptqmodel import BACKEND, GPTQModel

model = GPTQModel.load(
    "Qwen/Qwen3-4B-AWQ",
    revision="74d4bd2bd4bff9cafc9345221320bffb08b406a3",  # revisionを固定する。mainのままだと上流の更新で黙って別モデルになる
    backend=BACKEND.TORCH,
    device="cuda:0",
)
```

### 3-2. 非thinkingモードの指定

`enable_thinking=False`は、プロンプト側に空の`<think>\n\n</think>`を挿し込む方式。
**全文デコードには`<think>`という文字列自体は出る**（中身が空なだけ）。
「`<think>`が出た＝失敗」ではないので注意。テンプレートに空ブロックが入っているかで判定する。

```python
text = tokenizer.apply_chat_template(
    [{"role": "user", "content": prompt}],
    tokenize=False,
    add_generation_prompt=True,
    enable_thinking=False,
)
assert "<think>\n\n</think>" in text
```

### 3-3. 記録する項目

`data/teacher/manifest.json`に、モデル名・revision・量子化方式・推論ライブラリの版・
GPU情報・疎通確認の実測値（読み込み時間・生成速度・VRAM）・確認日時を書く。
**由来の正本はこのファイル**（MLflowは索引に過ぎない）。

参考までに、主プロジェクトでの実測値（同じGPU・同じモデル）：

| | 値 |
| --- | --- |
| 読み込み | 2.2秒 |
| VRAM（読み込み後） | 2.50 GiB |
| 生成速度 | 9.6 tok/s |

大きくズレる場合は構成が違う（バックエンドが`BACKEND.TORCH`になっていない等）を疑うこと。

## 4. ここまで通ったら次へ

環境構築（このドキュメントの範囲）と、実際の日本語表現生成（プロンプト設計・出力のパース・
承認フロー）は**別の作業として分ける**。理由は「失敗の種類が違う」から——環境の問題
（GPUが認識されない等）とプロンプトの問題（変な表現が出る等）を混ぜると、どちらが原因か
切り分けにくくなる。疎通確認（このドキュメントの3.）が通ってから、生成スクリプトに進むこと。

現状の分担は次のとおり。駆動スクリプトだけが`scripts/`直下にあり（他の`build_*.py`と
揃えるため）、教師モデルに触るコードはこのディレクトリに閉じたままである。

| ファイル | 役割 | 依存 |
| --- | --- | --- |
| `scripts/build_phrases.py` | 駆動。24opぶんの言い回しを生成して記録する | teacher（`--dry-run`は不要） |
| `scripts/teacher/qwen.py` | モデルの読み込み・プロンプト組み立て・生成 | teacher |
| `scripts/teacher/op_seeds.yaml` | 24opの意味・正例・禁止語（**人間が書く資産**） | — |
| `scripts/teacher/phrase_filters.py` | 出力の正規化と機械的な棄却 | 標準ライブラリのみ |

## トラブルシューティング早見表

| 症状 | 原因 | 対処 |
| --- | --- | --- |
| Tritonのビルドで`Python.h`が無いと落ちる | venvが3.13系（開発ヘッダ無し） | `.python-version`を3.12.13に固定し`uv sync`し直す |
| `AwqMarlinLinear`のビルドが`CUDA_HOME`要求で失敗 | `gptqmodel`の既定バックエンド | `BACKEND.TORCH`を明示する |
| `torch.cuda.get_arch_list()`に`sm_120`が無い | torchのビルドがBlackwell非対応 | torchを入れ直す（`pyproject.toml`の`torch>=2.9`で足りるはずだが、念のため確認） |
| CUDAが使えない / VRAM不足 | 他プロセスと共有中、または未起動 | `nvidia-smi`で空きを確認。学習（Phase 3相当）と同時に走らせない |
| AWQがどうしても動かない | 稀にあり得る | `Qwen/Qwen3-4B`（bf16）にフォールバックしてよい。ただしその判断と理由を`manifest.json`に明記する。VRAMは29GB空いているのでbf16でも動く |
