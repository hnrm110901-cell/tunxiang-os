"""v017: Fix RLS on KDS-related tables (production_depts / dish_dept_mappings)

Background:
    Audit (2026-03-27) identified that some tables' RLS policies may reference
    incorrect session variables (app.current_store_id or app.current_tenant).
    The application code (set_config calls in services) sets 'app.tenant_id'.
    Any mismatch means RLS never matches and multi-tenant isolation is bypassed.

Tables fixed:
    - production_depts       (出品部门 — KDS 档口)
    - dish_dept_mappings     (菜品-档口映射 — KDS 路由规则)

Fix applied:
    1. DROP any existing RLS policies (covering all known naming patterns)
    2. Re-create with v006+ safe 4-policy pattern using 'app.tenant_id':
         current_setting('app.tenant_id', TRUE) IS NOT NULL
         AND current_setting('app.tenant_id', TRUE) <> ''
         AND tenant_id = current_setting('app.tenant_id')::UUID
    3. ENABLE ROW LEVEL SECURITY + FORCE ROW LEVEL SECURITY

This is a safe re-apply migration: if the policies already use the correct
variable, DROP IF EXISTS + recreate is idempotent.

Revision ID: v017
Revises: v016
Create Date: 2026-03-30
"""
from typing import Sequence, Union

from alembic import op

revision = "v017"
down_revision= "v016"
branch_labels= None
depends_on= None

# KDS 相关表
KDS_TABLES = ["production_depts", "dish_dept_mappings"]

# v006+ 标准安全条件（禁止 NULL / 空值绕过）
_SAFE_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def _drop_all_known_policies(table: str) -> None:
    """删除所有已知命名模式的 RLS 策略，防止遗漏任何错误策略。"""
    # v001-v005 命名模式
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
    op.execute(f"DROP POLICY IF EXISTS tenant_insert_{table} ON {table}")
    # v006+ 命名模式（防止重复创建冲突）
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_select ON {table}")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_insert ON {table}")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_update ON {table}")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_delete ON {table}")


def _apply_safe_rls(table: str) -> None:
    """应用 v006+ 安全 RLS：4 个策略 + NULL 防护 + FORCE。"""
    op.execute(
        f"CREATE POLICY {table}_rls_select ON {table} "
        f"FOR SELECT USING ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table}_rls_insert ON {table} "
        f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table}_rls_update ON {table} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table}_rls_delete ON {table} "
        f"FOR DELETE USING ({_SAFE_CONDITION})"
    )
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    """重建 KDS 相关表的 RLS 策略，统一使用 app.tenant_id。"""
    for table in KDS_TABLES:
        _drop_all_known_policies(table)
        _apply_safe_rls(table)


def downgrade() -> None:
    """回退到 v006 之前的简单 RLS 模式（WARNING: 重新引入安全漏洞）。"""
    for table in KDS_TABLES:
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_rls_{suffix} ON {table}")

        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")

        # 还原为 v001-v005 风格策略（无 NULL 防护，无 UPDATE/DELETE）
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            f"USING (tenant_id = current_setting('app.tenant_id')::UUID)"
        )
        op.execute(
            f"CREATE POLICY tenant_insert_{table} ON {table} "
            f"FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID)"
        )
