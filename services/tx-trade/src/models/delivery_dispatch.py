"""配送调度持久化模型 — DeliveryDispatch + DeliveryProviderConfig

由 v391 迁移建表。从内存 dict 迁移到 PostgreSQL，继承 TenantBase 确保 RLS 隔离。
所有金额存分（fen）。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class DeliveryDispatch(TenantBase):
    """配送调度记录 — 每个外卖订单对应一条 dispatch。

    覆盖三类 provider：达达 / 顺丰同城 / 自有骑手。
    存 provider_order_id（三方单号）+ 完整状态时间戳 + 骑手最新位置。

    主键沿用 TenantBase 的 UUID id；业务可读编号存 dispatch_no（如 DSP-XXXX）。
    """

    __tablename__ = "delivery_dispatches"

    dispatch_no: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        unique=True,
        index=True,
        comment="业务可读编号：DSP-{12位hex}",
    )

    store_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="门店 ID（兼容字符串/UUID）",
    )
    order_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="关联交易订单 ID",
    )

    provider: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="dada / shunfeng / self_rider",
    )
    provider_order_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="三方平台返回的订单号",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        comment="状态机：pending/dispatched/accepted/picked_up/delivering/delivered/cancelled/failed",
    )

    # 骑手实时信息
    rider_name: Mapped[str | None] = mapped_column(String(50))
    rider_phone: Mapped[str | None] = mapped_column(String(20))
    rider_lat: Mapped[float | None] = mapped_column(Float)
    rider_lng: Mapped[float | None] = mapped_column(Float)
    rider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # 配送地址
    delivery_address: Mapped[str] = mapped_column(String(500), nullable=False)
    delivery_lat: Mapped[float | None] = mapped_column(Float)
    delivery_lng: Mapped[float | None] = mapped_column(Float)
    distance_meters: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivery_fee_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tip_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 时长（分钟）
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    actual_minutes: Mapped[int | None] = mapped_column(Integer)

    # 状态时间戳
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(200))
    fail_reason: Mapped[str | None] = mapped_column(String(200))

    # KDS 协同
    kds_ready_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="KDS 出餐完成时间，用于触发骑手取货推送",
    )
    rider_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="骑手 App 收到取货推送的时间",
    )

    provider_callback_raw: Mapped[dict | None] = mapped_column(
        JSONB,
        default=dict,
        comment="三方推送的最近一次 raw payload",
    )

    __table_args__ = (
        Index("idx_delivery_dispatches_tenant_store_status", "tenant_id", "store_id", "status"),
        {"comment": "自营外卖配送调度记录（达达/顺丰/自有骑手）"},
    )


class DeliveryProviderConfig(TenantBase):
    """门店级配送商配置（达达/顺丰/自有骑手）。

    一个门店每种 provider 只能有一条记录（unique 约束）。
    """

    __tablename__ = "delivery_provider_configs"

    store_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="dada / shunfeng / self_rider",
    )

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=99,
        comment="优先级 0=最高，99=最低",
    )

    # 凭据（生产应配合 KMS 加密；当前明文存储 + 应用层脱敏返回）
    app_key: Mapped[str | None] = mapped_column(String(200))
    app_secret: Mapped[str | None] = mapped_column(String(200))
    merchant_id: Mapped[str | None] = mapped_column(String(100))
    shop_no: Mapped[str | None] = mapped_column(String(100))
    callback_url: Mapped[str | None] = mapped_column(String(500))
    extra_config: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "store_id",
            "provider",
            name="uniq_delivery_provider_per_store",
        ),
        Index(
            "idx_delivery_provider_configs_lookup",
            "tenant_id",
            "store_id",
            "enabled",
            "priority",
        ),
        {"comment": "门店级配送商配置（达达/顺丰/自有骑手）"},
    )
