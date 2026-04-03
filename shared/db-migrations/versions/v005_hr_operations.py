"""v005: HR Operations tables for Sprint 5-6

New tables:
- attendance_rules: store-level attendance policies (grace period, OT rules)
- clock_records: individual clock-in/out events with method/status
- daily_attendance: aggregated daily view per employee
- payroll_batches: monthly payroll calculation batches
- payroll_items: per-employee payroll line items (base, commission, tax, etc.)
- leave_requests: leave applications with approval workflow
- leave_balances: employee annual leave quotas per type
- settlement_records: finalized payroll settlement (bank transfer)

Revision ID: v005
Revises: v004
Create Date: 2026-03-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON, ARRAY

revision: str = "v005"
down_revision: Union[str, None] = "v004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_TABLES = [
    "attendance_rules",
    "clock_records",
    "daily_attendance",
    "payroll_batches",
    "payroll_items",
    "leave_requests",
    "leave_balances",
    "settlement_records",
]


def _enable_rls(table_name: str) -> None:
    """为表启用 RLS + 创建租户隔离策略"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table_name} ON {table_name} "
        f"USING (tenant_id = current_setting('app.tenant_id')::UUID)"
    )
    op.execute(
        f"CREATE POLICY tenant_insert_{table_name} ON {table_name} "
        f"FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID)"
    )


