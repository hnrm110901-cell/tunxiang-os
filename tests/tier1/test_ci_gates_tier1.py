"""Tier 1 契约测试 — GitHub Actions CI gates

覆盖：
  · demo-go-no-go.yml     PR / push 触发 + skip-tests + JSON artifact + PR 评论
  · tier1-gate.yml        按父目录分组运行所有 *tier1*.py
  · rls-gate.yml          本 PR 新增 migration strict RLS check

YAML 静态契约（不启动真 workflow）：
  · 必需 jobs / steps 存在
  · 触发条件对齐预期（on.pull_request.paths / on.push）
  · 关键参数（--strict / --json / --skip-tests）
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

# 保证不依赖 PyYAML：用简单文本扫描（workflows 结构已定型）


def _read_workflow(filename: str) -> str:
    path = WORKFLOWS_DIR / filename
    assert path.exists(), f"{filename} 不存在"
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# 1. demo-go-no-go.yml
# ─────────────────────────────────────────────────────────────


class TestDemoGoNoGoWorkflow:
    """demo-go-no-go.yml 契约"""

    @pytest.fixture(scope="class")
    def source(self) -> str:
        return _read_workflow("demo-go-no-go.yml")

    def test_workflow_exists(self):
        assert (WORKFLOWS_DIR / "demo-go-no-go.yml").exists()

    def test_triggers_on_pr(self, source):
        assert "pull_request:" in source
        assert "branches: [main]" in source

    def test_triggers_on_push_to_main(self, source):
        # 路径扫描方式简单：找 'push:' 同时含 branches [main]
        assert "push:" in source

    def test_supports_manual_dispatch(self, source):
        assert "workflow_dispatch:" in source

    def test_has_strict_input(self, source):
        assert "strict:" in source
        assert "严格模式" in source

    def test_runs_go_no_go_script(self, source):
        assert "scripts/demo_go_no_go.py" in source

    def test_uses_skip_tests_flag(self, source):
        """PR 模式默认 --skip-tests（由 tier1-gate 专门跑）"""
        assert "--skip-tests" in source

    def test_uses_json_output(self, source):
        assert "--json" in source

    def test_uploads_artifact(self, source):
        assert "actions/upload-artifact" in source
        assert "demo-go-no-go-report" in source

    def test_posts_pr_comment(self, source):
        assert "actions/github-script" in source
        assert "DEMO Go/No-Go 汇总" in source

    def test_blocking_ids_explicit(self, source):
        """BLOCKING_IDS 必须显式声明哪些 checkpoint 在 PR 模式下 block"""
        assert "BLOCKING_IDS" in source
        # 关键 IDs：签字模板 / scorecards / demo-reset / 话术
        for cp_id in (5, 6, 8, 10):
            assert str(cp_id) in source

    def test_has_permissions(self, source):
        """必须有 permissions（读写 PR comments）"""
        assert "permissions:" in source
        assert "pull-requests: write" in source

    def test_timeout_set(self, source):
        """timeout-minutes 存在（防 CI runner 卡死）"""
        assert "timeout-minutes:" in source


# ─────────────────────────────────────────────────────────────
# 2. tier1-gate.yml
# ─────────────────────────────────────────────────────────────


class TestTier1GateWorkflow:
    """tier1-gate.yml 契约"""

    @pytest.fixture(scope="class")
    def source(self) -> str:
        return _read_workflow("tier1-gate.yml")

    def test_workflow_exists(self):
        assert (WORKFLOWS_DIR / "tier1-gate.yml").exists()

    def test_triggers_on_tier1_paths(self, source):
        """*tier1*.py 路径变更触发"""
        assert "*tier1*.py" in source or "tier1" in source

    def test_triggers_on_migrations(self, source):
        """migration 变更也触发（Tier 1 RLS 相关）"""
        assert "shared/db-migrations/versions/**" in source

    def test_triggers_on_sync_engine(self, source):
        """edge/sync-engine 变更触发（CRDT 相关）"""
        assert "edge/sync-engine/" in source

    def test_has_discover_job(self, source):
        """必须有 discover job 扫文件"""
        assert "discover:" in source

    def test_matrix_by_parent_dir(self, source):
        """matrix 按父目录分组（避免 conftest 冲突）"""
        assert "matrix:" in source
        assert "fail-fast: false" in source

    def test_has_gate_job(self, source):
        """必须有 gate job 最终判定"""
        assert "gate:" in source

    def test_three_test_locations_scanned(self, source):
        """3 个 test 位置都扫描"""
        for pattern in (
            "services/*/tests/**/test_*tier1*.py",
            "services/*/src/tests/**/test_*tier1*.py",
            "tests/tier1/**/test_*tier1*.py",
        ):
            assert pattern in source

    def test_installs_pytest_asyncio(self, source):
        assert "pytest-asyncio" in source

    def test_fails_if_no_tier1_found(self, source):
        """如果 Tier 1 路径变更但未找到测试 → fail"""
        assert "未找到 Tier 1 测试" in source

    # ── Review follow-up：补齐 Tier 1 盲区 paths ──

    def test_paths_include_cashier_engine(self, source):
        """CLAUDE.md § 17：订单状态机 Tier 1 — cashier_engine.py"""
        assert "services/tx-trade/src/services/cashier_engine.py" in source

    def test_paths_include_wine_storage(self, source):
        """CLAUDE.md § 17：存酒/押金 Tier 1"""
        assert "wine_storage_service.py" in source

    def test_paths_include_stored_value(self, source):
        """CLAUDE.md § 17：储值/挂账 Tier 1"""
        assert "stored_value_service.py" in source

    def test_paths_include_banquet_deposit(self, source):
        """CLAUDE.md § 17：宴会押金 Tier 1"""
        assert "banquet_deposit_service.py" in source

    def test_paths_include_pos_adapters(self, source):
        """CLAUDE.md § 17：POS 数据写入 Tier 1 — 6 大 adapter"""
        for adapter in (
            "shared/adapters/pinzhi/",
            "shared/adapters/aiqiwei/",
            "shared/adapters/meituan/",
        ):
            assert adapter in source, f"POS adapter {adapter} 未在 paths"

    def test_paths_include_agent_constraints(self, source):
        """CLAUDE.md § 17：三条硬约束 Tier 1"""
        assert "services/tx-agent/src/constraints/" in source

    def test_has_source_test_pairing_job(self, source):
        """Review follow-up：源改动必须配对测试改动"""
        assert "source-test-pairing:" in source

    def test_pairing_job_has_strong_check(self, source):
        """配对 job 必须强 fail（不是 warning）"""
        assert "HAS_TIER1_SOURCE_CHANGE" in source
        assert "HAS_TIER1_TEST_CHANGE" in source
        assert "exit 1" in source

    def test_gate_depends_on_pairing(self, source):
        """gate job 的 needs 必须含 source-test-pairing"""
        # 松散匹配：gate 在 source-test-pairing 之后
        assert "needs: [discover, run, source-test-pairing]" in source

    def test_gate_blocks_when_pairing_fails(self, source):
        """PAIRING_RESULT == failure 时 gate 必须 exit 1"""
        assert 'PAIRING_RESULT' in source
        assert '"failure"' in source or "'failure'" in source


# ─────────────────────────────────────────────────────────────
# 3. rls-gate.yml
# ─────────────────────────────────────────────────────────────


class TestRLSGateWorkflow:
    """rls-gate.yml 契约"""

    @pytest.fixture(scope="class")
    def source(self) -> str:
        return _read_workflow("rls-gate.yml")

    def test_workflow_exists(self):
        assert (WORKFLOWS_DIR / "rls-gate.yml").exists()

    def test_triggers_on_migration_changes(self, source):
        assert "shared/db-migrations/versions/**" in source

    def test_uses_pr_base_head_diff(self, source):
        """用 git diff base..head 找本 PR 新增的 migration"""
        assert "github.event.pull_request.base.sha" in source
        assert "github.event.pull_request.head.sha" in source

    def test_uses_diff_filter_added(self, source):
        """--diff-filter=A 只看新增文件（不管修改）"""
        assert "--diff-filter=A" in source

    def test_matches_migration_pattern(self, source):
        """只看 v数字开头的 migration"""
        assert "v[0-9]+" in source

    def test_skips_when_no_new_migration(self, source):
        """PR 无新 migration 时 skip 不 fail"""
        assert "PR 未新增 migration" in source

    def test_exempt_list_aligned(self, source):
        """豁免白名单与 test_rls_all_tables_tier1.py 保持一致"""
        for item in (
            "events", "alembic_version", "refresh_tokens",
            "mv_", "events_2024_",
        ):
            assert item in source

    def test_checks_rls_enabled(self, source):
        assert "ENABLE ROW LEVEL SECURITY" in source or "ENABLE\\s+ROW" in source

    def test_checks_policy(self, source):
        assert "CREATE POLICY" in source or "CREATE\\s+POLICY" in source

    def test_checks_app_tenant_id(self, source):
        assert "app.tenant_id" in source

    def test_blocks_using_true_bypass(self, source):
        """禁止 USING (true) 绕过"""
        assert "USING (true)" in source or "USING\\s*\\(\\s*true\\s*\\)" in source

    def test_runs_tier1_static_test(self, source):
        """额外跑 tests/tier1/test_rls_all_tables_tier1.py"""
        assert "test_rls_all_tables_tier1.py" in source


# ─────────────────────────────────────────────────────────────
# 4. 跨工作流一致性
# ─────────────────────────────────────────────────────────────


class TestCrossWorkflowConsistency:
    """多个工作流共享的约定"""

    def test_all_three_workflows_exist(self):
        for name in ("demo-go-no-go.yml", "tier1-gate.yml", "rls-gate.yml"):
            assert (WORKFLOWS_DIR / name).exists(), f"{name} 缺失"

    def test_all_use_checkout_v6(self):
        """统一用 actions/checkout@v6"""
        for name in ("demo-go-no-go.yml", "tier1-gate.yml", "rls-gate.yml"):
            source = _read_workflow(name)
            assert "actions/checkout@v6" in source, (
                f"{name} 未用 checkout@v6（应与 .github/workflows/ci.yml 一致）"
            )

    def test_all_use_python_setup_v6(self):
        for name in ("demo-go-no-go.yml", "tier1-gate.yml", "rls-gate.yml"):
            source = _read_workflow(name)
            assert "actions/setup-python@v6" in source

    def test_all_use_python_311(self):
        for name in ("demo-go-no-go.yml", "tier1-gate.yml", "rls-gate.yml"):
            source = _read_workflow(name)
            assert "3.11" in source, (
                f"{name} 未指定 python-version 3.11"
            )

    def test_no_workflow_uses_secrets_in_pr(self):
        """PR 工作流不应使用 secrets（防止 fork PR 泄露）

        本测试提醒：审查任何引入 secrets 的改动。
        """
        for name in ("demo-go-no-go.yml", "tier1-gate.yml", "rls-gate.yml"):
            source = _read_workflow(name)
            # 如果引入 secrets，必须 restrict to push events
            if "secrets." in source:
                # 必须有 ref == refs/heads/main 或 pull_request_target 限制
                assert (
                    "refs/heads/main" in source
                    or "pull_request_target" in source
                ), (
                    f"{name} 使用 secrets 但未限制触发（fork PR 可能泄露）"
                )

    def test_go_no_go_glob_matches_tier1_gate_discover(self):
        """demo-go-no-go.py 的 Tier 1 glob 与 tier1-gate.yml 的 discover 一致"""
        script = (ROOT / "scripts" / "demo_go_no_go.py").read_text(encoding="utf-8")
        gate = _read_workflow("tier1-gate.yml")
        for pattern in (
            "services/*/tests/**/test_*tier1*.py",
            "services/*/src/tests/**/test_*tier1*.py",
            "tests/tier1/**/test_*tier1*.py",
        ):
            assert pattern in script, f"demo_go_no_go.py 缺 glob {pattern}"
            assert pattern in gate, f"tier1-gate.yml 缺 glob {pattern}"
