"""Boku-nano本体の訓練ループ。

```
python -m scripts.train
python -m scripts.train train.target_real_tokens=100_000_000
```

対象は`model.transformer.BokuNanoModel`。データは`data/dataset/{train,val}.jsonl`を
`model.data`で1レコード=1系列にし、ミニバッチ単位で`<|pad|>`右詰め+`attention_mask`
付きでモデルに渡す。instruction部分を損失から除いたcompletion-only lossで学習する。

学習量`total_steps`はパディングの`<|pad|>`を除いた「実トークン」予算
(`train.target_real_tokens`)から決める。1 stepあたりの実トークン数/パディング込み
トークン数はどちらも起動時に表示し、累計も逐次ログする。

数値形式はBF16。マスター重みはfp32のまま保ち、順伝播(logitsを出す行列積)だけを
`torch.autocast`でbf16にする。損失のクロスエントロピーはlogitsを`.float()`でfp32に
戻してから計算する(log_softmaxはbf16だと丸めに弱いため。autocastブロックの外に置いて
あるのもこの理由)。小さいモデルでも重み全体をbf16化すると更新量が丸め落ちしやすいため、
より安定するこちらを既定にした。

生成評価は文字列一致ではなく`src.verify`(生成データセット自身の検証と同じ経路)で
実行して参照コードと結果が一致したらpass
"""

from __future__ import annotations

import hashlib
import random
import time
from pathlib import Path
from typing import Any
from unittest import result

import hydra
import mlflow
import torch
import torch.nn.functional as F
from omegaconf import DictConfig
from tokenizers import Tokenizer

from model.data import (
    SpecialIds,
    encode_record,
    iter_padded_records,
    load_records,
    load_special_ids,
)
from model.generate import batch_greedy_generate
from model.schedule import lr_at_step
from model.transformer import BokuNanoModel, ModelConfig
from src.probes.behavior_probes import load_probe_set
from src.verify import safety, sandbox

Record = tuple[list[int], list[int]]  # (トークン列, loss_mask)。パディング前なので長さは可変。


def _build_model_config(cfg: DictConfig) -> ModelConfig:
    return ModelConfig(
        vocab_size=cfg.model.vocab_size,
        max_seq_len=cfg.model.max_seq_len,
        d_model=cfg.model.d_model,
        n_layers=cfg.model.n_layers,
        n_heads=cfg.model.n_heads,
        n_kv_heads=cfg.model.n_kv_heads,
        head_dim=cfg.model.head_dim,
        d_ff=cfg.model.d_ff,
        rope_theta=cfg.model.rope_theta,
        rms_norm_eps=cfg.model.rms_norm_eps,
    )


