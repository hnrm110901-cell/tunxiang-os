"""v309 — 会员徽章关联表: member_badges

记录会员解锁的徽章，UNIQUE(tenant_id, customer_id, badge_id)
防止重复解锁，记录解锁时间和解锁时的上下文快照。

Revision ID: v309_member_badges
Revises: v308_badges
Create Date: 2026-04-25
"""
from alembic import op

revision = "v309_member_badges"
down_revision = "v308_badges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS member_badges (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            customer_id         UUID NOT NULL,
            badge_id            UUID NOT NULL,
            unlocked_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            unlock_context      JSONB NOT NULL DEFAULT '{}',
            is_showcase         BOOLEAN NOT NULL DEFAULT FALSE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_member_badges_tenant_customer_badge
                UNIQUE (tenant_id, customer_id, badge_id)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_member_badges_customer
            ON member_badges(tenant_id, customer_id, unlocked_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_member_badges_badge
            ON member_badges(tenant_id, badge_id)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE member_badges ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS member_badges_tenant_isolation ON member_badges;
        CREATE POLICY member_badges_tenant_isolation ON member_badges
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE member_badges FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS member_badges CASCADE")
