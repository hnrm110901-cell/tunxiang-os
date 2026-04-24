"""v065 — 巡店管理模块：模板、记录、明细、整改任务

Revision ID: v065
Revises: v064
Create Date: 2026-03-31

新建5张表：
  patrol_templates         — 巡检模板
  patrol_template_items    — 模板检查项
  patrol_records           — 巡检记录
  patrol_record_items      — 巡检结果明细
  patrol_issues            — 整改任务

所有表：
  - 包含 tenant_id + RLS 四操作策略 + FORCE ROW LEVEL SECURITY
  - RLS 使用正确变量: NULLIF(current_setting('app.tenant_id', true), '')::UUID
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "v065"
down_revision = "v064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. patrol_templates（巡检模板） ───────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS patrol_templates (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    UUID NOT NULL,
            brand_id     UUID,
            name         TEXT NOT NULL,
            description  TEXT,
            category     TEXT NOT NULL CHECK (category IN ('safety', 'hygiene', 'service', 'equipment')),
            is_active    BOOLEAN NOT NULL DEFAULT TRUE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted   BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("ALTER TABLE patrol_templates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE patrol_templates FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY patrol_templates_select ON patrol_templates
            FOR SELECT USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)
    op.execute("""
        CREATE POLICY patrol_templates_insert ON patrol_templates
            FOR INSERT WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)
    op.execute("""
        CREATE POLICY patrol_templates_update ON patrol_templates
            FOR UPDATE USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)
    op.execute("""
        CREATE POLICY patrol_templates_delete ON patrol_templates
            FOR DELETE USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_patrol_templates_tenant ON patrol_templates (tenant_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_patrol_templates_brand ON patrol_templates (brand_id) WHERE brand_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_patrol_templates_active ON patrol_templates (tenant_id, is_active) WHERE is_deleted = FALSE"
    )

    # ── 2. patrol_template_items（模板检查项） ────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS patrol_template_items (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            template_id     UUID NOT NULL REFERENCES patrol_templates(id) ON DELETE CASCADE,
            item_name       TEXT NOT NULL,
            item_type       TEXT NOT NULL CHECK (item_type IN ('check', 'score', 'photo', 'text')),
            max_score       NUMERIC(5, 1) NOT NULL DEFAULT 10,
            is_required     BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order      INT NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("ALTER TABLE patrol_template_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE patrol_template_items FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY patrol_template_items_select ON patrol_template_items
            FOR SELECT USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)
    op.execute("""
        CREATE POLICY patrol_template_items_insert ON patrol_template_items
            FOR INSERT WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)
    op.execute("""
        CREATE POLICY patrol_template_items_update ON patrol_template_items
            FOR UPDATE USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)
    op.execute("""
        CREATE POLICY patrol_template_items_delete ON patrol_template_items
            FOR DELETE USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_patrol_template_items_template ON patrol_template_items (template_id, sort_order)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_patrol_template_items_tenant ON patrol_template_items (tenant_id)")

    # ── 3. patrol_records（巡检记录） ─────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS patrol_records (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID NOT NULL,
            store_id       UUID NOT NULL,
            template_id    UUID REFERENCES patrol_templates(id),
            patrol_date    DATE NOT NULL,
            patroller_id   UUID,
            status         TEXT NOT NULL DEFAULT 'draft'
                               CHECK (status IN ('draft', 'in_progress', 'submitted', 'reviewed')),
            total_score    NUMERIC(5, 1),
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted     BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("ALTER TABLE patrol_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE patrol_records FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY patrol_records_select ON patrol_records
            FOR SELECT USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)
    op.execute("""
        CREATE POLICY patrol_records_insert ON patrol_records
            FOR INSERT WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)
    op.execute("""
        CREATE POLICY patrol_records_update ON patrol_records
            FOR UPDATE USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)
    op.execute("""
        CREATE POLICY patrol_records_delete ON patrol_records
            FOR DELETE USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_patrol_records_tenant ON patrol_records (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_patrol_records_store ON patrol_records (tenant_id, store_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_patrol_records_date ON patrol_records (tenant_id, patrol_date DESC) WHERE is_deleted = FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_patrol_records_patroller ON patrol_records (patroller_id) WHERE patroller_id IS NOT NULL"
    )

    # ── 4. patrol_record_items（巡检结果明细） ────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS patrol_record_items (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id          UUID NOT NULL,
            record_id          UUID NOT NULL REFERENCES patrol_records(id) ON DELETE CASCADE,
            template_item_id   UUID REFERENCES patrol_template_items(id),
            item_name          TEXT NOT NULL,
            actual_score       NUMERIC(5, 1),
            max_score          NUMERIC(5, 1) NOT NULL DEFAULT 10,
            is_passed          BOOLEAN,
            photo_urls         JSONB NOT NULL DEFAULT '[]'::jsonb,
            notes              TEXT,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted         BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("ALTER TABLE patrol_record_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE patrol_record_items FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY patrol_record_items_select ON patrol_record_items
            FOR SELECT USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)
    op.execute("""
        CREATE POLICY patrol_record_items_insert ON patrol_record_items
            FOR INSERT WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)
    op.execute("""
        CREATE POLICY patrol_record_items_update ON patrol_record_items
            FOR UPDATE USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)
    op.execute("""
        CREATE POLICY patrol_record_items_delete ON patrol_record_items
            FOR DELETE USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_patrol_record_items_record ON patrol_record_items (record_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_patrol_record_items_tenant ON patrol_record_items (tenant_id)")

    # ── 5. patrol_issues（整改任务） ──────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS patrol_issues (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            record_id           UUID REFERENCES patrol_records(id),
            store_id            UUID NOT NULL,
            item_name           TEXT NOT NULL,
            severity            TEXT NOT NULL CHECK (severity IN ('critical', 'major', 'minor')),
            description         TEXT,
            photo_urls          JSONB NOT NULL DEFAULT '[]'::jsonb,
            status              TEXT NOT NULL DEFAULT 'open'
                                    CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
            assignee_id         UUID,
            due_date            DATE,
            resolved_at         TIMESTAMPTZ,
            resolution_notes    TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("ALTER TABLE patrol_issues ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE patrol_issues FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY patrol_issues_select ON patrol_issues
            FOR SELECT USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)
    op.execute("""
        CREATE POLICY patrol_issues_insert ON patrol_issues
            FOR INSERT WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)
    op.execute("""
        CREATE POLICY patrol_issues_update ON patrol_issues
            FOR UPDATE USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)
    op.execute("""
        CREATE POLICY patrol_issues_delete ON patrol_issues
            FOR DELETE USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_patrol_issues_tenant ON patrol_issues (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_patrol_issues_store ON patrol_issues (tenant_id, store_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_patrol_issues_status ON patrol_issues (tenant_id, status) WHERE is_deleted = FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_patrol_issues_assignee ON patrol_issues (assignee_id) WHERE assignee_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_patrol_issues_record ON patrol_issues (record_id) WHERE record_id IS NOT NULL"
    )


def downgrade() -> None:
    # 按依赖顺序逆序删除
    op.execute("DROP TABLE IF EXISTS patrol_issues CASCADE")
    op.execute("DROP TABLE IF EXISTS patrol_record_items CASCADE")
    op.execute("DROP TABLE IF EXISTS patrol_records CASCADE")
    op.execute("DROP TABLE IF EXISTS patrol_template_items CASCADE")
    op.execute("DROP TABLE IF EXISTS patrol_templates CASCADE")
