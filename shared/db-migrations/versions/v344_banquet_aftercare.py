"""v344 — 宴会售后与复购 (Aftercare)

- banquet_feedbacks: 宴会评价
- banquet_referrals: 转介绍追踪

Revision: v344_banquet_aftercare
"""

from alembic import op

revision = "v344_banquet_aftercare"
down_revision = "v343_banquet_settlements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_feedbacks (
            id                      UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID            NOT NULL,
            banquet_id              UUID            NOT NULL,
            customer_id             UUID,
            customer_name           VARCHAR(100),
            customer_phone          VARCHAR(20),
            overall_score           INT             NOT NULL,
            food_score              INT             NOT NULL DEFAULT 0,
            service_score           INT             NOT NULL DEFAULT 0,
            venue_score             INT             NOT NULL DEFAULT 0,
            value_score             INT             NOT NULL DEFAULT 0,
            comments                TEXT,
            highlights              JSONB           NOT NULL DEFAULT '[]',
            improvement_suggestions TEXT,
            would_recommend         BOOLEAN         NOT NULL DEFAULT TRUE,
            photos_json             JSONB           NOT NULL DEFAULT '[]',
            submitted_at            TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            replied_at              TIMESTAMPTZ,
            reply_content           TEXT,
            replied_by              UUID,
            created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_feedbacks_pkey PRIMARY KEY (id),
            CONSTRAINT bf_score_chk CHECK (overall_score BETWEEN 1 AND 5)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bf_banquet ON banquet_feedbacks (tenant_id, banquet_id)")
    op.execute("ALTER TABLE banquet_feedbacks ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_feedbacks_tenant_isolation ON banquet_feedbacks")
    op.execute("""
        CREATE POLICY banquet_feedbacks_tenant_isolation ON banquet_feedbacks
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_feedbacks FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_referrals (
            id                      UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID            NOT NULL,
            referrer_banquet_id     UUID            NOT NULL,
            referrer_name           VARCHAR(100),
            referrer_phone          VARCHAR(20),
            referred_lead_id        UUID,
            referred_name           VARCHAR(100),
            referred_phone          VARCHAR(20),
            referrer_reward_type    VARCHAR(30)     NOT NULL DEFAULT 'coupon',
            referrer_reward_value_fen INT           NOT NULL DEFAULT 0,
            referrer_reward_issued  BOOLEAN         NOT NULL DEFAULT FALSE,
            status                  VARCHAR(20)     NOT NULL DEFAULT 'pending',
            converted_at            TIMESTAMPTZ,
            rewarded_at             TIMESTAMPTZ,
            created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN         NOT NULL DEFAULT FALSE,
            CONSTRAINT banquet_referrals_pkey PRIMARY KEY (id),
            CONSTRAINT br_reward_type_chk CHECK (referrer_reward_type IN ('coupon','cash','points','gift','discount')),
            CONSTRAINT br_status_chk CHECK (status IN ('pending','contacted','converted','rewarded','expired'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_br_referrer ON banquet_referrals (tenant_id, referrer_banquet_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_br_status   ON banquet_referrals (tenant_id, status)")
    op.execute("ALTER TABLE banquet_referrals ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_referrals_tenant_isolation ON banquet_referrals")
    op.execute("""
        CREATE POLICY banquet_referrals_tenant_isolation ON banquet_referrals
            USING  (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
    """)
    op.execute("ALTER TABLE banquet_referrals FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_referrals CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_feedbacks CASCADE")
