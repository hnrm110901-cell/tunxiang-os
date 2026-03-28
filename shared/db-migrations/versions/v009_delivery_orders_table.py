"""v009: Add delivery_orders table for persistent delivery order storage

Migrates delivery order storage from in-memory dict (_delivery_orders)
to PostgreSQL persistent table with full RLS.

New table:
  - delivery_orders: 外卖平台统一订单表（美团/饿了么/抖音）

All standard fields: UUID PK, tenant_id, created_at, updated_at, is_deleted.
RLS: ENABLE + FORCE + 4 policies with IS NOT NULL guard.

Revision ID: v009
Revises: v008
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision: str = "v009"
down_revision: Union[str, None] = "v008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "delivery_orders"

# Safe RLS condition (consistent with v006-v008)
_SAFE_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def _enable_rls(table_name: str) -> None:
    """Enable RLS with FORCE + 4 safe policies."""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")

    op.execute(
        f"CREATE POLICY {table_name}_rls_select ON {table_name} "
        f"FOR SELECT USING ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table_name}_rls_insert ON {table_name} "
        f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table_name}_rls_update ON {table_name} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table_name}_rls_delete ON {table_name} "
        f"FOR DELETE USING ({_SAFE_CONDITION})"
    )


def _disable_rls(table_name: str) -> None:
    """Drop RLS policies and disable RLS (for downgrade)."""
    for op_suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {table_name}_rls_{op_suffix} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.create_table(
        TABLE_NAME,
        # ── 基类字段 ──
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),

        # ── 内部编号 ──
        sa.Column("order_no", sa.String(64), unique=True, nullable=False, index=True,
                  comment="内部流水号 MT20260328..."),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False, index=True,
                  comment="门店ID"),
        sa.Column("brand_id", sa.String(50), nullable=False, index=True,
                  comment="品牌ID"),

        # ── 平台信息 ──
        sa.Column("platform", sa.String(20), nullable=False, index=True,
                  comment="meituan / eleme / douyin"),
        sa.Column("platform_name", sa.String(50), nullable=False, server_default="",
                  comment="美团外卖 / 饿了么 / 抖音外卖"),
        sa.Column("platform_order_id", sa.String(100), unique=True, nullable=False, index=True,
                  comment="平台原始订单号"),
        sa.Column("sales_channel", sa.String(50), nullable=False, server_default="",
                  comment="delivery_meituan等"),

        # ── 关联内部订单 ──
        sa.Column("internal_order_id", UUID(as_uuid=True), index=True, nullable=True,
                  comment="关联orders.id"),

        # ── 状态 ──
        sa.Column("status", sa.String(20), nullable=False, server_default="confirmed", index=True,
                  comment="pending/confirmed/preparing/ready/delivering/completed/cancelled/refunded"),

        # ── 菜品 ──
        sa.Column("items_json", JSON, nullable=True,
                  comment="菜品列表JSON"),

        # ── 金额(分) ──
        sa.Column("total_fen", sa.Integer(), nullable=False, server_default="0",
                  comment="订单总额(分)"),
        sa.Column("commission_rate", sa.Float(), nullable=False, server_default="0",
                  comment="平台佣金比例"),
        sa.Column("commission_fen", sa.Integer(), nullable=False, server_default="0",
                  comment="平台佣金(分)"),
        sa.Column("merchant_receive_fen", sa.Integer(), nullable=False, server_default="0",
                  comment="商户实收(分)"),

        # ── 骑手信息 ──
        sa.Column("rider_name", sa.String(50), nullable=True, comment="骑手姓名"),
        sa.Column("rider_phone", sa.String(20), nullable=True, comment="骑手电话"),

        # ── 顾客与配送 ──
        sa.Column("customer_phone", sa.String(20), nullable=True, comment="顾客电话"),
        sa.Column("delivery_address", sa.String(500), nullable=True, comment="配送地址"),
        sa.Column("expected_time", sa.String(30), nullable=True, comment="期望送达时间ISO"),

        # ── 时间戳 ──
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estimated_ready_min", sa.Integer(), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.String(500), nullable=True),
        sa.Column("cancel_responsible", sa.String(20), nullable=True,
                  comment="merchant/customer/platform/rider"),

        # ── 未映射菜品 ──
        sa.Column("unmapped_items", JSON, nullable=True, comment="未映射菜品名列表"),

        # ── 备注 ──
        sa.Column("notes", sa.Text(), nullable=True, comment="订单备注"),

        comment="外卖平台统一订单表",
    )

    # 复合索引
    op.create_index(
        "idx_delivery_order_store_platform",
        TABLE_NAME,
        ["store_id", "platform"],
    )
    op.create_index(
        "idx_delivery_order_store_status",
        TABLE_NAME,
        ["store_id", "status"],
    )
    op.create_index(
        "idx_delivery_order_created",
        TABLE_NAME,
        ["created_at"],
    )

    # RLS
    _enable_rls(TABLE_NAME)


def downgrade() -> None:
    _disable_rls(TABLE_NAME)
    op.drop_table(TABLE_NAME)
