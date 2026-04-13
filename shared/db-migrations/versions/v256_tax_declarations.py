"""v256: tax_declarations — 个税申报记录表

薪税申报对接模块持久化存储。

Revision ID: v256
Revises: v255
Create Date: 2026-04-13
"""
from alembic import op

revision = "v256"
down_revision = "v255"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── tax_declarations — 个税申报记录表 ──────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS tax_declarations (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID NOT NULL,
            store_id          UUID NOT NULL,
            month             VARCHAR(7) NOT NULL,
            employee_count    INT NOT NULL DEFAULT 0,
            total_tax_fen     BIGINT NOT NULL DEFAULT 0,
            declaration_data  JSONB,
            status            VARCHAR(20) NOT NULL DEFAULT 'draft',
            receipt_no        VARCHAR(64),
            submitted_at      TIMESTAMPTZ,
            created_at        TIMESTAMPTZ DEFAULT NOW(),
            updated_at        TIMESTAMPTZ DEFAULT NOW(),
            is_deleted        BOOLEAN DEFAULT FALSE
        );
    """)
    op.execute("""
        ALTER TABLE tax_declarations ENABLE ROW LEVEL SECURITY;
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'tax_declarations'
                  AND policyname = 'tax_declarations_tenant_isolation'
            ) THEN
                CREATE POLICY tax_declarations_tenant_isolation
                ON tax_declarations
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
            END IF;
        END $$;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_tax_declarations_tenant_month
        ON tax_declarations (tenant_id, month DESC);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_tax_declarations_store
        ON tax_declarations (tenant_id, store_id, month DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tax_declarations CASCADE;")
