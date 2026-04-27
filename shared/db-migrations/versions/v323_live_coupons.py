"""v323 — 直播优惠券表: live_coupons

视频号+直播模块 S3W10-11：
  直播间优惠券批次管理与核销追踪，
  记录每张券的领取/核销/过期状态，
  归因直播间带来的实际营收转化。

Revision ID: v323_live_coupons
Revises: v322_live_events
Create Date: 2026-04-25
"""
from alembic import op

revision = "v323_live_coupons"
down_revision = "v322_live_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS live_coupons (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            live_event_id           UUID NOT NULL,
            coupon_batch_id         UUID,
            coupon_name             VARCHAR(200) NOT NULL,
            discount_desc           VARCHAR(200),
            total_quantity          INT NOT NULL,
            claimed_quantity        INT DEFAULT 0,
            redeemed_quantity       INT DEFAULT 0,
            claim_code              VARCHAR(30),
            claimed_by              UUID,
            claimed_at              TIMESTAMPTZ,
            redeemed_order_id       UUID,
            redeemed_at             TIMESTAMPTZ,
            revenue_fen             BIGINT DEFAULT 0,
            status                  VARCHAR(20) DEFAULT 'available'
                                    CHECK (status IN (
                                        'available', 'claimed',
                                        'redeemed', 'expired'
                                    )),
            expires_at              TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_coupons_event_status
            ON live_coupons(tenant_id, live_event_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_live_coupons_claim_code
            ON live_coupons(tenant_id, claim_code)
            WHERE claim_code IS NOT NULL AND is_deleted = false
    """)

    op.execute("ALTER TABLE live_coupons ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS live_coupons_tenant_isolation ON live_coupons;
        CREATE POLICY live_coupons_tenant_isolation ON live_coupons
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE live_coupons FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS live_coupons CASCADE")
