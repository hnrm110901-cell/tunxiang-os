"""split payment and profit distribution

Revision ID: v204
Revises: v203
Create Date: 2026-04-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v204"
down_revision = "v203"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    # 分账订单主表（一笔支付对应一个分账订单）

    if "split_payment_orders" not in existing:
        op.create_table(
            "split_payment_orders",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("order_id", UUID(as_uuid=True), nullable=False),  # 业务订单 ID
            sa.Column("total_fen", sa.BigInteger(), nullable=False),  # 总金额（分）
            sa.Column("channel", sa.String(20), nullable=False),  # wechat/alipay
            sa.Column("merchant_order_id", sa.String(64), nullable=False),  # 渠道侧商户订单号
            sa.Column("split_status", sa.String(20), nullable=False, server_default="pending"),
            # pending/splitting/completed/failed
            sa.Column("split_count", sa.Integer(), nullable=False, server_default="0"),  # 拆分方数
            sa.Column("extra", JSONB(), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
            sa.Column("is_deleted", sa.Boolean(), server_default="false"),
        )
        op.create_index("ix_split_orders_tenant", "split_payment_orders", ["tenant_id"])
        op.create_index("ix_split_orders_order_id", "split_payment_orders", ["order_id"])
        op.create_index(
            "ix_split_orders_merchant_order_id",
            "split_payment_orders",
            ["merchant_order_id"],
            unique=True,
        )
        op.execute("""
            ALTER TABLE split_payment_orders ENABLE ROW LEVEL SECURITY;
            CREATE POLICY split_payment_orders_rls ON split_payment_orders
                USING (tenant_id = current_setting('app.tenant_id', true)::UUID)
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::UUID);
        """)

        # 分账明细记录（每笔分账订单可拆成多条明细，各方各一条）

    if "split_payment_records" not in existing:
        op.create_table(
            "split_payment_records",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("split_order_id", UUID(as_uuid=True), nullable=False),  # 关联分账订单
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("receiver_type", sa.String(20), nullable=False),
            # brand/franchise/platform_fee
            sa.Column("receiver_id", sa.String(64), nullable=False),  # 收款方标识（门店/品牌/平台）
            sa.Column("amount_fen", sa.BigInteger(), nullable=False),  # 应收金额（分）
            sa.Column("channel_sub_merchant_id", sa.String(64), nullable=True),  # 渠道子商户号
            sa.Column("split_result", sa.String(20), nullable=False, server_default="pending"),
            # pending/success/failed
            sa.Column("async_notify_id", sa.String(64), nullable=True),  # 渠道异步通知 ID
            sa.Column("idempotency_key", sa.String(64), nullable=False),  # sha256(split_order_id+receiver_id)
            sa.Column("extra", JSONB(), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
            sa.Column("is_deleted", sa.Boolean(), server_default="false"),
        )
        op.create_index("ix_split_records_order", "split_payment_records", ["split_order_id"])
        op.create_index("ix_split_records_tenant", "split_payment_records", ["tenant_id"])
        op.create_index(
            "ix_split_records_idempotency",
            "split_payment_records",
            ["idempotency_key"],
            unique=True,
        )
        op.execute("""
            ALTER TABLE split_payment_records ENABLE ROW LEVEL SECURITY;
            CREATE POLICY split_payment_records_rls ON split_payment_records
                USING (tenant_id = current_setting('app.tenant_id', true)::UUID)
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::UUID);
        """)

        # 差错账调账日志

    if "split_adjustment_logs" not in existing:
        op.create_table(
            "split_adjustment_logs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("split_record_id", UUID(as_uuid=True), nullable=False),  # 关联分账明细
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("original_amount_fen", sa.BigInteger(), nullable=False),
            sa.Column("adjusted_amount_fen", sa.BigInteger(), nullable=False),
            sa.Column("adjusted_by", sa.String(64), nullable=False),  # 操作人（用户ID或邮箱）
            sa.Column("extra", JSONB(), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        )
        op.create_index("ix_split_adjustments_tenant", "split_adjustment_logs", ["tenant_id"])
        op.create_index("ix_split_adjustments_record", "split_adjustment_logs", ["split_record_id"])
        op.execute("""
            ALTER TABLE split_adjustment_logs ENABLE ROW LEVEL SECURITY;
            CREATE POLICY split_adjustment_logs_rls ON split_adjustment_logs
                USING (tenant_id = current_setting('app.tenant_id', true)::UUID)
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::UUID);
        """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS split_adjustment_logs_rls ON split_adjustment_logs")
    op.execute("DROP POLICY IF EXISTS split_payment_records_rls ON split_payment_records")
    op.execute("DROP POLICY IF EXISTS split_payment_orders_rls ON split_payment_orders")

    op.drop_index("ix_split_adjustments_record", table_name="split_adjustment_logs")
    op.drop_index("ix_split_adjustments_tenant", table_name="split_adjustment_logs")
    op.drop_index("ix_split_records_idempotency", table_name="split_payment_records")
    op.drop_index("ix_split_records_tenant", table_name="split_payment_records")
    op.drop_index("ix_split_records_order", table_name="split_payment_records")
    op.drop_index("ix_split_orders_merchant_order_id", table_name="split_payment_orders")
    op.drop_index("ix_split_orders_order_id", table_name="split_payment_orders")
    op.drop_index("ix_split_orders_tenant", table_name="split_payment_orders")

    op.drop_table("split_adjustment_logs")
    op.drop_table("split_payment_records")
    op.drop_table("split_payment_orders")
