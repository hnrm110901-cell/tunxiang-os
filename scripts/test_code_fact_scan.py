"""
test_code_fact_scan.py — unit tests for code-fact-scan.py

Run with:
    pytest scripts/test_code_fact_scan.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import importlib.util

import pytest

# code-fact-scan.py has a hyphen in its name, so we use importlib to load it
_SCRIPT = Path(__file__).resolve().parent / "code-fact-scan.py"
_spec = importlib.util.spec_from_file_location("code_fact_scan", _SCRIPT)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
scan_service = _mod.scan_service
main = _mod.main


def _make_service(tmp_path: Path, name: str, main_content: str) -> Path:
    """Create a fake service directory under tmp_path/services/<name>/src/main.py."""
    svc_dir = tmp_path / "services" / name
    src_dir = svc_dir / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "main.py").write_text(main_content, encoding="utf-8")
    return svc_dir


class TestScanService:
    def test_router_count_and_try_except(self, tmp_path: Path) -> None:
        """Basic router + try/except counts from main.py."""
        # silent_failure patterns: `except Foo: pass` inline (same line)
        content = (
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "app.include_router(router_a)\n"
            "app.include_router(router_b)\n"
            "app.include_router(router_c)\n"
            "def foo():\n"
            "    try:\n"
            "        pass\n"
            "    except ValueError: pass\n"
            "    try:\n"
            "        bar()\n"
            "    except Exception: return None\n"
        )
        svc_dir = _make_service(tmp_path, "svc-a", content)
        stats = scan_service(svc_dir, tmp_path)

        assert stats["service_name"] == "svc-a"
        assert stats["router_count"] == 3
        assert stats["try_except_count"] == 2
        assert stats["silent_failure_count"] == 2
        # main_loc: 12 lines
        assert stats["main_loc"] == 12

    def test_silent_failure_multiline_excepts(self, tmp_path: Path) -> None:
        """AST 必须抓到多行写法 (regression guard for PR #659 round-1 P1-1).

        Mainstream Python style is multi-line `except Foo:\\n    pass`. Old
        regex impl only matched same-line `except Foo: pass` and missed the
        multi-line form, causing W20.md to falsely report 0 silent failures
        across all 20 services. This test is the regression line — if anyone
        reverts to regex, this fails.
        """
        content = (
            "def f():\n"
            "    try: a()\n"             # try #1
            "    except OSError:\n"      # multi-line `pass` — silent #1
            "        pass\n"
            "    try: b()\n"             # try #2
            "    except (TypeError, ValueError):\n"  # multi-line `return None` — silent #2
            "        return None\n"
            "    try: c()\n"             # try #3
            "    except KeyError:\n"     # multi-line bare `return` — silent #3
            "        return\n"
            "    try: d()\n"             # try #4
            "    except RuntimeError:\n"  # NOT silent — has logging
            "        logger.warning('caught', exc_info=True)\n"
            "    try: e()\n"             # try #5
            "    except IOError:\n"      # NOT silent — re-raise
            "        raise\n"
        )
        svc_dir = _make_service(tmp_path, "svc-multi", content)
        stats = scan_service(svc_dir, tmp_path)

        assert stats["try_except_count"] == 5, "应抓 5 个 try 块"
        assert stats["silent_failure_count"] == 3, (
            "应抓 3 个多行 silent (pass / return None / 裸 return), "
            "regex 旧实现会返回 0 — 这是 PR #659 round-1 P1-1 修复的回归门"
        )

    def test_week_override_format_validation(self, tmp_path: Path, capsys, monkeypatch) -> None:
        """--week-override 必须校验 YYYY-WXX 格式, 防 path traversal."""
        # 让 main 跑在 tmp_path 仓库根, 不写到真实仓库
        monkeypatch.chdir(tmp_path)
        (tmp_path / "services").mkdir()  # 防 scan_all 抛 FileNotFoundError

        with pytest.raises(SystemExit) as exc_info:
            main(["--week-override", "../../etc/passwd", "--repo-root", str(tmp_path)])
        # argparse error() exits with code 2
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "YYYY-WXX" in captured.err

    def test_no_main_py_falls_back_to_server_py(self, tmp_path: Path) -> None:
        """When main.py absent, server.py is used for loc/router counts."""
        svc_dir = tmp_path / "services" / "svc-b"
        src_dir = svc_dir / "src"
        src_dir.mkdir(parents=True)
        server_content = (
            "# server.py\n"
            "app = FastAPI()\n"
            "app.include_router(r1)\n"
        )
        (src_dir / "server.py").write_text(server_content, encoding="utf-8")

        stats = scan_service(svc_dir, tmp_path)

        assert stats["service_name"] == "svc-b"
        assert stats["router_count"] == 1
        assert stats["main_loc"] == 3

    def test_missing_src_returns_minus_one(self, tmp_path: Path) -> None:
        """Service with no src/ dir returns main_loc=-1, router_count=0."""
        svc_dir = tmp_path / "services" / "svc-c"
        svc_dir.mkdir(parents=True)

        stats = scan_service(svc_dir, tmp_path)

        assert stats["main_loc"] == -1
        assert stats["router_count"] == 0
        assert stats["try_except_count"] == 0
        assert stats["silent_failure_count"] == 0
