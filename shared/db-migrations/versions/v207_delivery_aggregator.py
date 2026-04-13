"""v207 — 外卖聚合订单表 + 指标表（Y-A5 Mock→DB）

aggregator_orders: 美团/饿了么/抖音统一订单落库
aggregator_metrics: Webhook处理指标持久化

Revision ID: v207
Revises: v206
Create Date: 2026-04-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v207"
down_revision = "v206b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()


    # ── aggregator_orders（外卖聚合订单）──

    if 'aggregator_orders' not in existing:
        op.create_table(
            "aggregator_orders",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.String(50), nullable=False, index=True),
            sa.Column("platform", sa.String(20), nullable=False, index=True, comment="meituan/eleme/douyin"),
            sa.Column("platform_order_id", sa.String(100), nullable=False),
            sa.Column("store_id", sa.String(50), nullable=False, index=True),
            sa.Column("items", JSONB, nullable=False, server_default="[]"),
            sa.Column("total_fen", sa.BigInteger, nullable=False, server_default="0"),
            sa.Column("customer_phone_hash", sa.String(16), nullable=True),
            sa.Column("customer_phone_masked", sa.String(15), nullable=True),
            sa.Column("estimated_delivery_at", sa.String(50), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="new",
                      comment="new/accepted/ready/delivering/completed/cancelled"),
            sa.Column("cancel_reason", sa.String(200), nullable=True),
            sa.Column("raw_payload", JSONB, nullable=True),
            sa.Column("extra", JSONB, server_default="{}"),
            sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.DateTime, server_default=sa.text("NOW()")),
            sa.UniqueConstraint("tenant_id", "platform", "platform_order_id", name="uq_agg_tenant_platform_order"),
        )
        op.execute("ALTER TABLE aggregator_orders ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE aggregator_orders FORCE ROW LEVEL SECURITY;")
        op.execute("""
            CREATE POLICY aggregator_orders_tenant ON aggregator_orders
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
        """)

        # ── aggregator_metrics（Webhook处理指标）──

    if 'aggregator_metrics' not in existing:
        op.create_table(
            "aggregator_metrics",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.String(50), nullable=False, index=True),
            sa.Column("platform", sa.String(20), nullable=False),
            sa.Column("success", sa.Boolean, nullable=False),
            sa.Column("duration_ms", sa.Float, nullable=False),
            sa.Column("error_code", sa.String(50), nullable=True),
            sa.Column("recorded_at", sa.DateTime, server_default=sa.text("NOW()")),
        )
        op.create_index("idx_agg_metrics_time", "aggregator_metrics", ["recorded_at"])


def downgrade() -> None:
    op.drop_index("idx_agg_metrics_time", table_name="aggregator_metrics")
    op.drop_table("aggregator_metrics")
    op.execute("DROP POLICY IF EXISTS aggregator_orders_tenant ON aggregator_orders;")
    op.drop_table("aggregator_orders")
