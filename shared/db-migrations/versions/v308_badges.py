"""v308 — 徽章表: badges

游戏化忠诚度2.0 — 徽章定义表：
类别(category)、解锁规则(unlock_rule JSONB)、稀有度(rarity)、
积分奖励(points_reward)、图标(icon_url)。

Revision ID: v308_badges
Revises: v307_churn_interventions
Create Date: 2026-04-25
"""
from alembic import op

revision = "v308_badges"
down_revision = "v307_churn_interventions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS badges (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            name                VARCHAR(100) NOT NULL,
            description         TEXT NOT NULL DEFAULT '',
            category            VARCHAR(40) NOT NULL
                                CHECK (category IN (
                                    'loyalty', 'social', 'exploration',
                                    'seasonal', 'milestone', 'secret'
                                )),
            unlock_rule         JSONB NOT NULL DEFAULT '{}',
            rarity              VARCHAR(20) NOT NULL DEFAULT 'common'
                                CHECK (rarity IN (
                                    'common', 'uncommon', 'rare',
                                    'epic', 'legendary'
                                )),
            points_reward       INT NOT NULL DEFAULT 0,
            icon_url            TEXT NOT NULL DEFAULT '',
            display_order       INT NOT NULL DEFAULT 0,
            is_active           BOOLEAN NOT NULL DEFAULT TRUE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_badges_tenant_category
            ON badges(tenant_id, category)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_badges_tenant_active
            ON badges(tenant_id, is_active)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE badges ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS badges_tenant_isolation ON badges;
        CREATE POLICY badges_tenant_isolation ON badges
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE badges FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS badges CASCADE")
