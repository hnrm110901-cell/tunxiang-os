"""Tier1-gate import-only carve-out: detect_import_only_diff.py 单元测试。

覆盖 issue #417 实施方案 1（流程 3 §"根治 follow-up"）。
TDD 6+ 边界场景全集，验证 carve-out 既不放过真业务 PR，也不阻塞纯 codemod PR。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "detect_import_only_diff.py"


def _run_script(base: str, head: str, cwd: Path) -> tuple[str, int]:
    """Invoke detect_import_only_diff.py against a temp git repo. Returns (stdout, returncode)."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--base", base, "--head", head],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip(), proc.returncode


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create an isolated git repo with an initial commit on `main`."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    return tmp_path


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    return sha


# ---- Carve-out should TRIGGER (output: true) ----


def test_pure_from_import_change_returns_true(tmp_repo: Path) -> None:
    """纯 from-import 路径切换 → carve-out 通过。"""
    base = _commit(
        tmp_repo,
        {"a.py": "from foo import bar\n\ndef f():\n    return bar()\n"},
        "init",
    )
    head = _commit(
        tmp_repo,
        {"a.py": "from foo.baz import bar\n\ndef f():\n    return bar()\n"},
        "rename import",
    )
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    assert out == "true"


def test_pure_import_change_returns_true(tmp_repo: Path) -> None:
    """纯 import-as 路径切换 → carve-out 通过。"""
    base = _commit(tmp_repo, {"a.py": "import foo\n"}, "init")
    head = _commit(tmp_repo, {"a.py": "import foo.bar as foo\n"}, "rename import")
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    assert out == "true"


def test_indented_lazy_import_change_returns_true(tmp_repo: Path) -> None:
    """函数体内 lazy import（缩进 from）切换 → carve-out 通过（覆盖决策 84 第 1/2/6 轮场景）。"""
    base = _commit(
        tmp_repo,
        {"a.py": "def f():\n    from foo import bar\n    return bar()\n"},
        "init",
    )
    head = _commit(
        tmp_repo,
        {"a.py": "def f():\n    from foo.baz import bar\n    return bar()\n"},
        "lazy import rename",
    )
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    assert out == "true"


def test_import_with_blank_lines_returns_true(tmp_repo: Path) -> None:
    """import 改动伴随空行调整 → 仍 carve-out 通过。"""
    base = _commit(
        tmp_repo,
        {"a.py": "from foo import bar\nfrom foo import baz\n"},
        "init",
    )
    head = _commit(
        tmp_repo,
        {"a.py": "from foo.x import bar\n\nfrom foo.x import baz\n"},
        "import + blank",
    )
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    assert out == "true"


def test_pure_deletion_of_import_returns_true(tmp_repo: Path) -> None:
    """删 import 行 → carve-out 通过。"""
    base = _commit(
        tmp_repo,
        {"a.py": "import foo\nimport bar\n"},
        "init",
    )
    head = _commit(
        tmp_repo,
        {"a.py": "import foo\n"},
        "remove unused",
    )
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    assert out == "true"


def test_multi_file_all_import_only_returns_true(tmp_repo: Path) -> None:
    """多文件混合，全部 import-only → carve-out 通过。"""
    base = _commit(
        tmp_repo,
        {
            "a.py": "from foo import bar\n",
            "b.py": "import baz\n",
        },
        "init",
    )
    head = _commit(
        tmp_repo,
        {
            "a.py": "from foo.x import bar\n",
            "b.py": "import baz.y as baz\n",
        },
        "all imports",
    )
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    assert out == "true"


# ---- Carve-out should NOT TRIGGER (output: false) ----


def test_business_logic_change_returns_false(tmp_repo: Path) -> None:
    """业务代码改 → carve-out 不通过。"""
    base = _commit(
        tmp_repo,
        {"a.py": "from foo import bar\n\ndef f():\n    return bar()\n"},
        "init",
    )
    head = _commit(
        tmp_repo,
        {"a.py": "from foo import bar\n\ndef f():\n    return bar() + 1\n"},
        "behavior change",
    )
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    assert out == "false"


def test_mixed_import_and_business_returns_false(tmp_repo: Path) -> None:
    """import 改 + 业务改混合 → carve-out 不通过（任一非 import → false）。"""
    base = _commit(
        tmp_repo,
        {"a.py": "from foo import bar\n\ndef f():\n    return bar()\n"},
        "init",
    )
    head = _commit(
        tmp_repo,
        {"a.py": "from foo.x import bar\n\ndef f():\n    return bar() * 2\n"},
        "import + behavior",
    )
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    assert out == "false"


def test_docstring_only_change_returns_false(tmp_repo: Path) -> None:
    """仅 docstring 改 → carve-out 不通过（不是 import）。"""
    base = _commit(
        tmp_repo,
        {"a.py": '"""old doc."""\n\nimport foo\n'},
        "init",
    )
    head = _commit(
        tmp_repo,
        {"a.py": '"""new doc."""\n\nimport foo\n'},
        "doc change",
    )
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    assert out == "false"