def _disable_rls(table_name: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_insert_{table_name} ON {table_name}")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table_name} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # ---------------------------------------------------------------
    # 1. attendance_rules — 考勤规则
    # ---------------------------------------------------------------
    op.create_table(
        "attendance_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("rule_name", sa.String(128), nullable=False),
        sa.Column("grace_period_minutes", sa.Integer, nullable=False, server_default="5",
                  comment="迟到宽限分钟"),
        sa.Column("early_leave_grace_minutes", sa.Integer, nullable=False, server_default="5"),
        sa.Column("overtime_min_minutes", sa.Integer, nullable=False, server_default="30",
                  comment="加班最低认定分钟"),
        sa.Column("max_hours_week", sa.Integer, nullable=False, server_default="40"),
        sa.Column("max_overtime_month_hours", sa.Integer, nullable=False, server_default="36"),
        sa.Column("late_deduction_fen", sa.BigInteger, nullable=False, server_default="5000",
                  comment="每次迟到扣款(分)"),
        sa.Column("early_leave_deduction_fen", sa.BigInteger, nullable=False, server_default="5000"),
        sa.Column("full_attendance_bonus_fen", sa.BigInteger, nullable=False, server_default="30000",
                  comment="全勤奖(分)"),
        sa.Column("clock_methods", ARRAY(sa.String), server_default="{device,face,app}",
                  comment="允许的打卡方式"),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_attendance_rules_store", "attendance_rules", ["store_id"])

    # ---------------------------------------------------------------
    # 2. clock_records — 打卡记录
    # ---------------------------------------------------------------
    op.create_table(
        "clock_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("employee_id", sa.String(64), nullable=False),
        sa.Column("clock_type", sa.String(10), nullable=False, comment="in/out"),
        sa.Column("clock_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.String(20), nullable=False, server_default="device",
                  comment="device/face/app/manual"),
        sa.Column("scheduled_shift", sa.String(32), nullable=True, comment="排班班次名称"),
        sa.Column("scheduled_time", sa.DateTime(timezone=True), nullable=True,
                  comment="排班应到时间"),
        sa.Column("status", sa.String(20), nullable=False, server_default="on_time",
                  comment="on_time/late/early/early_leave/overtime/unscheduled"),
        sa.Column("diff_minutes", sa.Integer, nullable=True,
                  comment="与排班时间差异(分钟，正=迟到/加班)"),
        sa.Column("paired_clock_id", UUID(as_uuid=True), nullable=True,
                  comment="配对的打卡记录ID(out配in)"),
        sa.Column("work_hours", sa.Float, nullable=True, comment="实际工时(小时)"),
        sa.Column("device_info", sa.String(256), nullable=True),
        sa.Column("location", sa.String(256), nullable=True, comment="打卡位置"),
        sa.Column("photo_url", sa.String(512), nullable=True, comment="人脸打卡照片"),
        sa.Column("remark", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.execute("CREATE INDEX ix_clock_records_employee_date ON clock_records (employee_id, clock_time)")
    op.execute("CREATE INDEX ix_clock_records_store_date ON clock_records (store_id, clock_time)")

    # ---------------------------------------------------------------
    # 3. daily_attendance — 日考勤汇总
    # ---------------------------------------------------------------
    op.create_table(
        "daily_attendance",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("employee_id", sa.String(64), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("scheduled_shift", sa.String(32), nullable=True),
        sa.Column("clock_in_id", UUID(as_uuid=True), nullable=True),
        sa.Column("clock_out_id", UUID(as_uuid=True), nullable=True),
        sa.Column("clock_in_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clock_out_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending",
                  comment="normal/late/early_leave/absent/overtime/on_leave/day_off/missing_clock_out"),
        sa.Column("work_hours", sa.Float, nullable=True),
        sa.Column("overtime_hours", sa.Float, server_default="0"),
        sa.Column("leave_type", sa.String(32), nullable=True),
        sa.Column("leave_id", UUID(as_uuid=True), nullable=True),
        sa.Column("remark", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
        sa.UniqueConstraint("tenant_id", "employee_id", "date", name="uq_daily_attendance_emp_date"),
    )
    op.create_index("ix_daily_attendance_store_date", "daily_attendance", ["store_id", "date"])
    op.execute("CREATE INDEX ix_daily_attendance_employee_month ON daily_attendance (employee_id, date)")

    # ---------------------------------------------------------------
    # 4. payroll_batches — 薪资批次
    # ---------------------------------------------------------------
    op.create_table(
        "payroll_batches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("batch_no", sa.String(64), nullable=False, unique=True),
        sa.Column("month", sa.String(7), nullable=False, comment="YYYY-MM"),
        sa.Column("employee_count", sa.Integer, nullable=False),
        sa.Column("total_gross_fen", sa.BigInteger, nullable=False),
        sa.Column("total_net_fen", sa.BigInteger, nullable=False),
        sa.Column("total_company_si_fen", sa.BigInteger, nullable=False,
                  comment="公司承担五险一金(分)"),
        sa.Column("total_labor_cost_fen", sa.BigInteger, nullable=False,
                  comment="总人力成本(分)=gross+company_si"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft",
                  comment="draft/approved/paid/cancelled"),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("approved_by", sa.String(64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_payroll_batches_store_month", "payroll_batches", ["store_id", "month"])

    # ---------------------------------------------------------------
    # 5. payroll_items — 薪资明细
    # ---------------------------------------------------------------
    op.create_table(
        "payroll_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", sa.String(64), nullable=False),
        sa.Column("month", sa.String(7), nullable=False),

        # Income
        sa.Column("base_pay_fen", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("position_allowance_fen", sa.BigInteger, server_default="0"),
        sa.Column("commission_fen", sa.BigInteger, server_default="0"),
        sa.Column("overtime_pay_fen", sa.BigInteger, server_default="0"),
        sa.Column("overtime_weekday_fen", sa.BigInteger, server_default="0"),
        sa.Column("overtime_weekend_fen", sa.BigInteger, server_default="0"),
        sa.Column("overtime_holiday_fen", sa.BigInteger, server_default="0"),
        sa.Column("performance_bonus_fen", sa.BigInteger, server_default="0"),
        sa.Column("seniority_subsidy_fen", sa.BigInteger, server_default="0"),
        sa.Column("full_attendance_bonus_fen", sa.BigInteger, server_default="0"),
        sa.Column("other_income_fen", sa.BigInteger, server_default="0"),
        sa.Column("gross_salary_fen", sa.BigInteger, nullable=False),

        # Deductions
        sa.Column("absence_deduction_fen", sa.BigInteger, server_default="0"),
        sa.Column("late_deduction_fen", sa.BigInteger, server_default="0"),
        sa.Column("early_leave_deduction_fen", sa.BigInteger, server_default="0"),
        sa.Column("pension_employee_fen", sa.BigInteger, server_default="0"),
        sa.Column("medical_employee_fen", sa.BigInteger, server_default="0"),
        sa.Column("unemployment_employee_fen", sa.BigInteger, server_default="0"),
        sa.Column("housing_fund_employee_fen", sa.BigInteger, server_default="0"),
        sa.Column("tax_fen", sa.BigInteger, server_default="0"),
        sa.Column("other_deduction_fen", sa.BigInteger, server_default="0"),
        sa.Column("total_deduction_fen", sa.BigInteger, nullable=False),

        # Company costs
        sa.Column("pension_company_fen", sa.BigInteger, server_default="0"),
        sa.Column("medical_company_fen", sa.BigInteger, server_default="0"),
        sa.Column("unemployment_company_fen", sa.BigInteger, server_default="0"),
        sa.Column("work_injury_company_fen", sa.BigInteger, server_default="0"),
        sa.Column("maternity_company_fen", sa.BigInteger, server_default="0"),
        sa.Column("housing_fund_company_fen", sa.BigInteger, server_default="0"),

        # Net
        sa.Column("net_pay_fen", sa.BigInteger, nullable=False),

        # Tax detail
        sa.Column("tax_rate", sa.Float, server_default="0"),
        sa.Column("cumulative_taxable_yuan", sa.Float, server_default="0"),
        sa.Column("cumulative_tax_yuan", sa.Float, server_default="0"),

        # Attendance summary
        sa.Column("work_days_in_month", sa.Integer, nullable=False),
        sa.Column("attendance_days", sa.Float, nullable=False),
        sa.Column("absence_days", sa.Float, server_default="0"),
        sa.Column("late_count", sa.Integer, server_default="0"),
        sa.Column("early_leave_count", sa.Integer, server_default="0"),
        sa.Column("overtime_hours", sa.Float, server_default="0"),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_payroll_items_batch", "payroll_items", ["batch_id"])
    op.create_index("ix_payroll_items_employee_month", "payroll_items", ["employee_id", "month"])

    # ---------------------------------------------------------------
    # 6. leave_requests — 请假申请
    # ---------------------------------------------------------------
    op.create_table(
        "leave_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("employee_id", sa.String(64), nullable=False),
        sa.Column("leave_type", sa.String(32), nullable=False,
                  comment="annual/sick/personal/maternity/paternity/marriage/bereavement"),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("days_requested", sa.Float, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("attachments", JSON, nullable=True, comment="附件（病假条等）URL列表"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending",
                  comment="pending/approved/rejected/cancelled"),
        sa.Column("approved_by", sa.String(64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_leave_requests_employee", "leave_requests", ["employee_id"])
    op.create_index("ix_leave_requests_store_status", "leave_requests", ["store_id", "status"])
    op.create_index("ix_leave_requests_dates", "leave_requests", ["start_date", "end_date"])

    # ---------------------------------------------------------------
    # 7. leave_balances — 假期余额
    # ---------------------------------------------------------------
    op.create_table(
        "leave_balances",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", sa.String(64), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("leave_type", sa.String(32), nullable=False),
        sa.Column("total_days", sa.Float, nullable=False, comment="年度总额度"),
        sa.Column("used_days", sa.Float, nullable=False, server_default="0"),
        sa.Column("remaining_days", sa.Float, nullable=False),
        sa.Column("carried_over_days", sa.Float, server_default="0",
                  comment="上年结转天数"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
        sa.UniqueConstraint("tenant_id", "employee_id", "year", "leave_type",
                            name="uq_leave_balance_emp_year_type"),
    )
    op.create_index("ix_leave_balances_employee_year", "leave_balances", ["employee_id", "year"])

    # ---------------------------------------------------------------
    # 8. settlement_records — 薪资结算打款记录
    # ---------------------------------------------------------------
    op.create_table(
        "settlement_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", sa.String(64), nullable=False),
        sa.Column("payroll_item_id", UUID(as_uuid=True), nullable=False),
        sa.Column("amount_fen", sa.BigInteger, nullable=False, comment="实发金额(分)"),
        sa.Column("bank_name", sa.String(64), nullable=True),
        sa.Column("bank_account", sa.String(32), nullable=True, comment="银行卡号(脱敏)"),
        sa.Column("transfer_ref", sa.String(128), nullable=True, comment="银行流水号"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending",
                  comment="pending/processing/success/failed"),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column("transferred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_settlement_records_batch", "settlement_records", ["batch_id"])
    op.create_index("ix_settlement_records_employee", "settlement_records", ["employee_id"])

    # ---------------------------------------------------------------
    # Enable RLS on all new tables
    # ---------------------------------------------------------------
    for table in NEW_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        _disable_rls(table)
        op.drop_table(table)
