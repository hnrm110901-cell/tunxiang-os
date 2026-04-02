"""积分商城数据模型

两张核心表：
  points_mall_products  — 商城商品（实物/优惠券/菜品兑换/储值金）
  points_mall_orders    — 兑换订单

金额单位：分（fen）。库存 -1 表示不限库存。
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

PRODUCT_TYPES = ("physical", "coupon", "dish", "stored_value")
ORDER_STATUSES = ("pending", "fulfilled", "cancelled", "expired")


class PointsMallProduct(TenantBase):
    """积分商城商品主档

    product_type 决定 product_content 结构：
      physical:     {"sku": "xxx", "weight_g": 50}
      coupon:       {"coupon_template_id": "xxx", "amount_fen": 1000}
      dish:         {"dish_id": "xxx", "dish_name": "辣子鸡"}
      stored_value: {"amount_fen": 500}
    """
    __tablename__ = "points_mall_products"

    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="商品名称")
    description: Mapped[str | None] = mapped_column(Text, comment="商品描述")
    image_url: Mapped[str | None] = mapped_column(String(500), comment="商品图片URL")

    product_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="physical=实物 | coupon=优惠券 | dish=菜品兑换 | stored_value=储值金",
    )

    points_required: Mapped[int] = mapped_column(Integer, nullable=False, comment="所需积分")

    # 库存：-1 = 不限库存
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=-1, comment="-1=不限库存")
    stock_sold: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="已兑换数量")

    # 商品内容（JSONB，根据 product_type 不同内容不同）
    product_content: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, comment="商品内容详情")

    # 兑换限制
    limit_per_customer: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="每人最多兑换次数（0=不限）",
    )
    limit_per_period: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="每周期最多兑换次数（0=不限）",
    )
    limit_period_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, comment="限制周期（天数）",
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否上架")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="排序权重（ASC）")

    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="上架生效时间")
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="下架时间")

    __table_args__ = (
        Index("idx_pm_products_tenant_active", "tenant_id", "is_active"),
        Index("idx_pm_products_tenant_sort", "tenant_id", "sort_order"),
        {"comment": "积分商城商品主档"},
    )


class PointsMallOrder(TenantBase):
    """积分商城兑换订单

    status 流转：
      pending  → fulfilled（门店核销 / 自动发放）
      pending  → cancelled（退款退积分）
      pending  → expired（超期未核销）
    """
    __tablename__ = "points_mall_orders"

    order_no: Mapped[str] = mapped_column(
        String(40), unique=True, nullable=False, index=True,
        comment="订单号 PM-{YYYYMMDD}-{6位}",
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="兑换顾客ID",
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="兑换商品ID",
    )
    store_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), comment="兑换门店（实物需要）",
    )

    points_deducted: Mapped[int] = mapped_column(Integer, nullable=False, comment="扣除积分")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="兑换数量")

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True,
        comment="pending | fulfilled | cancelled | expired",
    )

    # 配送信息（实物商品）
    delivery_address: Mapped[str | None] = mapped_column(String(500), comment="配送地址")
    delivery_name: Mapped[str | None] = mapped_column(String(50), comment="收件人姓名")
    delivery_phone: Mapped[str | None] = mapped_column(String(20), comment="收件人电话")
    tracking_no: Mapped[str | None] = mapped_column(String(100), comment="快递单号")

    # 关联业务
    coupon_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), comment="兑换的优惠券ID")

    # 操作时间
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="核销时间")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="取消时间")
    cancel_reason: Mapped[str | None] = mapped_column(String(200), comment="取消原因")

    __table_args__ = (
        Index("idx_pm_orders_customer", "tenant_id", "customer_id"),
        Index("idx_pm_orders_status", "tenant_id", "status"),
        Index("idx_pm_orders_product", "tenant_id", "product_id"),
        {"comment": "积分商城兑换订单"},
    )
