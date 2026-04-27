"""供应链域事件类型定义

供应链域所有跨服务事件均通过 SupplyEvent 传递，事件类型由 SupplyEventType 枚举定义。
Redis Stream key: supply_events
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4


class SupplyEventType(str, Enum):
    """供应链域事件类型

    命名规范：supply.{entity}.{action}
    全部小写，单词间用点分隔。
    """

    # ── 库存类 ─────────────────────────────────────────────────────
    STOCK_LOW = "supply.stock.low"  # 库存低于阈值
    STOCK_ZERO = "supply.stock.zero"  # 库存清零

    # ── 食材类 ─────────────────────────────────────────────────────
    INGREDIENT_EXPIRING = "supply.ingredient.expiring"  # 食材临期
    INGREDIENT_EXPIRED = "supply.ingredient.expired"  # 食材过期

    # ── 收货类 ─────────────────────────────────────────────────────
    RECEIVING_COMPLETED = "supply.receiving.completed"  # 收货完成
    RECEIVING_VARIANCE = "supply.receiving.variance"  # 收货差异超5%

    # ── 调拨类 ─────────────────────────────────────────────────────
    TRANSFER_COMPLETED = "supply.transfer.completed"  # 门店调拨完成
    TRANSFER_LOSS_DETECTED = "supply.transfer.loss_detected"  # 调拨损耗超标

    # ── 采购类 ─────────────────────────────────────────────────────
    PROCUREMENT_SUGGESTED = "supply.procurement.suggested"  # 智能补货建议


@dataclass
class SupplyEvent:
    """供应链域事件数据类

    Attributes:
        event_type:     事件类型（SupplyEventType 枚举值）
        tenant_id:      租户 UUID（RLS 隔离）
        store_id:       门店 UUID
        entity_id:      主体实体 UUID（ingredient_id / po_id / transfer_id 等）
        event_data:     事件具体数据（业务字段，按事件类型不同）
        event_id:       唯一事件 ID（默认自动生成 uuid4）
        occurred_at:    事件发生时刻（UTC，默认当前时间）
        source_service: 来源服务名
    """

    event_type: SupplyEventType
    tenant_id: UUID
    store_id: UUID
    entity_id: UUID
    event_data: dict
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_service: str = "tx-supply"
