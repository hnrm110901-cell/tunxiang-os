"""Sprint B2: 金税四期合规 — invoice_xml_archive + invoice_ocr_jobs

全电发票 XML 归档 + 发票 OCR 识别任务。

表:
  invoice_xml_archive  — 全电发票 XML（金税四期格式）归档 + XSD 校验
  invoice_ocr_jobs     — 发票 OCR 识别任务队列

RLS: 4条 PERMISSIVE + FORCE

Revision ID: v385_invoice_compliance
Revises: v384_overtime_compliance
Create Date: 2026-05-02
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v385_invoice_compliance"
down_revision: Union[str, None] = "v384_overtime_compliance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        policy = f"rls_{table}_{action.lower()}"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(
            f"CREATE POLICY {policy} ON {table} "
            f"AS PERMISSIVE FOR {action} TO PUBLIC "
            f"USING (tenant_id = {_RLS_EXPR})"
        )


def upgrade() -> None:
    # ---- invoice_xml_archive ----
    op.execute("""
        CREATE TABLE IF NOT EXISTS invoice_xml_archive (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID,
            invoice_id          UUID,
            xml_content         TEXT NOT NULL,
            schema_version      VARCHAR(16),
            status              VARCHAR(16) DEFAULT 'pending'
                                    CHECK (status IN (
                                        'pending', 'validated', 'rejected', 'submitted'
                                    )),
            validation_errors   JSONB,
            submitted_at        TIMESTAMPTZ,
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            is_deleted          BOOLEAN DEFAULT FALSE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invoice_xml_tenant
            ON invoice_xml_archive (tenant_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invoice_xml_invoice
            ON invoice_xml_archive (invoice_id)
            WHERE invoice_id IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invoice_xml_status
            ON invoice_xml_archive (status)
    """)

    # ---- invoice_ocr_jobs ----
    op.execute("""
        CREATE TABLE IF NOT EXISTS invoice_ocr_jobs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            image_path      VARCHAR(512),
            ocr_result      JSONB,
            status          VARCHAR(16) DEFAULT 'pending'
                                CHECK (status IN (
                                    'pending', 'processing', 'done', 'failed'
                                )),
            invoice_id      UUID,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invoice_ocr_jobs_tenant
            ON invoice_ocr_jobs (tenant_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invoice_ocr_jobs_status
            ON invoice_ocr_jobs (status)
    """)

    # RLS
    _enable_rls("invoice_xml_archive")
    _enable_rls("invoice_ocr_jobs")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS invoice_xml_archive CASCADE")
    op.execute("DROP TABLE IF EXISTS invoice_ocr_jobs CASCADE")
