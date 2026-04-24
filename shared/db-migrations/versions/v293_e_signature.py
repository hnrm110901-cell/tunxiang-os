"""v252: contract_templates + contract_signing_records tables

电子签约模块。合同模板管理 + 签署流程记录（草稿→待签→员工签→企业盖章→已完成/过期/终止）。

Revision ID: v252
Revises: v251
Create Date: 2026-04-13
"""

from alembic import op

revision = "v293"
down_revision = "v292"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── contract_templates — 合同模板表 ──────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS contract_templates (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            template_name   VARCHAR(200) NOT NULL,
            contract_type   VARCHAR(50) NOT NULL,
            content_html    TEXT DEFAULT '',
            variables       JSONB DEFAULT '[]',
            is_active       BOOLEAN DEFAULT TRUE,
            version         INT DEFAULT 1,
            created_by      UUID,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_contract_tpl_tenant_type
            ON contract_templates (tenant_id, contract_type)
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE contract_templates ENABLE ROW LEVEL SECURITY;
        EXCEPTION WHEN others THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE POLICY contract_templates_rls ON contract_templates
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)

    # ── contract_signing_records — 签署记录表 ────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS contract_signing_records (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            template_id         UUID NOT NULL,
            contract_type       VARCHAR(50) NOT NULL,
            employee_id         UUID NOT NULL,
            employee_name       VARCHAR(100),
            store_id            UUID,
            contract_no         VARCHAR(100),
            start_date          DATE,
            end_date            DATE,
            status              VARCHAR(30) DEFAULT 'draft',
            signed_at           TIMESTAMPTZ,
            company_signed_at   TIMESTAMPTZ,
            company_signer_id   UUID,
            content_snapshot    TEXT,
            variables_filled    JSONB DEFAULT '{}',
            e_sign_doc_id       VARCHAR(200),
            metadata            JSONB DEFAULT '{}',
            expire_remind_days  INT DEFAULT 30,
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            updated_at          TIMESTAMPTZ DEFAULT NOW(),
            is_deleted          BOOLEAN DEFAULT FALSE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_signing_tenant_type
            ON contract_signing_records (tenant_id, contract_type)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_signing_tenant_employee
            ON contract_signing_records (tenant_id, employee_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_signing_tenant_status
            ON contract_signing_records (tenant_id, status)
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE contract_signing_records ENABLE ROW LEVEL SECURITY;
        EXCEPTION WHEN others THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE POLICY contract_signing_records_rls ON contract_signing_records
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contract_signing_records")
    op.execute("DROP TABLE IF EXISTS contract_templates")
