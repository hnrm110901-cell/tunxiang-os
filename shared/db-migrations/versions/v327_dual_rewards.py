"""v327 — 双向奖励表: dual_rewards

社交裂变 S4W14-15：
  双向奖励（Dual Rewards）— 老带新双方均获奖励，
  支持积分/优惠券/储值三种奖励类型，
  首单触发自动发放，超时自动过期。

Revision ID: v327_dual_rewards
Revises: v326_alliance_transactions
Create Date: 2026-04-25
"""
from alembic import op

revision = "v327_dual_rewards"
down_revision = "v326_alliance_transactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS dual_rewards (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            referrer_id             UUID NOT NULL,
            referee_id              UUID NOT NULL,
            referral_campaign_id    UUID,
            referrer_reward         JSONB NOT NULL DEFAULT '{}',
            referee_reward          JSONB NOT NULL DEFAULT '{}',
            trigger_order_id        UUID,
            trigger_order_amount_fen BIGINT DEFAULT 0,
            referrer_reward_status  VARCHAR(20) NOT NULL DEFAULT 'pending'
                                    CHECK (referrer_reward_status IN (
                                        'pending', 'claimed', 'expired', 'failed'
                                    )),
            referee_reward_status   VARCHAR(20) NOT NULL DEFAULT 'pending'
                                    CHECK (referee_reward_status IN (
                                        'pending', 'claimed', 'expired', 'failed'
                                    )),
            referrer_claimed_at     TIMESTAMPTZ,
            referee_claimed_at      TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dual_rewards_referrer
            ON dual_rewards(tenant_id, referrer_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dual_rewards_referee
            ON dual_rewards(tenant_id, referee_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dual_rewards_campaign
            ON dual_rewards(tenant_id, referral_campaign_id)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE dual_rewards ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS dual_rewards_tenant_isolation ON dual_rewards;
        CREATE POLICY dual_rewards_tenant_isolation ON dual_rewards
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE dual_rewards FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dual_rewards CASCADE")
