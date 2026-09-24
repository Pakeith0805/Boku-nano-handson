# model/ — モデルと訓練・生成用の部品

decoder-only Transformerと、トークナイズ・学習率・貪欲生成・checkpoint復元を置きます。訓練ループと保存は [scripts/train.py](../scripts/train.py)、評価の入口は [scripts/README.md](../scripts/README.md) です。`src/` の標準ライブラリ限定とは異なり、このパッケージはPyTorchを使います。

## __init__.py

`BokuNanoModel` と `ModelConfig` を再エクスポートします。`from model import BokuNanoModel` と書けます。パッケージ初期化時に `transformer.py` を読むため、`model.data` などのimportにもPyTorchが必要です。

## transformer.py

アーキテクチャを定義します。`ModelConfig` 自体に既定値はなく、訓練では [conf/model/default.yaml](../conf/model/default.yaml) の値を渡します。

### ModelConfigのプロパティ

| フィールド | 設定ファイルの既定値・意味 |
| --- | --- |
| `vocab_size` | 4,096。埋め込み・出力の行数。現行トークナイザの実語彙1,256とは別 |
| `max_seq_len` | 256。入力できる系列長の上限 |
| `d_model` / `n_layers` | 隠れ次元384、8層 |
| `n_heads` / `n_kv_heads` / `head_dim` | Qは8head、KVは2head、各48次元。GQA比4:1 |
| `d_ff` | SwiGLUの中間次元1,024 |
| `rope_theta` | RoPEの周波数の基数10,000.0 |
| `rms_norm_eps` | RMSNormの安定化項 `1e-5` |

### クラスの主要プロパティ

| クラス | プロパティ | 役割 |
| --- | --- | --- |
| `RMSNorm` | `weight`, `eps` | 学習するスケールと安定化項 |
| `GroupedQueryAttention` | `q_proj`, `k_proj`, `v_proj`, `o_proj` | biasなしのQ/K/V・出力射影 |
| `SwiGLU` | `gate_proj`, `up_proj`, `down_proj` | `down(silu(gate(x)) * up(x))` を構成する射影 |
| `TransformerBlock` | `attn_norm`, `attn`, `ffn_norm`, `ffn` | pre-normのattentionとFFN、各残差接続 |
| `BokuNanoModel` | `cfg`, `matrix_emb`, `layers`, `final_RMSnorm`, `lm_head` | 埋め込みから語彙logitsまで。`lm_head.weight` は `matrix_emb.weight` と共有 |
| `BokuNanoModel` | `rope_cos`, `rope_sin` | `(max_seq_len, head_dim / 2)` のbuffer。state_dictには保存せず構築時に再計算 |

### メソッド

| メソッド | 説明 |
| --- | --- |
| `ModelConfig.__post_init__()` | `n_heads % n_kv_heads == 0` と `head_dim * n_heads == d_model` を検査し、不一致なら `ValueError` |
| `RMSNorm.forward(x)` | 最終次元の二乗平均で正規化して `weight` を掛ける。正規化部分はFP32 |
| `GroupedQueryAttention.forward(x, cos, sin, attn_mask=None)` | Q/KにRoPEを適用し、PyTorchのSDPAでGQAを計算する。マスク未指定なら因果マスクを使う |
| `SwiGLU.forward(x)` | 最終次元をFFNで変換し、元の隠れ次元へ戻す |
| `TransformerBlock.forward(x, cos, sin, attn_mask=None)` | attentionとFFNを順に適用し、それぞれ入力を残差として足す |
| `BokuNanoModel.forward(input_ids, attention_mask=None, position_ids=None)` | `(B, L)` のIDから `(B, L, vocab_size)` のlogitsを返す。系列長超過は `ValueError` |
| `BokuNanoModel.num_parameters(*, exclude_tied=True)` | パラメータ数を返す。現在は `parameters()` 自体が共有重みを重複除去するため、`False` でも共有分は二重に数えない |
| `BokuNanoModel._init_weights(module)` | 内部ヘルパー。LinearとEmbeddingを標準偏差0.02の正規分布で初期化 |

### 関数

| 関数 | 説明 |
| --- | --- |
| `precompute_rope(head_dim, max_seq_len, theta)` | `(max_seq_len, head_dim / 2)` のcos/sin表を返す |
| `apply_rope(x, cos, sin)` | `(B, H, L, head_dim)` のQ/Kを前半・後半の対応要素で回転する。cos/sinは `(B, L, head_dim / 2)` |

