"""`src/` が標準ライブラリだけに依存すること（`pyproject.toml` L6-11, L26-27）。

依存の層は次のとおりで、**この境界は変更しない**と `pyproject.toml` が宣言している。

    src/semantics, src/interp, src/probes  … 標準ライブラリのみ
    scripts/                               … ＋ hydra-core, mlflow
    tests/                                 … ＋ pytest

意味の権威（参照インタプリタ・レジストリ）に外部ライブラリを持ち込まないための境界である。
教師モデルを触るコードが `scripts/teacher/` に閉じているのも同じ線引きで、そちらは
`torch` と `gptqmodel` を要求するため `src/` から import してはならない。

import を実行せず `ast` で静的に読む。実行してしまうと、その時点で入っている依存に
結果が左右されるうえ、副作用のあるモジュールを踏む余地も残る。
"""

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

SOURCE_FILES = sorted(SRC.rglob("*.py"))

# 自リポジトリのパッケージ。標準ライブラリ判定の対象から外す。
LOCAL_ROOTS = {"src"}


def imported_roots(path: Path) -> set[str]:
    """ファイルが import しているトップレベルのモジュール名を集める。

    相対 import（`from . import x`）は外部依存になり得ないので飛ばす。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_source_files_were_found():
    """走査対象が空でないこと。

    パスを間違えて0件を検査し、何も見ていないのに緑になるのが一番まずい。
    """
    assert SOURCE_FILES, f"{SRC} に .py が無い"


@pytest.mark.parametrize(
    "path", SOURCE_FILES, ids=[str(p.relative_to(ROOT)) for p in SOURCE_FILES]
)
def test_module_imports_only_stdlib(path):
    """`src/` 配下の各モジュールが標準ライブラリと自リポジトリしか import しない。"""
    external = {
        name
        for name in imported_roots(path)
        if name not in sys.stdlib_module_names and name not in LOCAL_ROOTS
    }
    assert not external, (
        f"{path.relative_to(ROOT)} が外部ライブラリを import している: {sorted(external)}\n"
        "  意味の権威に外部依存を持ち込まないこと（pyproject.toml の依存の層）。"
    )


@pytest.mark.parametrize(
    "path", SOURCE_FILES, ids=[str(p.relative_to(ROOT)) for p in SOURCE_FILES]
)
def test_module_does_not_import_the_teacher_stack(path):
    """教師モデルの推論スタックを `src/` から触らない。

    上のテストに含まれるが、破ったときの意味が違う（依存が重いだけでなく、
    ルールベースで作るべき部分に教師モデルが入り込む合図になる）ので個別に見る。
    """
    forbidden = {"torch", "transformers", "gptqmodel", "accelerate", "torchvision"}
    hit = imported_roots(path) & forbidden
    assert not hit, f"{path.relative_to(ROOT)} が教師モデルの依存を import している: {sorted(hit)}"
