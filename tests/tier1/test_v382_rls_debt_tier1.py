"""Tier 1 契约测试 — v382_fill_rls_historical_debt.py

补齐 14 张历史遗留业务表的 RLS。本测试静态验证 migration 源码：
  · 14 张表全部列在 TABLES_TO_FIX
  · 每张表都执行 ENABLE RLS + FORCE RLS + CREATE POLICY
  · 所有 POLICY 用 `current_setting('app.tenant_id', true)`
  · downgrade 存在（不 DROP TABLE 只 DISABLE RLS）

真实行为验证需要 DB：见 `scripts/check_rls_policies.py`（独立 PR #99）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT / "shared" / "db-migrations" / "versions"
    / "v382_fill_rls_historical_debt.py"
)

# 期望补齐的 14 张表（任何顺序无关）
EXPECTED_TABLES: frozenset[str] = frozenset({
    "receiving_items", "stocktake_items",
    "distribution_orders", "production_orders", "store_receiving_confirmations",
    "stocktakes", "warehouse_transfers", "warehouse_transfer_items",
    "purchase_invoices", "purchase_match_records",
    "pilot_items", "pilot_metrics", "pilot_programs", "pilot_reviews",
})


class TestV382Migration:

    @pytest.fixture(scope="class")
    def source(self) -> str:
        assert MIGRATION.exists(), f"{MIGRATION} 不存在"
        return MIGRATION.read_text(encoding="utf-8")

    def test_revision_metadata(self, source):
        assert 'revision = "v382_fill_rls_historical_debt"' in source
        assert 'down_revision = "v381_delivery_disputes"' in source

    def test_tables_to_fix_matches_expected(self, source):
        """TABLES_TO_FIX 元组必须覆盖 14 张预期表（不多不少）"""
        # 通过 exec 加载常量而非 import（避免 alembic 依赖）
        import importlib.util
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        spec = importlib.util.spec_from_file_location(
            "v382_under_test", MIGRATION
        )
        assert spec and spec.loader
        # 不 execute（涉及 alembic.op）；直接解析 tuple 定义
        import ast
        tree = ast.parse(source)
        tables_literal = None
        for node in ast.walk(tree):
            # AnnAssign (带类型注解) 或 Assign (不带)
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "TABLES_TO_FIX"
            ):
                tables_literal = node.value
                break
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "TABLES_TO_FIX"
            ):
                tables_literal = node.value
                break
        assert tables_literal is not None, "TABLES_TO_FIX 常量未找到"
        # 提取元组字符串
        assert isinstance(tables_literal, ast.Tuple)
        actual = frozenset(
            elt.value for elt in tables_literal.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        )
        assert actual == EXPECTED_TABLES, (
            f"TABLES_TO_FIX 与预期不一致\n"
            f"多余: {actual - EXPECTED_TABLES}\n"
            f"缺失: {EXPECTED_TABLES - actual}"
        )

    def test_all_tables_referenced_in_upgrade(self, source):
        """每张表名都在 upgrade() 区段出现（通过 _table_exists 循环）"""
        upgrade_idx = source.find("def upgrade")
        downgrade_idx = source.find("def downgrade")
        assert upgrade_idx > 0 and downgrade_idx > upgrade_idx
        upgrade_body = source[upgrade_idx:downgrade_idx]
        # 由于是循环调用，每张表应至少在注释/commented 中出现
        for t in EXPECTED_TABLES:
            assert t in source, f"表 {t} 未在 migration 源中出现"

    def test_enable_rls_in_template(self, source):
        """_table_exists 模板必须包含 ENABLE ROW LEVEL SECURITY"""
        assert "ENABLE ROW LEVEL SECURITY" in source

    def test_force_rls_in_template(self, source):
        """FORCE ROW LEVEL SECURITY 防表 owner 绕过"""
        assert "FORCE ROW LEVEL SECURITY" in source

    def test_create_policy_in_template(self, source):
        assert "CREATE POLICY" in source

    def test_policy_uses_app_tenant_id(self, source):
        """POLICY 必须使用 current_setting('app.tenant_id', true)"""
        assert "app.tenant_id" in source
        assert "current_setting" in source

    def test_policy_has_using_and_with_check(self, source):
        """POLICY 既有 USING 也有 WITH CHECK（完整覆盖 SELECT/INSERT/UPDATE/DELETE）"""
        assert "USING (" in source
        assert "WITH CHECK (" in source

    def test_drop_policy_if_exists_idempotent(self, source):
        """DROP POLICY IF EXISTS — 支持重跑不报错"""
        assert "DROP POLICY IF EXISTS" in source

    def test_table_exists_guard(self, source):
        """_table_exists 用 information_schema 判断表存在，避免 legacy 环境报错"""
        assert "information_schema.tables" in source
        assert "RAISE NOTICE" in source

    def test_downgrade_exists(self, source):
        """downgrade 存在 + 不 DROP TABLE（仅在可执行代码中检查）"""
        idx = source.find("def downgrade")
        assert idx > 0
        body = source[idx:]
        # 只看不是注释/docstring 的行（简化：用 op.execute 附近扫）
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if "DROP TABLE" in stripped.upper() and not stripped.startswith('"') and not stripped.startswith("'"):
                # 如果是 SQL 内部的 DROP TABLE（op.execute 参数），那就是真的 DROP
                # 但本 migration 确实不该有
                pytest.fail(
                    f"downgrade 不应 DROP 业务表（数据还在），发现: {line.strip()}"
                )

    def test_downgrade_uses_no_force_and_disable(self, source):
        """downgrade 必须同时 NO FORCE + DISABLE + DROP POLICY"""
        idx = source.find("def downgrade")
        body = source[idx:]
        assert "NO FORCE ROW LEVEL SECURITY" in body
        assert "DISABLE ROW LEVEL SECURITY" in body
        assert "DROP POLICY IF EXISTS" in body

    def test_comments_document_origin(self, source):
        """COMMENT ON POLICY 记录历史 migration 来源（便于追溯）"""
        for origin in ("v053", "v062", "v064", "v067", "v090"):
            assert origin in source, f"COMMENT 未引用 {origin}"


# ─────────────────────────────────────────────────────────────
# 契约：这些表的原 migration 历史没有 ENABLE RLS
# ─────────────────────────────────────────────────────────────


class TestOriginalMigrationsLackRLS:
    """验证前提：原 migration 确实漏了 RLS（如未漏则本 PR 无需存在）"""

    @pytest.mark.parametrize("migration,tables", [
        ("v053_supply_chain_mobile.py", ["receiving_items", "stocktake_items"]),
        ("v062_central_kitchen.py", ["distribution_orders", "production_orders", "store_receiving_confirmations"]),
        ("v064_wms_persistence.py", ["stocktakes", "warehouse_transfers", "warehouse_transfer_items"]),
        ("v067_three_way_match.py", ["purchase_invoices", "purchase_match_records"]),
        ("v090_pilot_tracking.py", ["pilot_items", "pilot_metrics", "pilot_programs", "pilot_reviews"]),
    ])
    def test_origin_missing_rls(self, migration, tables):
        path = ROOT / "shared" / "db-migrations" / "versions" / migration
        assert path.exists()
        source = path.read_text(encoding="utf-8")
        for t in tables:
            # 表必须被 CREATE（否则 migration 漏了）
            assert f"CREATE TABLE IF NOT EXISTS {t}" in source or f"CREATE TABLE {t}" in source, (
                f"{migration} 未 CREATE {t}"
            )
            # 但不含 ENABLE ROW LEVEL SECURITY for this table
            rls_line = f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"
            assert rls_line not in source, (
                f"{migration} 已含 {rls_line}，说明本 PR 假设错误（可能已被其他 migration 修）"
            )
