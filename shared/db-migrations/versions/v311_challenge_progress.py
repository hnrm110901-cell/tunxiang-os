"""v311 — 挑战进度表: challenge_progress

记录会员参与挑战的进度，UNIQUE(tenant_id, customer_id, challenge_id)
追踪当前进度值、目标值、完成状态、奖励领取状态。

Revision ID: v311_challenge_progress
Revises: v310_challenges
Create Date: 2026-04-25
"""
from alembic import op

revision = "v311_challenge_progress"
down_revision = "v310_challenges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS challenge_progress (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            customer_id         UUID NOT NULL,
            challenge_id        UUID NOT NULL,
            current_value       INT NOT NULL DEFAULT 0,
            target_value        INT NOT NULL DEFAULT 1,
            progress_detail     JSONB NOT NULL DEFAULT '{}',
            status              VARCHAR(20) NOT NULL DEFAULT 'active'
                                CHECK (status IN (
                                    'active', 'completed', 'claimed',
                                    'expired', 'abandoned'
                                )),
            joined_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at        TIMESTAMPTZ,
            claimed_at          TIMESTAMPTZ,
            reward_snapshot     JSONB NOT NULL DEFAULT '{}',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_challenge_progress_tenant_customer_challenge
                UNIQUE (tenant_id, customer_id, challenge_id)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_challenge_progress_customer
            ON challenge_progress(tenant_id, customer_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_challenge_progress_challenge
            ON challenge_progress(tenant_id, challenge_id, status)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE challenge_progress ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS challenge_progress_tenant_isolation ON challenge_progress;
        CREATE POLICY challenge_progress_tenant_isolation ON challenge_progress
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE challenge_progress FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS challenge_progress CASCADE")
