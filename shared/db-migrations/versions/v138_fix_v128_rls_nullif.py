"""v138: 修复 v128 增长表 RLS 策略缺少 NULLIF 保护

v128 创建的 coupons / customer_coupons / notification_tasks / anomaly_dismissals
RLS 策略使用 `current_setting('app.tenant_id', true)::uuid`，缺少 NULLIF 空串保护。

当 app.tenant_id 未设置或为空串时，::uuid 强转可能产生非预期行为。
统一替换为带 NULLIF + WITH CHECK 的标准写法，与 v097/v101/v102 保持一致。

注意：v128 的 campaigns 表 RLS 同样缺少 NULLIF 和 WITH CHECK，
但 v097 已为 campaigns 创建了正确的 RLS (campaigns_rls)，
v128 创建的 campaigns_tenant_isolation 策略实际是冗余的，一并替换。

Revision ID: v138
Revises: v137
Create Date: 2026-04-02
"""

from alembic import op

revision = "v138"
down_revision = "v137"
branch_labels = None
depends_on = None

_TABLES_TO_FIX = [
    ("coupons", "coupons_tenant_isolation"),
    ("customer_coupons", "customer_coupons_tenant_isolation"),
    ("notification_tasks", "notification_tasks_tenant_isolation"),
    ("anomaly_dismissals", "anomaly_dismissals_tenant_isolation"),
    ("campaigns", "campaigns_tenant_isolation"),
]


def upgrade() -> None:
    for table, old_policy in _TABLES_TO_FIX:
        # 删除旧策略（如果存在）
        op.execute(f"DROP POLICY IF EXISTS {old_policy} ON {table};")

        # 创建标准化策略（NULLIF + WITH CHECK，与 v097/v101/v102 一致）
        new_policy = f"{table}_rls_v138"
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = '{table}' AND policyname = '{new_policy}'
                ) THEN
                    CREATE POLICY {new_policy} ON {table}
                        AS PERMISSIVE FOR ALL TO PUBLIC
                        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
                END IF;
            END $$;
        """)


def downgrade() -> None:
    for table, old_policy in _TABLES_TO_FIX:
        new_policy = f"{table}_rls_v138"
        op.execute(f"DROP POLICY IF EXISTS {new_policy} ON {table};")
        # 恢复旧策略
        op.execute(f"""
            CREATE POLICY {old_policy} ON {table}
            USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
        """)
