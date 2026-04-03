"""v048 — 折扣审计链

新增表 discount_audit_log：
  记录每笔折扣/赠品/退菜的完整审计信息

Revision ID: v048
Revises: v047
Create Date: 2026-03-31
"""

from alembic import op

revision = "v048"
down_revision = "v047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS discount_audit_log (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            order_id        UUID        NOT NULL,
            order_item_id   UUID,
            operator_id     UUID        NOT NULL,
            operator_name   VARCHAR(100) NOT NULL,
            approver_id     UUID,
            approver_name   VARCHAR(100),
            action_type     VARCHAR(50) NOT NULL,
            original_amount NUMERIC(12,2) NOT NULL,
            final_amount    NUMERIC(12,2) NOT NULL,
            discount_amount NUMERIC(12,2) NOT NULL,
            reason          TEXT,
            extra           JSONB,
            device_id       VARCHAR(100),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        );

        COMMENT ON TABLE discount_audit_log IS
            '折扣审计链：记录每笔折扣/赠品/退菜操作，防欺诈，支持总部审计';
        COMMENT ON COLUMN discount_audit_log.action_type IS
            '操作类型: discount_pct/discount_amt/gift_item/return_item/free_order/price_override/coupon';

        CREATE INDEX IF NOT EXISTS ix_dal_tenant_store
            ON discount_audit_log (tenant_id, store_id);
        CREATE INDEX IF NOT EXISTS ix_dal_order
            ON discount_audit_log (order_id);
        CREATE INDEX IF NOT EXISTS ix_dal_operator
            ON discount_audit_log (operator_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_dal_created
            ON discount_audit_log (created_at);
    """)

    op.execute("ALTER TABLE discount_audit_log ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE discount_audit_log FORCE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY dal_tenant_isolation ON discount_audit_log
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS dal_tenant_isolation ON discount_audit_log;")
    op.execute("DROP TABLE IF EXISTS discount_audit_log;")
