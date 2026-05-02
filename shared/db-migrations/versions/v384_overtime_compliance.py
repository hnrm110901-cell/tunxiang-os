"""Sprint B1: 加班合规管控 — schedule_compliance_blocks + monthly_overtime_summary

劳动法第四十一条：月加班不超过 36 小时。
超过 32h 预警 → 超过 36h 自动冻结排班 → HRD+CEO 双签覆盖。

表:
  schedule_compliance_blocks  — 排班冻结（employee_id + block_date 唯一）
  monthly_overtime_summary    — 月度加班累计快照

RLS: 4条 PERMISSIVE + FORCE

Revision ID: v384_overtime_compliance
Revises: v383_chain_consolidation
Create Date: 2026-05-02
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v384_overtime_compliance"
down_revision: Union[str, None] = "v383_chain_consolidation"
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
    # ---- schedule_compliance_blocks ----
    op.execute("""
        CREATE TABLE IF NOT EXISTS schedule_compliance_blocks (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            employee_id     UUID NOT NULL,
            block_date      DATE NOT NULL,
            reason          VARCHAR(128),
            override_by     UUID,
            override_reason VARCHAR(256),
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE,

            CONSTRAINT uq_schedule_block_employee_date
                UNIQUE (employee_id, block_date)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_schedule_blocks_tenant
            ON schedule_compliance_blocks (tenant_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_schedule_blocks_employee
            ON schedule_compliance_blocks (employee_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_schedule_blocks_date
            ON schedule_compliance_blocks (block_date)
    """)

    # ---- monthly_overtime_summary ----
    op.execute("""
        CREATE TABLE IF NOT EXISTS monthly_overtime_summary (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            employee_id             UUID NOT NULL,
            year_month              DATE NOT NULL,
            total_overtime_hours    NUMERIC(5,1) DEFAULT 0,
            last_calculated_at      TIMESTAMPTZ DEFAULT NOW(),
            is_deleted              BOOLEAN DEFAULT FALSE,

            CONSTRAINT uq_overtime_summary_employee_month
                UNIQUE (employee_id, year_month)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_overtime_summary_tenant
            ON monthly_overtime_summary (tenant_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_overtime_summary_employee
            ON monthly_overtime_summary (employee_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_overtime_summary_month
            ON monthly_overtime_summary (year_month)
    """)

    # RLS
    _enable_rls("schedule_compliance_blocks")
    _enable_rls("monthly_overtime_summary")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS schedule_compliance_blocks CASCADE")
    op.execute("DROP TABLE IF EXISTS monthly_overtime_summary CASCADE")