`attention_mask` は1が実トークン、0がpadです。指定時は因果マスクと合成してpadのキーを参照させません。訓練は右パディングなので位置0からの既定値を使えます。生成は左パディングなので、生成関数がpadを除いた `position_ids` を渡します。

既定構成は13,965,696パラメータです。`python -m model.transformer` はダミー入力の形状を確認するだけで、訓練しません。

## data.py

JSONLを読み、1レコードを `[bos, task, *instruction_ids, code, *code_ids, eos]` にします。実際の特殊トークン表記は `<|bos|>` などです。ここではパディングしません。

### SpecialIdsのプロパティ

| フィールド | 説明 |
| --- | --- |
| `pad`, `bos`, `eos`, `task`, `code` | 5つの特殊トークンIDを持つ不変の `NamedTuple` |

### 関数

| 関数 | 説明 |
| --- | --- |
| `load_special_ids(tokenizer)` | 5つのIDを `SpecialIds` で返す。見つからなければ `ValueError` |
| `load_records(path)` | 検証3フラグがすべてtrueの行から `(instruction_ja, reference_code)` を返す。不合格・欠落の除外件数は警告し、有効行が0件ならエラー |
| `encode_record(tokenizer, instruction, code, ids)` | トークン列と、各位置から次トークンを予測する損失マスクを返す |
| `iter_padded_records(records, tokenizer, ids, *, max_seq_len, rng)` | エポックごとに順序をシャッフルし、可変長の1レコードを無限にyieldする。上限を超えるレコードは切り詰めず `ValueError`。非空の `records` が前提 |

マスクは `bos/task/instruction` が0、`code` 区切りから `eos` 自身までが1です。`train._compute_loss` は入力側に合わせた `loss_mask[:, :-1]` を使うため、コード先頭とEOSの予測が損失に入ります。**現行実装では、右padがある系列は `eos → 最初のpad` も損失に入ります。** padを入力とする位置は0ですが、EOSを入力とする位置は1だからです。詳細は [損失計算の解説](../docs/compute-loss-explanation.md) を参照してください。

## schedule.py

### 関数

| 関数 | 説明 |
| --- | --- |
| `lr_at_step(step, *, max_lr, total_steps, warmup_ratio, min_lr_ratio)` | 0始まりのstepから学習率を返す。warmup後はcosineで減衰し、`step >= total_steps` で下限になる |

`warmup_steps = max(1, round(total_steps * warmup_ratio))` で、最初の学習率は `max_lr / warmup_steps` です。0から始まるわけではなく、`warmup_ratio=0` でも1stepのwarmupが残ります。訓練の最終stepは `total_steps - 1` なので通常は下限の少し上です。

## generate.py

長さの違うプロンプトを左padして貪欲デコードします。KVキャッシュはなく、毎回系列全体を計算します。

### 関数

| 関数 | 説明 |
| --- | --- |
| `batch_greedy_generate(model, prompts, *, eos_id, pad_id, max_new_tokens)` | 左pad・プロンプト・生成分を含むID列を各行について返す。空でないプロンプト群が前提 |
| `greedy_generate(model, prompt_ids, *, eos_id, pad_id, max_new_tokens)` | 上記を1件で呼び、1本のID列を返す |

生成分は `row[prompt_width:]` です。追加できる長さは `max(0, min(max_new_tokens, model.cfg.max_seq_len - prompt_width))`。EOSを出した行は以後padを追加し、全行EOSまたは予算終了で止まります。EOS終了自体を評価の合格条件にはしていません。

生成中だけ `eval()` に切り替え、終了・例外時に元のtrain/eval状態へ戻します。勾配は作りません。

## checkpoint.py

### 関数

| 関数 | 説明 |
| --- | --- |
| `load_model(checkpoint_path, device)` | checkpointの `model_config` からモデルを構築し、`model_state_dict` をロードして指定deviceへ置く。`eval()` 状態の `(model, step)` を返す |

保存されるキーは `step`, `model_config`, `model_state_dict`, `optimizer_state_dict` です。この関数はoptimizerを復元しません。訓練スクリプトに再開用のCLIはなく、乱数・データイテレータの状態もcheckpointには保存されません。

トークナイザ本体はcheckpointに含まれません。訓練時のファイルとSHA-256はMLflowへ記録しますが、`evaluate.py` と `try_generate.py` は常に `data/tokenizer/tokenizer.json` を読み、対応を自動検査しません。v1とv2ではIDの意味が違うため、保存重みと同じ版を使う必要があります。
