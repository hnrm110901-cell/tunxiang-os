"""外卖自动接单规则 ORM 模型

每门店一条配置，控制自动接单的时间窗口、并发上限和平台白名单。
继承 TenantBase，已包含 id/tenant_id/created_at/updated_at/is_deleted。
"""

import uuid
from datetime import time

from sqlalchemy import Boolean, Integer, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class DeliveryAutoAcceptRule(TenantBase):
    """外卖自动接单规则（每门店一条）"""

    __tablename__ = "delivery_auto_accept_rules"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="门店ID",
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否启用自动接单",
    )
    business_hours_start: Mapped[time | None] = mapped_column(
        Time,
        nullable=True,
        comment="自动接单营业开始时间",
    )
    business_hours_end: Mapped[time | None] = mapped_column(
        Time,
        nullable=True,
        comment="自动接单营业结束时间",
    )
    max_concurrent_orders: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=10,
        comment="同时最多自动接多少单（活跃中的 accepted/preparing 订单）",
    )
    excluded_platforms: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment='不自动接单的平台列表，如 ["meituan"]',
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "store_id", name="uq_auto_accept_rule_store"),
        {"comment": "外卖自动接单规则（每门店一条）"},
    )
