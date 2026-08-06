"""教師モデル（Qwen3-4B-AWQ）の疎通確認。

  1. GPUとcompute capabilityを確認する
  2. モデルを読み込み、1プロンプトだけ生成して日本語が返ることを確認する
  3. 版・量子化方式などを data/teacher/manifest.json に記録する

生成の中身（プロンプト設計・出力のパース）はここでは扱わない。環境の問題とプロンプトの問題を混ぜない。

    uv sync --group teacher
    .venv/bin/python scripts/teacher/check_env.py
"""

from __future__ import annotations

import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
import transformers
from transformers import AutoTokenizer

import gptqmodel
from gptqmodel import BACKEND, GPTQModel

MODEL_ID = "Qwen/Qwen3-4B-AWQ"
# revisionを固定する。mainのままだと上流の更新で黙って別モデルになる。
REVISION = "74d4bd2bd4bff9cafc9345221320bffb08b406a3"
# 既定（AUTO）は AwqMarlinLinear を選び、そのJITビルドが CUDA_HOME（nvcc）を要求して失敗する。
# BACKEND.TORCH はコンパイル不要。24opぶんを1回ずつ流す用途には十分な速度が出る。
BACKEND_NAME = BACKEND.TORCH

EXPECTED_CAPABILITY = (12, 0)  # RTX 5090 = sm_120（Blackwell）

MANIFEST_PATH = Path("data/teacher/manifest.json")

# 疎通確認用。日本語が返るかを見るだけなので中身は何でもよい。
PROBE_PROMPT = "「リストの各要素を2倍にする」を、別の日本語の言い方で1つだけ挙げてください。"
MAX_NEW_TOKENS = 64

GIB = 1024**3


def check_gpu() -> dict:
    """1. GPUとcompute capabilityを確認する。"""
    if not torch.cuda.is_available():
        raise RuntimeError("CUDAが使えない。nvidia-smi でGPUの状態を確認すること。")

    capability = torch.cuda.get_device_capability()
    arch_list = torch.cuda.get_arch_list()
    name = torch.cuda.get_device_name(0)
    free, total = torch.cuda.mem_get_info(0)

    print(f"GPU                : {name}")
    print(f"compute capability : {capability}")
    print(f"torch arch list    : {arch_list}")
    print(f"VRAM               : free {free / GIB:.2f} GiB / total {total / GIB:.2f} GiB")

    if capability != EXPECTED_CAPABILITY:
        raise RuntimeError(
            f"compute capabilityが想定と違う: {capability} != {EXPECTED_CAPABILITY}。"
            "README §0 の前提が変わっていないか確認すること。"
        )
    # torchのビルドがBlackwell非対応だと、読み込みは通っても生成でこける。
    if f"sm_{capability[0]}{capability[1]}" not in arch_list:
        raise RuntimeError(
            f"torchのビルドに sm_{capability[0]}{capability[1]} が無い: {arch_list}。torchを入れ直すこと。"
        )

    return {
        "name": name,
        "compute_capability": list(capability),
        "torch_arch_list": arch_list,
        "vram_total_gib": round(total / GIB, 2),
        "vram_free_before_load_gib": round(free / GIB, 2),
        "driver_version": _driver_version(),
    }


def _driver_version() -> str | None:
    try:
        import subprocess

        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip().splitlines()[0]
    except Exception:
        return None


def load_model() -> tuple[object, object, float, float]:
    """モデルとトークナイザを読み込む。読み込み時間とVRAM実測を返す。"""
    torch.cuda.reset_peak_memory_stats(0)

    started = time.perf_counter()
    model = GPTQModel.load(
        MODEL_ID,
        revision=REVISION,
        backend=BACKEND_NAME,
        device="cuda:0",
    )
    load_seconds = time.perf_counter() - started

    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=REVISION)

    free, total = torch.cuda.mem_get_info(0)
    vram_after_load_gib = (total - free) / GIB

    print(f"読み込み           : {load_seconds:.1f}秒（参考値 2.2秒）")
    print(f"VRAM（読み込み後） : {vram_after_load_gib:.2f} GiB（参考値 2.50 GiB）")

    return model, tokenizer, load_seconds, vram_after_load_gib


def build_prompt(tokenizer, prompt: str) -> str:
    """非thinkingモードのプロンプトを組む。

    enable_thinking=False は、プロンプト側に空の <think>\\n\\n</think> を挿し込む方式。
    全文デコードには <think> という文字列自体は出る（中身が空なだけ）ので、
    「<think>が出た＝失敗」ではない。テンプレートに空ブロックが入っているかで判定する。
    """
    text = tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    assert "<think>\n\n</think>" in text, (
        "空の<think>ブロックがテンプレートに入っていない。"
        "enable_thinking=False が効いていない可能性がある。"
    )
    return text


def generate(model, tokenizer, text: str) -> tuple[str, int, float]:
    """2. 1プロンプトだけ生成する。出力・生成トークン数・生成速度を返す。"""
    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    started = time.perf_counter()
    with torch.inference_mode():
        outputs = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,  # 疎通確認なので再現性優先
        )
    elapsed = time.perf_counter() - started

    generated_ids = outputs[0][inputs["input_ids"].shape[-1] :]
    completion = tokenizer.decode(generated_ids, skip_special_tokens=True)
    n_tokens = int(generated_ids.shape[-1])
    tok_per_sec = n_tokens / elapsed

    print(f"生成速度           : {tok_per_sec:.1f} tok/s（参考値 9.6 tok/s）")
    print(f"出力               : {completion.strip()!r}")

    return completion, n_tokens, tok_per_sec


def assert_japanese(completion: str) -> None:
    """日本語が返っているかのゆるい判定（ひらがな・カタカナが含まれるか）。"""
    has_kana = any(
        "぀" <= ch <= "ゟ" or "゠" <= ch <= "ヿ" for ch in completion
    )
    if not has_kana:
        raise RuntimeError(f"日本語が返っていない: {completion!r}")


def write_manifest(record: dict) -> None:
    """3. 由来の正本を書く。MLflowは索引に過ぎない。"""
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"記録               : {MANIFEST_PATH}")


def main() -> None:
    gpu = check_gpu()

    model, tokenizer, load_seconds, vram_after_load_gib = load_model()
    text = build_prompt(tokenizer, PROBE_PROMPT)
    completion, n_tokens, tok_per_sec = generate(model, tokenizer, text)
    assert_japanese(completion)

    write_manifest(
        {
            "model": {
                "id": MODEL_ID,
                "revision": REVISION,
                "quantization": "AWQ (4bit)",
                "backend": str(BACKEND_NAME),
                "thinking_mode": "disabled (enable_thinking=False)",
            },
            "libraries": {
                "python": platform.python_version(),
                "torch": torch.__version__,
                "transformers": transformers.__version__,
                "gptqmodel": gptqmodel.__version__,
            },
            "gpu": gpu,
            "smoke_test": {
                "prompt": PROBE_PROMPT,
                "completion": completion.strip(),
                "load_seconds": round(load_seconds, 2),
                "vram_after_load_gib": round(vram_after_load_gib, 2),
                "generated_tokens": n_tokens,
                "tokens_per_second": round(tok_per_sec, 2),
            },
            "checked_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "notes": [],  # フォールバックした場合はその判断と理由をここに書く
        }
    )
    print("\n疎通確認OK。")


if __name__ == "__main__":
    main()
