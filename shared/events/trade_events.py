"""交易域事件类型定义

交易域所有跨服务事件均通过 TradeEvent 传递，事件类型由 TradeEventType 枚举定义。
Redis Stream key: trade_events
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4


class TradeEventType(str, Enum):
    """交易域事件类型

    命名规范：trade.{entity}.{action}
    全部小写，单词间用点分隔。
    """

    # ── 订单类 ─────────────────────────────────────────────────────
    ORDER_CREATED = "trade.order.created"  # 订单创建
    ORDER_PAID = "trade.order.paid"  # 支付成功
    ORDER_REFUNDED = "trade.order.refunded"  # 退款
    ORDER_CANCELLED = "trade.order.cancelled"  # 取消

    # ── 折扣类 ─────────────────────────────────────────────────────
    DISCOUNT_BLOCKED = "trade.discount.blocked"  # 折扣被折扣守护拦截

    # ── 桌台类 ─────────────────────────────────────────────────────
    TABLE_OPENED = "trade.table.opened"  # 桌台开台
    TABLE_CLOSED = "trade.table.closed"  # 桌台结台

    # ── 班次类 ─────────────────────────────────────────────────────
    SHIFT_HANDOVER = "trade.shift.handover"  # 班次交接

    # ── 日结类 ─────────────────────────────────────────────────────
    DAILY_SETTLEMENT_COMPLETED = "trade.daily_settlement.completed"  # 日结完成


@dataclass
class TradeEvent:
    """交易域事件数据类

    Attributes:
        event_type:     事件类型（TradeEventType 枚举值）
        tenant_id:      租户 UUID（RLS 隔离）
        store_id:       门店 UUID（餐饮业务必须有门店维度）
        entity_id:      主体实体 UUID（order_id / table_id 等）
        event_data:     事件具体数据（业务字段，按事件类型不同）
        event_id:       唯一事件 ID（默认自动生成 uuid4）
        occurred_at:    事件发生时刻（UTC，默认当前时间）
        source_service: 来源服务名
    """

    event_type: TradeEventType
    tenant_id: UUID
    store_id: UUID
    entity_id: UUID
    event_data: dict
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_service: str = "tx-trade"
