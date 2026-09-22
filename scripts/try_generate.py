"""学習済みcheckpointから、日本語指示1件に対する生成結果を1本だけ見る。

```
python -m scripts.try_generate --checkpoint runs/checkpoints/step_006000.pt \
    --instruction "整数を要素に持つリストに対して、偶数だけを残すsolve関数を書いてください。"
python -m scripts.try_generate --checkpoint runs/checkpoints/step_006000.pt --random-val
python -m scripts.try_generate --checkpoint runs/checkpoints/step_006000.pt --random-val --seed 3
```

`--random-val`は`data/dataset/val.jsonl`からランダムに1件取り、参照コードとの実行結果を
`src.verify`(safety+sandbox。生成データセット自身の検証と同じ経路)で突き合わせて
PASS/FAILまで表示する。`--instruction`で自分で指示文を書いた場合は正解が無いので、
安全性検査(構文が許可リストの範囲内か)までしか見ない。

`scripts.train`の`_eval_generation`と同じ検証ロジックを、1件だけ手元で試すための足場。
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import torch
from tokenizers import Tokenizer

from model.checkpoint import load_model
from model.data import load_records, load_special_ids
from model.generate import greedy_generate
from src.probes.behavior_probes import PROBE_SET_VERSION, default_probe_set_path, load_probe_set
from src.verify import safety, sandbox

ROOT = Path(__file__).resolve().parents[1]
TOKENIZER_PATH = ROOT / "data" / "tokenizer" / "tokenizer.json"
VAL_PATH = ROOT / "data" / "dataset" / "val.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, help="scripts/train.pyが書いたcheckpoint(.pt)")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--instruction", help="日本語の指示文を直接指定する（正解コードは無い）")
    source.add_argument(
        "--random-val", action="store_true", help="data/dataset/val.jsonlからランダムに1件取る"
    )
    parser.add_argument("--seed", type=int, default=0, help="--random-val選択時の乱数シード")
    parser.add_argument("--max-new-tokens", type=int, default=192)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = Tokenizer.from_file(str(TOKENIZER_PATH))
    ids = load_special_ids(tokenizer)
    model, step = load_model(Path(args.checkpoint), device)
    print(f"checkpoint: {args.checkpoint} (step {step})")

    reference_code: str | None = None
    if args.random_val:
        records = load_records(VAL_PATH)
        instruction, reference_code = random.Random(args.seed).choice(records)
    else:
        instruction = args.instruction

    prompt = [ids.bos, ids.task, *tokenizer.encode(instruction).ids, ids.code]
    out_ids = greedy_generate(
        model, prompt, eos_id=ids.eos, pad_id=ids.pad, max_new_tokens=args.max_new_tokens
    )
    gen_code = tokenizer.decode(out_ids[len(prompt) :], skip_special_tokens=True)

    print(f"instruction: {instruction}")
    print("--- generated code ---")
    print(gen_code)

    reason = safety.check(gen_code)
    if reason is not None:
        print(f"[safety NG] {reason}")
        return

    if reference_code is None:
        print("(--instructionで直接指定した場合は正解コードが無いので、安全性検査までしか見ない)")
        return

    probes = load_probe_set(default_probe_set_path(ROOT, PROBE_SET_VERSION))
    ok = True
    for xs, k in probes:
        try:
            expected = sandbox.execute(reference_code, xs, k)
            got = sandbox.execute(gen_code, xs, k)
        except Exception as e:
            print(f"[execution error] {e}")
            ok = False
            break
        if got != expected:
            print(f"[mismatch] xs={xs} k={k} expected={expected} got={got}")
            ok = False
            break

    print("--- reference code ---")
    print(reference_code)
    print("PASS" if ok else "FAIL")


if __name__ == "__main__":
    main()
