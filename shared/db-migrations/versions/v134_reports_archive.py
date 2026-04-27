"""v134 — 经营日报 + 订单归档 + 搜索热词

新增三张表：
  daily_business_reports  — 经营日报预计算汇总（加速 BI 查询）
  archived_orders         — 订单冷数据归档（减轻主表压力）
  search_hot_keywords     — 小程序搜索热词（运营可推荐）

Revision ID: v134
Revises: v133
Create Date: 2026-04-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v134"
down_revision = "v133"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── daily_business_reports 经营日报预计算 ───────────────────
    if "daily_business_reports" not in _existing:
        op.create_table(
            "daily_business_reports",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("report_date", sa.Date, nullable=False),
            sa.Column("order_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("revenue_fen", sa.BigInteger, nullable=False, server_default="0"),
            sa.Column("cost_fen", sa.BigInteger, nullable=False, server_default="0"),
            sa.Column("gross_profit_fen", sa.BigInteger, nullable=False, server_default="0"),
            sa.Column("gross_margin", sa.Numeric(5, 4)),
            sa.Column("avg_ticket_fen", sa.Integer, nullable=False, server_default="0"),
            sa.Column("table_turnover", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("new_members", sa.Integer, nullable=False, server_default="0"),
            sa.Column("payment_breakdown", JSONB),
            sa.Column("channel_breakdown", JSONB),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
    # 唯一约束：同一租户+门店+日期只能有一条
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='daily_business_reports' AND column_name IN ('tenant_id', 'store_id', 'report_date')) = 3 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_daily_report_tenant_store_date ON daily_business_reports (tenant_id, store_id, report_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='daily_business_reports' AND column_name IN ('tenant_id', 'report_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_daily_report_tenant_date ON daily_business_reports (tenant_id, report_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='daily_business_reports' AND column_name IN ('store_id', 'report_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_daily_report_store_date ON daily_business_reports (store_id, report_date)';
            END IF;
        END $$;
    """)
    # RLS
    op.execute("ALTER TABLE daily_business_reports ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY daily_business_reports_tenant_isolation
        ON daily_business_reports
        FOR ALL
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
    """)

    # ── archived_orders 订单归档 ──────────────────────────────
    if "archived_orders" not in _existing:
        op.create_table(
            "archived_orders",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("original_order_id", UUID(as_uuid=True), nullable=False),
            sa.Column("order_data", JSONB, nullable=False),
            sa.Column("order_date", sa.Date, nullable=False),
            sa.Column("total_fen", sa.BigInteger, nullable=False, server_default="0"),
            sa.Column("archived_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("archive_reason", sa.String(20), nullable=False, server_default="auto"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='archived_orders' AND column_name IN ('tenant_id', 'order_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_archived_orders_tenant_date ON archived_orders (tenant_id, order_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='archived_orders' AND (column_name = 'original_order_id')) = 1 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS ix_archived_orders_original_id ON archived_orders (original_order_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='archived_orders' AND column_name IN ('store_id', 'order_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_archived_orders_store_date ON archived_orders (store_id, order_date)';
            END IF;
        END $$;
    """)
    # RLS
    op.execute("ALTER TABLE archived_orders ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY archived_orders_tenant_isolation
        ON archived_orders
        FOR ALL
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
    """)

    # ── search_hot_keywords 搜索热词 ─────────────────────────
    if "search_hot_keywords" not in _existing:
        op.create_table(
            "search_hot_keywords",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("keyword", sa.String(50), nullable=False),
            sa.Column("search_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("is_promoted", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
    # 同一租户下关键词唯一
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='search_hot_keywords' AND column_name IN ('tenant_id', 'keyword')) = 2 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_search_keyword_tenant ON search_hot_keywords (tenant_id, keyword)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='search_hot_keywords' AND column_name IN ('tenant_id', 'is_active')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_search_keywords_tenant_active ON search_hot_keywords (tenant_id, is_active)';
            END IF;
        END $$;
    """)
    # RLS
    op.execute("ALTER TABLE search_hot_keywords ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY search_hot_keywords_tenant_isolation
        ON search_hot_keywords
        FOR ALL
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS search_hot_keywords_tenant_isolation ON search_hot_keywords")
    op.drop_table("search_hot_keywords")

    op.execute("DROP POLICY IF EXISTS archived_orders_tenant_isolation ON archived_orders")
    op.drop_table("archived_orders")

    op.execute("DROP POLICY IF EXISTS daily_business_reports_tenant_isolation ON daily_business_reports")
    op.drop_table("daily_business_reports")
