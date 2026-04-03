"""v011: Supplement Order/OrderItem fields for adapter mapping completeness

New columns on orders:
  - cashier_id (UUID)           — 收银员ID（品智 cashiers 映射）
  - service_charge_fen (int)    — 服务费总额（天财 service_fee_income_money 映射）
  - order_source (varchar 50)   — 原始订单来源编码
  - table_transfer_from (varchar 20) — 转台前桌号

New columns on order_items:
  - original_price_fen (int)    — 原价/折前价
  - single_discount_fen (int)   — 单品折扣金额
  - practice_names (varchar 500)— 做法名称（冗余，逗号分隔）
  - is_gift (boolean)           — 是否赠菜（默认 false）
  - gift_reason (varchar 200)   — 赠菜原因
  - combo_id (UUID)             — 所属套餐ID

向前兼容：所有新字段允许 NULL 或有默认值。
RLS 无变化：仅添加列，不新增表。

Revision ID: v011
Revises: v010
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v011"
down_revision: Union[str, None] = "v010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =====================================================================
    # orders — 4 new columns
    # =====================================================================
    op.add_column("orders", sa.Column(
        "cashier_id", UUID(as_uuid=True), comment="收银员ID"))
    op.add_column("orders", sa.Column(
        "service_charge_fen", sa.Integer, comment="服务费总额(分)"))
    op.add_column("orders", sa.Column(
        "order_source", sa.String(50), comment="原始订单来源编码"))
    op.add_column("orders", sa.Column(
        "table_transfer_from", sa.String(20), comment="转台前桌号"))

    # =====================================================================
    # order_items — 6 new columns
    # =====================================================================
    op.add_column("order_items", sa.Column(
        "original_price_fen", sa.Integer, comment="原价/折前价(分)"))
    op.add_column("order_items", sa.Column(
        "single_discount_fen", sa.Integer, comment="单品折扣金额(分)"))
    op.add_column("order_items", sa.Column(
        "practice_names", sa.String(500), comment="做法名称(冗余,逗号分隔)"))
    op.add_column("order_items", sa.Column(
        "is_gift", sa.Boolean, server_default="false", comment="是否赠菜"))
    op.add_column("order_items", sa.Column(
        "gift_reason", sa.String(200), comment="赠菜原因"))
    op.add_column("order_items", sa.Column(
        "combo_id", UUID(as_uuid=True), comment="所属套餐ID(NULL=非套餐)"))


def downgrade() -> None:
    # order_items
    op.drop_column("order_items", "combo_id")
    op.drop_column("order_items", "gift_reason")
    op.drop_column("order_items", "is_gift")
    op.drop_column("order_items", "practice_names")
    op.drop_column("order_items", "single_discount_fen")
    op.drop_column("order_items", "original_price_fen")

    # orders
    op.drop_column("orders", "table_transfer_from")
    op.drop_column("orders", "order_source")
    op.drop_column("orders", "service_charge_fen")
    op.drop_column("orders", "cashier_id")