def test_non_python_file_change_returns_false(tmp_repo: Path) -> None:
    """非 Python 文件改 → 保守 false（避免漏过非 .py 业务文件，如 yaml / sql）。"""
    base = _commit(
        tmp_repo,
        {
            "a.py": "import foo\n",
            "config.yaml": "key: old\n",
        },
        "init",
    )
    head = _commit(
        tmp_repo,
        {
            "a.py": "import foo.x as foo\n",
            "config.yaml": "key: new\n",
        },
        "py + yaml",
    )
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    assert out == "false"


def test_multi_file_one_business_returns_false(tmp_repo: Path) -> None:
    """多文件混合，任一非 import-only → carve-out 不通过。"""
    base = _commit(
        tmp_repo,
        {
            "a.py": "from foo import bar\n",
            "b.py": "import baz\n\ndef g():\n    return baz()\n",
        },
        "init",
    )
    head = _commit(
        tmp_repo,
        {
            "a.py": "from foo.x import bar\n",
            "b.py": "import baz\n\ndef g():\n    return baz() + 1\n",
        },
        "import-only + behavior",
    )
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    assert out == "false"


def test_comment_only_change_returns_false(tmp_repo: Path) -> None:
    """仅注释改 → carve-out 不通过（无业务行为变化但也不是 import 沉淀）。"""
    base = _commit(
        tmp_repo,
        {"a.py": "import foo\n# old comment\n"},
        "init",
    )
    head = _commit(
        tmp_repo,
        {"a.py": "import foo\n# new comment\n"},
        "comment",
    )
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    assert out == "false"


# ---- Edge cases ----


def test_no_changes_returns_false(tmp_repo: Path) -> None:
    """空 diff → carve-out 不通过（保守 — 让原 gate 逻辑判）。"""
    base = _commit(tmp_repo, {"a.py": "import foo\n"}, "init")
    out, rc = _run_script(base, base, tmp_repo)
    assert rc == 0
    assert out == "false"


def test_semicolon_compound_from_returns_false(tmp_repo: Path) -> None:
    """``from X import Y; side_effect()`` 复合语句 → carve-out 不通过（PR #419 P0 attack vector）。

    code review 发现 ``IMPORT_LINE_RE`` 的 from 分支用 ``\\S.*`` 贪婪匹配吞 ``;
    side_effect()``，让伪 import 行假装是纯 import。修复改为 ``[^;\\n]+`` 排除分号。
    """
    base = _commit(tmp_repo, {"a.py": "from foo import bar\n"}, "init")
    head = _commit(
        tmp_repo,
        {"a.py": "from foo.x import bar; _register(bar)\n"},
        "compound statement disguised as from-import",
    )
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    assert out == "false"


def test_semicolon_compound_import_returns_false(tmp_repo: Path) -> None:
    """``import X; side_effect()`` 复合语句 → carve-out 不通过（import 分支天然拒绝，补显式覆盖）。"""
    base = _commit(tmp_repo, {"a.py": "import foo\n"}, "init")
    head = _commit(
        tmp_repo,
        {"a.py": "import foo; foo.initialize()\n"},
        "compound statement disguised as import",
    )
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    assert out == "false"


def test_stub_key_setdefault_change_returns_false(tmp_repo: Path) -> None:
    """conftest stub key setdefault 改 → 非 import-only（决策 84 第 3 轮 stub key 是单独 lesson lane，不计入 carve-out）。"""
    base = _commit(
        tmp_repo,
        {"conftest.py": 'sys.modules.setdefault("services.x", mod)\n'},
        "init",
    )
    head = _commit(
        tmp_repo,
        {"conftest.py": 'sys.modules.setdefault("services.x.src", mod)\n'},
        "stub rename",
    )
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    assert out == "false"


def test_script_handles_invalid_sha_with_nonzero_exit(tmp_repo: Path) -> None:
    """无效 SHA → exit 非零（不静默吞错）。"""
    _commit(tmp_repo, {"a.py": "import foo\n"}, "init")
    _, rc = _run_script("deadbeef0000", "feedface0000", tmp_repo)
    assert rc != 0


def test_pep328_relative_import_returns_true(tmp_repo: Path) -> None:
    """相对 import (`from .x import y`) → carve-out 通过。"""
    base = _commit(
        tmp_repo,
        {"pkg/__init__.py": "", "pkg/a.py": "from .x import y\n"},
        "init",
    )
    head = _commit(
        tmp_repo,
        {"pkg/__init__.py": "", "pkg/a.py": "from ..x import y\n"},
        "relative rename",
    )
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    assert out == "true"


def test_multiline_import_paren_returns_false_conservative(tmp_repo: Path) -> None:
    """多行 import `from x import (\\n    a,\\n    b,\\n)` 续行的中间行 → 保守 false。

    续行内仅 identifier，没 `from`/`import` 关键字。本 carve-out 第一版不解析 AST
    续行，遇到这类形式保守判 false（让原 gate 走，不冒险通过）。未来 issue 可升级 AST 检测。
    """
    base = _commit(
        tmp_repo,
        {"a.py": "from foo import a\n"},
        "init",
    )
    head = _commit(
        tmp_repo,
        {"a.py": "from foo import (\n    a,\n    b,\n)\n"},
        "to multiline",
    )
    out, rc = _run_script(base, head, tmp_repo)
    assert rc == 0
    # 第一版保守 — 续行里有非 from/import 行 → false
    assert out == "false"
