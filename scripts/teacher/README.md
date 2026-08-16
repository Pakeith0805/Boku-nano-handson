# scripts/teacher/ — 教師モデル（Qwen）環境構築の手順と、このディレクトリの関数一覧

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
3. 版・量子化方式などを記録する（`qwen.provenance()`がそのまま使える）

**このスクリプトは一度通したら消してよい**（実際に消してある）。役目は「その時点の環境が
条件を満たしていたことを確かめて記録に残す」ことだからである。環境を疑う事態になったら、
この手順に沿って書き直して流し直すこと。読み込み方そのものは`scripts/teacher/qwen.py`に
残っている。

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

モデル名・revision・量子化方式・推論ライブラリの版・GPU情報・疎通確認の実測値
（読み込み時間・生成速度・VRAM）・確認日時。前半は`qwen.provenance()`が返すので、
実測値と日時を足して書けばよい。

**由来の正本は生成物の側にある**（MLflowは索引に過ぎない）。かつては疎通確認1回ぶんを
`data/teacher/manifest.json`に置いていたが、環境の記録が1つしかないと、後から流した生成が
どの環境で走ったのか分からない——ライブラリが更新されても生成物は何も知らないままになる。
そのため現在は`build_phrases.py`が実行のたびに`provenance()`を呼び、
`data/teacher/phrases_runs.jsonl`へ1行ずつ追記する形にしてある（各候補の`run_id`から引ける）。
疎通確認だけを別に記録したい場合も、上書きされないファイルに追記すること。

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
| `scripts/review_phrases.py` | 駆動。候補を人が承認して辞書に凍結する（**意味の検査はここだけ**） | teacher 不要（pyyamlはhydra経由で入る） |
| `scripts/teacher/qwen.py` | モデルの読み込み・プロンプト組み立て・生成・由来の収集 | teacher |
| `scripts/teacher/op_seeds.yaml` | 24opの意味・正例・禁止語（**人間が書く資産**） | — |
| `scripts/teacher/phrase_filters.py` | 出力の正規化と機械的な棄却 | 標準ライブラリのみ |

駆動スクリプト2本の使い方は`scripts/README.md`にある。以下はこのディレクトリの2ファイルの
関数一覧である。

## qwen.py

教師モデルを呼ぶための最小の層。疎通確認で通った構成をそのまま関数にしただけのもので、
**プロンプトの中身も出力のパースも持たない**（それは`build_phrases.py`の担当）。
上の §4 が言う「環境の問題とプロンプトの問題を混ぜない」を、モジュールの境界としても引いてある。

### 定数

| 名前 | 説明 |
| --- | --- |
| `MODEL_ID` | `"Qwen/Qwen3-4B-AWQ"` |
| `REVISION` | 固定するrevision。`main`のままだと上流の更新で黙って別モデルになる |
| `BACKEND_NAME` | `BACKEND.TORCH`。既定の自動選択は`AwqMarlinLinear`を選び、そのJITビルドが`CUDA_HOME`を要求して失敗する |
| `QUANTIZATION` | 量子化方式の表示名（`"AWQ (4bit)"`）。由来の記録に載る |
| `ENABLE_THINKING` | thinkingモードを使うか（`False`）。由来に記録するので、切り替えたら記録も自動で変わる |

**この5つが、実際に使うモデルを決める唯一の場所である。** 変えたら疎通確認からやり直すこと。
`provenance()`がそのまま生成物に焼き付けるので、書き換えれば以降の記録も自動で追従する。

### 関数

| 関数 | 説明 |
| --- | --- |
| `provenance()` | 生成物に焼き付ける「何で作ったか」——モデルの同一性・推論スタックの版・GPU情報を辞書で返す。**呼び出し時点の実測値**であり、別の日に書いた記録の写しではない |
| `load()` | モデルとトークナイザを読み込む（実測：約2.2秒、VRAM約2.50GiB）。GPUやcompute capabilityの検査はしない（疎通確認済みの環境を前提にする） |
| `build_prompt(tokenizer, user, system=None)` | 非thinkingモードのプロンプト文字列を組む。空の`<think>`ブロックがテンプレートに入っていなければ`AssertionError`（全文デコードに`<think>`が出ること自体は失敗ではない） |
| `generate(model, tokenizer, text, *, max_new_tokens, seed, temperature=None, top_p=0.95)` | 1プロンプト生成し、`(出力, 生成トークン数, 所要秒数)`を返す。`temperature=None`で貪欲法。`seed`はキーワード必須で既定値を置いていない（何を種にしたかを記録しないと生成物を再現できないため） |

