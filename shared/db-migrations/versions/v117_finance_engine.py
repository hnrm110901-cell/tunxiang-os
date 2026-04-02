"""v117 — 财务计算引擎核心表

新建：
  daily_pnl         — 门店日损益表（每店每日一条）
  cost_items        — 成本明细（采购/损耗/劳动力/房租等每笔记录）
  revenue_records   — 收入明细（从订单聚合，按渠道分类）
  finance_configs   — 财务配置（成本比例/房租/水电等门店级配置）

所有表 tenant_id + RLS（app.tenant_id）。

Revision ID: v117
Revises: v116
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC

revision = "v117"
down_revision = "v116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── daily_pnl 日损益表 ──────────────────────────────────────────────────
    op.create_table(
        "daily_pnl",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False),
        sa.Column("pnl_date", sa.Date, nullable=False),

        # 收入侧
        sa.Column("gross_revenue_fen", sa.Integer, nullable=False, server_default="0",
                  comment="合计营收（分）"),
        sa.Column("dine_in_revenue_fen", sa.Integer, nullable=False, server_default="0",
                  comment="堂食营收（分）"),
        sa.Column("takeaway_revenue_fen", sa.Integer, nullable=False, server_default="0",
                  comment="外卖营收（分）"),
        sa.Column("banquet_revenue_fen", sa.Integer, nullable=False, server_default="0",
                  comment="宴席营收（分）"),
        sa.Column("discount_amount_fen", sa.Integer, nullable=False, server_default="0",
                  comment="折扣金额（分）"),
        sa.Column("net_revenue_fen", sa.Integer, nullable=False, server_default="0",
                  comment="净营收 = gross_revenue - discount（分）"),

        # 成本侧
        sa.Column("food_cost_fen", sa.Integer, nullable=False, server_default="0",
                  comment="食材成本（分，BOM展开+损耗）"),
        sa.Column("labor_cost_fen", sa.Integer, nullable=False, server_default="0",
                  comment="人工成本（分，从排班实际工时计算）"),
        sa.Column("rent_cost_fen", sa.Integer, nullable=False, server_default="0",
                  comment="房租分摊（分，月租/当月天数）"),
        sa.Column("utilities_cost_fen", sa.Integer, nullable=False, server_default="0",
                  comment="水电分摊（分）"),
        sa.Column("other_cost_fen", sa.Integer, nullable=False, server_default="0",
                  comment="其他成本（分）"),
        sa.Column("total_cost_fen", sa.Integer, nullable=False, server_default="0",
                  comment="总成本 = food+labor+rent+utilities+other（分）"),

        # 利润侧
        sa.Column("gross_profit_fen", sa.Integer, nullable=False, server_default="0",
                  comment="毛利 = net_revenue - food_cost（分）"),
        sa.Column(
            "gross_margin_pct", NUMERIC(5, 2), nullable=False, server_default="0.00",
            comment="毛利率（百分比，如 68.50 表示 68.50%）",
        ),
        sa.Column("operating_profit_fen", sa.Integer, nullable=False, server_default="0",
                  comment="经营利润 = gross_profit - labor - rent - utilities - other（分）"),
        sa.Column("net_profit_fen", sa.Integer, nullable=False, server_default="0",
                  comment="净利润（分，当前与 operating_profit 相同，预留税后使用）"),
        sa.Column(
            "net_margin_pct", NUMERIC(5, 2), nullable=False, server_default="0.00",
            comment="净利润率（百分比）",
        ),

        # 经营指标
        sa.Column("orders_count", sa.Integer, nullable=False, server_default="0",
                  comment="当日订单数"),
        sa.Column("avg_order_value_fen", sa.Integer, nullable=False, server_default="0",
                  comment="客单价（分）"),
        sa.Column(
            "table_turnover_rate", NUMERIC(4, 2), nullable=False, server_default="0.00",
            comment="翻台率",
        ),

        # 状态
        sa.Column("status", sa.String(20), nullable=False, server_default="'draft'",
                  comment="draft/confirmed/locked"),
        sa.Column("calculated_at", sa.TIMESTAMP(timezone=True), nullable=True,
                  comment="最近一次计算时间"),
        sa.Column("confirmed_by", UUID(as_uuid=True), nullable=True,
                  comment="确认人员ID"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),

        sa.UniqueConstraint("tenant_id", "store_id", "pnl_date", name="uq_daily_pnl_store_date"),
    )

    op.create_index("ix_daily_pnl_store_date", "daily_pnl", ["store_id", "pnl_date"])
    op.create_index("ix_daily_pnl_tenant_date", "daily_pnl", ["tenant_id", "pnl_date"])
    op.create_index("ix_daily_pnl_status", "daily_pnl", ["status"])

    op.execute("ALTER TABLE daily_pnl ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY daily_pnl_tenant_isolation ON daily_pnl
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── cost_items 成本明细 ─────────────────────────────────────────────────
    op.create_table(
        "cost_items",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False),
        sa.Column("cost_date", sa.Date, nullable=False),
        sa.Column(
            "cost_type", sa.String(30), nullable=False,
            comment="purchase/wastage/live_seafood_death/labor/rent/utilities/other",
        ),
        sa.Column("reference_id", UUID(as_uuid=True), nullable=True,
                  comment="关联采购单/损耗记录/排班等外键ID"),
        sa.Column("description", sa.String(200), nullable=True,
                  comment="成本描述"),
        sa.Column("amount_fen", sa.Integer, nullable=False, server_default="0",
                  comment="金额（分）"),
        sa.Column(
            "quantity", NUMERIC(10, 3), nullable=True,
            comment="数量（kg/个/份等）",
        ),
        sa.Column("unit", sa.String(20), nullable=True,
                  comment="单位（kg/g/个/份）"),
        sa.Column("unit_cost_fen", sa.Integer, nullable=True,
                  comment="单位成本（分）"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )

    op.create_index("ix_cost_items_store_date", "cost_items", ["store_id", "cost_date"])
    op.create_index("ix_cost_items_tenant_date", "cost_items", ["tenant_id", "cost_date"])
    op.create_index("ix_cost_items_cost_type", "cost_items", ["cost_type"])
    op.create_index("ix_cost_items_reference_id", "cost_items", ["reference_id"])

    op.execute("ALTER TABLE cost_items ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY cost_items_tenant_isolation ON cost_items
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── revenue_records 收入明细 ────────────────────────────────────────────
    op.create_table(
        "revenue_records",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False),
        sa.Column("record_date", sa.Date, nullable=False),
        sa.Column("order_id", UUID(as_uuid=True), nullable=True,
                  comment="关联订单ID"),
        sa.Column(
            "channel", sa.String(30), nullable=False,
            comment="dine_in/meituan/eleme/banquet/self_order/other",
        ),
        sa.Column("gross_amount_fen", sa.Integer, nullable=False, server_default="0",
                  comment="订单原始金额（分）"),
        sa.Column("discount_fen", sa.Integer, nullable=False, server_default="0",
                  comment="折扣金额（分）"),
        sa.Column("net_amount_fen", sa.Integer, nullable=False, server_default="0",
                  comment="净收入 = gross - discount（分）"),
        sa.Column("payment_method", sa.String(30), nullable=True,
                  comment="支付方式（wechat/alipay/cash/card/etc.）"),
        sa.Column("is_actual_revenue", sa.Boolean, nullable=False, server_default="true",
                  comment="是否为实际到账（团购券等可能有差异）"),
        sa.Column("actual_revenue_fen", sa.Integer, nullable=True,
                  comment="实际到账金额（分，团购结算后金额）"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),

        sa.UniqueConstraint("tenant_id", "order_id", name="uq_revenue_records_order"),
    )

    op.create_index("ix_revenue_records_store_date", "revenue_records", ["store_id", "record_date"])
    op.create_index("ix_revenue_records_tenant_date", "revenue_records", ["tenant_id", "record_date"])
    op.create_index("ix_revenue_records_channel", "revenue_records", ["channel"])
    op.create_index("ix_revenue_records_order_id", "revenue_records", ["order_id"])

    op.execute("ALTER TABLE revenue_records ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY revenue_records_tenant_isolation ON revenue_records
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── finance_configs 财务配置 ────────────────────────────────────────────
    op.create_table(
        "finance_configs",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=True,
                  comment="NULL=集团级通用配置 / 有值=门店专属配置"),
        sa.Column(
            "config_type", sa.String(50), nullable=False,
            comment=(
                "labor_cost_pct         — 人工成本目标比率\n"
                "rent_monthly_fen       — 月租金（分）\n"
                "utilities_daily_fen    — 日水电预算（分）\n"
                "target_food_cost_pct   — 食材成本目标比率\n"
                "other_daily_opex_fen   — 日其他运营费（分）"
            ),
        ),
        sa.Column("value_fen", sa.Integer, nullable=True,
                  comment="金额类配置（分）"),
        sa.Column(
            "value_pct", NUMERIC(5, 2), nullable=True,
            comment="百分比类配置（如 30.00 表示 30%）",
        ),
        sa.Column("effective_from", sa.Date, nullable=True,
                  comment="配置生效起始日期（NULL=立即生效）"),
        sa.Column("effective_until", sa.Date, nullable=True,
                  comment="配置失效日期（NULL=永久有效）"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )

    op.create_index(
        "ix_finance_configs_store_type",
        "finance_configs",
        ["tenant_id", "store_id", "config_type"],
    )
    op.create_index("ix_finance_configs_effective", "finance_configs",
                    ["effective_from", "effective_until"])

    op.execute("ALTER TABLE finance_configs ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY finance_configs_tenant_isolation ON finance_configs
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)


def downgrade() -> None:
    op.drop_table("finance_configs")
    op.drop_table("revenue_records")
    op.drop_table("cost_items")
    op.drop_table("daily_pnl")
