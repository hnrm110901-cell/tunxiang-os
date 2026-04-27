"""统一事件总线框架测试 -- 全部 Mock 模式，不依赖 Redis / PG"""

from __future__ import annotations

import json

import pytest

from shared.events.src.consumer import EventConsumer
from shared.events.src.event_base import TxEvent
from shared.events.src.event_types import (
    AgentEventType,
    InventoryEventType,
    KdsEventType,
    MemberEventType,
    OrderEventType,
    PaymentEventType,
    resolve_stream_key,
)
from shared.events.src.middleware import (
    DeduplicationMiddleware,
    LoggingMiddleware,
    TenantIsolationMiddleware,
    apply_middleware,
)
from shared.events.src.pg_notify import PgListener, PgNotifier
from shared.events.src.publisher import EventPublisher

# ------------------------------------------------------------------
# TxEvent 序列化 / 反序列化
# ------------------------------------------------------------------


class TestTxEvent:
    def test_create_event(self) -> None:
        event = TxEvent(
            event_type="order.created",
            tenant_id="t-001",
            payload={"total_fen": 8800},
            source="tx-trade",
            store_id="s-001",
        )
        assert event.event_type == "order.created"
        assert event.tenant_id == "t-001"
        assert event.store_id == "s-001"
        assert event.version == "1.0"
        assert event.event_id  # 非空

    def test_stream_roundtrip(self) -> None:
        original = TxEvent(
            event_type="inventory.low_stock",
            tenant_id="t-002",
            payload={"ingredient_id": "i-99", "current_qty": 5},
            source="tx-supply",
        )
        fields = original.to_stream_fields()
        assert isinstance(fields, dict)
        assert all(isinstance(v, str) for v in fields.values())

        restored = TxEvent.from_stream_fields(fields)
        assert restored.event_type == original.event_type
        assert restored.tenant_id == original.tenant_id
        assert restored.payload == original.payload
        assert restored.event_id == original.event_id

    def test_json_roundtrip(self) -> None:
        original = TxEvent(
            event_type="kds.order_ready",
            tenant_id="t-003",
            payload={"order_id": "o-123"},
            source="tx-trade",
            store_id="s-003",
        )
        json_str = original.to_json()
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["event_type"] == "kds.order_ready"

        restored = TxEvent.from_json(json_str)
        assert restored.event_type == original.event_type
        assert restored.event_id == original.event_id

    def test_from_stream_fields_missing_key_raises(self) -> None:
        with pytest.raises(KeyError):
            TxEvent.from_stream_fields({"tenant_id": "t-1"})  # missing event_type


# ------------------------------------------------------------------
# 事件类型注册
# ------------------------------------------------------------------


class TestEventTypes:
    def test_order_event_values(self) -> None:
        assert OrderEventType.CREATED.value == "order.created"
        assert OrderEventType.PAID.value == "order.paid"
        assert OrderEventType.CANCELLED.value == "order.cancelled"
        assert OrderEventType.REFUNDED.value == "order.refunded"

    def test_all_domains_have_stream_keys(self) -> None:
        all_types = [
            OrderEventType.CREATED,
            InventoryEventType.LOW_STOCK,
            MemberEventType.REGISTERED,
            KdsEventType.ORDER_READY,
            PaymentEventType.CONFIRMED,
            AgentEventType.DECISION,
        ]
        for et in all_types:
            key = resolve_stream_key(et.value)
            assert key != "tx_unknown_events", f"No stream key for {et.value}"

    def test_unknown_domain_returns_fallback(self) -> None:
        assert resolve_stream_key("unicorn.appeared") == "tx_unknown_events"


# ------------------------------------------------------------------
# EventPublisher (Mock)
# ------------------------------------------------------------------


class TestEventPublisher:
    @pytest.mark.asyncio
    async def test_mock_publish(self) -> None:
        pub = EventPublisher(mock=True)
        event = TxEvent(
            event_type="order.created",
            tenant_id="t-1",
            payload={"total": 100},
            source="test",
        )
        entry_id = await pub.publish(event)
        assert entry_id is not None
        assert entry_id.startswith("mock-")

    @pytest.mark.asyncio
    async def test_mock_batch_publish(self) -> None:
        pub = EventPublisher(mock=True)
        events = [
            TxEvent(
                event_type="order.created",
                tenant_id="t-1",
                payload={"i": i},
                source="test",
            )
            for i in range(5)
        ]
        results = await pub.publish_batch(events)
        assert len(results) == 5
        assert all(r is not None for r in results)

    @pytest.mark.asyncio
    async def test_mock_get_events(self) -> None:
        pub = EventPublisher(mock=True)
        event = TxEvent(
            event_type="order.created",
            tenant_id="t-1",
            payload={},
            source="test",
        )
        await pub.publish(event)

        all_events = pub.get_mock_events()
        assert len(all_events) == 1
        assert all_events[0].event_type == "order.created"

        stream_events = pub.get_mock_events("tx_order_events")
        assert len(stream_events) == 1

    @pytest.mark.asyncio
    async def test_mock_clear(self) -> None:
        pub = EventPublisher(mock=True)
        await pub.publish(TxEvent(event_type="order.paid", tenant_id="t-1", payload={}, source="test"))
        pub.clear_mock()
        assert pub.get_mock_events() == []


