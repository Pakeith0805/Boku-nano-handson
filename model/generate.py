"""貪欲デコード(temperature=0)による生成。訓練中の定期評価用。"""

from __future__ import annotations

import time

import torch

from model.transformer import BokuNanoModel

# この関数は改善の余地あり。読みづらめ
@torch.no_grad()
def batch_greedy_generate(
    model: BokuNanoModel, # Transformer本体
    prompts: list[list[int]], # プロンプトのバッチ。トークンidの列のリストのリスト。
    *, # これ以降はキーワード引数専用にする。つまり、名前を指定して渡さなければならない。
    eos_id: int,
    pad_id: int,
    metrics: dict[str, float | int] | None = None,
    max_new_tokens: int, # 最大何トークンまで生成し続けるか
) -> list[list[int]]:
    """返り値のshapeは(batch, seq_len)。プロンプトの数だけの、プロンプトのトークンから生成されたトークンまでの一件分が入る。
    
    複数プロンプトに対し、temperature=0で生成する。モデルの性能評価用。

    プロンプトの長さが揃っていないので、短い方の先頭を`pad_id`で埋める(left padding)。

    ある行が`eos_id`を出した後は、以降その行にはモデルの予測を使わず`pad_id`で埋める。
    """
    device = next(model.parameters()).device # モデルが扱っているデバイス
    if metrics is not None:
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        started = time.perf_counter()
    max_len = model.cfg.max_seq_len # モデルが扱える最大系列長
    # 一番長いプロンプトに合わせる
    prompt_width = max(len(p) for p in prompts)
    batch = len(prompts)

    # 短いプロンプトは先頭側をpad_idで埋める。
    ids = torch.full((batch, prompt_width), pad_id, dtype=torch.long, device=device)
    # 先頭側を0で埋める
    attention_mask = torch.zeros((batch, prompt_width), dtype=torch.long, device=device)
    for i, prompt in enumerate(prompts):
        ids[i, prompt_width - len(prompt) :] = torch.tensor(prompt, dtype=torch.long, device=device)
        attention_mask[i, prompt_width - len(prompt) :] = 1

    # max_new_tokens=呼び出し側が生成したい最大トークン数
    # max_len - prompt_width=モデルに追加で入れられる残りトークン
    budget = max(0, min(max_new_tokens, max_len - prompt_width))
    # 各行が既に0を出したかどうかをおうための変数finished。初期値は0。
    finished = torch.zeros(batch, dtype=torch.bool, device=device)

    was_training = model.training
    model.eval()
    try:
        for _ in range(budget):
            # -1しているのは、0番目が最初だから。
            position_ids = (attention_mask.cumsum(dim=-1) - 1).clamp(min=0)
            logits = model(ids, attention_mask=attention_mask, position_ids=position_ids)
            # logitsの形は(batch, seq_len, vocab_size)。
            next_ids = logits[:, -1, :].argmax(dim=-1)

            # finished、was_finishedは、終わっているかどうかの真偽値を要素に持つテンソル。1次元でサイズはbatch
            was_finished = finished
            # 終了済みの行はそれ以上出力しない
            # 形がnext_idsと同じで、全てpad_idで満たしたテンソルを作る
            # pad_bector
            pad_vector = torch.full_like(next_ids, pad_id)
            # next_idsのうち、終了していないものだけnext_idsを予測
            next_ids = torch.where(was_finished, pad_vector, next_ids)
            finished = was_finished | (next_ids == eos_id)

            # idsの末尾に、next_idsを連結した。
            ids = torch.cat([ids, next_ids.unsqueeze(1)], dim=1)
            # 今回追加した列は、直前まで未終了だった行だけ「本物」(1)。既に終了した行は
            # pad_idを積んだだけなので0(=以降そのpad位置を自分自身のattentionでも見せない)。
            # 途中まで未終了だった行だけ1で扱う
            attention_mask = torch.cat(
                [attention_mask, (~was_finished).long().unsqueeze(1)], dim=1
            )

            if bool(finished.all()):
                break
    finally:
        # trainの状態を呼び出し前に戻す。train中ならtrain中に戻る。
        model.train(was_training)

    # idsをtensorからlistに直し、出力。
    rows = ids.tolist()
    if metrics is not None:
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        seconds = time.perf_counter() - started
        # EOSは生成トークンとして数え、その後の埋め草padは数えない。
        count = 0
        for row in rows:
            tail = row[prompt_width:]
            count += tail.index(eos_id) + 1 if eos_id in tail else len(tail)
        metrics["generation_seconds"] = metrics.get("generation_seconds", 0.0) + seconds
        metrics["generated_tokens"] = metrics.get("generated_tokens", 0) + count
        metrics["generation_tokens_per_second"] = (
            metrics["generated_tokens"] / metrics["generation_seconds"]
            if metrics["generation_seconds"] else 0.0
        )
    return rows


@torch.no_grad()
def greedy_generate(
    model: BokuNanoModel,
    prompt_ids: list[int],
    *,
    eos_id: int,
    pad_id: int,
    max_new_tokens: int,
) -> list[int]:
    """1件だけ貪欲デコードする(`batch_greedy_generate`をbatch=1で呼ぶ薄いラッパー)。"""
    return batch_greedy_generate(
        model, [prompt_ids], eos_id=eos_id, pad_id=pad_id, max_new_tokens=max_new_tokens
    )[0]
