"""Sprint B3: 湘食通合规 — civic_traceability_submissions

湖南省湘食通食品安全追溯平台的上报数据表。

表:
  civic_traceability_submissions — 湘食通上报记录

上报类型:
  ingredient_batch   — 食材批次
  waste_disposal     — 废弃物处理
  inspection_report  — 检测报告

RLS: 4条 PERMISSIVE + FORCE

Revision ID: v386_civic_trace_submissions
Revises: v385_invoice_compliance
Create Date: 2026-05-02
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v386_civic_trace_submissions"
down_revision: Union[str, None] = "v385_invoice_compliance"
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
    op.execute("""
        CREATE TABLE IF NOT EXISTS civic_traceability_submissions (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID,
            submission_type     VARCHAR(32) NOT NULL
                                    CHECK (submission_type IN (
                                        'ingredient_batch',
                                        'waste_disposal',
                                        'inspection_report'
                                    )),
            payload             JSONB NOT NULL,
            status              VARCHAR(16) DEFAULT 'draft'
                                    CHECK (status IN (
                                        'draft', 'submitted',
                                        'acknowledged', 'rejected'
                                    )),
            submission_id       VARCHAR(128),
            acknowledged_at     TIMESTAMPTZ,
            error_message       TEXT,
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            is_deleted          BOOLEAN DEFAULT FALSE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_civic_trace_submissions_tenant
            ON civic_traceability_submissions (tenant_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_civic_trace_submissions_store
            ON civic_traceability_submissions (store_id)
            WHERE store_id IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_civic_trace_submissions_type
            ON civic_traceability_submissions (submission_type)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_civic_trace_submissions_status
            ON civic_traceability_submissions (status)
    """)

    _enable_rls("civic_traceability_submissions")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS civic_traceability_submissions CASCADE")
