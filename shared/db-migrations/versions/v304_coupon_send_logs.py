"""v304 — 1v1发券追踪表: coupon_send_logs

记录企微侧边栏/到店场景下导购员工向客户发放优惠券的行为,
支持发券效果追踪(发放→领取→核销→过期)和员工/门店维度统计.

Revision ID: v304_coupon_send_logs
Revises: v303_customer_journey_sop
Create Date: 2026-04-24
"""
from alembic import op

revision = "v304_coupon_send_logs"
down_revision = "v303_customer_journey_sop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS coupon_send_logs (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID,
            employee_id         UUID NOT NULL,
            customer_id         UUID NOT NULL,
            coupon_batch_id     UUID,
            coupon_instance_id  UUID,
            coupon_name         VARCHAR(200),
            discount_desc       VARCHAR(200),
            channel             VARCHAR(30) NOT NULL DEFAULT 'wecom_sidebar',
            send_status         VARCHAR(20) NOT NULL DEFAULT 'sent'
                                CHECK (send_status IN (
                                    'sent', 'received', 'used', 'expired', 'failed'
                                )),
            used_order_id       UUID,
            used_at             TIMESTAMPTZ,
            revenue_fen         BIGINT DEFAULT 0,
            failure_reason      TEXT,
            sent_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_coupon_send_logs_employee
            ON coupon_send_logs(tenant_id, employee_id, sent_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_coupon_send_logs_customer
            ON coupon_send_logs(tenant_id, customer_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_coupon_send_logs_store
            ON coupon_send_logs(tenant_id, store_id, sent_at DESC)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE coupon_send_logs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS coupon_send_logs_tenant_isolation ON coupon_send_logs;
        CREATE POLICY coupon_send_logs_tenant_isolation ON coupon_send_logs
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE coupon_send_logs FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS coupon_send_logs CASCADE")
