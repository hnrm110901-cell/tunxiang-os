"""
测试 v224 RLS修复迁移 — 验证SQL语法正确且使用 app.tenant_id

验证内容：
  1. 修复迁移的 upgrade() 生成的SQL包含 app.tenant_id（非 app.current_tenant）
  2. 所有6张受影响表都被覆盖
  3. 原始迁移 v206/v207/v208 已被同步修复
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import textwrap
from unittest.mock import MagicMock, call, patch

import pytest

_VERSIONS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "shared", "db-migrations", "versions"
)


def _load_migration(filename: str):
    """动态加载迁移模块"""
    path = os.path.join(_VERSIONS_DIR, filename)
    spec = importlib.util.spec_from_file_location(filename.replace(".py", ""), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 测试1：v224修复迁移覆盖所有受影响表 ──

EXPECTED_TABLES = [
    "corporate_customers",
    "corporate_orders",
    "corporate_bills",
    "aggregator_orders",
    "aggregator_reconcile_results",
    "aggregator_discrepancies",
]


class TestV224FixMigration:
    def test_revision_chain(self):
        mod = _load_migration("v224_fix_rls_tenant_variable.py")
        assert mod.revision == "v224"
        assert mod.down_revision == "v223"

    def test_upgrade_drops_and_creates_all_policies(self):
        mod = _load_migration("v224_fix_rls_tenant_variable.py")
        executed_sql = []
        mock_op = MagicMock()
        mock_op.execute = lambda sql: executed_sql.append(sql)

        with patch.object(mod, "op", mock_op):
            mod.upgrade()

        # 每张表应有2条SQL：DROP + CREATE
        assert len(executed_sql) == len(EXPECTED_TABLES) * 2

        for table in EXPECTED_TABLES:
            drop_stmts = [s for s in executed_sql if f"DROP POLICY" in s and table in s]
            create_stmts = [s for s in executed_sql if f"CREATE POLICY" in s and table in s]
            assert len(drop_stmts) == 1, f"Missing DROP for {table}"
            assert len(create_stmts) == 1, f"Missing CREATE for {table}"

            # 验证新策略使用 app.tenant_id
            assert "app.tenant_id" in create_stmts[0], f"{table} CREATE不包含 app.tenant_id"
            # 验证新策略不使用 app.current_tenant
            assert "app.current_tenant" not in create_stmts[0], (
                f"{table} CREATE仍包含错误的 app.current_tenant"
            )
            # 验证包含 WITH CHECK
            assert "WITH CHECK" in create_stmts[0], f"{table} CREATE缺少 WITH CHECK"

    def test_upgrade_uses_if_exists_on_drop(self):
        mod = _load_migration("v224_fix_rls_tenant_variable.py")
        executed_sql = []
        mock_op = MagicMock()
        mock_op.execute = lambda sql: executed_sql.append(sql)

        with patch.object(mod, "op", mock_op):
            mod.upgrade()

        drop_stmts = [s for s in executed_sql if "DROP POLICY" in s]
        for stmt in drop_stmts:
            assert "IF EXISTS" in stmt, f"DROP语句缺少 IF EXISTS: {stmt}"


# ── 测试2：原始迁移文件已修复 ──

class TestOriginalMigrationsFixed:
    def test_v206_no_current_tenant_in_policy(self):
        path = os.path.join(_VERSIONS_DIR, "v206_corporate_customers.py")
        with open(path) as f:
            content = f.read()
        # 检查USING子句中不再有 app.current_tenant
        policies = re.findall(r"USING\s*\(.*?\)", content, re.DOTALL)
        for p in policies:
            assert "app.current_tenant" not in p, f"v206仍包含 app.current_tenant: {p}"
            assert "app.tenant_id" in p, f"v206 USING子句缺少 app.tenant_id: {p}"

    def test_v207_no_current_tenant_in_policy(self):
        path = os.path.join(_VERSIONS_DIR, "v207_delivery_aggregator.py")
        with open(path) as f:
            content = f.read()
        policies = re.findall(r"USING\s*\(.*?\)", content, re.DOTALL)
        for p in policies:
            assert "app.current_tenant" not in p, f"v207仍包含 app.current_tenant: {p}"
            assert "app.tenant_id" in p, f"v207 USING子句缺少 app.tenant_id: {p}"

    def test_v208_no_current_tenant_in_policy(self):
        path = os.path.join(_VERSIONS_DIR, "v208_aggregator_reconcile.py")
        with open(path) as f:
            content = f.read()
        policies = re.findall(r"USING\s*\(.*?\)", content, re.DOTALL)
        for p in policies:
            assert "app.current_tenant" not in p, f"v208仍包含 app.current_tenant: {p}"
            assert "app.tenant_id" in p, f"v208 USING子句缺少 app.tenant_id: {p}"


# ── 测试3：验证SQL语法格式符合标准 ──

class TestSQLSyntax:
    def test_nullif_pattern_used(self):
        """验证使用 NULLIF 防止空字符串绕过"""
        mod = _load_migration("v224_fix_rls_tenant_variable.py")
        executed_sql = []
        mock_op = MagicMock()
        mock_op.execute = lambda sql: executed_sql.append(sql)

        with patch.object(mod, "op", mock_op):
            mod.upgrade()

        create_stmts = [s for s in executed_sql if "CREATE POLICY" in s]
        for stmt in create_stmts:
            assert "NULLIF" in stmt, f"缺少NULLIF防空字符串绕过: {stmt}"
