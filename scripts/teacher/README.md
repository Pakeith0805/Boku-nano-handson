# scripts/teacher/

教師モデルに24opの日本語の言い換え候補を作らせる補助層です。
正解ASTとコードは [src/](../../src/README.md) でルールにより作ります。
候補の採否は人間が確認し、承認された表現を辞書へ反映します。

## 環境と実行

リポジトリルートで教師用の依存グループを入れます。

```bash
uv sync --group teacher
uv run python -m scripts.build_phrases --dry-run --ops even
```

`--dry-run` はプロンプト確認用で、モデルをロードしません。
実際の生成・レビューのコマンドとオプションは [scripts/README.md](../README.md) にあります。
`.python-version` は3.12.13です。`teacher` グループにはtorch、transformers、accelerate、
huggingface-hub、gptqmodel、torchvision、pyyamlが含まれます。
`qwen.load()` は `cuda:0` を指定する実装で、CPUへの自動切り替えはありません。

### 過去の環境確認（2026-08-05）

以下は既存の作業記録です。今回の文書更新でGPUの状態確認や速度測定は行っていません。

| 項目 | 当時の記録 |
| --- | --- |
| GPU | NVIDIA GeForce RTX 5090、compute capability 12.0 |
| 総VRAM / ドライバ | 32,607 MiB / 595.84 |
| Qwen3-4B-AWQの読み込み | 約2.2秒、読み込み後のVRAM約2.50 GiB |
| 128トークン貪欲生成 | `AWQ_GEMM_TRITON`: 62.9 tok/s、`TORCH`: 11.2 tok/s |

当時のPython 3.13環境では `Python.h` 不足、Marlin等のビルドでは `CUDA_HOME` 不足が
記録されています。これはその環境での結果であり、Python 3.13全般でTritonが動かないという
意味ではありません。現在の空きVRAMや処理速度もこの表からは分かりません。
速度の低下だけを根拠に、別バックエンドへ切り替わったと断定することはできません。

環境を調べる場合は、実際のエラー、Pythonとライブラリの版、
`nvidia-smi`、`qwen.provenance()`、過去の `phrases_runs.jsonl` を照合します。
`check_env.py` は現在存在せず、常設の疎通確認コマンドではありません。

## ファイルの役割

| ファイル | 役割 |
| --- | --- |
| [qwen.py](qwen.py) | 固定revisionの教師モデルのロード、チャット形式への整形、生成、由来情報の収集 |
| [phrase_filters.py](phrase_filters.py) | 候補文字列の正規化と形式検査。標準ライブラリのみ |
| [op_seeds.yaml](op_seeds.yaml) | 各opの意味・正例・禁止語と共通の生成指示。人間が管理する入力資産 |
| [../build_phrases.py](../build_phrases.py) | プロンプト本文を作り、教師生成とフィルタを呼び、候補と実行記録を保存 |
| [../review_phrases.py](../review_phrases.py) | 候補を人間が承認・棄却し、辞書と由来情報へ反映 |

## qwen.py

`import` すると教師用の推論ライブラリが必要です。
`build_phrases.py` は必要になるまでこのimportを遅らせ、dry-runをモデルなしで動かします。

### 定数

| 名前 | 現在の値・用途 |
| --- | --- |
| `MODEL_ID` | `Qwen/Qwen3-4B-AWQ` |
| `REVISION` | `74d4bd2bd4bff9cafc9345221320bffb08b406a3`。モデルとtokenizerに同じrevisionを指定 |
| `BACKEND_NAME` | `BACKEND.AWQ_GEMM_TRITON`。ロード時に明示 |
| `QUANTIZATION` | 由来情報の表示名 `AWQ (4bit)` |
| `ENABLE_THINKING` | `False`。チャットテンプレートに渡し、由来にも記録 |

この定数群は実行時の由来に反映されます。ただし、後段の `build_dataset.py` には
教師ID・revisionの別定義があります。教師を変える場合に全生成物の表示が自動で追従する
わけではないため、[データの由来](../../data/README.md)も参照してください。

### 関数

| 関数 | 入出力・役割 |
| --- | --- |
| `provenance()` | モデル識別子・revision・量子化表示・backend・thinking設定、呼び出し時のPython/ライブラリ版、利用可能ならGPU名とcompute capabilityを辞書で返す。速度・VRAM使用量・日時は測定しない |
| `load()` | 固定revisionとbackend、`device="cuda:0"` でモデルを読み、同revisionのtokenizerと合わせて `(model, tokenizer)` を返す |
| `build_prompt(tokenizer, user, system=None)` | 任意のsystem文とuser文をチャットテンプレートへ渡す。非thinking設定では空のthinkブロックが含まれるかassertする |
| `generate(model, tokenizer, text, *, max_new_tokens, seed, temperature=None, top_p=0.95)` | torchのseedを設定し、1プロンプト生成する。prompt部分を除き、`(completion, 生成トークン数, 秒数)` を返す。`temperature=None` は貪欲法、それ以外はsampling |

`build_prompt` は言い換え指示の本文を作りません。本文は呼び出し側の担当です。
生成の由来は `build_phrases.py` が `data/teacher/phrases_runs.jsonl` へ記録します。
各候補の `run_id` から実行環境をたどれます。旧 `manifest.json` は最新実行全体の代わりにはなりません。

## phrase_filters.py

生成された言い回しの正規化と、機械的に判定できる棄却。

**このモジュールは意味の正しさを判定しない。** 見るのは形式だけ——文型・長さ・使用禁止語・
`k`の出現回数・重複である。日本語がopの意味と一致するかは、`review_phrases.py`で人間が確認する。後段の実行検証はコードとASTの一致を調べるもので、日本語の意味を読み取って検証するものではない。`qwen.py`に依存しないので、GPU無しで単体
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
| `not_terminal_form` | 末尾が `TERMINAL_KANA` に含まれない。文法解析で終止形を判定するわけではない |
| `k_missing` / `k_multiple` | `k`参照opなのに検査用リテラルが無い／2つ以上ある |
| `unexpected_literal` | `k`を取らないopなのに検査用リテラルが出た（`double`が「7倍する」と言うような取り違え） |
| `forbidden:<語>` | `op_seeds.yaml`の`forbid`に挙げた語を含む |
| `duplicate` | 既出の言い回しと同一 |

## op_seeds.yaml

24opの言い回しを生成させるための「種」。**人間が書く資産**であり、生成物ではない。教師モデルがopの意味を取り違えることがある（`reverse`と`desc`、`every_other`の「1個おき」など、
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
「を」なので崩れる。現在は4カテゴリを接続しやすい「〜に対して」の形を採用している。

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
