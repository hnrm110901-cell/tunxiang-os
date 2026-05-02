"""Sprint B4: 劳动合同扫描 — employee_labor_contracts

劳动合同法第10条：建立劳动关系应当订立书面劳动合同。
逾期不签：2N 人均 1.6 万罚款风险。

表:
  employee_labor_contracts — 员工劳动合同档案

合同类型:
  fixed_term    — 固定期限
  open_ended    — 无固定期限
  probation     — 试用期

状态:
  active          — 正常
  expiring_soon   — 即将到期（30天内）
  expired         — 已过期
  terminated      — 已终止

RLS: 4条 PERMISSIVE + FORCE

Revision ID: v387_employee_labor_contracts
Revises: v386_civic_trace_submissions
Create Date: 2026-05-02
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v387_employee_labor_contracts"
down_revision: Union[str, None] = "v386_civic_trace_submissions"
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
        CREATE TABLE IF NOT EXISTS employee_labor_contracts (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            employee_id         UUID NOT NULL,
            contract_type       VARCHAR(32) NOT NULL
                                    CHECK (contract_type IN (
                                        'fixed_term', 'open_ended', 'probation'
                                    )),
            signed_at           DATE,
            expires_at          DATE,
            file_path           VARCHAR(512),
            status              VARCHAR(16) DEFAULT 'active'
                                    CHECK (status IN (
                                        'active', 'expiring_soon',
                                        'expired', 'terminated'
                                    )),
            reminder_sent       BOOLEAN DEFAULT FALSE,
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            is_deleted          BOOLEAN DEFAULT FALSE,

            CONSTRAINT uq_employee_contract_type
                UNIQUE (employee_id, contract_type)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_labor_contracts_tenant
            ON employee_labor_contracts (tenant_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_labor_contracts_employee
            ON employee_labor_contracts (employee_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_labor_contracts_status
            ON employee_labor_contracts (status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_labor_contracts_expires
            ON employee_labor_contracts (expires_at)
            WHERE expires_at IS NOT NULL AND is_deleted = FALSE
    """)

    _enable_rls("employee_labor_contracts")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS employee_labor_contracts CASCADE")
