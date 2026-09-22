"""`scripts/train.py`が書いたcheckpoint(.pt)を読み込む共通処理。

`try_generate.py`・`evaluate.py`など、checkpointから`BokuNanoModel`を復元して使うだけの
スクリプトで共有する。checkpoint自体に`model_config`(`ModelConfig`をdictにしたもの)が
入っているため、呼び出し側はアーキテクチャの詳細を知らなくてよい。
"""

from __future__ import annotations

from pathlib import Path

import torch

from model.transformer import BokuNanoModel, ModelConfig


def load_model(checkpoint_path: Path, device: torch.device) -> tuple[BokuNanoModel, int]:
    """checkpointから`BokuNanoModel`を復元する。`(model, step)`を返す。"""
    ckpt = torch.load(checkpoint_path, map_location=device)
    cfg = ModelConfig(**ckpt["model_config"])
    model = BokuNanoModel(cfg).to(device)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    return model, ckpt["step"]
