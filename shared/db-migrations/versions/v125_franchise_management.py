"""v125 — 加盟管理核心表

新增五张表：
  franchisees               — 加盟商档案（基本信息/合同/费率）
  franchise_stores          — 加盟门店（含门店复制状态追踪）
  franchise_royalty_rules   — 分润规则（按营收比例/固定月费/分档）
  franchise_royalty_bills   — 分润账单（月度结算）
  franchise_kpi_records     — 绩效考核记录（月度KPI）

所有表含 tenant_id + RLS（current_setting('app.tenant_id', true)::uuid 模式）。

Revision ID: v125
Revises: v124
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v125"
down_revision = "v124"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── franchisees 加盟商档案 ────────────────────────────────────────────
    op.create_table(
        "franchisees",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "franchisee_no", sa.String(50), nullable=False,
            comment="加盟商编号，租户内唯一",
        ),
        sa.Column("legal_name", sa.String(200), nullable=False,
                  comment="工商注册名称"),
        sa.Column("brand_name", sa.String(100), nullable=True,
                  comment="品牌/门店简称"),
        sa.Column("contact_name", sa.String(50), nullable=True),
        sa.Column("contact_phone", sa.String(20), nullable=True),
        sa.Column("contact_email", sa.String(100), nullable=True),
        sa.Column("province", sa.String(50), nullable=True),
        sa.Column("city", sa.String(50), nullable=True),
        sa.Column("district", sa.String(50), nullable=True),
        sa.Column("address", sa.String(300), nullable=True),
        sa.Column("business_license_no", sa.String(50), nullable=True,
                  comment="营业执照编号"),
        sa.Column("legal_person_name", sa.String(50), nullable=True,
                  comment="法定代表人姓名"),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="'applying'",
            comment="applying/signing/preparing/operating/suspended/terminated",
        ),
        sa.Column(
            "tier", sa.String(20), nullable=False, server_default="'standard'",
            comment="standard/premium/flagship",
        ),
        sa.Column("contract_start_date", sa.Date, nullable=True),
        sa.Column("contract_end_date", sa.Date, nullable=True),
        sa.Column(
            "initial_fee_fen", sa.Integer, nullable=False, server_default="0",
            comment="入门费（分）",
        ),
        sa.Column(
            "royalty_rate", sa.Numeric(6, 4), nullable=False, server_default="0.05",
            comment="特许经营费比率，如 0.05 = 5%",
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index(
        "ix_franchisees_tenant_no",
        "franchisees",
        ["tenant_id", "franchisee_no"],
        unique=True,
    )
    op.create_index(
        "ix_franchisees_tenant_status",
        "franchisees",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_franchisees_tenant_city",
        "franchisees",
        ["tenant_id", "city"],
    )

    op.execute("ALTER TABLE franchisees ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY franchisees_tenant_isolation ON franchisees
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── franchise_stores 加盟门店 ─────────────────────────────────────────
    op.create_table(
        "franchise_stores",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "franchisee_id", UUID(as_uuid=True), nullable=False,
            comment="FK → franchisees.id",
        ),
        sa.Column(
            "store_id", sa.String(100), nullable=False,
            comment="关联 stores.id（外部引用，不建DB外键）",
        ),
        sa.Column("store_name", sa.String(200), nullable=False),
        sa.Column("open_date", sa.Date, nullable=True),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="'preparing'",
            comment="preparing/operating/suspended/closed",
        ),
        sa.Column(
            "template_store_id", sa.String(100), nullable=True,
            comment="门店复制来源 store_id",
        ),
        sa.Column(
            "clone_status", sa.String(20), nullable=True,
            comment="pending/cloning/completed/failed",
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_franchise_stores_tenant_franchisee",
        "franchise_stores",
        ["tenant_id", "franchisee_id"],
    )
    op.create_index(
        "ix_franchise_stores_tenant_store",
        "franchise_stores",
        ["tenant_id", "store_id"],
    )
    op.create_index(
        "ix_franchise_stores_clone_status",
        "franchise_stores",
        ["clone_status"],
        postgresql_where=sa.text("clone_status IN ('pending', 'cloning')"),
    )
    op.create_foreign_key(
        "fk_franchise_stores_franchisee",
        "franchise_stores", "franchisees",
        ["franchisee_id"], ["id"],
        ondelete="CASCADE",
    )

    op.execute("ALTER TABLE franchise_stores ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY franchise_stores_tenant_isolation ON franchise_stores
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── franchise_royalty_rules 分润规则 ──────────────────────────────────
    op.create_table(
        "franchise_royalty_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "franchisee_id", UUID(as_uuid=True), nullable=False,
            comment="FK → franchisees.id",
        ),
        sa.Column(
            "rule_type", sa.String(30), nullable=False,
            comment="revenue_pct/fixed_monthly/tiered_revenue",
        ),
        sa.Column(
            "revenue_pct", sa.Numeric(6, 4), nullable=True,
            comment="按营收比例，如 0.05 = 5%（rule_type=revenue_pct 时有效）",
        ),
        sa.Column(
            "monthly_fee_fen", sa.Integer, nullable=True,
            comment="固定月费（分）（rule_type=fixed_monthly 时有效）",
        ),
        sa.Column(
            "tiers", JSONB, nullable=True,
            comment=(
                "分档营收规则（rule_type=tiered_revenue 时有效）。"
                "格式：[{min:0,max:100000,rate:0.08},{min:100000,rate:0.05}]"
            ),
        ),
        sa.Column(
            "applies_to", sa.String(20), nullable=False, server_default="'all'",
            comment="all/dine_in/takeaway/retail",
        ),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date, nullable=True,
                  comment="NULL 表示长期有效"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
    )
    op.create_index(
        "ix_franchise_royalty_rules_franchisee",
        "franchise_royalty_rules",
        ["franchisee_id", "is_active"],
    )
    op.create_index(
        "ix_franchise_royalty_rules_tenant",
        "franchise_royalty_rules",
        ["tenant_id"],
    )
    op.create_foreign_key(
        "fk_franchise_royalty_rules_franchisee",
        "franchise_royalty_rules", "franchisees",
        ["franchisee_id"], ["id"],
        ondelete="CASCADE",
    )

    op.execute("ALTER TABLE franchise_royalty_rules ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY franchise_royalty_rules_tenant_isolation ON franchise_royalty_rules
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── franchise_royalty_bills 分润账单 ──────────────────────────────────
    op.create_table(
        "franchise_royalty_bills",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "franchisee_id", UUID(as_uuid=True), nullable=False,
            comment="FK → franchisees.id",
        ),
        sa.Column(
            "store_id", sa.String(100), nullable=False,
            comment="对应加盟门店 store_id",
        ),
        sa.Column(
            "bill_period", sa.String(7), nullable=False,
            comment="账期，格式 YYYY-MM，如 2026-03",
        ),
        sa.Column("revenue_fen", sa.Integer, nullable=False, server_default="0",
                  comment="当期营业额（分）"),
        sa.Column("royalty_rate_applied", sa.Numeric(6, 4), nullable=False,
                  server_default="0",
                  comment="实际应用的分润比率快照"),
        sa.Column("royalty_amount_fen", sa.Integer, nullable=False, server_default="0",
                  comment="分润金额（分）"),
        sa.Column("initial_fee_fen", sa.Integer, nullable=False, server_default="0",
                  comment="首期入门费（仅第一期账单收取）"),
        sa.Column("other_fee_fen", sa.Integer, nullable=False, server_default="0",
                  comment="其他杂项费用（分）"),
        sa.Column("total_due_fen", sa.Integer, nullable=False, server_default="0",
                  comment="本期应付合计（分）"),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="'pending'",
            comment="pending/invoiced/paid/overdue",
        ),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("paid_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_franchise_royalty_bills_franchisee_period",
        "franchise_royalty_bills",
        ["franchisee_id", "bill_period"],
    )
    op.create_index(
        "ix_franchise_royalty_bills_tenant_status",
        "franchise_royalty_bills",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_franchise_royalty_bills_tenant_period",
        "franchise_royalty_bills",
        ["tenant_id", "bill_period"],
    )
    # 唯一约束：同加盟商 + 同门店 + 同账期只有一张账单（支持 upsert）
    op.create_unique_constraint(
        "uq_franchise_royalty_bills_period",
        "franchise_royalty_bills",
        ["franchisee_id", "store_id", "bill_period"],
    )
    op.create_foreign_key(
        "fk_franchise_royalty_bills_franchisee",
        "franchise_royalty_bills", "franchisees",
        ["franchisee_id"], ["id"],
        ondelete="CASCADE",
    )

    op.execute("ALTER TABLE franchise_royalty_bills ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY franchise_royalty_bills_tenant_isolation ON franchise_royalty_bills
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── franchise_kpi_records 绩效考核记录 ────────────────────────────────
    op.create_table(
        "franchise_kpi_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "franchisee_id", UUID(as_uuid=True), nullable=False,
            comment="FK → franchisees.id",
        ),
        sa.Column(
            "store_id", sa.String(100), nullable=False,
            comment="对应加盟门店 store_id",
        ),
        sa.Column(
            "kpi_period", sa.String(7), nullable=False,
            comment="考核期间，格式 YYYY-MM",
        ),
        sa.Column("kpi_month", sa.Date, nullable=False,
                  comment="考核月份首日（用于范围查询）"),
        sa.Column("revenue_target_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("revenue_actual_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("order_count_target", sa.Integer, nullable=False, server_default="0"),
        sa.Column("order_count_actual", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "customer_satisfaction_score", sa.Numeric(4, 2), nullable=True,
            comment="顾客满意度得分（0~10）",
        ),
        sa.Column(
            "food_safety_score", sa.Numeric(4, 2), nullable=True,
            comment="食安合规得分（0~10）",
        ),
        sa.Column(
            "overall_score", sa.Numeric(5, 2), nullable=True,
            comment="综合评分（由 API 层计算后写入）",
        ),
        sa.Column(
            "tier_recommendation", sa.String(20), nullable=True,
            comment="层级建议 standard/premium/flagship/downgrade",
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_franchise_kpi_records_franchisee_period",
        "franchise_kpi_records",
        ["franchisee_id", "kpi_period"],
    )
    op.create_index(
        "ix_franchise_kpi_records_tenant_month",
        "franchise_kpi_records",
        ["tenant_id", "kpi_month"],
    )
    op.create_foreign_key(
        "fk_franchise_kpi_records_franchisee",
        "franchise_kpi_records", "franchisees",
        ["franchisee_id"], ["id"],
        ondelete="CASCADE",
    )

    op.execute("ALTER TABLE franchise_kpi_records ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY franchise_kpi_records_tenant_isolation ON franchise_kpi_records
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS franchise_kpi_records_tenant_isolation ON franchise_kpi_records;")
    op.drop_table("franchise_kpi_records")

    op.execute("DROP POLICY IF EXISTS franchise_royalty_bills_tenant_isolation ON franchise_royalty_bills;")
    op.drop_constraint("uq_franchise_royalty_bills_period", "franchise_royalty_bills", type_="unique")
    op.drop_table("franchise_royalty_bills")

    op.execute("DROP POLICY IF EXISTS franchise_royalty_rules_tenant_isolation ON franchise_royalty_rules;")
    op.drop_table("franchise_royalty_rules")

    op.execute("DROP POLICY IF EXISTS franchise_stores_tenant_isolation ON franchise_stores;")
    op.drop_table("franchise_stores")

    op.execute("DROP POLICY IF EXISTS franchisees_tenant_isolation ON franchisees;")
    op.drop_table("franchisees")
