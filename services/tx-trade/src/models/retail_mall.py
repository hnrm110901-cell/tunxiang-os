"""零售商城 ORM 模型 — 商品 / 订单 / 订单明细

所有金额单位：分(fen)。继承 TenantBase 确保 RLS 租户隔离。
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase


class RetailProduct(TenantBase):
    """零售商品"""
    __tablename__ = "retail_products_v2"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="所属门店ID"
    )
    name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="商品名称"
    )
    sku: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="SKU编码"
    )
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, default="merchandise",
        comment="分类: seafood_gift/prepared_dish/seasoning/merchandise"
    )
    price_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="售价(分)"
    )
    cost_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="成本价(分)"
    )
    stock_qty: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="库存数量"
    )
    min_stock: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="最低库存预警值"
    )
    image_url: Mapped[Optional[str]] = mapped_column(
        Text, comment="商品主图URL"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", index=True,
        comment="状态: active/inactive/sold_out"
    )
    is_weighable: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否称重商品"
    )

    # 关系
    order_items: Mapped[list["RetailOrderItem"]] = relationship(
        back_populates="product", lazy="selectin"
    )


class RetailOrder(TenantBase):
    """零售订单"""
    __tablename__ = "retail_orders_v2"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="所属门店ID"
    )
    order_no: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, comment="订单编号"
    )
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), comment="顾客ID"
    )
    total_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="订单总额(分)"
    )
    discount_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="优惠金额(分)"
    )
    final_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="实付金额(分)"
    )
    payment_method: Mapped[Optional[str]] = mapped_column(
        String(30), comment="支付方式: wechat/alipay/cash/card"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True,
        comment="状态: pending/paid/refunded/cancelled"
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(comment="支付时间")

    # 关系
    items: Mapped[list["RetailOrderItem"]] = relationship(
        back_populates="order", lazy="selectin", cascade="all, delete-orphan"
    )


class RetailOrderItem(TenantBase):
    """零售订单明细"""
    __tablename__ = "retail_order_items_v2"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("retail_orders_v2.id"), nullable=False, index=True,
        comment="关联订单ID"
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("retail_products_v2.id"), nullable=False, index=True,
        comment="关联商品ID"
    )
    product_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="商品名称快照"
    )
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="数量"
    )
    unit_price_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="单价(分)"
    )
    subtotal_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="小计(分)"
    )

    # 关系
    order: Mapped["RetailOrder"] = relationship(back_populates="items")
    product: Mapped["RetailProduct"] = relationship(back_populates="order_items")
