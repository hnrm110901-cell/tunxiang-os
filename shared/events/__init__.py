"""shared.events — 会员行为事件总线（Redis Streams）

导出：
    MemberEventType   — 事件类型枚举
    MemberEvent       — 事件数据类
    MemberEventPublisher — 发布器（异步，单例 Redis 连接）
    MemberEventConsumer  — 消费器（Consumer Group 模式）
"""

from .member_events import MemberEvent, MemberEventType
from .event_publisher import MemberEventPublisher
from .event_consumer import MemberEventConsumer

__all__ = [
    "MemberEvent",
    "MemberEventType",
    "MemberEventPublisher",
    "MemberEventConsumer",
]
