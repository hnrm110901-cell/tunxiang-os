"""v301 -- 社群运营工具 + 企业素材库

五张表：
  1. group_tags         — 群标签（按标签组分类）
  2. group_tag_bindings — 群-标签绑定关系
  3. group_mass_sends   — 群发任务（立即/定时，按标签筛选）
  4. material_groups    — 素材分组（树形结构）
  5. material_library   — 素材库（多类型，时段匹配）

Revision ID: v301_group_ops_material
Revises: v300_mkt_task_effect_worker
Create Date: 2026-04-24
"""
from alembic import op

revision = "v301_group_ops_material"
down_revision = "v300_mkt_task_effect_worker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. group_tags ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS group_tags (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            tag_group       VARCHAR(100) NOT NULL,
            tag_name        VARCHAR(100) NOT NULL,
            tag_color       VARCHAR(20) NOT NULL DEFAULT '#666',
            sort_order      INT NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_group_tags_tenant_group_name UNIQUE (tenant_id, tag_group, tag_name)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_group_tags_tenant_group
            ON group_tags (tenant_id, tag_group)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE group_tags ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS group_tags_tenant_isolation ON group_tags;
        CREATE POLICY group_tags_tenant_isolation ON group_tags
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 2. group_tag_bindings ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS group_tag_bindings (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            group_chat_id   VARCHAR(200) NOT NULL,
            tag_id          UUID NOT NULL REFERENCES group_tags(id),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_group_tag_bindings_tenant_group_tag UNIQUE (tenant_id, group_chat_id, tag_id)
        )
    """)

    op.execute("ALTER TABLE group_tag_bindings ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS group_tag_bindings_tenant_isolation ON group_tag_bindings;
        CREATE POLICY group_tag_bindings_tenant_isolation ON group_tag_bindings
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 3. group_mass_sends ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS group_mass_sends (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            send_name       VARCHAR(200) NOT NULL,
            content         JSONB NOT NULL,
            target_tag_ids  JSONB NOT NULL DEFAULT '[]'::jsonb,
            exclude_tag_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            target_group_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            send_type       VARCHAR(20) NOT NULL DEFAULT 'immediate'
                            CHECK (send_type IN ('immediate', 'scheduled')),
            scheduled_at    TIMESTAMPTZ,
            status          VARCHAR(20) NOT NULL DEFAULT 'draft'
                            CHECK (status IN (
                                'draft', 'scheduled', 'sending',
                                'completed', 'failed', 'cancelled'
                            )),
            total_groups    INT NOT NULL DEFAULT 0,
            sent_groups     INT NOT NULL DEFAULT 0,
            failed_groups   INT NOT NULL DEFAULT 0,
            created_by      UUID,
            sent_at         TIMESTAMPTZ,
            completed_at    TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_group_mass_sends_tenant_status
            ON group_mass_sends (tenant_id, status, created_at DESC)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE group_mass_sends ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS group_mass_sends_tenant_isolation ON group_mass_sends;
        CREATE POLICY group_mass_sends_tenant_isolation ON group_mass_sends
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 4. material_groups ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS material_groups (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            group_name      VARCHAR(100) NOT NULL,
            parent_id       UUID REFERENCES material_groups(id),
            icon            VARCHAR(50),
            sort_order      INT NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("ALTER TABLE material_groups ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS material_groups_tenant_isolation ON material_groups;
        CREATE POLICY material_groups_tenant_isolation ON material_groups
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 5. material_library ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS material_library (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            group_id        UUID REFERENCES material_groups(id),
            title           VARCHAR(300) NOT NULL,
            material_type   VARCHAR(30) NOT NULL
                            CHECK (material_type IN (
                                'text', 'image', 'link', 'miniapp',
                                'video', 'file', 'poster'
                            )),
            content         TEXT,
            media_url       TEXT,
            thumbnail_url   TEXT,
            link_url        TEXT,
            link_title      VARCHAR(300),
            miniapp_appid   VARCHAR(100),
            miniapp_path    VARCHAR(500),
            metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
            time_slots      JSONB NOT NULL DEFAULT '[]'::jsonb,
            tags            JSONB NOT NULL DEFAULT '[]'::jsonb,
            usage_count     INT NOT NULL DEFAULT 0,
            is_template     BOOLEAN NOT NULL DEFAULT FALSE,
            sort_order      INT NOT NULL DEFAULT 0,
            created_by      UUID,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_material_library_tenant_type
            ON material_library (tenant_id, material_type)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_material_library_tenant_group
            ON material_library (tenant_id, group_id)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE material_library ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS material_library_tenant_isolation ON material_library;
        CREATE POLICY material_library_tenant_isolation ON material_library
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS material_library CASCADE")
    op.execute("DROP TABLE IF EXISTS material_groups CASCADE")
    op.execute("DROP TABLE IF EXISTS group_mass_sends CASCADE")
    op.execute("DROP TABLE IF EXISTS group_tag_bindings CASCADE")
    op.execute("DROP TABLE IF EXISTS group_tags CASCADE")
