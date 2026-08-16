"""教師モデル（Qwen3-4B-AWQ）を呼ぶための最小の層。

疎通確認で通った構成——revision固定・バックエンド固定・非thinkingモード——をそのまま関数に
しただけのものである。**プロンプトの中身も出力のパースもここでは扱わない。**
それは`scripts/build_phrases.py`の担当である。`scripts/teacher/README.md` §4 が言う
「環境の問題とプロンプトの問題を混ぜない」を、モジュールの境界としても引いておく。

このモジュールを import すると `torch` と `gptqmodel` が要る（`uv sync --group teacher`）。
教師モデルに触るコードはこのファイルだけに閉じる。`phrase_filters.py`がここに依存して
いないのは、フィルタをGPU無しでテストできるようにするためであり、`build_phrases.py`が
`qwen`の import を関数の中まで遅らせているのは`--dry-run`を`torch`無しで動かすためである。

以下5定数が、実際に使うモデルを決める唯一の場所である。`provenance()`がここから読んで
生成物に焼き付けるので、記録と食い違う余地はない（以前は`data/teacher/manifest.json`に
別途書いていたが、実行ごとの記録に一本化した）。変えたら疎通確認からやり直すこと。
"""

from __future__ import annotations

import time

import torch
from transformers import AutoTokenizer

from gptqmodel import BACKEND, GPTQModel

MODEL_ID = "Qwen/Qwen3-4B-AWQ"
REVISION = "74d4bd2bd4bff9cafc9345221320bffb08b406a3"
BACKEND_NAME = BACKEND.AWQ_GEMM_TRITON
"""AWQの行列積カーネル。**バックエンドの選択は速度を5.6倍変える。**

同じマシンでの実測（4B-AWQ、128トークン生成、貪欲法）:

| バックエンド | 生成速度 | 備考 |
| --- | ---: | --- |
| `TORCH` | 11.2 tok/s | 素朴な逆量子化。コンパイル不要だが遅い |
| `AWQ_GEMM_TRITON` | **62.9 tok/s** | TritonのJIT。nvcc不要 |
| `AWQ_GEMM` / `AWQ_MARLIN` | — | `CUDA_HOME`（nvcc）を要求して失敗 |
| `AWQ_TORCH_FUSED` | — | CUDAデバイス非対応 |

当初`TORCH`にしていたのは、`.venv`がPython 3.13系でTritonのランタイムコンパイルが
`Python.h`（開発ヘッダ）を見つけられず落ちたためである。**その前提はもう成り立たない**——
`.python-version`を3.12.13に固定した時点でヘッダは揃っており、Tritonは正常にビルドできる。

nvcc を要求する系（`AWQ_GEMM`・`AWQ_MARLIN`）はこのマシンにCUDA toolkitが無いので使えない。
入れればさらに速くなる可能性はあるが、Tritonで十分な速度が出ているので追っていない。
"""

QUANTIZATION = "AWQ (4bit)"
ENABLE_THINKING = False
"""thinkingモードを使うか。生成物の由来に記録するので、切り替えたら記録も自動で変わる。"""


def provenance() -> dict:
    """生成物に焼き付ける「何で作ったか」。

    モデルの同一性（名前・revision・量子化・バックエンド・thinkingの有無）と、推論スタックの
    版をここでまとめて返す。**呼び出し時点の実測値**であり、別の日に書いた記録の写しではない。
    生成のたびにこれを記録しないと、ライブラリが更新されても生成物は何も知らないままになる。
    """
    import platform

    import transformers

    import gptqmodel

    gpu = {}
    if torch.cuda.is_available():
        gpu = {
            "name": torch.cuda.get_device_name(0),
            "compute_capability": list(torch.cuda.get_device_capability()),
        }

    return {
        "model": {
            "id": MODEL_ID,
            "revision": REVISION,
            "quantization": QUANTIZATION,
            "backend": str(BACKEND_NAME),
            "thinking_mode": "enabled" if ENABLE_THINKING else "disabled",
        },
        "libraries": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "gptqmodel": gptqmodel.__version__,
        },
        "gpu": gpu,
    }


def load() -> tuple[object, object]:
    """モデルとトークナイザを読み込む（実測：約2.2秒、VRAM約2.50GiB）。

    GPUやcompute capabilityの検査はしない。疎通確認で一度通した環境であることを前提にする
    （`scripts/teacher/README.md`の手順）。読み込みや生成が落ちるようになったら、直近の
    `data/teacher/phrases_runs.jsonl`の`libraries`・`gpu`と`nvidia-smi`を突き合わせること。
    """
    model = GPTQModel.load(
        MODEL_ID,
        revision=REVISION,
        backend=BACKEND_NAME,
        device="cuda:0",
    )
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=REVISION)
    return model, tokenizer


def build_prompt(tokenizer, user: str, system: str | None = None) -> str:
    """非thinkingモードのプロンプト文字列を組む。

    `enable_thinking=False`はプロンプト側に空の `<think>\\n\\n</think>` を挿し込む方式なので、
    全文デコードには `<think>` という文字列自体が出る（中身が空なだけ）。
    「`<think>`が出た＝失敗」ではない。効いているかはテンプレート側の空ブロックで判定する。
    """
    messages = []
    if system is not None:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})

    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=ENABLE_THINKING,
    )
    if not ENABLE_THINKING:
        assert "<think>\n\n</think>" in text, (
            "空の<think>ブロックがテンプレートに入っていない。"
            "enable_thinking=False が効いていない可能性がある。"
        )
    return text


def generate(
    model,
    tokenizer,
    text: str,
    *,
    max_new_tokens: int,
    seed: int,
    temperature: float | None = None,
    top_p: float = 0.95,
) -> tuple[str, int, float]:
    """1プロンプト生成する。出力・生成トークン数・所要秒数を返す。

    `temperature=None` で貪欲法（`do_sample=False`）になる。言い回しを増やす用途では
    貪欲法は使えない——同じプロンプトを何度流しても毎回まったく同じ出力になるためである
    （疎通確認が`do_sample=False`だったのは再現性が欲しかったからで、用途が違う）。

    `seed`は必ず受け取る。サンプリングを使う以上、何を種にしたかを記録しないと
    生成物を再現できない。呼び出し側が省略できないよう、既定値を置かずキーワード必須にしてある。
    """
    torch.manual_seed(seed)

    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    if temperature is None:
        sampling = {"do_sample": False}
    else:
        sampling = {"do_sample": True, "temperature": temperature, "top_p": top_p}

    started = time.perf_counter()
    with torch.inference_mode():
        outputs = model.generate(**inputs, max_new_tokens=max_new_tokens, **sampling)
    elapsed = time.perf_counter() - started

    generated_ids = outputs[0][inputs["input_ids"].shape[-1] :]
    completion = tokenizer.decode(generated_ids, skip_special_tokens=True)

    return completion, int(generated_ids.shape[-1]), elapsed
