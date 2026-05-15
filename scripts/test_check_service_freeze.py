"""
test_check_service_freeze.py — unit tests for check-service-freeze.py

Run:
    pytest scripts/test_check_service_freeze.py -v
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


# load script (hyphen in name, use importlib)
_SCRIPT = Path(__file__).resolve().parent / "check-service-freeze.py"
_spec = importlib.util.spec_from_file_location("check_service_freeze", _SCRIPT)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
_check_violations = _mod._check_violations
_git_changed_files = _mod._git_changed_files


class TestCheckViolations:
    forbidden = [
        "services/tx-*/main.py",
        "services/tx-*/src/main.py",
        "services/tx-*/Dockerfile",
    ]
    allowed = ["tx-trade", "tx-agent", "tx-pay"]

    def test_existing_service_main_py_not_violation(self) -> None:
        """改已存在服务的 main.py 不违规."""
        files = [
            "services/tx-trade/src/main.py",
            "services/tx-agent/src/main.py",
        ]
        violations = _check_violations(files, self.forbidden, self.allowed)
        assert violations == []

    def test_new_service_dir_violates(self) -> None:
        """新建未在 allowed 的 services/tx-X/main.py 触发违规."""
        files = [
            "services/tx-newservice/src/main.py",
            "services/tx-trade/src/main.py",  # 不违规
        ]
        violations = _check_violations(files, self.forbidden, self.allowed)
        assert len(violations) == 1
        assert violations[0][0] == "services/tx-newservice/src/main.py"

    def test_new_service_dockerfile_violates(self) -> None:
        """新建 Dockerfile 也违规 (任一 forbidden_pattern 命中)."""
        files = ["services/tx-evil/Dockerfile"]
        violations = _check_violations(files, self.forbidden, self.allowed)
        assert len(violations) == 1
        assert "Dockerfile" in violations[0][1]

    def test_non_service_files_ignored(self) -> None:
        """非 services/ 路径完全忽略."""
        files = [
            "scripts/foo.py",
            "docs/readme.md",
            "shared/ontology/customer.py",
            "edge/mac-station/foo.py",
        ]
        violations = _check_violations(files, self.forbidden, self.allowed)
        assert violations == []

    def test_apps_not_affected(self) -> None:
        """apps/ 目录不在 policy scope (前端不属服务收敛)."""
        files = [
            "apps/web-pos/src/App.tsx",
            "apps/web-newshell/main.ts",
        ]
        violations = _check_violations(files, self.forbidden, self.allowed)
        assert violations == []


class TestGitChangedFilesAllMode:
    """regression guard for §19 round-1 P1-2: rename (R 状态码) 必须被抓."""

    def test_rename_status_code_captured(self, monkeypatch) -> None:
        """git status --porcelain `R  old -> new` rename 必须抓 new path.

        旧实现 `if status.startswith("??") or "A" in status` 漏 'R' 整个状态码,
        让 `git mv services/tx-trade services/tx-evil` 静默放过 policy.
        """
        import subprocess as _sp

        class _FakeResult:
            def __init__(self, stdout: str) -> None:
                self.stdout = stdout
                self.returncode = 0

        # 模拟 status: A (新增 normal) / R (rename) / M (modify, 不应抓) / ?? (untracked)
        fake_stdout = (
            "A  services/tx-newsvc/src/main.py\n"
            "R  services/tx-old/src/main.py -> services/tx-evil/src/main.py\n"
            " M services/tx-trade/src/services/cashier_engine.py\n"
            "?? scripts/sketch.py\n"
        )

        def fake_run(cmd, **kwargs):
            return _FakeResult(fake_stdout)

        monkeypatch.setattr(_sp, "run", fake_run)
        files = _git_changed_files("all", None)

        assert "services/tx-newsvc/src/main.py" in files, "A (added) 应被抓"
        assert "services/tx-evil/src/main.py" in files, (
            "R (rename) new path 应被抓 — 旧实现漏掉, 让 git mv 静默绕过 policy"
        )
        assert "scripts/sketch.py" in files, "?? (untracked) 应被抓"
        assert "services/tx-trade/src/services/cashier_engine.py" not in files, (
            "M (modify only) 不应抓 — policy 只拦新文件不拦改文件"
        )
