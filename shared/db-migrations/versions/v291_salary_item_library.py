"""v250: salary item templates library

薪资项目库持久化表 — 支持7大类71项标准薪资项模板。
租户初始化时从内存模板批量写入，后续支持自定义新增/启用禁用。

Revision ID: v250
Revises: v249
Create Date: 2026-04-13
"""

from alembic import op

revision = "v291"
down_revision = "v249"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── salary_item_templates 薪资项目模板库 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS salary_item_templates (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            item_code       VARCHAR(50) NOT NULL,
            item_name       VARCHAR(100) NOT NULL,
            category        VARCHAR(30) NOT NULL,
            tax_type        VARCHAR(20) DEFAULT 'pre_tax_add',
            calc_rule       VARCHAR(20) DEFAULT 'fixed',
            formula         TEXT DEFAULT '',
            is_required     BOOLEAN DEFAULT FALSE,
            default_value_fen BIGINT DEFAULT 0,
            is_system       BOOLEAN DEFAULT FALSE,
            is_enabled      BOOLEAN DEFAULT TRUE,
            sort_order      INT DEFAULT 0,
            description     TEXT DEFAULT '',
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE,
            UNIQUE(tenant_id, item_code)
        )
    """)

    # RLS
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE salary_item_templates ENABLE ROW LEVEL SECURITY;
        EXCEPTION WHEN others THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE POLICY salary_item_templates_rls ON salary_item_templates
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)

    # Indexes
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_salary_item_templates_tenant_cat
            ON salary_item_templates (tenant_id, category)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_salary_item_templates_tenant_code
            ON salary_item_templates (tenant_id, item_code)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_salary_item_templates_enabled
            ON salary_item_templates (tenant_id, is_enabled)
            WHERE is_deleted = FALSE
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS salary_item_templates CASCADE")
