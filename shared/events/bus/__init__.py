"""shared.events.bus — Ontology 事件总线抽象层 (T5.1.1+).

提供 EventBus 抽象接口, 供 RedisStreamsEventBus (T5.1.2) 等传输层实现.
新 Agent 只依赖此抽象层, 不直接依赖 Redis/Kafka 等具体传输.
"""
from .event_bus import EventBus, EventEnvelope

__all__ = ["EventBus", "EventEnvelope"]
