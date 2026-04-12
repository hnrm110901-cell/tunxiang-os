"""宴席高级管理 — 排菜方案 + 场次管理 + 分席结账

Revision: v215
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v215"
down_revision = "v214"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    # ── 排菜方案模板 ──
    op.create_table(
        "banquet_menu_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.VARCHAR(100), nullable=False, comment="方案名: 如 '8人商务宴'"),
        sa.Column("guest_count", sa.INTEGER, nullable=False, comment="标准人数"),
        sa.Column("budget_fen", sa.BIGINT, nullable=True, comment="预算(分)"),
        sa.Column("dishes", postgresql.JSONB, nullable=False, server_default="[]",
                  comment="[{dish_id, dish_name, qty, unit_price_fen, category}]"),
        sa.Column("total_cost_fen", sa.BIGINT, server_default="0", comment="总成本(分)"),
        sa.Column("total_price_fen", sa.BIGINT, server_default="0", comment="总售价(分)"),
        sa.Column("margin_rate", sa.NUMERIC(5, 2), nullable=True, comment="毛利率%"),
        sa.Column("status", sa.VARCHAR(20), server_default="active"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
    )
    op.create_index("ix_bmp_tenant", "banquet_menu_plans", ["tenant_id"])
    op.execute("ALTER TABLE banquet_menu_plans ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE banquet_menu_plans FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY bmp_tenant ON banquet_menu_plans
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)

    # ── 宴席场次 ──
    if 'banquet_sessions' not in existing:
        op.create_table(
            "banquet_sessions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("menu_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("session_date", sa.DATE, nullable=False),
            sa.Column("time_slot", sa.VARCHAR(20), nullable=False, comment="lunch/dinner/custom"),
            sa.Column("room_ids", postgresql.JSONB, server_default="[]", comment="包厢ID列表"),
            sa.Column("table_count", sa.INTEGER, nullable=False, server_default="1"),
            sa.Column("guest_count", sa.INTEGER, nullable=False),
            sa.Column("contact_name", sa.VARCHAR(50), nullable=True),
            sa.Column("contact_phone", sa.VARCHAR(20), nullable=True),
            sa.Column("status", sa.VARCHAR(20), server_default="confirmed",
                      comment="confirmed/preparing/serving/completed/cancelled"),
            sa.Column("total_amount_fen", sa.BIGINT, server_default="0"),
            sa.Column("deposit_fen", sa.BIGINT, server_default="0", comment="定金"),
            sa.Column("notes", sa.TEXT, nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
        )
        op.create_index("ix_bs_tenant_date", "banquet_sessions", ["tenant_id", "session_date"])
    op.execute("ALTER TABLE banquet_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE banquet_sessions FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'banquet_sessions'
                AND policyname = 'bs_tenant'
            ) THEN
                EXECUTE 'CREATE POLICY bs_tenant ON banquet_sessions
                    USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::UUID)
                    WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::UUID)';
            END IF;
        END$$;
    """)

    # ── 分席账单 ──
    op.create_table(
        "banquet_split_bills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("table_no", sa.INTEGER, nullable=False, comment="桌号/席号"),
        sa.Column("split_mode", sa.VARCHAR(20), nullable=False,
                  comment="by_table/by_person/custom_ratio"),
        sa.Column("ratio", sa.NUMERIC(5, 2), nullable=True, comment="自定义比例"),
        sa.Column("amount_fen", sa.BIGINT, nullable=False),
        sa.Column("paid", sa.BOOLEAN, server_default="false"),
        sa.Column("paid_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("payment_method", sa.VARCHAR(20), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
    )
    op.create_index("ix_bsb_session", "banquet_split_bills", ["tenant_id", "session_id"])
    op.execute("ALTER TABLE banquet_split_bills ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE banquet_split_bills FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY bsb_tenant ON banquet_split_bills
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)


def downgrade() -> None:
    for t in ["banquet_split_bills", "banquet_sessions", "banquet_menu_plans"]:
        op.execute(f"DROP POLICY IF EXISTS {t.replace('banquet_', '').split('_')[0]}_tenant ON {t}")
        op.drop_table(t)
