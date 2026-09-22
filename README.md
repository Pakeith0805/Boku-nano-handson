# Boku-nano handson

日本語の指示から、整数リストを処理する `solve(xs, k)` を生成する小型言語モデルの実習プロジェクトです。意味ASTと正解コードの生成、言い回しの査読、トークナイザの学習、Transformerの訓練・評価までを扱います。

全部自分の手で実装してみる。AIは使うが、エージェントに実装を任せず、自分で理解しながら進める、という方針です。

## 読み始める場所

| 知りたいこと | ドキュメント |
| --- | --- |
| 全体の構成とファイルの役割 | [ファイル地図](src/README.md) |
| データ生成・訓練・評価の実行方法 | [scripts/README.md](scripts/README.md) |
| モデル、データローダ、生成、checkpoint | [model/README.md](model/README.md) |
| データの形式と分割の制約 | [Dataset Card](data/dataset/README.md) |
| 生成物と由来の保存先 | [data/README.md](data/README.md) |
| トークナイザの版の違い | [tokenizer.md](data/tokenizer/tokenizer.md) |
| 実験の履歴 | [EXPERIMENTS.md](EXPERIMENTS.md) |
| 教師モデルの来歴 | [THIRD_PARTY.md](THIRD_PARTY.md) |

## 実行環境と最小の確認

リポジトリのルートで実行します。Pythonは `.python-version` の3.12.13、依存は `pyproject.toml` と `uv.lock` を参照してください。生成コードの実行検証は `signal.setitimer` を使うため、Unix系OSのメインスレッドで動かします。

```bash
uv sync --group dev
uv run python -m scripts.try_codegen --ops asc,take_first
uv run pytest
```

モデルの訓練・評価には `uv sync --group train`、教師モデルによる言い回し生成には `uv sync --group teacher` を使います。両方を同じ環境へ入れる場合は両グループを指定します。

## データからモデルまで

```text
固定入力集合 → 意味AST ───────────────┐
教師モデル → 言い回し候補 → 人間の査読 ├→ データセット → BPE → 訓練 → 評価
固定入力集合 ────────────────────────┘
```

承認済み辞書は `phrases/` にあります。大きなJSONLやcheckpointは手元で生成するファイルもあるため、取得直後にすべてが揃うとは限りません。必要な入力とコマンドの順序は [scripts/README.md](scripts/README.md) を参照してください。

対象は24操作を重複なく1〜4個並べた問題です。固定入力での一致率は、この限定タスク上の評価であり、任意のPythonプログラムの正しさを示すものではありません。
