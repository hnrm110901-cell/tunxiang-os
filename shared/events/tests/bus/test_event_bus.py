"""T5.1.1 — EventBus 抽象基类 + EventEnvelope 信封的 TDD 测试套件.

覆盖目标:
- EventEnvelope: 字段完整性 / 不可变性 / 分区键语义 / 可选字段默认值
- EventBus: 抽象方法强制实现 / 子类实例化规则 / 方法签名约束
- 事件演进规则: schema_version 存在性

设计:
- 不依赖 Redis/PG, 纯内存 Mock 子类验证抽象契约
- OntologyEvent 最小 stub (T5.1.3 完整实现)
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import AsyncIterator, Awaitable, Callable, ClassVar, Optional
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from shared.events.bus.event_bus import EventBus, EventEnvelope
from shared.events.schemas.base import OntologyEvent

# ----------------------------------------------------------------------
# 测试用 Payload (作为 OntologyEvent 的合法子类)
# ----------------------------------------------------------------------

class _OrderPaidTestPayload(OntologyEvent):
    order_id: str
    total_fen: int


class _InvoiceVerifiedTestPayload(OntologyEvent):
    invoice_no: str
    amount_fen: int


def _make_envelope(**overrides) -> EventEnvelope:
    defaults = dict(
        event_id=str(uuid4()),
        aggregate_id="order-001",
        aggregate_type="order",
        event_type="order.paid",
        tenant_id=uuid4(),
        occurred_at=datetime.now(timezone.utc),
        schema_version="1.0",
        payload=_OrderPaidTestPayload(order_id="order-001", total_fen=8800),
    )
    defaults.update(overrides)
    return EventEnvelope(**defaults)


# ======================================================================
# §1 EventEnvelope 字段完整性 + 不可变性
# ======================================================================

class TestEventEnvelopeFields:
    def test_envelope_constructs_with_required_fields(self) -> None:
        """EventEnvelope 必需字段齐全时构造成功."""
        env = _make_envelope()
        assert env.aggregate_id == "order-001"
        assert env.aggregate_type == "order"
        assert env.event_type == "order.paid"
        assert env.schema_version == "1.0"
        assert isinstance(env.payload, _OrderPaidTestPayload)

    def test_envelope_is_frozen_dataclass(self) -> None:
        """EventEnvelope 必须不可变(防止总线传输中被篡改)."""
        env = _make_envelope()
        with pytest.raises(dataclasses.FrozenInstanceError):
            env.aggregate_id = "hacked"  # type: ignore[misc]

    def test_causation_and_correlation_default_to_none(self) -> None:
        """causation_id / correlation_id 为可选, 默认 None."""
        env = _make_envelope()
        assert env.causation_id is None
        assert env.correlation_id is None

    def test_causation_and_correlation_can_be_set(self) -> None:
        parent_id = str(uuid4())
        corr_id = str(uuid4())
        env = _make_envelope(causation_id=parent_id, correlation_id=corr_id)
        assert env.causation_id == parent_id
        assert env.correlation_id == corr_id

    def test_tenant_id_must_be_uuid(self) -> None:
        """tenant_id 强类型 UUID, 非 str."""
        env = _make_envelope()
        assert isinstance(env.tenant_id, UUID)

    def test_occurred_at_is_datetime(self) -> None:
        env = _make_envelope()
        assert isinstance(env.occurred_at, datetime)


# ======================================================================
# §2 EventEnvelope 分区键语义 (aggregate_id)
# ======================================================================

class TestEventEnvelopePartitionKey:
    def test_same_aggregate_same_partition_key(self) -> None:
        """同一聚合根的事件应有相同 aggregate_id (分区键)."""
        env_a = _make_envelope(event_id=str(uuid4()), aggregate_id="order-42")
        env_b = _make_envelope(event_id=str(uuid4()), aggregate_id="order-42")
        assert env_a.aggregate_id == env_b.aggregate_id

    def test_different_aggregates_have_different_keys(self) -> None:
        env_a = _make_envelope(aggregate_id="order-1")
        env_b = _make_envelope(aggregate_id="order-2")
        assert env_a.aggregate_id != env_b.aggregate_id


# ======================================================================
# §3 EventEnvelope payload 类型约束
# ======================================================================

class TestEventEnvelopePayloadTyping:
    def test_payload_accepts_any_ontology_event_subclass(self) -> None:
        """任何 OntologyEvent 子类均可作为 payload."""
        env = _make_envelope(
            aggregate_type="invoice",
            event_type="invoice.verified",
            payload=_InvoiceVerifiedTestPayload(invoice_no="INV-001", amount_fen=10000),
        )
        assert isinstance(env.payload, _InvoiceVerifiedTestPayload)


# ======================================================================
# §4 EventBus 抽象契约
# ======================================================================

class TestEventBusAbstractContract:
    def test_event_bus_cannot_be_instantiated_directly(self) -> None:
        """EventBus 是 ABC, 不可直接实例化."""
        with pytest.raises(TypeError, match="abstract"):
            EventBus()  # type: ignore[abstract]

    def test_incomplete_subclass_cannot_instantiate(self) -> None:
        """子类未实现全部抽象方法时, 不能实例化."""

        class IncompleteBus(EventBus):
            async def publish(self, envelope, *, maxlen=100_000):  # type: ignore[override]
                return "id-0"
            # 未实现 subscribe/replay/ack/close

        with pytest.raises(TypeError, match="abstract"):
            IncompleteBus()  # type: ignore[abstract]

    def test_complete_subclass_can_instantiate(self) -> None:
        """子类实现全部抽象方法时, 可正常实例化."""
        bus = _MockBus()
        assert isinstance(bus, EventBus)

    async def test_publish_is_async(self) -> None:
        bus = _MockBus()
        env = _make_envelope()
        event_id = await bus.publish(env)
        assert isinstance(event_id, str)
        assert bus.published == [env]

    async def test_subscribe_registers_handler(self) -> None:
        bus = _MockBus()
        received: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env)

        await bus.subscribe(
            consumer_group="g1",
            topics=["ontology.tenant.order"],
            handler=handler,
        )
        assert bus.subscribed_group == "g1"
        assert bus.subscribed_topics == ["ontology.tenant.order"]
        # 推送一条事件, 验证 handler 被调用
        env = _make_envelope()
        await bus.trigger(env)
        assert received == [env]

    async def test_ack_by_event_id(self) -> None:
        bus = _MockBus()
        event_id = str(uuid4())
        await bus.ack(topic="t", consumer_group="g1", event_id=event_id)
        assert bus.acked == [(["t", "g1", event_id])]

    async def test_replay_returns_async_iterator(self) -> None:
        """replay 返回 AsyncIterator, 支持 async for 遍历."""
        bus = _MockBus()
        env = _make_envelope()
        bus.replay_buffer = [env]
        collected: list[EventEnvelope] = []
        async for e in bus.replay(topic="t"):
            collected.append(e)
        assert collected == [env]

    async def test_close_is_idempotent(self) -> None:
        """close 可多次调用而不报错."""
        bus = _MockBus()
        await bus.close()
        await bus.close()
        assert bus.closed_count == 2


# ======================================================================
# §5 OntologyEvent schema_version ClassVar 契约
# ======================================================================

class TestOntologyEventSchemaVersion:
    def test_base_has_default_schema_version(self) -> None:
        """OntologyEvent 基类带有默认 schema_version '1.0'."""
        assert OntologyEvent.schema_version == "1.0"

    def test_subclass_inherits_schema_version(self) -> None:
        assert _OrderPaidTestPayload.schema_version == "1.0"

    def test_subclass_can_override_schema_version(self) -> None:
        """子类可覆写 schema_version (须声明为 ClassVar), 支持事件演进."""

        class _V2Payload(OntologyEvent):
            schema_version: ClassVar[str] = "2.0"

        assert _V2Payload.schema_version == "2.0"
        # 基类不受影响
        assert OntologyEvent.schema_version == "1.0"

    def test_payload_is_frozen_forbids_extra_fields(self) -> None:
        """OntologyEvent 子类 frozen=True, extra='forbid', 拒绝额外字段."""
        with pytest.raises(ValidationError):
            _OrderPaidTestPayload(order_id="o", total_fen=1, unknown_field="x")  # type: ignore[call-arg]

    def test_payload_is_immutable(self) -> None:
        """OntologyEvent 实例不可变."""
        p = _OrderPaidTestPayload(order_id="o-1", total_fen=100)
        with pytest.raises(ValidationError):
            p.order_id = "o-2"  # type: ignore[misc]


# ======================================================================
# 测试用 Mock 实现 (最小完整 EventBus 子类)
# ======================================================================

class _MockBus(EventBus):
    """纯内存 Mock, 仅用于抽象契约测试. 不保证顺序 / 持久化."""

    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []
        self.subscribed_group: str | None = None
        self.subscribed_topics: list[str] = []
        self._handler: Callable[[EventEnvelope], Awaitable[None]] | None = None
        self.acked: list[list[str]] = []
        self.closed_count: int = 0
        self.replay_buffer: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope, *, maxlen: int = 100_000) -> str:
        self.published.append(envelope)
        return envelope.event_id

    async def subscribe(
        self,
        *,
        consumer_group: str,
        topics: list[str],
        handler: Callable[[EventEnvelope], Awaitable[None]],
        start_from: str = ">",
    ) -> None:
        self.subscribed_group = consumer_group
        self.subscribed_topics = list(topics)
        self._handler = handler

    async def trigger(self, envelope: EventEnvelope) -> None:
        """测试辅助: 模拟总线推送给 handler."""
        if self._handler is not None:
            await self._handler(envelope)

    async def replay(
        self,
        *,
        topic: str,
        after_event_id: Optional[str] = None,
        limit: int = 1000,
    ) -> AsyncIterator[EventEnvelope]:
        for env in self.replay_buffer[:limit]:
            yield env

    async def ack(self, *, topic: str, consumer_group: str, event_id: str) -> None:
        self.acked.append([topic, consumer_group, event_id])

    async def close(self) -> None:
        self.closed_count += 1