## phrase_filters.py

生成された言い回しの正規化と、機械的に判定できる棄却。

**このモジュールは意味の正しさを判定しない。** 見るのは形式だけ——文型・長さ・使用禁止語・
`k`の出現回数・重複である。意味の検査は`review_phrases.py`（人間の承認）か、後段
（生成文→コード→参照インタプリタ照合）の担当。`qwen.py`に依存しないので、GPU無しで単体
テストできる。この境界は崩さないこと。

`MIN_LEN`/`MAX_LEN`と終止形の規則は`op_seeds.yaml`の`style`と対になっている。あちらはモデル
への指示、こちらは検査であり、二重に書いているのは意図的である（導出すると検査が常に真に
なって意味を失う）。片方を変えたらもう片方も直すこと。

### 定数

| 名前 | 説明 |
| --- | --- |
| `MIN_LEN` / `MAX_LEN` | 言い回しの文字数（5〜40、`{k}`を具体値に展開した状態で数える） |
| `TERMINAL_KANA` | 動詞の終止形の末尾になりうるかな（う段）。『る』だけで見ると「残す」「足す」が全部落ちる |
| `POLITE_SUFFIXES` | 丁寧形の語尾。文体の統一だけでなく、「以下が言い換えです」のような**前置きを落とす罠**として効く |
| `BAD_CHAR` | 出てはいけない文字。ラテン文字を一律で弾くと、コード片・英語のop名・英語で答えた行がまとめて落ちる。`-`と`×``÷`は除外していない |
| `KANA` / `DIGIT_RUN` | かなを含むかの判定と、数字の並びの検出 |

### 関数

| 関数 | 説明 |
| --- | --- |
| `normalize(line, literal)` | 1行を比較・検査できる形に均す（箇条書き記号・番号・鉤括弧・末尾の句点・補足の括弧書き・空白を落とし、`{k}`は`literal`へ展開する）。落とさないと「偶数だけを残す」と「- 偶数だけを残す。」が別物として2件に数えられる |
| `to_placeholder(phrase, literal)` | 具体値で書かれた言い回しを`{k}`版に戻す。数字の並びが`literal`と**完全に一致する**ものだけを置き換える（単純な文字列置換だと「17より大きい」が「1{k}より大きい」になる） |
| `check(phrase, *, uses_k, literal, forbid, seen)` | `normalize`済みの言い回しを検査する。通れば`None`、弾くなら理由の文字列を返す |
| `_literal_count(phrase, literal)` | `literal`とちょうど一致する数字の並びの個数。内部ヘルパー |

`check`が返す棄却理由は`data/teacher/phrases_raw.jsonl`にそのまま記録して集計する。
どの規則がどれだけ効いたかが分かれば、プロンプトのどこを直すべきかも分かる。

| 理由 | 意味 |
| --- | --- |
| `empty` / `too_short` / `too_long` | 空、または`MIN_LEN`〜`MAX_LEN`の外 |
| `bad_char` | ラテン文字や記号を含む（コード片・英語で答えた行） |
| `no_kana` | かなを1文字も含まない |
| `polite_form` | 丁寧形で終わる（前置きの行もここで落ちる） |
| `not_terminal_form` | 終止形の動詞句で終わっていない（体言止め・連用形） |
| `k_missing` / `k_multiple` | `k`参照opなのに検査用リテラルが無い／2つ以上ある |
| `unexpected_literal` | `k`を取らないopなのに検査用リテラルが出た（`double`が「7倍する」と言うような取り違え） |
| `forbidden:<語>` | `op_seeds.yaml`の`forbid`に挙げた語を含む |
| `duplicate` | 既出の言い回しと同一 |

