"""v224 — 修复 v206/v207/v208 RLS策略使用错误的session变量

CRITICAL安全修复：这三个迁移中的RLS策略使用了 app.current_tenant
而非标准的 app.tenant_id，导致RLS策略完全不生效，存在跨租户数据泄露风险。

受影响的表和策略：
  - corporate_customers  → corporate_customers_tenant
  - corporate_orders     → corporate_orders_tenant
  - corporate_bills      → corporate_bills_tenant
  - aggregator_orders    → aggregator_orders_tenant
  - aggregator_reconcile_results → arr_tenant
  - aggregator_discrepancies     → ad_tenant

修复方式：DROP旧策略 + CREATE使用 app.tenant_id 的新策略。
所有操作幂等（IF EXISTS / IF NOT EXISTS）。

Revision ID: v224
Revises: v223
Create Date: 2026-04-09
"""

from alembic import op

revision = "v224"
down_revision = "v223"
branch_labels = None
depends_on = None

# 受影响的表及其旧策略名称
# tenant_id 在这些表中是 String(50)，不需要 ::UUID 转换
_AFFECTED = [
    ("corporate_customers", "corporate_customers_tenant"),
    ("corporate_orders", "corporate_orders_tenant"),
    ("corporate_bills", "corporate_bills_tenant"),
    ("aggregator_orders", "aggregator_orders_tenant"),
    ("aggregator_reconcile_results", "arr_tenant"),
    ("aggregator_discrepancies", "ad_tenant"),
]


def upgrade() -> None:
    for table, policy in _AFFECTED:
        # 1. 删除使用错误变量的旧策略
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table};")
        # 2. 创建使用正确变量的新策略（::uuid cast 兼容 UUID 类型列）
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='{table}' AND policyname='{policy}') THEN
                    EXECUTE 'CREATE POLICY {policy} ON {table}
                        USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid)
                        WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid)';
                END IF;
            END$$;
        """)


def downgrade() -> None:
    # 回滚到旧的（有漏洞的）策略 — 仅用于紧急回滚
    for table, policy in _AFFECTED:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table};")
        op.execute(f"""
            CREATE POLICY {policy} ON {table}
            USING (
                current_setting('app.current_tenant', TRUE) IS NOT NULL
                AND tenant_id = current_setting('app.current_tenant', TRUE)
            );
        """)
