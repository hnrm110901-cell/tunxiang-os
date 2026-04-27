"""v126 — 排班管理表

新增一张表：
  work_schedules — 员工排班计划（按门店/员工/日期）

Revision ID: v126
Revises: v125
Create Date: 2026-04-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v126"
down_revision = "v125"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── work_schedules 员工排班计划 ───────────────────────────────────────────
    if "work_schedules" not in _existing:
        op.create_table(
            "work_schedules",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("employee_id", UUID(as_uuid=True), nullable=False),
            sa.Column("schedule_date", sa.Date, nullable=False),
            sa.Column("shift_start", sa.Time, nullable=False, comment="班次开始时间，如 09:00"),
            sa.Column("shift_end", sa.Time, nullable=False, comment="班次结束时间，如 18:00"),
            sa.Column("role", sa.String(30), nullable=False, comment="cashier/chef/waiter/manager"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="'planned'",
                comment="planned/confirmed/cancelled",
            ),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )

    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='work_schedules' AND column_name IN ('tenant_id', 'store_id', 'schedule_date')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_work_schedules_tenant_store_date ON work_schedules (tenant_id, store_id, schedule_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='work_schedules' AND column_name IN ('employee_id', 'schedule_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_work_schedules_employee_date ON work_schedules (employee_id, schedule_date)';
            END IF;
        END $$;
    """)

    # 防止同一员工同日同时间重复排班
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='work_schedules' AND column_name IN ('tenant_id', 'employee_id', 'schedule_date', 'shift_start')) = 4 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_work_schedules_employee_shift ON work_schedules (tenant_id, employee_id, schedule_date, shift_start)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE work_schedules ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS work_schedules_tenant_isolation ON work_schedules;")
    op.execute("""
        CREATE POLICY work_schedules_tenant_isolation ON work_schedules
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS work_schedules_tenant_isolation ON work_schedules;")
    op.drop_table("work_schedules")
