"""v206 — 团餐企业客户 + 企业订单 + 企业账单（Y-A9 Mock→DB）

将 corporate_order_routes.py 中的内存 Mock 数据持久化到 DB。

Revision ID: v206
Revises: v205
Create Date: 2026-04-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v206"
down_revision = "v205"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    # ── corporate_customers（企业客户主数据）──
    if 'corporate_customers' not in existing:
        op.create_table(
            "corporate_customers",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.String(50), nullable=False, index=True),
            sa.Column("store_id", sa.String(50), nullable=False, index=True),
            sa.Column("company_name", sa.String(200), nullable=False),
            sa.Column("company_code", sa.String(50), nullable=True, unique=True),
            sa.Column("contact_name", sa.String(100), nullable=True),
            sa.Column("contact_phone", sa.String(20), nullable=True),
            sa.Column("billing_type", sa.String(20), nullable=False, server_default="monthly",
                      comment="monthly/weekly/per_order"),
            sa.Column("credit_limit_fen", sa.BigInteger, nullable=False, server_default="0"),
            sa.Column("used_credit_fen", sa.BigInteger, nullable=False, server_default="0"),
            sa.Column("tax_no", sa.String(50), nullable=True),
            sa.Column("invoice_title", sa.String(200), nullable=True),
            sa.Column("discount_rate", sa.Float, nullable=False, server_default="1.0",
                      comment="企业折扣率，如 0.95 = 95折"),
            sa.Column("approved_menu_ids", JSONB, server_default="[]"),
            sa.Column("status", sa.String(20), nullable=False, server_default="active",
                      comment="active/suspended/terminated"),
            sa.Column("is_deleted", sa.Boolean, server_default=sa.text("FALSE")),
            sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.DateTime, server_default=sa.text("NOW()")),
        )
        op.execute("ALTER TABLE corporate_customers ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE corporate_customers FORCE ROW LEVEL SECURITY;")
        op.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = 'corporate_customers'
                    AND policyname = 'corporate_customers_tenant'
                ) THEN
                    EXECUTE 'CREATE POLICY corporate_customers_tenant ON corporate_customers
                        USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), ''''))
                        WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), ''''))';
                END IF;
            END$$;
        """)

    # ── corporate_orders（企业订单）──
    if 'corporate_orders' not in existing:
        op.create_table(
            "corporate_orders",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.String(50), nullable=False, index=True),
            sa.Column("store_id", sa.String(50), nullable=False, index=True),
            sa.Column("corporate_customer_id", UUID(as_uuid=True),
                      sa.ForeignKey("corporate_customers.id"), nullable=False, index=True),
            sa.Column("order_no", sa.String(30), nullable=False, unique=True),
            sa.Column("items", JSONB, nullable=False, server_default="[]"),
            sa.Column("original_amount_fen", sa.BigInteger, nullable=False),
            sa.Column("discount_rate", sa.Float, nullable=False),
            sa.Column("final_amount_fen", sa.BigInteger, nullable=False),
            sa.Column("covers", sa.Integer, server_default="1"),
            sa.Column("status", sa.String(20), server_default="'pending'",
                      comment="pending/confirmed/billed/paid/cancelled"),
            sa.Column("billed", sa.Boolean, server_default=sa.text("FALSE")),
            sa.Column("bill_id", UUID(as_uuid=True), nullable=True),
            sa.Column("ordered_at", sa.DateTime, server_default=sa.text("NOW()")),
            sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
        )
        op.execute("ALTER TABLE corporate_orders ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE corporate_orders FORCE ROW LEVEL SECURITY;")
        op.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = 'corporate_orders'
                    AND policyname = 'corporate_orders_tenant'
                ) THEN
                    EXECUTE 'CREATE POLICY corporate_orders_tenant ON corporate_orders
                        USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), ''''))
                        WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), ''''))';
                END IF;
            END$$;
        """)

    # ── corporate_bills（企业账单）──
    if 'corporate_bills' not in existing:
        op.create_table(
            "corporate_bills",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.String(50), nullable=False, index=True),
            sa.Column("store_id", sa.String(50), nullable=False, index=True),
            sa.Column("corporate_customer_id", UUID(as_uuid=True),
                      sa.ForeignKey("corporate_customers.id"), nullable=False),
            sa.Column("bill_no", sa.String(30), nullable=False, unique=True),
            sa.Column("period_start", sa.Date, nullable=False),
            sa.Column("period_end", sa.Date, nullable=False),
            sa.Column("order_count", sa.Integer, nullable=False),
            sa.Column("total_amount_fen", sa.BigInteger, nullable=False),
            sa.Column("status", sa.String(20), server_default="'pending'",
                      comment="pending/sent/confirmed/paid"),
            sa.Column("paid_at", sa.DateTime, nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
        )
        op.execute("ALTER TABLE corporate_bills ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE corporate_bills FORCE ROW LEVEL SECURITY;")
        op.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = 'corporate_bills'
                    AND policyname = 'corporate_bills_tenant'
                ) THEN
                    EXECUTE 'CREATE POLICY corporate_bills_tenant ON corporate_bills
                        USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), ''''))
                        WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), ''''))';
                END IF;
            END$$;
        """)


def downgrade() -> None:
    for t in ("corporate_bills", "corporate_orders", "corporate_customers"):
        op.execute(f"DROP POLICY IF EXISTS {t}_tenant ON {t};")
        op.drop_table(t)