# ------------------------------------------------------------------
# EventConsumer (Mock)
# ------------------------------------------------------------------


class TestEventConsumer:
    @pytest.mark.asyncio
    async def test_mock_drain(self) -> None:
        pub = EventPublisher(mock=True)
        consumer = EventConsumer("test_group", "test_consumer", mock=True)

        received: list[TxEvent] = []

        async def handler(event: TxEvent) -> None:
            received.append(event)

        consumer.subscribe("order.created", handler)

        # 发布事件
        await pub.publish(TxEvent(event_type="order.created", tenant_id="t-1", payload={"x": 1}, source="test"))
        await pub.publish(TxEvent(event_type="order.created", tenant_id="t-1", payload={"x": 2}, source="test"))

        # 消费
        count = await consumer.drain_mock(pub)
        assert count == 2
        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_subscribe_multiple_handlers(self) -> None:
        pub = EventPublisher(mock=True)
        consumer = EventConsumer("g", "c", mock=True)

        results_a: list[str] = []
        results_b: list[str] = []

        async def handler_a(event: TxEvent) -> None:
            results_a.append(event.event_id)

        async def handler_b(event: TxEvent) -> None:
            results_b.append(event.event_id)

        consumer.subscribe("order.created", handler_a)
        consumer.subscribe("order.created", handler_b)

        await pub.publish(TxEvent(event_type="order.created", tenant_id="t-1", payload={}, source="test"))
        await consumer.drain_mock(pub)

        assert len(results_a) == 1
        assert len(results_b) == 1

    @pytest.mark.asyncio
    async def test_unmatched_events_ignored(self) -> None:
        pub = EventPublisher(mock=True)
        consumer = EventConsumer("g", "c", mock=True)

        received: list[TxEvent] = []

        async def handler(event: TxEvent) -> None:
            received.append(event)

        consumer.subscribe("order.created", handler)

        # 发布一个不匹配的事件类型（但在同一个 stream）
        await pub.publish(TxEvent(event_type="order.paid", tenant_id="t-1", payload={}, source="test"))
        await consumer.drain_mock(pub)
        # order.paid 在同一个 stream，但 handler 只注册了 order.created
        # drain_mock 逐条检查 event_type，所以不应触发
        assert len(received) == 0


# ------------------------------------------------------------------
# PG NOTIFY (Mock)
# ------------------------------------------------------------------


class TestPgNotifier:
    @pytest.mark.asyncio
    async def test_mock_notify(self) -> None:
        notifier = PgNotifier(mock=True)
        event = TxEvent(
            event_type="kds.order_ready",
            tenant_id="t-1",
            payload={"order_id": "o-1"},
            source="tx-trade",
        )
        await notifier.notify("kds_ready", event)

        records = notifier.get_mock_notifications()
        assert len(records) == 1
        assert records[0][0] == "kds_ready"
        parsed = json.loads(records[0][1])
        assert parsed["event_type"] == "kds.order_ready"

    @pytest.mark.asyncio
    async def test_mock_clear(self) -> None:
        notifier = PgNotifier(mock=True)
        event = TxEvent(
            event_type="kds.order_ready",
            tenant_id="t-1",
            payload={},
            source="test",
        )
        await notifier.notify("ch", event)
        notifier.clear_mock()
        assert notifier.get_mock_notifications() == []


class TestPgListener:
    @pytest.mark.asyncio
    async def test_mock_inject(self) -> None:
        listener = PgListener(mock=True)
        received: list[tuple[str, TxEvent]] = []

        async def handler(channel: str, event: TxEvent) -> None:
            received.append((channel, event))

        listener.listen("table_status", handler)

        event = TxEvent(
            event_type="order.created",
            tenant_id="t-1",
            payload={"table_id": "tb-5"},
            source="tx-trade",
        )
        await listener.inject_mock("table_status", event)

        assert len(received) == 1
        assert received[0][0] == "table_status"
        assert received[0][1].event_type == "order.created"

    @pytest.mark.asyncio
    async def test_inject_mock_raises_outside_mock(self) -> None:
        listener = PgListener(mock=False)
        event = TxEvent(event_type="x.y", tenant_id="t", payload={}, source="s")
        with pytest.raises(RuntimeError, match="mock mode"):
            await listener.inject_mock("ch", event)


# ------------------------------------------------------------------
# Middleware
# ------------------------------------------------------------------


