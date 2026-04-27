"""T5.1.5 — EventRelay 的 TDD 测试套件.

覆盖:
- 抽象 OutboxReader 契约
- EventRelay.run_once() 正常路径
- 部分批次失败 (publish 中间失败) 游标只前进到成功点
- 空 events 表返回 0
- 多次调用幂等 (第二次无新事件)
- batch 上限

使用内存 FakeOutboxReader + MockBus, 不依赖 PG / Redis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Awaitable, Callable, Optional
from uuid import UUID, uuid4

import pytest

from shared.events.bus.event_bus import EventBus, EventEnvelope
from shared.events.bus.relay import (
    EventRelay,
    OutboxReader,
    PendingEvent,
)
from shared.events.schemas.base import OntologyEvent

# ----------------------------------------------------------------------
# Payload for tests
# ----------------------------------------------------------------------

class _Payload(OntologyEvent):
    note: str


# ----------------------------------------------------------------------
# Fake OutboxReader (内存, 无 PG 依赖)
# ----------------------------------------------------------------------

@dataclass
class FakeOutboxReader(OutboxReader):
    events: list[PendingEvent] = field(default_factory=list)
    cursors: dict[str, int] = field(default_factory=dict)

    async def get_cursor(self, relay_name: str) -> int:
        return self.cursors.get(relay_name, 0)

    async def fetch_batch(
        self, *, after_sequence: int, limit: int
    ) -> list[PendingEvent]:
        result = [e for e in self.events if e.sequence_num > after_sequence]
        result.sort(key=lambda e: e.sequence_num)
        return result[:limit]

    async def update_cursor(
        self,
        *,
        relay_name: str,
        last_sequence: int,
        last_event_id: str,
    ) -> None:
        self.cursors[relay_name] = last_sequence


# ----------------------------------------------------------------------
# Mock EventBus (publish 可注入失败)
# ----------------------------------------------------------------------

class MockBus(EventBus):
    def __init__(self, *, fail_after: int | None = None) -> None:
        self.published: list[EventEnvelope] = []
        self._fail_after = fail_after

    async def publish(
        self, envelope: EventEnvelope, *, maxlen: int = 100_000
    ) -> str:
        if self._fail_after is not None and len(self.published) >= self._fail_after:
            raise RuntimeError("injected failure")
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
        ...

    async def replay(
        self,
        *,
        topic: str,
        after_event_id: Optional[str] = None,
        limit: int = 1000,
    ) -> AsyncIterator[EventEnvelope]:
        if False:  # pragma: no cover
            yield  # type: ignore[misc]

    async def ack(
        self, *, topic: str, consumer_group: str, event_id: str
    ) -> None: ...

    async def close(self) -> None: ...


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _make_pending(
    seq: int,
    *,
    tenant_id: UUID | None = None,
    aggregate_id: str = "a-1",
    event_type: str = "test.event",
) -> PendingEvent:
    return PendingEvent(
        event_id=str(uuid4()),
        sequence_num=seq,
        aggregate_id=aggregate_id,
        aggregate_type="test",
        event_type=event_type,
        tenant_id=tenant_id or uuid4(),
        occurred_at=datetime.now(timezone.utc),
        schema_version="1.0",
        payload_dict={"note": f"e-{seq}"},
        causation_id=None,
        correlation_id=None,
    )


SCHEMA_REGISTRY: dict[str, type[OntologyEvent]] = {
    "test.event": _Payload,
}


# ======================================================================
# §1 OutboxReader 抽象契约
# ======================================================================

class TestOutboxReaderContract:
    def test_outbox_reader_is_abstract(self) -> None:
        with pytest.raises(TypeError, match="abstract"):
            OutboxReader()  # type: ignore[abstract]


# ======================================================================
# §2 EventRelay.run_once() 正常路径
# ======================================================================

class TestEventRelayHappyPath:
    async def test_run_once_empty_reader_returns_zero(self) -> None:
        reader = FakeOutboxReader()
        bus = MockBus()
        relay = EventRelay(bus=bus, reader=reader, schema_registry=SCHEMA_REGISTRY)
        n = await relay.run_once()
        assert n == 0

    async def test_run_once_forwards_all_events(self) -> None:
        reader = FakeOutboxReader(events=[
            _make_pending(1), _make_pending(2), _make_pending(3),
        ])
        bus = MockBus()
        relay = EventRelay(bus=bus, reader=reader, schema_registry=SCHEMA_REGISTRY)
        n = await relay.run_once()
        assert n == 3
        assert len(bus.published) == 3

    async def test_run_once_updates_cursor_to_last_sequence(self) -> None:
        reader = FakeOutboxReader(events=[
            _make_pending(10), _make_pending(11), _make_pending(12),
        ])
        bus = MockBus()
        relay = EventRelay(
            bus=bus,
            reader=reader,
            schema_registry=SCHEMA_REGISTRY,
            relay_name="my-relay",
        )
        await relay.run_once()
        assert reader.cursors["my-relay"] == 12

    async def test_run_once_converts_pending_to_envelope_with_pydantic(
        self,
    ) -> None:
        reader = FakeOutboxReader(events=[_make_pending(5)])
        bus = MockBus()
        relay = EventRelay(bus=bus, reader=reader, schema_registry=SCHEMA_REGISTRY)
        await relay.run_once()
        published = bus.published[0]
        assert isinstance(published, EventEnvelope)
        assert isinstance(published.payload, _Payload)
        assert published.payload.note == "e-5"


# ======================================================================
# §3 边界: 部分批次失败 / batch 限制 / 幂等
# ======================================================================

class TestEventRelayEdgeCases:
    async def test_stops_on_publish_failure_preserves_partial_progress(
        self,
    ) -> None:
        """publish 第 2 条失败, 游标应停在第 1 条的 sequence."""
        reader = FakeOutboxReader(events=[
            _make_pending(1), _make_pending(2), _make_pending(3),
        ])
        bus = MockBus(fail_after=1)  # 第 0 条成功, 第 1 条失败
        relay = EventRelay(
            bus=bus,
            reader=reader,
            schema_registry=SCHEMA_REGISTRY,
            relay_name="my-relay",
        )
        n = await relay.run_once()
        assert n == 1
        assert reader.cursors["my-relay"] == 1  # 只推到第 1 条

    async def test_second_run_is_idempotent_when_no_new_events(self) -> None:
        reader = FakeOutboxReader(events=[_make_pending(1), _make_pending(2)])
        bus = MockBus()
        relay = EventRelay(bus=bus, reader=reader, schema_registry=SCHEMA_REGISTRY)
        first = await relay.run_once()
        second = await relay.run_once()
        assert first == 2
        assert second == 0  # 无新事件

    async def test_respects_batch_limit(self) -> None:
        reader = FakeOutboxReader(
            events=[_make_pending(i) for i in range(1, 11)]
        )
        bus = MockBus()
        relay = EventRelay(
            bus=bus,
            reader=reader,
            schema_registry=SCHEMA_REGISTRY,
            batch=3,
        )
        n = await relay.run_once()
        assert n == 3
        assert len(bus.published) == 3
        # 游标停在第 3 条
        assert reader.cursors[relay._name] == 3

        # 第二次 run 继续消费剩余
        n2 = await relay.run_once()
        assert n2 == 3
        assert len(bus.published) == 6

    async def test_unknown_event_type_skips_but_advances_cursor(
        self,
    ) -> None:
        """未注册 event_type 的事件应跳过 (标记 poisoned), 但游标仍前进避免卡死."""
        events = [
            _make_pending(1, event_type="test.event"),       # 合法
            _make_pending(2, event_type="totally.unknown"),  # 毒丸
            _make_pending(3, event_type="test.event"),       # 合法
        ]
        reader = FakeOutboxReader(events=events)
        bus = MockBus()
        relay = EventRelay(bus=bus, reader=reader, schema_registry=SCHEMA_REGISTRY)
        n = await relay.run_once()
        # 2 条成功发布 (第 1 和 3), 毒丸跳过
        assert len(bus.published) == 2
        # 但游标前进到 3 (全批次处理完)
        assert n == 3
        assert reader.cursors[relay._name] == 3


# ======================================================================
# §4 构造参数 / 默认值
# ======================================================================

class TestEventRelayConstruction:
    def test_default_relay_name(self) -> None:
        relay = EventRelay(
            bus=MockBus(), reader=FakeOutboxReader(),
            schema_registry=SCHEMA_REGISTRY,
        )
        assert relay._name == "ontology_relay_default"

    def test_default_batch_size(self) -> None:
        relay = EventRelay(
            bus=MockBus(), reader=FakeOutboxReader(),
            schema_registry=SCHEMA_REGISTRY,
        )
        assert relay._batch == 500
