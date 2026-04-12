"""计件提成3.0（天财对标 模块2.6）— commission_schemes / commission_rules / commission_records

Tables:
  commission_schemes  — 绩效提成方案（含适用门店JSONB/有效期）
  commission_rules    — 提成规则（4类维度：dish/table/time_slot/revenue_tier）
  commission_records  — 员工月度提成结算记录

Revision ID: v244_commission_v3
Revises: v244
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v244"
down_revision = "v243"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 表1：commission_schemes — 绩效提成方案
    # ------------------------------------------------------------------
    op.create_table(
        "commission_schemes",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False, comment="方案名称"),
        sa.Column(
            "applicable_stores", JSONB, nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="适用门店ID列表，空数组=集团全部门店",
        ),
        sa.Column("effective_date", sa.Date, nullable=True, comment="生效日期"),
        sa.Column("expiry_date", sa.Date, nullable=True, comment="失效日期，NULL=长期有效"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("TRUE")),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"), nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
    )
    op.create_index("ix_commission_schemes_tenant", "commission_schemes", ["tenant_id"])
    op.create_index(
        "ix_commission_schemes_tenant_active",
        "commission_schemes", ["tenant_id", "is_active"],
    )

    # RLS
    op.execute("ALTER TABLE commission_schemes ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY commission_schemes_tenant_isolation
        ON commission_schemes
        USING (tenant_id = current_setting('app.tenant_id')::uuid)
    """)

    # ------------------------------------------------------------------
    # 表2：commission_rules — 提成规则（4类维度）
    # ------------------------------------------------------------------
    op.create_table(
        "commission_rules",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "scheme_id", UUID(as_uuid=True), nullable=False,
            comment="关联方案ID",
        ),
        sa.Column(
            "rule_type", sa.String(20), nullable=False,
            comment="dish=品项提成 / table=桌型提成 / time_slot=时段提成 / revenue_tier=营收阶梯",
        ),
        sa.Column(
            "params", JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment=(
                "规则参数 — dish:{dish_id,dish_name,amount_fen,min_qty}；"
                "table:{table_type,amount_fen}；"
                "time_slot:{start_time,end_time,multiplier}；"
                "revenue_tier:{tiers:[{min_fen,max_fen,rate_bps}]}"
            ),
        ),
        sa.Column(
            "amount_fen", sa.BigInteger, nullable=False,
            server_default=sa.text("0"),
            comment="基础金额（分），阶梯类型在params.tiers中",
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["scheme_id"], ["commission_schemes.id"],
            name="fk_commission_rules_scheme",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_commission_rules_scheme", "commission_rules", ["scheme_id"])
    op.create_index("ix_commission_rules_tenant", "commission_rules", ["tenant_id"])
    op.create_index(
        "ix_commission_rules_tenant_type",
        "commission_rules", ["tenant_id", "rule_type"],
    )

    # RLS
    op.execute("ALTER TABLE commission_rules ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY commission_rules_tenant_isolation
        ON commission_rules
        USING (tenant_id = current_setting('app.tenant_id')::uuid)
    """)

    # ------------------------------------------------------------------
    # 表3：commission_records — 员工月度提成结算记录
    # ------------------------------------------------------------------
    op.create_table(
        "commission_records",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"), nullable=False,
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "year_month", sa.String(7), nullable=False,
            comment="结算月份，格式 YYYY-MM",
        ),
        sa.Column(
            "total_commission_fen", sa.BigInteger, nullable=False,
            server_default=sa.text("0"),
            comment="本月总提成（分）",
        ),
        sa.Column(
            "breakdown", JSONB, nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="提成明细列表（各规则来源、金额）",
        ),
        sa.Column(
            "status", sa.String(20), nullable=False,
            server_default=sa.text("'pending'"),
            comment="pending=待结算 / settled=已结算 / voided=已作废",
        ),
        sa.Column("settled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"), nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "employee_id", "store_id", "year_month",
            name="uq_commission_records_employee_month",
        ),
    )
    op.create_index(
        "ix_commission_records_tenant_month",
        "commission_records", ["tenant_id", "year_month"],
    )
    op.create_index(
        "ix_commission_records_employee",
        "commission_records", ["employee_id"],
    )
    op.create_index(
        "ix_commission_records_store_month",
        "commission_records", ["store_id", "year_month"],
    )

    # RLS
    op.execute("ALTER TABLE commission_records ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY commission_records_tenant_isolation
        ON commission_records
        USING (tenant_id = current_setting('app.tenant_id')::uuid)
    """)


def downgrade() -> None:
    # 移除 RLS 策略
    op.execute("DROP POLICY IF EXISTS commission_records_tenant_isolation ON commission_records")
    op.execute("DROP POLICY IF EXISTS commission_rules_tenant_isolation ON commission_rules")
    op.execute("DROP POLICY IF EXISTS commission_schemes_tenant_isolation ON commission_schemes")

    op.drop_table("commission_records")
    op.drop_table("commission_rules")
    op.drop_table("commission_schemes")
