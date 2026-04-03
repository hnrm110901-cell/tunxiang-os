"""v126 — 排班管理表

新增一张表：
  work_schedules — 员工排班计划（按门店/员工/日期）

Revision ID: v126
Revises: v125
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "v126"
down_revision = "v125"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── work_schedules 员工排班计划 ───────────────────────────────────────────
    op.create_table(
        "work_schedules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_date", sa.Date, nullable=False),
        sa.Column("shift_start", sa.Time, nullable=False,
                  comment="班次开始时间，如 09:00"),
        sa.Column("shift_end", sa.Time, nullable=False,
                  comment="班次结束时间，如 18:00"),
        sa.Column("role", sa.String(30), nullable=False,
                  comment="cashier/chef/waiter/manager"),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="'planned'",
                  comment="planned/confirmed/cancelled"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )

    op.create_index(
        "ix_work_schedules_tenant_store_date",
        "work_schedules",
        ["tenant_id", "store_id", "schedule_date"],
    )
    op.create_index(
        "ix_work_schedules_employee_date",
        "work_schedules",
        ["employee_id", "schedule_date"],
    )

    # 防止同一员工同日同时间重复排班
    op.create_unique_constraint(
        "uq_work_schedules_employee_shift",
        "work_schedules",
        ["tenant_id", "employee_id", "schedule_date", "shift_start"],
    )

    op.execute("ALTER TABLE work_schedules ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY work_schedules_tenant_isolation ON work_schedules
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS work_schedules_tenant_isolation ON work_schedules;")
    op.drop_table("work_schedules")
