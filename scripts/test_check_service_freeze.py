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
