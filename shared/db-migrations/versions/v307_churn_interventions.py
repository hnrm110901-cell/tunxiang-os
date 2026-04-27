"""v307 — 流失干预记录表: churn_interventions

记录每次流失干预的执行详情和结果归因：
干预类型(warm_touch/urgent_offer/manager_invite)、
渠道、优惠券、结果(pending/returned/ignored/converted)、归因订单和收入。

Revision ID: v307_churn_interventions
Revises: v306_churn_scores
Create Date: 2026-04-25
"""
from alembic import op

revision = "v307_churn_interventions"
down_revision = "v306_churn_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS churn_interventions (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            customer_id         UUID NOT NULL,
            churn_score_id      UUID NOT NULL,
            store_id            UUID,
            intervention_type   VARCHAR(30) NOT NULL
                                CHECK (intervention_type IN (
                                    'warm_touch', 'urgent_offer', 'manager_invite'
                                )),
            channel             VARCHAR(30) NOT NULL DEFAULT 'wecom_chat',
            offer_id            UUID,
            offer_detail        JSONB DEFAULT '{}',
            message_content     TEXT,
            outcome             VARCHAR(20) NOT NULL DEFAULT 'pending'
                                CHECK (outcome IN (
                                    'pending', 'sent', 'delivered', 'opened',
                                    'returned', 'ignored', 'converted', 'expired'
                                )),
            outcome_order_id    UUID,
            outcome_updated_at  TIMESTAMPTZ,
            revenue_fen         BIGINT NOT NULL DEFAULT 0,
            cost_fen            BIGINT NOT NULL DEFAULT 0,
            roi_ratio           FLOAT,
            sent_at             TIMESTAMPTZ,
            attribution_window_hours INT NOT NULL DEFAULT 72,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_churn_interventions_customer
            ON churn_interventions(tenant_id, customer_id, created_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_churn_interventions_outcome
            ON churn_interventions(tenant_id, outcome)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_churn_interventions_score
            ON churn_interventions(tenant_id, churn_score_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_churn_interventions_pending
            ON churn_interventions(tenant_id, outcome)
            WHERE is_deleted = false AND outcome IN ('pending', 'sent', 'delivered')
    """)

    op.execute("ALTER TABLE churn_interventions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS churn_interventions_tenant_isolation ON churn_interventions;
        CREATE POLICY churn_interventions_tenant_isolation ON churn_interventions
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE churn_interventions FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS churn_interventions CASCADE")
