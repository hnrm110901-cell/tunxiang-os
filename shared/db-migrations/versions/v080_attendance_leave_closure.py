"""v077: 考勤打卡与请假管理完整闭环补充字段

补充内容：
1. leave_requests 表添加 approval_instance_id、half_day 支持、deduction_fen
2. employee_schedules 表（员工每日排班分配，连接 shift_configs）
3. approval_workflow_templates / approval_instances 的 business_type 扩展（leave）

Revision ID: v077
Revises: v076_brand_publish_system
Create Date: 2026-03-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "v080"
down_revision= "v079"
branch_labels= None
depends_on= None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # 1. leave_requests 补充字段
    # ---------------------------------------------------------------
    # approval_instance_id: 关联审批流实例
    op.add_column(
        "leave_requests",
        sa.Column("approval_instance_id", UUID(as_uuid=True), nullable=True,
                  comment="关联审批流实例 ID"),
    )
    # start_half_day / end_half_day: 支持半天请假
    op.add_column(
        "leave_requests",
        sa.Column("start_half_day", sa.Boolean, nullable=False, server_default="false",
                  comment="开始日是否半天（下午）"),
    )
    op.add_column(
        "leave_requests",
        sa.Column("end_half_day", sa.Boolean, nullable=False, server_default="false",
                  comment="结束日是否半天（上午）"),
    )
    # deduction_fen: 事假/病假扣款（分），审批通过后由薪资引擎填写
    op.add_column(
        "leave_requests",
        sa.Column("deduction_fen", sa.BigInteger, nullable=False, server_default="0",
                  comment="薪资扣减金额（分），事假/病假"),
    )
    # store_id 已存在，toil 类型通过 leave_type='toil' 支持

    # ---------------------------------------------------------------
    # 2. employee_schedules — 员工每日排班分配表
    # ---------------------------------------------------------------
    op.create_table(
        "employee_schedules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("employee_id", sa.String(64), nullable=False),
        sa.Column("work_date", sa.Date, nullable=False),
        sa.Column("shift_config_id", UUID(as_uuid=True), nullable=True,
                  comment="关联 shift_configs.id，NULL 表示当日休息"),
        sa.Column("shift_name", sa.String(50), nullable=True,
                  comment="冗余班次名称（快速查询）"),
        sa.Column("shift_start_time", sa.Time, nullable=True,
                  comment="冗余班次开始时间"),
        sa.Column("shift_end_time", sa.Time, nullable=True,
                  comment="冗余班次结束时间"),
        sa.Column("is_day_off", sa.Boolean, nullable=False, server_default="false",
                  comment="是否排休/当日不上班"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
        sa.UniqueConstraint("tenant_id", "employee_id", "work_date",
                            name="uq_employee_schedules_emp_date"),
    )
    op.create_index(
        "ix_employee_schedules_store_date",
        "employee_schedules",
        ["store_id", "work_date"],
    )
    op.create_index(
        "ix_employee_schedules_employee_date",
        "employee_schedules",
        ["employee_id", "work_date"],
    )

    # RLS for employee_schedules
    op.execute("ALTER TABLE employee_schedules ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_employee_schedules ON employee_schedules "
        "USING (tenant_id = current_setting('app.tenant_id')::UUID)"
    )
    op.execute(
        "CREATE POLICY tenant_insert_employee_schedules ON employee_schedules "
        "FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID)"
    )

    # ---------------------------------------------------------------
    # 3. daily_attendance 补充 late_minutes / early_leave_minutes
    # ---------------------------------------------------------------
    op.add_column(
        "daily_attendance",
        sa.Column("late_minutes", sa.Integer, nullable=False, server_default="0",
                  comment="迟到分钟数"),
    )
    op.add_column(
        "daily_attendance",
        sa.Column("early_leave_minutes", sa.Integer, nullable=False, server_default="0",
                  comment="早退分钟数"),
    )


def downgrade() -> None:
    op.drop_column("daily_attendance", "early_leave_minutes")
    op.drop_column("daily_attendance", "late_minutes")

    op.execute("DROP POLICY IF EXISTS tenant_insert_employee_schedules ON employee_schedules")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_employee_schedules ON employee_schedules")
    op.drop_table("employee_schedules")

    op.drop_column("leave_requests", "deduction_fen")
    op.drop_column("leave_requests", "end_half_day")
    op.drop_column("leave_requests", "start_half_day")
    op.drop_column("leave_requests", "approval_instance_id")
