"""v326 — 跨品牌联盟交易表: alliance_transactions

跨品牌联盟忠诚度 S4W13-14：
  联盟积分兑换交易记录，支持积分双向兑换（inbound/outbound），
  优惠券兑换，交易状态追踪，合作伙伴引用ID。

Revision ID: v326_alliance_transactions
Revises: v325_alliance_partners
Create Date: 2026-04-25
"""
from alembic import op

revision = "v326_alliance_transactions"
down_revision = "v325_alliance_partners"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS alliance_transactions (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            partner_id              UUID NOT NULL,
            customer_id             UUID NOT NULL,
            direction               VARCHAR(10) NOT NULL
                                    CHECK (direction IN ('inbound', 'outbound')),
            points_amount           INT NOT NULL CHECK (points_amount > 0),
            converted_points        INT NOT NULL,
            exchange_rate           FLOAT NOT NULL,
            coupon_id               UUID,
            coupon_name             VARCHAR(200),
            status                  VARCHAR(20) NOT NULL DEFAULT 'pending'
                                    CHECK (status IN (
                                        'pending', 'completed', 'failed', 'reversed'
                                    )),
            failure_reason          TEXT,
            partner_reference_id    VARCHAR(100),
            completed_at            TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_alliance_tx_customer
            ON alliance_transactions(tenant_id, customer_id, created_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_alliance_tx_partner_dir
            ON alliance_transactions(tenant_id, partner_id, direction)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_alliance_tx_status
            ON alliance_transactions(tenant_id, status)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE alliance_transactions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS alliance_transactions_tenant_isolation ON alliance_transactions;
        CREATE POLICY alliance_transactions_tenant_isolation ON alliance_transactions
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE alliance_transactions FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS alliance_transactions CASCADE")
