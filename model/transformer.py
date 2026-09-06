"""Boku-nano本体のTransformerアーキテクチャ（decoder-only, causal LM）。

指定ハイパーパラメータ（既定値は`conf/model/default.yaml`参照）:

| 項目 | 値 |
| --- | --- |
| 層数 | 8 |
| d_model | 384 |
| Attention head数 | 8 |
| KV head数 | 2 |
| head_dim | 48 |
| FFN size (d_ff) | 1,024 |
| 語彙数 | 4,096 |
| 最大系列長 | 256 |
| 位置表現 | RoPE |
| 正規化 | RMSNorm |
| 活性化 | SwiGLU |
| Attention方式 | GQA (8:2 = 4:1) |
| 入出力埋め込み | weight tying |

線形層・埋め込み・`scaled_dot_product_attention`（GQA・causal maskとも引数一つで
まかなえる）はPyTorchの提供する部品を使う。RoPE・RMSNorm・SwiGLU・GQAをどう
組み合わせるかは本ファイルの実装であり、`src/`とは違いこちらは`torch`に依存してよい
（`tests/test_core_has_no_external_deps.py`の境界は`src/`だけを対象にしている）。
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F

# @はデコレータ。これをつけると、その下のクラスや関数を定義した後に、デコレータに通したものが手に入る。
# dataclassをつけると、vocab_sizeなど宣言するときに自動で、self.vocab_size=vocab_sizeを実行したような処理が起こる。
@dataclass
class ModelConfig:
    """中身はmodel/default.yamlを参照"""

    vocab_size: int
    max_seq_len: int
    d_model: int
    n_layers: int
    n_heads: int
    n_kv_heads: int
    head_dim: int
    d_ff: int
    rope_theta: float
    rms_norm_eps: float

    # post_initは、initが終わった瞬間に呼ばれる関数。
    # ここでは値の整合性のチェックなどを行っているが、ここでinitで作った値から新しい値を定義することとかもできる。
    def __post_init__(self) -> None:
        if self.n_heads % self.n_kv_heads != 0:
            raise ValueError(
                f"n_heads({self.n_heads})はn_kv_heads({self.n_kv_heads})の倍数である必要がある(GQA)"
            )
        if self.head_dim * self.n_heads != self.d_model:
            raise ValueError(
                f"head_dim({self.head_dim}) * n_heads({self.n_heads}) は"
                f" d_model({self.d_model})と一致する必要がある"
            )


class RMSNorm(nn.Module):
    """RMSNormを定義。`x / rms(x) * weight`。LayerNormと違い平均を引かない（学習可能なのはスケールのみ）。"""

    def __init__(self, dim: int, eps: float) -> None:
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x_fp32 = x.float()
        norm = x_fp32 * torch.rsqrt(x_fp32.pow(2).mean(dim=-1, keepdim=True) + self.eps)
        return (norm.type_as(x)) * self.weight

# こっから始まる1連の関数を実行しきると、単語ベクトルを入力として、それが回転した後のベクトルが手に入る
def precompute_rope(
    head_dim: int, max_seq_len: int, theta: float
) -> tuple[torch.Tensor, torch.Tensor]:
    """RoPEのcos/sinテーブルを位置0..max_seq_len-1ぶん事前計算する。形は(max_seq_len, head_dim/2)。

    回転ペアは`head_dim/2`個(`apply_rope`参照)なので、角度θも1ペアにつき1個で足りる。
    """
    inv_freq = 1.0 / (
        theta ** (torch.arange(0, head_dim, 2, dtype=torch.float32) / head_dim)
    )
    # この単語が文中のどの位置にいるか
    position = torch.arange(max_seq_len, dtype=torch.float32)
    freqs = torch.outer(position, inv_freq)  # (max_seq_len, head_dim/2)
    return freqs.cos(), freqs.sin()

# このRoPEは半分割方式。index=0からx1、index=24からx2をとってきてタプルにしている。
def apply_rope(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    """`x`: (batch, n_heads, seq_len, head_dim)。`cos`/`sin`: (batch, seq_len, head_dim/2)。

    行(batch)ごとに別々の位置を持てるよう、cos/sinは常にbatch次元込みで渡す
    （left paddingしたバッチ生成では、行によって「本物のトークンが何番目の位置から
    始まるか」が違うため。右パディングの訓練時はpositionが全行共通なので、
    `BokuNanoModel.forward`側で`arange`をbatch分に複製したものを渡す）。

    `x`をhead_dim方向に前半/後半で2分割し、`(x1[i], x2[i])`を1組のペアとして角度
    `θ_i`だけ回転する(2次元回転の公式 `a' = a*cosθ - b*sinθ`, `b' = b*cosθ + a*sinθ`
    をそのまま書いている)。ペアは`head_dim/2`個なので、`cos`/`sin`もその数だけあれば足りる。
    """
    # unsqueezeで、n_headsに相当する位置に1つ」軸を差し込む。xと掛け合わせるとき、この軸がn_heads分ブロードキャストされる。
    cos = cos.unsqueeze(1).to(x.dtype)  # (batch, 1, seq_len, head_dim/2)
    sin = sin.unsqueeze(1).to(x.dtype)
    x1, x2 = x.chunk(2, dim=-1)  # (a, b): x1[..., i] と x2[..., i] が1組の回転ペア
    # cosの加法定理
    rotated1 = x1 * cos - x2 * sin  # a' = a*cosθ - b*sinθ
    # sinの加法定理
    rotated2 = x2 * cos + x1 * sin  # b' = b*cosθ + a*sinθ
    return torch.cat([rotated1, rotated2], dim=-1)


class GroupedQueryAttention(nn.Module):
    """GQA: `n_kv_heads`個のK/Vを`n_heads // n_kv_heads`個ずつのQで共有する。"""

    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        self.n_heads = cfg.n_heads
        self.n_kv_heads = cfg.n_kv_heads
        self.head_dim = cfg.head_dim

        self.q_proj = nn.Linear(cfg.d_model, cfg.n_heads * cfg.head_dim, bias=False)
        self.k_proj = nn.Linear(cfg.d_model, cfg.n_kv_heads * cfg.head_dim, bias=False)
        self.v_proj = nn.Linear(cfg.d_model, cfg.n_kv_heads * cfg.head_dim, bias=False)
        self.o_proj = nn.Linear(cfg.n_heads * cfg.head_dim, cfg.d_model, bias=False)

    def forward(
        self,
        x: torch.Tensor,
        cos: torch.Tensor,
        sin: torch.Tensor,
        attn_mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        # bszはバッチサイズ
        bsz, seq_len, _ = x.shape

        # viewで、マルチヘッドにする。その後、transposeで軸を入れ替える。
        q = self.q_proj(x).view(bsz, seq_len, self.n_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(x).view(bsz, seq_len, self.n_kv_heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(x).view(bsz, seq_len, self.n_kv_heads, self.head_dim).transpose(1, 2)

        q = apply_rope(q, cos, sin)
        k = apply_rope(k, cos, sin)


        if attn_mask is None:
            # 呼び出し側が「因果性だけで足りる」と判断した経路。is_causal一つで済む。
            # pytorchが凄い。
            out = F.scaled_dot_product_attention(q, k, v, is_causal=True, enable_gqa=True)
        else:
            # pad tokenを含むバッチ(訓練の右パディング / 生成の左パディング)。attn_maskは
            # 因果マスクとpaddingマスクを合成済み(bool, Trueが「attendしてよい」)なので、
            # is_causalは使わずこちらに任せる。
            out = F.scaled_dot_product_attention(q, k, v, attn_mask=attn_mask, enable_gqa=True)

        out = out.transpose(1, 2).contiguous().view(bsz, seq_len, self.n_heads * self.head_dim)
        return self.o_proj(out)


class SwiGLU(nn.Module):
    """`down(silu(gate(x)) * up(x))`。d_ffはgate/up共通（Llama系の一般的な構成）。"""

    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        self.gate_proj = nn.Linear(cfg.d_model, cfg.d_ff, bias=False)
        self.up_proj = nn.Linear(cfg.d_model, cfg.d_ff, bias=False)
        self.down_proj = nn.Linear(cfg.d_ff, cfg.d_model, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # silu=swishと考えてよいが、swishの方がやや広い概念。
        return self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))


class TransformerBlock(nn.Module):
    """pre-norm構成: `x + Attn(RMSNorm(x))` → `x + FFN(RMSNorm(x))`。"""

    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        self.attn_norm = RMSNorm(cfg.d_model, eps=cfg.rms_norm_eps)
        self.attn = GroupedQueryAttention(cfg)
        self.ffn_norm = RMSNorm(cfg.d_model, eps=cfg.rms_norm_eps)
        self.ffn = SwiGLU(cfg)

    def forward(
        self,
        x: torch.Tensor,
        cos: torch.Tensor,
        sin: torch.Tensor,
        attn_mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        # 正規化前のxの値を引き継いでいく、pre-norm構成。原論文とは別の方式
        x = x + self.attn(self.attn_norm(x), cos, sin, attn_mask)
        x = x + self.ffn(self.ffn_norm(x))
        return x


class BokuNanoModel(nn.Module):
    """decoder-only Transformer LM本体。入出力埋め込みは重み共有(weight tying)。"""

    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        self.cfg = cfg

        self.matrix_emb = nn.Embedding(cfg.vocab_size, cfg.d_model)
        # layer一つ一つが、一つ前に作ったTransformerBlock。
        self.layers = nn.ModuleList(TransformerBlock(cfg) for _ in range(cfg.n_layers))
        self.final_RMSnorm = RMSNorm(cfg.d_model, eps=cfg.rms_norm_eps)
        self.lm_head = nn.Linear(cfg.d_model, cfg.vocab_size, bias=False)
        self.lm_head.weight = self.matrix_emb.weight  # weight tying

        cos, sin = precompute_rope(cfg.head_dim, cfg.max_seq_len, cfg.rope_theta)
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)

        self.apply(self._init_weights)

    def _init_weights(self, module: nn.Module) -> None:
        if isinstance(module, nn.Linear):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if module.bias is not None:
                nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor | None = None,
        position_ids: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """`input_ids`: (batch, seq_len) → logits: (batch, seq_len, vocab_size)。

        `attention_mask`(1=本物のトークン / 0=pad): pad位置を鍵として見ないための
        マスク。訓練は右パディングなので`scripts/train.py`が渡す。無指定なら因果マスク
        だけになる。
        `position_ids`: 無指定なら全行で位置0..seq_len-1。右パディングでは本物の
        トークンが位置0から並ぶのでこれで正しく、渡す必要は無い。left paddingする
        バッチ生成のときだけ`model.generate.batch_greedy_generate`がpad分を除いた
        位置を明示的に渡す。
        """
        # bszはbatch_size
        bsz, seq_len = input_ids.shape
        if seq_len > self.cfg.max_seq_len:
            raise ValueError(f"seq_len({seq_len}) > max_seq_len({self.cfg.max_seq_len})")

        if position_ids is None:
            position_ids = torch.arange(seq_len, device=input_ids.device).expand(bsz, seq_len)
        cos = self.rope_cos[position_ids]  # (batch, seq_len, head_dim/2)
        sin = self.rope_sin[position_ids]

        attn_mask = None
        if attention_mask is not None:
            causal = torch.tril(
                torch.ones(seq_len, seq_len, dtype=torch.bool, device=input_ids.device)
            )
            key_ok = attention_mask.bool()[:, None, None, :]  # (batch, 1, 1, seq_len)
            attn_mask = causal[None, None, :, :] & key_ok  # (batch, 1, seq_len, seq_len)

        embedded = self.matrix_emb(input_ids)
        hidden = embedded
        for layer in self.layers:
            hidden = layer(hidden, cos, sin, attn_mask)
        out = self.final_RMSnorm(hidden)
        return self.lm_head(out)

    def num_parameters(self, *, exclude_tied: bool = True) -> int:
        """総パラメータ数。`exclude_tied=True`なら`lm_head`の重複ぶんを数えない。"""
        seen: set[int] = set()
        total = 0
        for p in self.parameters():
            if exclude_tied:
                if id(p) in seen:
                    continue
                seen.add(id(p))
            total += p.numel()
        return total


if __name__ == "__main__":
    # conf/model/default.yaml と同じ値(このファイル単体で動作確認するための決め打ち)。
    cfg = ModelConfig(
        vocab_size=4_096,
        max_seq_len=256,
        d_model=384,
        n_layers=8,
        n_heads=8,
        n_kv_heads=2,
        head_dim=48,
        d_ff=1_024,
        rope_theta=10_000.0,
        rms_norm_eps=1e-5,
    )
    model = BokuNanoModel(cfg)
    print(f"config: {cfg}")
    print(f"パラメータ数: {model.num_parameters():,}")

    dummy = torch.randint(0, cfg.vocab_size, (2, 64))
    logits = model(dummy)
    print(f"入力形状: {tuple(dummy.shape)} → 出力形状: {tuple(logits.shape)}")
    assert logits.shape == (2, 64, cfg.vocab_size)
