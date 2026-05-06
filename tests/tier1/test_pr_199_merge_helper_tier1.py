"""PR #199 merge helper 静态测试

验证 helper 脚本 + checklist 文档存在且关键内容齐全。
真 alembic 链验证留 release manager 在 merge 时跑 helper 脚本本身。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_HELPER_SCRIPT = _REPO_ROOT / "scripts" / "db" / "check_alembic_head_for_pr_199.sh"
_CHECKLIST = _REPO_ROOT / "docs" / "runbooks" / "pr-199-merge-checklist.md"


class TestFilesExist:
    def test_helper_script_exists(self):
        assert _HELPER_SCRIPT.exists()

    def test_helper_script_executable(self):
        assert os.access(_HELPER_SCRIPT, os.X_OK)

    def test_checklist_exists(self):
        assert _CHECKLIST.exists()


class TestHelperScript:
    """脚本内容关键字"""

    def test_finds_alembic_heads(self):
        content = _HELPER_SCRIPT.read_text(encoding="utf-8")
        assert "down_revision" in content
        assert "head" in content.lower()
        # 用 comm 找 head（revision 不被 down_revision 引用）
        assert "comm -23" in content

    def test_compares_with_pr_199_down_revision(self):
        content = _HELPER_SCRIPT.read_text(encoding="utf-8")
        assert "v500_rls_force_all_business_tables.py" in content
        assert "pr_199_down" in content or "down_revision" in content

    def test_outputs_rebase_command_on_mismatch(self):
        content = _HELPER_SCRIPT.read_text(encoding="utf-8")
        assert "force-with-lease" in content, "rebase 必须用 --force-with-lease"
        assert "amend" in content, "rebase 必须 amend 而非新 commit"
        assert "NEEDS REBASE" in content


class TestChecklistDocStructure:
    """checklist 文档关键章节"""

    def test_lists_blocking_prerequisites(self):
        content = _CHECKLIST.read_text(encoding="utf-8")
        # 必须明示 PR #207 是前置
        assert "PR #207" in content, "checklist 必须明示 PR #207 是前置"
        assert "tx_system_role" in content
        assert "RLS_USE_TX_SYSTEM_ROLE=true" in content
        assert "create_tx_system_role" in content
        assert "revoke_tunxiang_bypassrls" in content

    def test_has_4_steps(self):
        content = _CHECKLIST.read_text(encoding="utf-8")
        # 4 步：核对 head / staging dry-run / merge 灰度 / merge 后验证
        for step in ["步骤 1", "步骤 2", "步骤 3", "步骤 4"]:
            assert step in content, f"checklist 缺 {step}"

    def test_includes_dry_run_commands(self):
        content = _CHECKLIST.read_text(encoding="utf-8")
        assert "alembic upgrade head" in content
        assert "tunxiang_dryrun" in content or "dry-run" in content.lower()

    def test_includes_emergency_rollback(self):
        content = _CHECKLIST.read_text(encoding="utf-8")
        assert "alembic downgrade" in content
        assert "BYPASSRLS" in content  # 紧急回滚需临时恢复

    def test_references_related_docs(self):
        content = _CHECKLIST.read_text(encoding="utf-8")
        for doc in [
            "rls-force-rollout.md",
            "audit-2026-05-cutover.md",
        ]:
            assert doc in content, f"checklist 必须引用 {doc}"

    def test_includes_canary_table(self):
        content = _CHECKLIST.read_text(encoding="utf-8")
        # 灰度阶段表（Canary 1/2/3 + Full）
        for canary in ["Canary 1", "Canary 2", "Canary 3", "Full"]:
            assert canary in content


class TestHelperScriptCanRunSyntax:
    """脚本本身 bash 语法合法（用 bash -n 干跑）"""

    def test_bash_syntax_ok(self):
        import subprocess
        result = subprocess.run(
            ["bash", "-n", str(_HELPER_SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bash 语法错：{result.stderr}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
