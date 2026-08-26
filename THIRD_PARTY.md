# THIRD_PARTY.md

このプロジェクトが合成データ生成に使う第三者資産（教師モデル）の来歴と、その扱いの記録。
課題文「ライセンスと来歴管理」の8項目に沿って、現状を正直に記す（満たしている項目・
まだ満たしていない項目の両方を書く）。

## 教師モデル

| 項目 | 値 |
| --- | --- |
| モデル名 | `Qwen/Qwen3-4B-AWQ` |
| ライセンス | Apache License 2.0 |
| revision（固定） | `74d4bd2bd4bff9cafc9345221320bffb08b406a3` |
| 量子化 | AWQ (4bit) |
| 推論バックエンド | `BACKEND.AWQ_GEMM_TRITON` |
| thinkingモード | 無効 |
| モデルカード | https://huggingface.co/Qwen/Qwen3-4B-AWQ |
| LICENSE原文の場所（HF上） | https://huggingface.co/Qwen/Qwen3-4B-AWQ/blob/main/LICENSE |

revisionは`scripts/teacher/qwen.py`の`REVISION`定数で固定しており、生成実行ごとに
`data/teacher/phrases_runs.jsonl`の`model.revision`にも記録される（全33回のrunで
この値と一致することを確認済み）。

### 何に使ったか / 使っていないか

- **使った**: 日本語表現辞書（`phrases/ja_phrases_v1.yaml`）の元になる言い換え候補の生成
  （`scripts/build_phrases.py`）。「偶数だけを残す」のような1op単位の短い言い換えだけを
  作らせている。
- **使っていない**: 正解コードの生成。`src/codegen/codegen.py`はルールベースの生成器で、
  教師モデルにもインターネット上のコードにも触れない（後述）。意味ASTの構造（どのopを
  どう組み合わせるか）も教師モデルには決めさせていない（`src/semantics/`がルールベースで
  全数列挙する）。

## 8項目それぞれの状況

| # | 項目 | 状況 |
| --- | --- | --- |
| 1 | 使用したモデルのLICENSEを保存する | ✅ `THIRD_PARTY_LICENSES/Qwen3-4B-AWQ-LICENSE.txt`にHF上のLICENSE原文をそのまま保存（201行、Apache License 2.0） |
| 2 | 正確なモデルrevisionを固定する | ✅ 上記の通り。`qwen.py`のコード上の定数と、全生成runの記録が一致することを確認済み |
| 3 | 教師プロンプトと生成条件を保存する | ✅ `data/teacher/prompts.jsonl`（投げた全文、418行）・`data/teacher/phrases_runs.jsonl`（sampling設定・ライブラリ版など、33run） |
| 4 | インターネットから取得したコードを合成データへ混入させない | ✅ 満たしている（構造的に）。正解コードは`codegen.py`のテンプレートだけから生成され、実行時も`src/verify/safety.py`の許可リスト（`abs`/`sorted`/`list`/`reversed`と`.append`のみ）を通るコードしか採用しない。この許可リストの外にあるものは存在し得ない |
| 5 | 既存コードとの長い一致を検査する | ❌ **未実施**。上記④の構造的な理由（許可リストの狭さ）から、既存コードとの偶発的な長い一致が起きる可能性自体は低いと考えているが、実際に検査するスクリプトはまだ書いていない |
| 6 | 自作テンプレートとルール生成物を中心にする | ✅ コード生成（`src/codegen/`）・日本語文組み立て（`src/nlg/`）・意味ASTの列挙（`src/semantics/`）はすべて自作のルールベース実装。教師モデルが関与するのは言い換え候補の生成だけで、そこも人間の査読（`scripts/review_phrases.py`）を必ず通す |
| 7 | THIRD_PARTY.mdを作成する | ✅ 本ファイル |
| 8 | Dataset CardとModel Cardに生成方法を明記する | ❌ **未着手**。Dataset Card・Model Card自体をまだ書いていない（別途の作業） |

## 保留にしている項目について

⑤「既存コードとの長い一致を検査する」と⑧「Dataset Card/Model Cardの作成」は、
本ファイル作成時点(2026-08-23)ではまだ手を付けていない。⑤は生成コードの構造が
極端に狭い（許可リストで4関数＋1メソッドしか使えない）ため優先度を下げているが、
検査自体は行っていないので「検査済み」とは言えない。⑧はモデル学習（Phase 3〜5）が
進んだ段階で書く方が自然なため、現時点では先送りにしている。
