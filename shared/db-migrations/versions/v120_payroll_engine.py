"""v120 — 薪资计算引擎核心表

新增三张表：
  payroll_configs     — 薪资方案配置（按岗位/门店/有效期）
  payroll_records     — 月度薪资单（draft/approved/paid/voided）
  payroll_line_items  — 薪资明细行（员工可见的每一笔收支明细）

Revision ID: v120
Revises: v119
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v120"
down_revision = "v119"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── payroll_configs 薪资方案配置 ─────────────────────────────────────
    op.create_table(
        "payroll_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=True,
                  comment="NULL 表示品牌级默认配置"),
        sa.Column("employee_role", sa.String(30), nullable=False,
                  comment="cashier/chef/waiter/manager"),
        # 底薪 / 时薪（二选一）
        sa.Column("base_salary_fen", sa.Integer, nullable=True,
                  comment="月薪（分），与 hourly_rate_fen 二选一"),
        sa.Column("hourly_rate_fen", sa.Integer, nullable=True,
                  comment="时薪（分），与 base_salary_fen 二选一"),
        sa.Column("salary_type", sa.String(20), nullable=False,
                  server_default="'monthly'",
                  comment="monthly/hourly/piecework"),
        # 计件工资
        sa.Column("piecework_unit", sa.String(30), nullable=True,
                  comment="per_order/per_dish/per_table"),
        sa.Column("piecework_rate_fen", sa.Integer, nullable=True,
                  comment="每计件单位工资（分）"),
        # 提成配置
        sa.Column("commission_type", sa.String(20), nullable=False,
                  server_default="'none'",
                  comment="none/fixed/percentage"),
        sa.Column("commission_rate", sa.Numeric(6, 4), nullable=True,
                  comment="提成比例，如 0.0500 = 5%"),
        sa.Column("commission_base", sa.String(20), nullable=True,
                  comment="revenue/profit/tips"),
        # 绩效奖金上限
        sa.Column("kpi_bonus_max_fen", sa.Integer, nullable=False,
                  server_default="0",
                  comment="月最高绩效奖金（分）"),
        # 有效期
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date, nullable=True,
                  comment="NULL 表示永久有效"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index(
        "ix_payroll_configs_tenant_store_role",
        "payroll_configs",
        ["tenant_id", "store_id", "employee_role"],
    )
    op.create_index(
        "ix_payroll_configs_tenant_active",
        "payroll_configs",
        ["tenant_id", "is_active"],
    )

    op.execute("ALTER TABLE payroll_configs ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY payroll_configs_tenant_isolation ON payroll_configs
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── payroll_records 月度薪资单 ───────────────────────────────────────
    op.create_table(
        "payroll_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", UUID(as_uuid=True), nullable=False),
        sa.Column("pay_period_start", sa.Date, nullable=False),
        sa.Column("pay_period_end", sa.Date, nullable=False),
        # 各收入分项（分）
        sa.Column("base_pay_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("overtime_pay_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("commission_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("piecework_pay_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("kpi_bonus_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("deduction_fen", sa.Integer, nullable=False, server_default="0",
                  comment="考勤扣款合计（分，正数）"),
        # 计算汇总（分）
        sa.Column("gross_pay_fen", sa.Integer, nullable=False, server_default="0",
                  comment="应发=base+overtime+commission+piecework+kpi-deduction"),
        sa.Column("tax_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("net_pay_fen", sa.Integer, nullable=False, server_default="0",
                  comment="实发=gross-tax"),
        # 状态机
        sa.Column("status", sa.String(20), nullable=False, server_default="'draft'",
                  comment="draft/approved/paid/voided"),
        sa.Column("approved_by", sa.String(100), nullable=True),
        sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("payment_method", sa.String(20), nullable=True,
                  comment="bank/cash/alipay/wechat"),
        sa.Column("notes", sa.Text, nullable=True),
        # 扩展明细（计算快照）
        sa.Column("calc_snapshot", JSONB, nullable=True,
                  comment="计算过程快照，含出勤/加班/绩效原始数据"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index(
        "ix_payroll_records_tenant_store_period",
        "payroll_records",
        ["tenant_id", "store_id", "pay_period_start"],
    )
    op.create_index(
        "ix_payroll_records_employee_period",
        "payroll_records",
        ["employee_id", "pay_period_start"],
    )
    op.create_index(
        "ix_payroll_records_status",
        "payroll_records",
        ["tenant_id", "status"],
    )
    # 同一员工同一月份只能有一条有效薪资单
    op.create_unique_constraint(
        "uq_payroll_records_employee_period",
        "payroll_records",
        ["tenant_id", "employee_id", "pay_period_start"],
    )

    op.execute("ALTER TABLE payroll_records ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY payroll_records_tenant_isolation ON payroll_records
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── payroll_line_items 薪资明细行 ────────────────────────────────────
    op.create_table(
        "payroll_line_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("record_id", UUID(as_uuid=True), nullable=False,
                  comment="FK → payroll_records.id"),
        sa.Column("item_type", sa.String(30), nullable=False,
                  comment="base/overtime/commission/piecework/kpi/deduction/tax"),
        sa.Column("item_name", sa.String(100), nullable=False,
                  comment="员工可见的显示名称"),
        sa.Column("amount_fen", sa.Integer, nullable=False,
                  comment="金额（分），正数=收入，负数=扣除"),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=True,
                  comment="件数/小时数 等数量"),
        sa.Column("unit_price_fen", sa.Integer, nullable=True,
                  comment="单价（分/件 或 分/小时）"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_payroll_line_items_record",
        "payroll_line_items",
        ["record_id"],
    )
    op.create_index(
        "ix_payroll_line_items_tenant",
        "payroll_line_items",
        ["tenant_id"],
    )

    # FK 约束
    op.create_foreign_key(
        "fk_payroll_line_items_record",
        "payroll_line_items", "payroll_records",
        ["record_id"], ["id"],
        ondelete="CASCADE",
    )

    op.execute("ALTER TABLE payroll_line_items ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY payroll_line_items_tenant_isolation ON payroll_line_items
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS payroll_line_items_tenant_isolation ON payroll_line_items;")
    op.drop_table("payroll_line_items")

    op.execute("DROP POLICY IF EXISTS payroll_records_tenant_isolation ON payroll_records;")
    op.drop_table("payroll_records")

    op.execute("DROP POLICY IF EXISTS payroll_configs_tenant_isolation ON payroll_configs;")
    op.drop_table("payroll_configs")
