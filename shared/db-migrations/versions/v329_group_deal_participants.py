"""v329 — 拼团参与者表: group_deal_participants

社交裂变 S4W14-15：
  拼团参与者记录，跟踪每位参团者的加入时间、
  支付状态及关联订单，支持唯一约束防止重复参团。

Revision ID: v329_group_deal_participants
Revises: v328_group_deals
Create Date: 2026-04-25
"""
from alembic import op

revision = "v329_group_deal_participants"
down_revision = "v328_group_deals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS group_deal_participants (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            deal_id             UUID NOT NULL,
            customer_id         UUID NOT NULL,
            joined_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            order_id            UUID,
            paid                BOOLEAN NOT NULL DEFAULT FALSE,
            paid_at             TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
            UNIQUE (tenant_id, deal_id, customer_id)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_gdp_deal
            ON group_deal_participants(tenant_id, deal_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_gdp_customer
            ON group_deal_participants(tenant_id, customer_id)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE group_deal_participants ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS gdp_tenant_isolation ON group_deal_participants;
        CREATE POLICY gdp_tenant_isolation ON group_deal_participants
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE group_deal_participants FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS group_deal_participants CASCADE")
