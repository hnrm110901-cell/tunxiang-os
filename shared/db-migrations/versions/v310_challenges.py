"""v310 — 挑战活动表: challenges

游戏化忠诚度2.0 — 挑战定义：
类型(type)、规则(rules JSONB)、奖励(reward JSONB)、
有效期(start_date/end_date)、参与上限(max_participants)。

Revision ID: v310_challenges
Revises: v309_member_badges
Create Date: 2026-04-25
"""
from alembic import op

revision = "v310_challenges"
down_revision = "v309_member_badges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS challenges (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            name                VARCHAR(100) NOT NULL,
            description         TEXT NOT NULL DEFAULT '',
            type                VARCHAR(40) NOT NULL
                                CHECK (type IN (
                                    'visit_streak', 'spend_target', 'dish_explorer',
                                    'social_share', 'referral_drive', 'seasonal_event',
                                    'time_limited', 'combo_quest'
                                )),
            rules               JSONB NOT NULL DEFAULT '{}',
            reward              JSONB NOT NULL DEFAULT '{}',
            badge_id            UUID,
            start_date          TIMESTAMPTZ NOT NULL,
            end_date            TIMESTAMPTZ NOT NULL,
            max_participants    INT NOT NULL DEFAULT 0,
            current_participants INT NOT NULL DEFAULT 0,
            is_active           BOOLEAN NOT NULL DEFAULT TRUE,
            display_order       INT NOT NULL DEFAULT 0,
            icon_url            TEXT NOT NULL DEFAULT '',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_challenges_tenant_active
            ON challenges(tenant_id, is_active, start_date, end_date)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_challenges_tenant_type
            ON challenges(tenant_id, type)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE challenges ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS challenges_tenant_isolation ON challenges;
        CREATE POLICY challenges_tenant_isolation ON challenges
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE challenges FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS challenges CASCADE")
