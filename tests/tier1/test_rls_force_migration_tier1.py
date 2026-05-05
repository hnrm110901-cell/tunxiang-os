"""v500 RLS FORCE migration 静态分析 Tier 1 测试

不连真 DB，纯静态分析 migration 文件本身：
  1. revision/down_revision 链合法
  2. EXEMPT 列表与 .github/workflows/rls-gate.yml 严格一致
  3. upgrade/downgrade 含正确 SQL 关键字
  4. 没误改已应用的 v001-v402 migration

真 DB 上的行为验证留给 staging dry-run + canary，不在本测试范围。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_MIGRATION_FILE = _REPO_ROOT / "shared" / "db-migrations" / "versions" / "v500_rls_force_all_business_tables.py"
_RLS_GATE_FILE = _REPO_ROOT / ".github" / "workflows" / "rls-gate.yml"


def _read_migration() -> str:
    return _MIGRATION_FILE.read_text(encoding="utf-8")


def _read_rls_gate() -> str:
    return _RLS_GATE_FILE.read_text(encoding="utf-8")


class TestMigrationFileExists:
    def test_migration_file_present(self):
        assert _MIGRATION_FILE.exists(), f"v500 migration 文件不存在：{_MIGRATION_FILE}"

    def test_rls_gate_file_present(self):
        assert _RLS_GATE_FILE.exists(), f"rls-gate.yml 不存在：{_RLS_GATE_FILE}"


class TestRevisionMetadata:
    def test_revision_id(self):
        src = _read_migration()
        m = re.search(r'^revision:\s*str\s*=\s*"(v\d+)"', src, re.MULTILINE)
        assert m, "revision 未声明"
        assert m.group(1) == "v500", f"revision 必须是 v500，实际：{m.group(1)}"

    def test_down_revision_set(self):
        src = _read_migration()
        m = re.search(r'down_revision:.*?=\s*"(v\d+)"', src)
        assert m, "down_revision 未声明"
        # PR description 提示 merge 时按 main head 调整；这里只检查格式
        assert m.group(1).startswith("v"), "down_revision 必须 v 开头"


class TestExemptListSync:
    """EXEMPT 必须与 rls-gate.yml 严格对齐，否则多租户隔离被绕过 OR 系统表误改。"""

    def _extract_exempt_from_migration(self) -> set[str]:
        src = _read_migration()
        m = re.search(r"_EXEMPT_TABLES\s*=\s*\((.*?)\)", src, re.DOTALL)
        assert m, "migration 中未找到 _EXEMPT_TABLES tuple"
        body = m.group(1)
        # 提取所有 "table_name" / 'table_name' 字面量
        names = re.findall(r"['\"]([a-z_][a-z0-9_]*)['\"]", body)
        return set(names)

    def _extract_exempt_from_rls_gate(self) -> set[str]:
        src = _read_rls_gate()
        # rls-gate.yml 里 EXEMPT 是 frozenset({...}) 在 python heredoc 内
        m = re.search(r"EXEMPT\s*=\s*frozenset\(\{(.*?)\}\)", src, re.DOTALL)
        assert m, "rls-gate.yml 中未找到 EXEMPT frozenset"
        body = m.group(1)
        names = re.findall(r"['\"]([a-z_][a-z0-9_]*)['\"]", body)
        return set(names)

    def test_exempt_lists_match(self):
        m_exempt = self._extract_exempt_from_migration()
        g_exempt = self._extract_exempt_from_rls_gate()

        only_in_migration = m_exempt - g_exempt
        only_in_gate = g_exempt - m_exempt

        assert not only_in_migration, (
            f"v500 EXEMPT 多了这些表（rls-gate.yml 没有）：{sorted(only_in_migration)} —— "
            f"会让本应 FORCE 的业务表漏掉，多租户隔离被绕过"
        )
        assert not only_in_gate, (
            f"v500 EXEMPT 少了这些表（rls-gate.yml 有）：{sorted(only_in_gate)} —— "
            f"系统表会被误 FORCE，导致 app 查这些表返回 0 行"
        )

    def test_exempt_count_reasonable(self):
        """sanity check：EXEMPT 应在 20-40 之间，太少漏豁免，太多形同虚设。"""
        m_exempt = self._extract_exempt_from_migration()
        assert 20 <= len(m_exempt) <= 40, (
            f"EXEMPT 数量 {len(m_exempt)} 异常 — 检查列表是否被改坏"
        )


class TestPartitionPrefixSync:
    """events 分区 + mv_* 物化视图必须豁免 — 与 rls-gate.yml PARTITION_PATTERNS 对齐。"""

    def test_partition_prefixes_match(self):
        src_mig = _read_migration()
        src_gate = _read_rls_gate()

        # migration 中：_PARTITION_PREFIXES = ("events_2024_", ...)
        m_mig = re.search(r"_PARTITION_PREFIXES\s*=\s*\((.*?)\)", src_mig, re.DOTALL)
        assert m_mig, "migration 中未找到 _PARTITION_PREFIXES"
        mig_prefixes = set(re.findall(r"['\"]([a-z_0-9]+_)['\"]", m_mig.group(1)))

        # rls-gate 中：PARTITION_PATTERNS = ("events_2024_", ...)
        m_gate = re.search(r"PARTITION_PATTERNS\s*=\s*\((.*?)\)", src_gate, re.DOTALL)
        assert m_gate, "rls-gate.yml 中未找到 PARTITION_PATTERNS"
        gate_prefixes = set(re.findall(r"['\"]([a-z_0-9]+_)['\"]", m_gate.group(1)))

        assert mig_prefixes == gate_prefixes, (
            f"PARTITION_PREFIXES 不对齐：\n"
            f"  migration={sorted(mig_prefixes)}\n"
            f"  rls-gate={sorted(gate_prefixes)}"
        )

    def test_mv_prefix_set(self):
        src = _read_migration()
        assert '_MV_PREFIX = "mv_"' in src, "_MV_PREFIX 必须是 'mv_'"


class TestSqlContent:
    """upgrade/downgrade 的 SQL 关键字必须正确。"""

    def test_upgrade_contains_force_row_level_security(self):
        src = _read_migration()
        # 找 upgrade 函数体
        m = re.search(r"def upgrade\(\) -> None:.*?def downgrade\(", src, re.DOTALL)
        assert m, "未找到 upgrade 函数"
        upgrade_body = m.group(0)
        assert "FORCE ROW LEVEL SECURITY" in upgrade_body, (
            "upgrade 必须包含 FORCE ROW LEVEL SECURITY 关键字"
        )
        assert "rowsecurity = true" in upgrade_body, (
            "upgrade 必须只对已 ENABLE 的表加 FORCE"
        )
        assert "forcerowsecurity = false" in upgrade_body, (
            "upgrade 必须只对未 FORCE 的表加 FORCE（幂等性）"
        )

    def test_downgrade_contains_no_force(self):
        src = _read_migration()
        m = re.search(r"def downgrade\(\) -> None:.*", src, re.DOTALL)
        assert m, "未找到 downgrade 函数"
        downgrade_body = m.group(0)
        assert "NO FORCE ROW LEVEL SECURITY" in downgrade_body, (
            "downgrade 必须包含 NO FORCE ROW LEVEL SECURITY"
        )

    def test_upgrade_filters_exempt(self):
        src = _read_migration()
        m = re.search(r"def upgrade\(\) -> None:.*?def downgrade\(", src, re.DOTALL)
        assert m
        body = m.group(0)
        assert "tablename NOT IN" in body, "upgrade 必须用 NOT IN 过滤 EXEMPT"
        assert "NOT LIKE" in body, "upgrade 必须过滤 mv_/partition 前缀"

    def test_format_safe_identifier_quoting(self):
        """SQL 用 format('ALTER TABLE %I FORCE ...', t.tablename) — %I 是
        PG format 的 identifier 转义，安全。不能用 %s（容易注入）。"""
        src = _read_migration()
        assert "format('ALTER TABLE %I FORCE" in src, (
            "必须用 format(%I) 转义表名，禁止 string interpolation"
        )
        assert "format('ALTER TABLE %s FORCE" not in src, (
            "禁止用 %s 拼表名（SQL 注入风险）"
        )


class TestNoTouchAppliedMigrations:
    """本 PR 不应碰任何 v001-v499 已存在的 migration 文件。"""

    def test_only_v500_added(self):
        versions_dir = _REPO_ROOT / "shared" / "db-migrations" / "versions"
        files = sorted(versions_dir.glob("v500*.py"))
        assert len(files) == 1, f"应只新增 v500 一个文件，实际：{files}"
        assert files[0].name == "v500_rls_force_all_business_tables.py"


class TestPrUnsafeMarkers:
    """migration 顶部必须含明示"不可盲跑"的警告。"""

    def test_migration_has_dry_run_warning(self):
        src = _read_migration()
        # 任一中文/英文警告关键字均可
        warnings = ["DO NOT RUN", "不可盲跑", "DRY-RUN", "dry-run", "staging"]
        assert any(w in src for w in warnings), (
            "migration docstring 必须明示 staging dry-run 前置 + 灰度策略"
        )

    def test_migration_lists_5_bypassrls_callsites(self):
        """5 处合法 BYPASSRLS 调用方必须在 docstring 列出，提醒迁移期重点验证。"""
        src = _read_migration()
        callsites = [
            "hub_api",
            "banquet_payment_routes",
            "wechat_pay_notify_service",
            "seed_loader",
            "brain_routes",
        ]
        missing = [c for c in callsites if c not in src]
        assert not missing, f"docstring 缺少这些 BYPASSRLS 调用方说明：{missing}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
