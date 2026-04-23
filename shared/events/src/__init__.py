"""shared.events.src -- 屯象OS 统一事件总线框架

架构升级（v147/v148）：Event Sourcing + CQRS
  - PgEventStore:   PostgreSQL append-only 事件存储（持久化 + 审计）
  - emit_event:     平行事件发射器（同时写入 Redis Stream + PG events 表）
  - ProjectorBase:  投影器基类（事件流 → 物化视图）
  - 10大事件域:     订单/折扣/支付/会员/库存/渠道/预订/结算/食安/能耗

旧接口（Redis Streams）保留兼容，新代码统一使用 emit_event。
"""

from .consumer import EventConsumer
from .emitter import emit_event, emits
from .event_base import TxEvent
from .event_types import (
    ALL_EVENT_ENUMS,
    DOMAIN_STREAM_MAP,
    # 核心业务域（七条因果链）
    AgentEventType,
    ChannelEventType,
    DiscountEventType,
    EnergyEventType,
    InventoryEventType,
    KdsEventType,
    MemberEventType,
    OpinionEventType,
    OrderEventType,
    PaymentEventType,
    RecipeEventType,
    ReservationEventType,
    ReviewEventType,
    SafetyEventType,
    SettlementEventType,
    # 工具函数
    resolve_stream_key,
    resolve_stream_type,
)
from .middleware import (
    DeduplicationMiddleware,
    EventMiddleware,
    LoggingMiddleware,
    TenantIsolationMiddleware,
)
from .pg_event_store import PgEventStore
from .pg_notify import PgListener, PgNotifier
from .projector import ProjectorBase
from .publisher import EventPublisher

__all__ = [
    # ── 事件基础 ──
    "TxEvent",
    # ── 事件类型（10大域 + 系统域）──
    "OrderEventType",
    "DiscountEventType",
    "PaymentEventType",
    "MemberEventType",
    "InventoryEventType",
    "ChannelEventType",
    "ReservationEventType",
    "SettlementEventType",
    "SafetyEventType",
    "EnergyEventType",
    "ReviewEventType",
    "OpinionEventType",
    "RecipeEventType",
    "KdsEventType",
    "AgentEventType",
    "ALL_EVENT_ENUMS",
    "resolve_stream_key",
    "resolve_stream_type",
    "DOMAIN_STREAM_MAP",
    # ── 核心基础设施 ──
    "PgEventStore",  # PostgreSQL 持久化事件存储
    "emit_event",  # 平行事件发射器（Redis + PG）
    "emits",  # 装饰器版发射器
    "ProjectorBase",  # 投影器基类
    # ── Redis Stream（保留兼容）──
    "EventPublisher",
    "EventConsumer",
    # ── PG NOTIFY ──
    "PgNotifier",
    "PgListener",
    # ── 中间件 ──
    "EventMiddleware",
    "LoggingMiddleware",
    "TenantIsolationMiddleware",
    "DeduplicationMiddleware",
]