def _make_batch(
    records: list[Record], pad_id: int, max_seq_len: int, device: torch.device
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """可変長レコード群を`max_seq_len`まで`<|pad|>`で右詰めし、3つのテンソルにする。

    - `input_ids` (long): pad位置は`pad_id`。
    - `loss_mask` (float): 1=損失を数える位置(code本文〜eos)、pad位置は0。
    - `attention_mask` (long): 1=実トークン / 0=pad。右パディングなので実トークンは
      位置0から並び、`position_ids`は不要(`BokuNanoModel.forward`のデフォルト
      `arange`が実トークンに対して正しい)。
    """
    # バッチの行数
    n = len(records)
    # 3つの(n, max_seq_len)の空の器を先に作る。
    input_ids = torch.full((n, max_seq_len), pad_id, dtype=torch.long, device=device)
    loss_mask = torch.zeros((n, max_seq_len), dtype=torch.float32, device=device)
    attention_mask = torch.zeros((n, max_seq_len), dtype=torch.long, device=device)
    # enumerateは、リスト回しつつ番号ももらえる。
    for i, (tokens, mask) in enumerate(records):
        length = len(tokens)
        # i行目、先頭length列。トークン列の長さだけ確保
        input_ids[i, :length] = torch.tensor(tokens, dtype=torch.long, device=device)
        loss_mask[i, :length] = torch.tensor(mask, dtype=torch.float32, device=device)
        # 実トークンがあるところだけを1に
        attention_mask[i, :length] = 1
    return input_ids, loss_mask, attention_mask


def _compute_loss(
    model: BokuNanoModel,
    tokens: torch.Tensor, # (B, L)。処理対象のトークン
    loss_mask: torch.Tensor, # (B, L)。学習対象以外にマスク。1が学習対象
    attention_mask: torch.Tensor, # (B, L)。実トークンの位置に1、pad位置に0。
) -> torch.Tensor:
    """`loss_mask`が1の位置(code本文〜eos)だけ計算に入れ、cross entropyを返す関数。"""
    # B: バッチ件数、L: パディング込みの系列長、V: 語彙数。
    device_type = "cuda" if tokens.is_cuda else "cpu"  # str（テンソルではない）
    with torch.autocast(device_type=device_type, dtype=torch.bfloat16): # 学習対象以外の精度をちょっと下げる
        # tokens[:, :-1] と attention_mask[:, :-1]: どちらも (B, L-1)。
        # tokensとattention maskの最後の位置を除外。tokensとattention maskは問題側だから。
        logits = model(tokens[:, :-1], attention_mask=attention_mask[:, :-1])  # (B, L-1, V)。各位置について、語彙すべての候補のスコア
    targets = tokens[:, 1:]  # (B, L-1)。targetの最初のトークンを除外。最初のトークンは<code>であり、予測できないから。
    target_mask = loss_mask[:, :-1]  # (B, L-1)。loss_maskはその位置を入力したとき、次のトークンの予測損失を数えるかを表す。

    # logits.transpose(1, 2).float(): (B, V, L-1)。cross entropyを計算。
    # reduction=none: 損失を平均せず、各位置の損失を返す。なぜ平均しないかというと、maskをかけてから平均する必要があるため。
    loss_per_token = F.cross_entropy(logits.transpose(1, 2).float(), targets, reduction="none")  # (B, L-1)
    denom = target_mask.sum().clamp(min=1.0)  # ()（0次元のスカラーTensor）
    return (loss_per_token * target_mask).sum() / denom  # 積: (B, L-1)、返り値: ()


@torch.no_grad()
def _eval_loss(
    model: BokuNanoModel,
    val_iter,
    n_batches: int,
    batch_size: int,
    pad_id: int,
    max_seq_len: int,
    device: torch.device,
) -> float:
    """バッチ内の損失を平均して返す関数。"""
    total = 0.0
    for _ in range(n_batches):
        # records: 評価用データ。バッチサイズ分取り出す。
        records = [next(val_iter) for _ in range(batch_size)]
        tokens, loss_mask, attention_mask = _make_batch(records, pad_id, max_seq_len, device)
        total += float(_compute_loss(model, tokens, loss_mask, attention_mask))
    return total / n_batches


@torch.no_grad()
def _eval_generation(
    model: BokuNanoModel,
    val_records: list[tuple[str, str]],
    tokenizer: Tokenizer,
    ids: SpecialIds,
    probes,
    cfg: DictConfig,
) -> dict[str, Any]:
    """モデルの性能を評価するための関数。実際にプロンプトを与え、どれだけ正解したかと、生成結果の例を出力する。"""
    rng = random.Random(cfg.seed)
    # sampleには評価用データの一部が入る。
    # ("日本語指示文", "正解コード")という形式。
    sample = rng.sample(val_records, min(cfg.eval.generation.n_samples, len(val_records)))

    # 日本語指示文だけ取り出す。
    encoded = tokenizer.encode_batch([instruction for instruction, _ in sample])
    # promptsはcode本文以外をtoken idの文字列にしてリストにしたもの。
    prompts = [[ids.bos, ids.task, *enc.ids, ids.code] for enc in encoded]
    prompt_width = max(len(p) for p in prompts)
    # rowsにはprompt, 生成結果や特殊トークン、pad idが入っている。rowsはrowのリスト
    rows = batch_greedy_generate(
        model,
        prompts,
        eos_id=ids.eos,
        pad_id=ids.pad,
        max_new_tokens=cfg.eval.generation.max_new_tokens,
    )

    passed = 0
    examples: list[tuple[str, str, bool]] = []
    # zipで、sampleの0番目の要素とrowsの0番目の要素を同時に取り出し、タプルとしている。
    for (instruction, reference_code), row in zip(sample, rows):
        # gen_codeには生成されたコード本文だけが入る。
        gen_code = tokenizer.decode(row[prompt_width:], skip_special_tokens=True)

        # 安全性チェック。大丈夫ならNoneが入るし、だめならその理由が入る。
        check_result = safety.check(gen_code)
        # 大丈夫ならtrue、だめならfalse。
        ok = check_result is None
        # コードが安全な場合のみコードを実行してみる。
        # 実行結果が参照コードと同じだった場合のみ合格。
        if ok:
            for xs, k in probes:
                try:
                    expected = sandbox.execute(reference_code, xs, k)
                    got = sandbox.execute(gen_code, xs, k)
                except Exception:
                    ok = False
                    break
                if got != expected:
                    ok = False
                    break
        passed += int(ok)
        examples.append((instruction, gen_code, ok))

    # 返り値は、生成結果の合格率と、その例。
    return {"pass_rate": passed / len(sample), "examples": examples}

# hydraの読み込み
@hydra.main(config_path="../conf", config_name="train", version_base=None)
def main(cfg: DictConfig) -> None:
    root = Path(hydra.utils.get_original_cwd())
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {device}")

    torch.manual_seed(cfg.seed)

    tokenizer_path = root / cfg.paths.tokenizer
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    # idsは特殊トークンのidのリスト
    ids = load_special_ids(tokenizer)
    # どのtokenizerで学習したかをrunに焼き込む。パスは同じ`tokenizer.json`のまま
    # 中身だけ差し替わる運用（v1→v2）なので、ファイル内容のハッシュで版を区別できるようにする。
    tokenizer_sha256 = hashlib.sha256(tokenizer_path.read_bytes()).hexdigest()

    train_records = load_records(root / cfg.paths.train_in)
    val_records = load_records(root / cfg.paths.val_in)
    probes = load_probe_set(root / cfg.paths.probes)
    print(f"train records: {len(train_records):,} / val records: {len(val_records):,}")

    model_cfg = _build_model_config(cfg)
    model = BokuNanoModel(model_cfg).to(device)
    print(f"パラメータ数: {model.num_parameters():,}")

    global_batch_sequences = int(cfg.train.global_batch_sequences)
    """この数のレコードの勾配の平均をとり、その方向に更新する。バッチサイズ。"""

    # パディング前のトークン長を全レコード実測し、total_stepsは「実トークン」予算から出す。
    # <|pad|>で埋まる分は数えない(EXPERIMENTS.mdのスイープと同じ実トークン量基準で
    # total_stepsを決めるため)。1 step = global_batch_sequences レコード。
    record_token_lens = [
        min(len(encode_record(tokenizer, instruction, code, ids)[0]), model_cfg.max_seq_len)
        for instruction, code in train_records
    ]
    mean_real_tokens_per_record = sum(record_token_lens) / len(record_token_lens)
    real_tokens_per_step = global_batch_sequences * mean_real_tokens_per_record
    padded_tokens_per_step = global_batch_sequences * model_cfg.max_seq_len
    pad_fraction = 1.0 - real_tokens_per_step / padded_tokens_per_step
    target_real_tokens = int(cfg.train.target_real_tokens)
    """学習で使用する実際のトークン数の目標値。この目標値に到達するようにステップ数が決まる。"""
    total_steps = int(target_real_tokens // real_tokens_per_step)
    print(
        f"global_batch_sequences={global_batch_sequences} seq_len={model_cfg.max_seq_len}\n"
        f"mean_real_tokens/record={mean_real_tokens_per_record:.1f} "
        f"real_tokens/step={real_tokens_per_step:,.0f} "
        f"padded_tokens/step={padded_tokens_per_step:,} pad={pad_fraction:.0%}\n"
        f"target_real_tokens={target_real_tokens:,} / total_steps={total_steps:,}"
    )

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=cfg.optim.max_lr,
        weight_decay=cfg.optim.weight_decay,
        betas=tuple(cfg.optim.betas),
        eps=cfg.optim.eps,
    )

    # 学習用データと検証用データをモデルに渡せる形式へ変換。
    train_iter = iter_padded_records(
        train_records, tokenizer, ids, max_seq_len=model_cfg.max_seq_len, rng=random.Random(cfg.seed)
    )
    val_iter = iter_padded_records(
        val_records, tokenizer, ids, max_seq_len=model_cfg.max_seq_len, rng=random.Random(cfg.seed + 1)
    )

    # mlflowの諸設定。
    db_path = root / cfg.mlflow.tracking_db
    db_path.parent.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(f"sqlite:///{db_path}")
    mlflow.set_experiment(cfg.mlflow.experiment)

    with mlflow.start_run() as run:
        # チェックポイントの保存先のパスを設定。パスの名前は、run_id。
        ckpt_dir = root / cfg.paths.out_dir / "checkpoints" / run.info.run_id
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        print(f"mlflow run_id: {run.info.run_id}")
        print(f"checkpoint dir: {ckpt_dir}")

        # tokenizerそのものを保存する。
        mlflow.log_artifact(str(tokenizer_path), artifact_path="tokenizer")

        # mlflowにハイパーパラメータを保存。
        mlflow.log_params(
            {
                "tokenizer_path": str(cfg.paths.tokenizer),
                "tokenizer_sha256": tokenizer_sha256,
                "tokenizer_vocab_size": tokenizer.get_vocab_size(),
                "max_lr": cfg.optim.max_lr,
                "weight_decay": cfg.optim.weight_decay,
                "warmup_ratio": cfg.optim.warmup_ratio,
                "grad_clip": cfg.optim.grad_clip,
                "global_batch_sequences": global_batch_sequences,
                "target_real_tokens": target_real_tokens,
                "mean_real_tokens_per_record": round(mean_real_tokens_per_record, 2),
                "real_tokens_per_step": round(real_tokens_per_step),
                "padded_tokens_per_step": padded_tokens_per_step,
                "pad_fraction": round(pad_fraction, 4),
                "total_steps": total_steps,
                "n_params": model.num_parameters(),
                **{f"model.{k}": v for k, v in vars(model_cfg).items()},
            }
        )

        # 学習開始時刻を指定。
        t_start = time.time()
        # <|pad|>を除いた実トークンの累計
        real_tokens_seen = 0 
        # パディング込み(モデルが実際に順伝播した)トークンの累計
        padded_tokens_seen = 0  
        # さっき指定したステップ数だけ学習を繰り返す。
        for step in range(total_steps):
            # 学習率を計算。
            lr = lr_at_step(
                step,
                max_lr=cfg.optim.max_lr,
                total_steps=total_steps,
                warmup_ratio=cfg.optim.warmup_ratio,
                min_lr_ratio=cfg.optim.min_lr_ratio,
            )
            # 学習率を反映。
            for group in optimizer.param_groups:
                group["lr"] = lr

            # 勾配を消去。
            optimizer.zero_grad(set_to_none=True)
            # 1バッチ分のレコードを取得。
            records = [next(train_iter) for _ in range(global_batch_sequences)]
            # レコードをモデルに渡せる形式に変更。
            tokens, loss_mask, attention_mask = _make_batch(
                records, ids.pad, model_cfg.max_seq_len, device
            )
            # 二つのトークン数を記録
            real_tokens_seen += int(attention_mask.sum())
            padded_tokens_seen += tokens.numel()
            # 損失を計算
            loss = _compute_loss(model, tokens, loss_mask, attention_mask)
            # 勾配を計算
            loss.backward()
            # 表示できる形に変更
            step_loss = loss.item()

            # 勾配の大きさを制限。=の後ろで勾配がクリップ処理されており、grad_normにはクリップ前の値が残っている。
            grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.optim.grad_clip)
            # 重みを更新。
            optimizer.step()

            # 現在のステップが最後かどうか判定。最後ならTrueが入る。
            is_last_step = step == total_steps - 1
            # 一定間隔のステップ火災後のステップに達していたら処理が動く。
            if step % cfg.eval.interval == 0 or is_last_step:
                # 検証データでのLossを計算。
                val_loss = _eval_loss(
                    model, val_iter, cfg.eval.n_batches, global_batch_sequences,
                    ids.pad, model_cfg.max_seq_len, device,
                )
                # 生成結果の合格率と生成例などが入る。
                gen = _eval_generation(model, val_records, tokenizer, ids, probes, cfg)
                # 学習開始からの経過時間を計算。
                elapsed = time.time() - t_start
                print(
                    f"step {step:>5}/{total_steps} lr={lr:.2e} "
                    f"train_loss={step_loss:.4f} val_loss={val_loss:.4f} "
                    f"gen_pass_rate={gen['pass_rate']:.2f} grad_norm={float(grad_norm):.2f} "
                    f"real_tok={real_tokens_seen:,} padded_tok={padded_tokens_seen:,} "
                    f"elapsed={elapsed:.0f}s"
                )
                # 生成例を表示
                for instruction, gen_code, ok in gen["examples"][:2]:
                    mark = "OK" if ok else "NG"
                    print(f"  [{mark}] {instruction}\n      -> {gen_code!r}")
                # mlflowにlossや評価結果を保存。
                mlflow.log_metrics(
                    {
                        "train_loss": step_loss,
                        "val_loss": val_loss,
                        "lr": lr,
                        "grad_norm": float(grad_norm),
                        "gen_pass_rate": gen["pass_rate"],
                        "real_tokens_seen": real_tokens_seen,
                        "padded_tokens_seen": padded_tokens_seen,
                    },
                    step=step,
                )

            # 指定された間隔または最後のステップに達したらチェックポイントを保存。
            if (step % cfg.checkpoint.interval == 0 and step > 0) or is_last_step:
                ckpt_path = ckpt_dir / f"step_{step:06d}.pt"
                torch.save(
                    {
                        "step": step,
                        "model_config": vars(model_cfg),
                        "model_state_dict": model.state_dict(),
                        "optimizer_state_dict": optimizer.state_dict(),
                    },
                    ckpt_path,
                )
                print(f"checkpoint: {ckpt_path}")

        print("学習完了")


if __name__ == "__main__":
    main()