## op_seeds.yaml

24opの言い回しを生成させるための「種」。**人間が書く資産**であり、生成物ではない。教師モデルに
opの意味を推測させると必ずズレる（`reverse`と`desc`、`every_other`の「1個おき」など、
`registry.py`の`notes`がまさにその曖昧性を潰している箇所）。意味の確定はこちらで行い、教師には
「同じ意味の別の言い方」だけを作らせる。`ops`のキー集合は`OP_REGISTRY`と完全一致していなければ
ならず、`build_phrases.load_seeds()`がそれを検査する。

### トップレベルのキー

| キー | 説明 |
| --- | --- |
| `version` | プロンプトの版。`frame`/`style`/`meaning`/`examples`/`forbid`のどれかを変えたら上げる。生成した各行に記録して、どの種から出た表現かを後から辿れるようにする |
| `frame` | 意味AST→日本語文の書き出し（`整数を要素に持つリストに対して`）。**全ての文がここから始まる**ものとして表現を作るので、各opの言い回しは「この書き出しに続く部分」であり単独で完結した文ではない |
| `literal_probe` | `k`参照opの生成に使う具体値（`7`）。`examples`中の`{k}`はプロンプトを組むときにこの値へ展開し、生成された行の中のこの値を`{k}`へ戻す |
| `style` | 全opに共通する文型の制約。プロンプトにそのまま並べ、一部は`phrase_filters`が機械的に検査する |
| `ops` | op名 → `{meaning, examples, forbid}` の辞書（24件） |

`frame`を「〜から」にしないのは、filterにしか合わないためである。sliceの表現は「先頭から」
「末尾から」を自分で含むので「から」が二重になり、mapは「〜から足す」が繋がらず、orderは助詞が
「を」なので崩れる。4カテゴリ全部を通せるのは「〜に対して」「〜を受け取り」の形だけ。

`literal_probe`が`7`なのは (1) 全10個の`k`参照opの`literal_domain`（最小でも`mul_k`の4以上）に
入る、(2) opに焼き付いた定数 2（`double`）・3（`triple`）・2乗（`square`）と衝突しない、
(3) 日本語の慣用句に紛れ込みにくい、の3点による。2や3にすると`double`/`triple`/`square`の表現と
区別がつかなくなるので変えないこと。

### 各opのキー

| キー | 説明 |
| --- | --- |
| `meaning` | opの意味。**人間向けの補足を書かないこと**——モデルはそれも言い換えの対象として飲み込む（v1では「要素の個数も順序も変えない」と書いたせいで「{k}を足して列を保つ／保持する／維持する」を量産した） |
| `examples` | 言い換えの正例2つ。`{k}`の有無が`OP_REGISTRY`の`uses_k`と一致していなければならない |
| `forbid` | 使ってはいけない語。ほぼ全てが**紛らわしいop同士の取り違えを防ぐため**にある（`gt`の`以上`＝`ge`との混同、`reverse`の`並べ替え`／`降順`＝`desc`との混同など） |

## トラブルシューティング早見表

| 症状 | 原因 | 対処 |
| --- | --- | --- |
| Tritonのビルドで`Python.h`が無いと落ちる | venvが3.13系（開発ヘッダ無し） | `.python-version`を3.12.13に固定し`uv sync`し直す |
| `AwqMarlinLinear`のビルドが`CUDA_HOME`要求で失敗 | `gptqmodel`の既定バックエンド | `BACKEND.TORCH`を明示する |
| `torch.cuda.get_arch_list()`に`sm_120`が無い | torchのビルドがBlackwell非対応 | torchを入れ直す（`pyproject.toml`の`torch>=2.9`で足りるはずだが、念のため確認） |
| CUDAが使えない / VRAM不足 | 他プロセスと共有中、または未起動 | `nvidia-smi`で空きを確認。学習（Phase 3相当）と同時に走らせない |
| AWQがどうしても動かない | 稀にあり得る | `Qwen/Qwen3-4B`（bf16）にフォールバックしてよい。ただしその判断と理由を`manifest.json`に明記する。VRAMは29GB空いているのでbf16でも動く |
