"""成本归集系统：每日成本归集日报 + 成本归集明细
Tables: daily_cost_reports, cost_attribution_items
Sprint: P2-S2（成本归集日报Worker + A6 POS对账Agent）

设计原则：
  - daily_cost_reports 按 (tenant_id, store_id, report_date) 唯一，支持 upsert
  - 营收数据来自 tx-ops POS 日结，成本数据来自费控申请单
  - food_cost_rate / labor_cost_rate / gross_margin_rate 由 Worker 计算后写入
  - data_status 生命周期：pending → complete → manual_adjusted

Revision ID: v243
Revises: v242
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "v243"
down_revision = "v242"
branch_labels = None
depends_on = None

# 标准安全 RLS 条件（NULLIF 保护，与 v241 规范一致）
_RLS_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 表1：daily_cost_reports（每日成本归集日报）
    # ------------------------------------------------------------------
    op.create_table(
        "daily_cost_reports",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False, comment="日报日期"),

        # 营收数据（来自POS）
        sa.Column(
            "total_revenue_fen", sa.BigInteger(), nullable=True, server_default="0",
            comment="当日营收（分）",
        ),
        sa.Column(
            "table_count", sa.Integer(), nullable=True, server_default="0",
            comment="桌次",
        ),
        sa.Column(
            "customer_count", sa.Integer(), nullable=True, server_default="0",
            comment="客数",
        ),

        # 成本数据（来自费控）
        sa.Column(
            "food_cost_fen", sa.BigInteger(), nullable=True, server_default="0",
            comment="食材成本（分）",
        ),
        sa.Column(
            "labor_cost_fen", sa.BigInteger(), nullable=True, server_default="0",
            comment="人力成本（分）",
        ),
        sa.Column(
            "other_cost_fen", sa.BigInteger(), nullable=True, server_default="0",
            comment="其他费用（分）",
        ),
        sa.Column(
            "total_cost_fen", sa.BigInteger(), nullable=True, server_default="0",
            comment="总成本（分）",
        ),

        # 计算指标
        sa.Column(
            "food_cost_rate", sa.Numeric(7, 4), nullable=True,
            comment="食材成本率 = food_cost_fen / total_revenue_fen",
        ),
        sa.Column(
            "labor_cost_rate", sa.Numeric(7, 4), nullable=True,
            comment="人力成本率 = labor_cost_fen / total_revenue_fen",
        ),
        sa.Column(
            "gross_margin_rate", sa.Numeric(7, 4), nullable=True,
            comment="毛利率 = (total_revenue_fen - total_cost_fen) / total_revenue_fen",
        ),

        # 元数据
        sa.Column(
            "pos_data_source", sa.String(50), nullable=True,
            comment="POS数据来源：pinzhi/aoqiwei/meituan",
        ),
        sa.Column(
            "data_status", sa.String(32), nullable=False, server_default="pending",
            comment="数据状态：pending/complete/manual_adjusted",
        ),
        sa.Column("notes", sa.Text(), nullable=True, comment="备注"),

        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=True,
            server_default=sa.text("now()"),
        ),
    )

    # 唯一约束：每个租户每家门店每天只有一条日报
    op.create_unique_constraint(
        "uq_daily_cost_reports_tenant_store_date",
        "daily_cost_reports",
        ["tenant_id", "store_id", "report_date"],
    )

    # 索引
    op.create_index(
        "ix_daily_cost_reports_tenant_date",
        "daily_cost_reports",
        ["tenant_id", "report_date"],
    )
    op.create_index(
        "ix_daily_cost_reports_tenant_store_date",
        "daily_cost_reports",
        ["tenant_id", "store_id", "report_date"],
    )
    op.create_index(
        "ix_daily_cost_reports_tenant_status",
        "daily_cost_reports",
        ["tenant_id", "data_status"],
        postgresql_where=sa.text("data_status != 'complete'"),
    )

    # RLS
    op.execute("ALTER TABLE daily_cost_reports ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY daily_cost_reports_tenant_isolation
        ON daily_cost_reports
        USING ({_RLS_COND})
        """
    )

    # ------------------------------------------------------------------
    # 表2：cost_attribution_items（成本归集明细）
    # ------------------------------------------------------------------
    op.create_table(
        "cost_attribution_items",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "report_id", UUID(as_uuid=True), nullable=True,
            comment="关联日报ID",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["daily_cost_reports.id"],
            name="fk_cost_attribution_items_report_id",
            ondelete="SET NULL",
        ),
        sa.Column(
            "expense_application_id", UUID(as_uuid=True), nullable=True,
            comment="费控申请ID",
        ),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False),
        sa.Column("attribution_date", sa.Date(), nullable=False, comment="归集日期"),
        sa.Column(
            "cost_type", sa.String(32), nullable=True,
            comment="成本类型：food/labor/rent/utility/other",
        ),
        sa.Column(
            "amount_fen", sa.BigInteger(), nullable=False,
            comment="金额（分）",
        ),
        sa.Column("description", sa.Text(), nullable=True, comment="描述"),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=True,
            server_default=sa.text("now()"),
        ),
    )

    # 索引
    op.create_index(
        "ix_cost_attribution_items_tenant_report",
        "cost_attribution_items",
        ["tenant_id", "report_id"],
    )
    op.create_index(
        "ix_cost_attribution_items_tenant_store_date",
        "cost_attribution_items",
        ["tenant_id", "store_id", "attribution_date"],
    )
    op.create_index(
        "ix_cost_attribution_items_tenant_expense_app",
        "cost_attribution_items",
        ["tenant_id", "expense_application_id"],
        postgresql_where=sa.text("expense_application_id IS NOT NULL"),
    )
    op.create_index(
        "ix_cost_attribution_items_tenant_cost_type",
        "cost_attribution_items",
        ["tenant_id", "cost_type", "attribution_date"],
    )

    # RLS
    op.execute("ALTER TABLE cost_attribution_items ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY cost_attribution_items_tenant_isolation
        ON cost_attribution_items
        USING ({_RLS_COND})
        """
    )


def downgrade() -> None:
    # 按依赖反向删除

    # cost_attribution_items（先删，因为外键引用 daily_cost_reports）
    op.execute(
        "DROP POLICY IF EXISTS cost_attribution_items_tenant_isolation ON cost_attribution_items"
    )
    op.drop_table("cost_attribution_items")

    # daily_cost_reports
    op.execute(
        "DROP POLICY IF EXISTS daily_cost_reports_tenant_isolation ON daily_cost_reports"
    )
    op.drop_table("daily_cost_reports")
