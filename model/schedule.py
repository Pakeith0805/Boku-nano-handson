"""warmup付きcosine decayの学習率スケジュール。"""

from __future__ import annotations

import math


def lr_at_step(
    step: int, # 今何ステップ目か
    *,
    max_lr: float, # LRのピーク値
    total_steps: int, # 訓練全体のstep数
    warmup_ratio: float, # 全体のうちwarmupに使う割合
    min_lr_ratio: float, # 減衰しきったときの下限を、max_lrの何倍にするか
) -> float:
    """`step`(0始まり)における学習率。

    0..warmup_steps-1は線形warmup(0→`max_lr`)、それ以降は`min_lr_ratio * max_lr`を
    下限にcosineで減衰する(GPT-3方式: 最大値の10%を下限にする。`min_lr_ratio`の
    既定値0.1はこの慣例に合わせた)。
    """
    warmup_steps = max(1, round(total_steps * warmup_ratio))
    min_lr = max_lr * min_lr_ratio

    # warmup。線形に上昇
    if step < warmup_steps:
        return max_lr * (step + 1) / warmup_steps

    # stepがtotalを超えてしまった場合
    if step >= total_steps:
        return min_lr

    # cosine decay。学習曲線の形。前半は高い時間が長く、後半は低い時間が長い。
    progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
    coeff = 0.5 * (1.0 + math.cos(math.pi * progress))
    return min_lr + coeff * (max_lr - min_lr)
