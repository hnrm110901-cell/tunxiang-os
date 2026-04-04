"""shared.events — 屯象OS 全域业务事件总线（Redis Streams）

导出所有域的事件类型、数据类和发布器。
"""
# 会员域（保持向后兼容）
from .member_events import MemberEvent, MemberEventType
from .event_publisher import MemberEventPublisher
from .event_consumer import MemberEventConsumer

# 交易域
from .trade_events import TradeEvent, TradeEventType

# 供应链域
from .supply_events import SupplyEvent, SupplyEventType

# 财务域
from .finance_events import FinanceEvent, FinanceEventType

# 组织人事域
from .org_events import OrgEvent, OrgEventType

# 商品菜单域
from .menu_events import MenuEvent, MenuEventType

# 运营日清域
from .ops_events import OpsEvent, OpsEventType

# 通用发布器（推荐所有新代码使用）
from .universal_publisher import UniversalPublisher

# ── 新统一事件总线框架（推荐所有新代码使用） ─────────────────────────
from .src.event_base import TxEvent
from .src.event_types import (
    AgentEventType,
    ChannelEventType,
    DiscountEventType,
    EnergyEventType,
    InventoryEventType,
    KdsEventType,
    OpinionEventType,
    OrderEventType,
    PaymentEventType,
    RecipeEventType,
    ReservationEventType,
    ReviewEventType,
    SafetyEventType,
    SettlementEventType,
    resolve_stream_key,
    resolve_stream_type,
)
from .src.event_types import MemberEventType as MemberEventType2
from .src.publisher import EventPublisher
from .src.consumer import EventConsumer
from .src.pg_notify import PgNotifier, PgListener
from .src.pg_event_store import PgEventStore
from .src.emitter import emit_event, emits
from .src.projector import ProjectorBase
from .src.projectors import ALL_PROJECTORS
from .src.middleware import (
    EventMiddleware,
    LoggingMiddleware,
    TenantIsolationMiddleware,
    DeduplicationMiddleware,
    apply_middleware,
)

__all__ = [
    # 会员（旧域专属，保持向后兼容）
    "MemberEvent", "MemberEventType", "MemberEventPublisher", "MemberEventConsumer",
    # 交易
    "TradeEvent", "TradeEventType",
    # 供应链
    "SupplyEvent", "SupplyEventType",
    # 财务
    "FinanceEvent", "FinanceEventType",
    # 组织
    "OrgEvent", "OrgEventType",
    # 菜单
    "MenuEvent", "MenuEventType",
    # 运营
    "OpsEvent", "OpsEventType",
    # 通用发布器（旧）
    "UniversalPublisher",
    # ── 新统一事件总线 ──
    "TxEvent",
    # 10大事件域
    "OrderEventType", "DiscountEventType", "PaymentEventType",
    "MemberEventType2", "InventoryEventType", "ChannelEventType",
    "ReservationEventType", "SettlementEventType", "SafetyEventType",
    "EnergyEventType", "ReviewEventType", "OpinionEventType", "RecipeEventType",
    "KdsEventType", "AgentEventType",
    "resolve_stream_key", "resolve_stream_type",
    # 核心基础设施
    "PgEventStore", "emit_event", "emits",
    "ProjectorBase", "ALL_PROJECTORS",
    # Redis Stream（兼容）
    "EventPublisher", "EventConsumer",
    "PgNotifier", "PgListener",
    # 中间件
    "EventMiddleware", "LoggingMiddleware",
    "TenantIsolationMiddleware", "DeduplicationMiddleware",
    "apply_middleware",
]
