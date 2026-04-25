"""v328 — 拼团活动表: group_deals

社交裂变 S4W14-15：
  拼团（Group Deals）— 多人拼团享折扣价，
  分享链接拉人参团，达到最低人数自动成团，
  超时自动取消，支持按菜品/门店级别创建。

Revision ID: v328_group_deals
Revises: v327_dual_rewards
Create Date: 2026-04-25
"""
from alembic import op

revision = "v328_group_deals"
down_revision = "v327_dual_rewards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS group_deals (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            store_id                UUID NOT NULL,
            name                    VARCHAR(200) NOT NULL,
            description             TEXT,
            dish_id                 UUID,
            min_participants        INT NOT NULL CHECK (min_participants >= 2),
            max_participants        INT NOT NULL DEFAULT 10,
            current_participants    INT NOT NULL DEFAULT 0,
            original_price_fen      BIGINT NOT NULL,
            deal_price_fen          BIGINT NOT NULL,
            discount_fen            BIGINT GENERATED ALWAYS AS (original_price_fen - deal_price_fen) STORED,
            status                  VARCHAR(20) NOT NULL DEFAULT 'open'
                                    CHECK (status IN (
                                        'open', 'filled', 'expired', 'cancelled', 'completed'
                                    )),
            expires_at              TIMESTAMPTZ NOT NULL,
            filled_at               TIMESTAMPTZ,
            completed_at            TIMESTAMPTZ,
            initiator_customer_id   UUID NOT NULL,
            share_link_code         VARCHAR(50) NOT NULL,
            total_revenue_fen       BIGINT NOT NULL DEFAULT 0,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_group_deals_status_expires
            ON group_deals(tenant_id, status, expires_at)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_group_deals_store
            ON group_deals(tenant_id, store_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_group_deals_share_link
            ON group_deals(tenant_id, share_link_code)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE group_deals ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS group_deals_tenant_isolation ON group_deals;
        CREATE POLICY group_deals_tenant_isolation ON group_deals
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE group_deals FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS group_deals CASCADE")
