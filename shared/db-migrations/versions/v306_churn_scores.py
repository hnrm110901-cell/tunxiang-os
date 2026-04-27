"""v306 — 流失预测评分表: churn_scores

记录每个会员的流失概率评分(0-100)、风险等级(warm/urgent/critical)、
行为信号快照、根因分析结果。每日3am批量评分，支持旅程自动触发。

Revision ID: v306_churn_scores
Revises: v305_campaign_optimization
Create Date: 2026-04-25
"""
from alembic import op

revision = "v306_churn_scores"
down_revision = "v305_campaign_optimization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS churn_scores (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            customer_id         UUID NOT NULL,
            score               INT NOT NULL DEFAULT 0
                                CHECK (score >= 0 AND score <= 100),
            risk_tier           VARCHAR(20) NOT NULL DEFAULT 'warm'
                                CHECK (risk_tier IN ('warm', 'urgent', 'critical')),
            signals             JSONB NOT NULL DEFAULT '{}',
            root_cause          VARCHAR(50) DEFAULT 'unknown'
                                CHECK (root_cause IN (
                                    'price', 'taste', 'competition', 'moved',
                                    'seasonal', 'service', 'unknown'
                                )),
            scored_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            journey_triggered_at TIMESTAMPTZ,
            journey_id          UUID,
            previous_score      INT,
            score_delta         INT DEFAULT 0,
            model_version       VARCHAR(30) DEFAULT 'v1_expert_weights',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_churn_scores_customer
            ON churn_scores(tenant_id, customer_id, scored_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_churn_scores_risk_tier
            ON churn_scores(tenant_id, risk_tier, score DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_churn_scores_untriggered
            ON churn_scores(tenant_id, risk_tier)
            WHERE is_deleted = false AND journey_triggered_at IS NULL AND score >= 40
    """)

    op.execute("ALTER TABLE churn_scores ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS churn_scores_tenant_isolation ON churn_scores;
        CREATE POLICY churn_scores_tenant_isolation ON churn_scores
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE churn_scores FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS churn_scores CASCADE")
