"""外卖订单持久化模型 — DeliveryOrder

从内存 dict 迁移到 PostgreSQL，继承 TenantBase 确保 RLS 隔离。
所有金额存分（fen）。
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Integer, Float, String, Text,
    ForeignKey, Index, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class DeliveryOrder(TenantBase):
    """外卖平台订单 — 美团/饿了么/抖音统一存储"""
    __tablename__ = "delivery_orders"

    # 内部编号
    order_no: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True,
        comment="内部流水号 MT20260328...",
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="门店ID",
    )
    brand_id: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        comment="品牌ID",
    )

    # 平台信息
    platform: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
        comment="meituan / eleme / douyin",
    )
    platform_name: Mapped[str] = mapped_column(
        String(50), nullable=False, default="",
        comment="美团外卖 / 饿了么 / 抖音外卖",
    )
    platform_order_id: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True,
        comment="平台原始订单号",
    )
    sales_channel: Mapped[str] = mapped_column(
        String(50), nullable=False, default="",
        comment="delivery_meituan / delivery_eleme / delivery_douyin",
    )

    # 关联内部订单（可选，如需同步到 orders 主表）
    internal_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True,
        comment="关联 orders.id",
    )

    # 状态
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="confirmed", index=True,
        comment="pending/confirmed/preparing/ready/delivering/completed/cancelled/refunded",
    )

    # 菜品（JSON 存储映射后的菜品列表）
    items_json: Mapped[dict | None] = mapped_column(
        JSON, default=list,
        comment='[{name, quantity, price_fen, internal_dish_id, mapped, ...}]',
    )

    # 金额（分）
    total_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="订单总额(分)",
    )
    commission_rate: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="平台佣金比例",
    )
    commission_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="平台佣金(分)",
    )
    merchant_receive_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="商户实收(分)=total-commission",
    )

    # 骑手信息
    rider_name: Mapped[str | None] = mapped_column(String(50), comment="骑手姓名")
    rider_phone: Mapped[str | None] = mapped_column(String(20), comment="骑手电话")

    # 顾客与配送
    customer_phone: Mapped[str | None] = mapped_column(
        String(20), comment="顾客电话(脱敏)",
    )
    delivery_address: Mapped[str | None] = mapped_column(
        String(500), comment="配送地址",
    )
    expected_time: Mapped[str | None] = mapped_column(
        String(30), comment="期望送达时间 ISO",
    )

    # 时间戳
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_ready_min: Mapped[int | None] = mapped_column(
        Integer, comment="预计出餐分钟数",
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    cancel_responsible: Mapped[str | None] = mapped_column(
        String(20), comment="merchant/customer/platform/rider",
    )

    # 未映射菜品（需要人工处理）
    unmapped_items: Mapped[dict | None] = mapped_column(
        JSON, default=list,
        comment="未映射到内部菜品的平台菜名列表",
    )

    # 备注
    notes: Mapped[str | None] = mapped_column(Text, comment="订单备注")

    __table_args__ = (
        Index("idx_delivery_order_store_platform", "store_id", "platform"),
        Index("idx_delivery_order_store_status", "store_id", "status"),
        Index("idx_delivery_order_created", "created_at"),
        {"comment": "外卖平台统一订单表"},
    )
