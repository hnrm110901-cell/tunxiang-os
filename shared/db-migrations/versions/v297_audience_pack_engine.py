"""v297 — 人群包引擎

私域增长模块B：人群包引擎，支持动态/静态人群包+规则引擎+系统预设。

三张表：
  1. audience_packs — 人群包（动态规则/静态名单）
  2. audience_pack_members — 人群包成员（含快照数据）
  3. audience_pack_presets — 人群包预设模板（系统+自定义）

Revision ID: v297_audience_pack
Revises: v296_live_code_stats
Create Date: 2026-04-24
"""
from alembic import op

revision = "v297_audience_pack"
down_revision = "v296_live_code_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. audience_packs ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS audience_packs (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            pack_name               VARCHAR(200) NOT NULL,
            description             TEXT,
            pack_type               VARCHAR(20) NOT NULL DEFAULT 'dynamic'
                                    CHECK (pack_type IN ('dynamic', 'static')),
            rules                   JSONB NOT NULL DEFAULT '{}'::jsonb,
            member_count            INT NOT NULL DEFAULT 0,
            last_refreshed_at       TIMESTAMPTZ,
            refresh_interval_hours  INT NOT NULL DEFAULT 24,
            store_id                UUID,
            status                  VARCHAR(20) NOT NULL DEFAULT 'active'
                                    CHECK (status IN ('active', 'archived')),
            created_by              UUID NOT NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_audience_packs_tenant_status
            ON audience_packs (tenant_id, status, created_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_audience_packs_store
            ON audience_packs (tenant_id, store_id)
            WHERE is_deleted = false AND store_id IS NOT NULL
    """)

    op.execute("ALTER TABLE audience_packs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS audience_packs_tenant_isolation ON audience_packs;
        CREATE POLICY audience_packs_tenant_isolation ON audience_packs
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 2. audience_pack_members ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS audience_pack_members (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            pack_id             UUID NOT NULL REFERENCES audience_packs(id),
            customer_id         UUID NOT NULL,
            store_id            UUID,
            snapshot_data       JSONB,
            added_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            removed_at          TIMESTAMPTZ,
            is_active           BOOLEAN NOT NULL DEFAULT TRUE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_audience_pack_member
                UNIQUE (tenant_id, pack_id, customer_id)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_audience_pack_members_pack
            ON audience_pack_members (pack_id, is_active)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_audience_pack_members_customer
            ON audience_pack_members (tenant_id, customer_id)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE audience_pack_members ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS audience_pack_members_tenant_isolation ON audience_pack_members;
        CREATE POLICY audience_pack_members_tenant_isolation ON audience_pack_members
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 3. audience_pack_presets ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS audience_pack_presets (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            preset_name         VARCHAR(200) NOT NULL,
            description         TEXT,
            category            VARCHAR(50) NOT NULL DEFAULT 'lifecycle'
                                CHECK (category IN ('lifecycle', 'value', 'behavior', 'opportunity', 'risk')),
            rules               JSONB NOT NULL DEFAULT '{}'::jsonb,
            icon                VARCHAR(100),
            sort_order          INT NOT NULL DEFAULT 0,
            is_system           BOOLEAN NOT NULL DEFAULT FALSE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_audience_pack_presets_tenant
            ON audience_pack_presets (tenant_id, category, sort_order)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE audience_pack_presets ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS audience_pack_presets_tenant_isolation ON audience_pack_presets;
        CREATE POLICY audience_pack_presets_tenant_isolation ON audience_pack_presets
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audience_pack_presets CASCADE")
    op.execute("DROP TABLE IF EXISTS audience_pack_members CASCADE")
    op.execute("DROP TABLE IF EXISTS audience_packs CASCADE")