class TestLoggingMiddleware:
    @pytest.mark.asyncio
    async def test_logs_on_success(self) -> None:
        called = False

        async def handler(event: TxEvent) -> None:
            nonlocal called
            called = True

        mw = LoggingMiddleware()
        wrapped = mw.wrap(handler)

        event = TxEvent(
            event_type="order.created",
            tenant_id="t-1",
            payload={},
            source="test",
        )
        await wrapped(event)
        assert called

    @pytest.mark.asyncio
    async def test_reraises_on_failure(self) -> None:
        async def handler(event: TxEvent) -> None:
            raise ValueError("boom")

        mw = LoggingMiddleware()
        wrapped = mw.wrap(handler)

        event = TxEvent(
            event_type="order.created",
            tenant_id="t-1",
            payload={},
            source="test",
        )
        with pytest.raises(ValueError, match="boom"):
            await wrapped(event)


class TestTenantIsolationMiddleware:
    @pytest.mark.asyncio
    async def test_allows_matching_tenant(self) -> None:
        called = False

        async def handler(event: TxEvent) -> None:
            nonlocal called
            called = True

        mw = TenantIsolationMiddleware("t-1")
        wrapped = mw.wrap(handler)

        event = TxEvent(
            event_type="order.created",
            tenant_id="t-1",
            payload={},
            source="test",
        )
        await wrapped(event)
        assert called

    @pytest.mark.asyncio
    async def test_blocks_different_tenant(self) -> None:
        called = False

        async def handler(event: TxEvent) -> None:
            nonlocal called
            called = True

        mw = TenantIsolationMiddleware("t-1")
        wrapped = mw.wrap(handler)

        event = TxEvent(
            event_type="order.created",
            tenant_id="t-OTHER",
            payload={},
            source="test",
        )
        await wrapped(event)
        assert not called

    @pytest.mark.asyncio
    async def test_none_allows_all(self) -> None:
        called = False

        async def handler(event: TxEvent) -> None:
            nonlocal called
            called = True

        mw = TenantIsolationMiddleware(None)
        wrapped = mw.wrap(handler)

        event = TxEvent(
            event_type="order.created",
            tenant_id="any-tenant",
            payload={},
            source="test",
        )
        await wrapped(event)
        assert called


class TestDeduplicationMiddleware:
    @pytest.mark.asyncio
    async def test_dedup_blocks_duplicate(self) -> None:
        call_count = 0

        async def handler(event: TxEvent) -> None:
            nonlocal call_count
            call_count += 1

        mw = DeduplicationMiddleware(max_size=100)
        wrapped = mw.wrap(handler)

        event = TxEvent(
            event_type="order.created",
            tenant_id="t-1",
            payload={},
            source="test",
        )
        await wrapped(event)
        await wrapped(event)  # 同一个 event_id，应被去重
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_different_events_pass(self) -> None:
        call_count = 0

        async def handler(event: TxEvent) -> None:
            nonlocal call_count
            call_count += 1

        mw = DeduplicationMiddleware(max_size=100)
        wrapped = mw.wrap(handler)

        e1 = TxEvent(event_type="order.created", tenant_id="t-1", payload={}, source="test")
        e2 = TxEvent(event_type="order.created", tenant_id="t-1", payload={}, source="test")
        await wrapped(e1)
        await wrapped(e2)  # 不同 event_id
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_lru_eviction(self) -> None:
        call_count = 0

        async def handler(event: TxEvent) -> None:
            nonlocal call_count
            call_count += 1

        mw = DeduplicationMiddleware(max_size=2)
        wrapped = mw.wrap(handler)

        events = [TxEvent(event_type="order.created", tenant_id="t-1", payload={}, source="test") for _ in range(3)]
        for e in events:
            await wrapped(e)
        assert call_count == 3  # 全部不同 event_id

        # 再次发送第一个事件 -- 因为 LRU max_size=2，第一个已被淘汰
        await wrapped(events[0])
        assert call_count == 4


class TestApplyMiddleware:
    @pytest.mark.asyncio
    async def test_compose_middlewares(self) -> None:
        call_count = 0

        async def handler(event: TxEvent) -> None:
            nonlocal call_count
            call_count += 1

        wrapped = apply_middleware(
            handler,
            [
                LoggingMiddleware(),
                TenantIsolationMiddleware("t-1"),
                DeduplicationMiddleware(),
            ],
        )

        event = TxEvent(
            event_type="order.created",
            tenant_id="t-1",
            payload={},
            source="test",
        )
        await wrapped(event)
        assert call_count == 1

        # 重复事件被去重
        await wrapped(event)
        assert call_count == 1

        # 不同租户被过滤
        other = TxEvent(
            event_type="order.created",
            tenant_id="t-OTHER",
            payload={},
            source="test",
        )
        await wrapped(other)
        assert call_count == 1
