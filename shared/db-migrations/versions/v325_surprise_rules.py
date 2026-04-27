"""v325 — 惊喜奖励规则表: surprise_rules

游戏化忠诚度 — 惊喜规则持久化：
  nth_visit 到店触发、probability 概率发放、reward JSONB 奖励配置。
  配合 surprise_reward.py 从内存 _surprise_rules 迁移到 DB。

Revision ID: v325_surprise_rules
Revises: v324_content_calendar
Create Date: 2026-04-26
"""
from alembic import op

revision = "v325_surprise_rules"
down_revision = "v324_content_calendar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS surprise_rules (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            store_id        UUID,
            name            VARCHAR(100) NOT NULL DEFAULT '',
            nth_visit       INT NOT NULL CHECK (nth_visit > 0),
            probability     NUMERIC(5,4) NOT NULL DEFAULT 1.0
                            CHECK (probability >= 0 AND probability <= 1),
            reward          JSONB NOT NULL DEFAULT '{}',
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            max_triggers    INT NOT NULL DEFAULT 0,
            display_order   INT NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_surprise_rules_tenant_active
            ON surprise_rules(tenant_id, is_active)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE surprise_rules ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS surprise_rules_tenant_isolation ON surprise_rules;
        CREATE POLICY surprise_rules_tenant_isolation ON surprise_rules
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE surprise_rules FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS surprise_rules CASCADE")
