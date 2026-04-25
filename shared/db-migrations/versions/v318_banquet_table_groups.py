"""v318 — 宴会桌组: banquet_table_groups

将多张桌台编组用于宴会，记录布局快照和状态流转
（planned → set_up → in_use → cleared）。

Revision ID: v318_banquet_table_groups
Revises: v317_banquet_venues
Create Date: 2026-04-25
"""
from alembic import op

revision = "v318_banquet_table_groups"
down_revision = "v317_banquet_venues"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── banquet_table_groups 宴会桌组 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_table_groups (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID NOT NULL,
            banquet_id           UUID,
            venue_id             UUID REFERENCES banquet_venues(id),
            store_id             UUID NOT NULL,
            group_name           VARCHAR(100) NOT NULL,
            table_ids            JSONB DEFAULT '[]'::jsonb,
            layout_snapshot_json JSONB DEFAULT '{}'::jsonb,
            total_seats          INT DEFAULT 0,
            table_count          INT DEFAULT 0,
            status               VARCHAR(20) DEFAULT 'planned'
                CHECK (status IN ('planned','set_up','in_use','cleared')),
            set_up_at            TIMESTAMPTZ,
            cleared_at           TIMESTAMPTZ,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted           BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_btg_banquet
            ON banquet_table_groups(tenant_id, banquet_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_btg_store
            ON banquet_table_groups(tenant_id, store_id)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE banquet_table_groups ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS banquet_table_groups_tenant_isolation ON banquet_table_groups;
        CREATE POLICY banquet_table_groups_tenant_isolation ON banquet_table_groups
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE banquet_table_groups FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_table_groups CASCADE")
