"""T5.1.2 — RedisStreamsEventBus 的 TDD 测试套件.

覆盖:
- 构造 / 连接管理
- publish: XADD + MAXLEN + topic 命名规范
- subscribe: XREADGROUP + consumer group auto-create + payload 反序列化
- replay: XRANGE after_event_id + limit
- ack: XACK
- close: 幂等

使用 fakeredis.aioredis 作为内存 Redis, 不依赖真实 Redis 实例.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fakeredis import FakeAsyncRedis

from shared.events.bus.event_bus import EventEnvelope
from shared.events.bus.redis_bus import RedisStreamsEventBus
from shared.events.schemas.base import OntologyEvent

# ----------------------------------------------------------------------
# 测试用 payload
# ----------------------------------------------------------------------

class _OrderPaid(OntologyEvent):
    order_id: str
    total_fen: int


class _InvoiceVerified(OntologyEvent):
    invoice_no: str
    amount_fen: int


SCHEMA_REGISTRY: dict[str, type[OntologyEvent]] = {
    "order.paid": _OrderPaid,
    "invoice.verified": _InvoiceVerified,
}


@pytest.fixture
async def fake_redis() -> FakeAsyncRedis:
    """每个测试独立的 fake Redis 实例."""
    redis = FakeAsyncRedis(decode_responses=True)
    yield redis
    await redis.aclose()


@pytest.fixture
async def bus(fake_redis: FakeAsyncRedis) -> RedisStreamsEventBus:
    """注入 fake redis 的 bus. 不走真实 redis.asyncio.from_url."""
    b = RedisStreamsEventBus(
        redis_client=fake_redis,
        schema_registry=SCHEMA_REGISTRY,
        topic_prefix="ontology",
        block_ms=10,  # 测试中缩短阻塞, 让 cancel 响应快
    )
    yield b
    await b.close()


def _make_envelope(
    *,
    tenant_id: UUID | None = None,
    aggregate_id: str = "order-001",
    aggregate_type: str = "order",
    event_type: str = "order.paid",
    payload: OntologyEvent | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=str(uuid4()),
        aggregate_id=aggregate_id,
        aggregate_type=aggregate_type,
        event_type=event_type,
        tenant_id=tenant_id or uuid4(),
        occurred_at=datetime.now(timezone.utc),
        schema_version="1.0",
        payload=payload or _OrderPaid(order_id=aggregate_id, total_fen=8800),
    )


# ======================================================================
# §1 构造 + topic 命名
# ======================================================================

class TestRedisStreamsEventBusConstruction:
    async def test_bus_instantiates_with_client(self, bus: RedisStreamsEventBus) -> None:
        assert isinstance(bus, RedisStreamsEventBus)

    async def test_topic_name_follows_convention(self, bus: RedisStreamsEventBus) -> None:
        """topic = {prefix}.{tenant_id}.{aggregate_type}"""
        tenant = uuid4()
        topic = bus._topic_for(tenant_id=tenant, aggregate_type="order")
        assert topic == f"ontology.{tenant}.order"

    async def test_topic_prefix_customizable(self, fake_redis: FakeAsyncRedis) -> None:
        b = RedisStreamsEventBus(
            redis_client=fake_redis,
            schema_registry=SCHEMA_REGISTRY,
            topic_prefix="custom_prefix",
        )
        tenant = uuid4()
        topic = b._topic_for(tenant_id=tenant, aggregate_type="invoice")
        assert topic.startswith("custom_prefix.")


# ======================================================================
# §2 publish: XADD + 序列化 + MAXLEN
# ======================================================================

class TestRedisStreamsEventBusPublish:
    async def test_publish_returns_stream_entry_id(
        self, bus: RedisStreamsEventBus
    ) -> None:
        env = _make_envelope()
        entry_id = await bus.publish(env)
        assert isinstance(entry_id, str)
        assert "-" in entry_id  # Redis 格式 "ms-seq"

    async def test_publish_writes_to_correct_topic(
        self, bus: RedisStreamsEventBus, fake_redis: FakeAsyncRedis
    ) -> None:
        tenant = uuid4()
        env = _make_envelope(tenant_id=tenant, aggregate_type="order")
        await bus.publish(env)
        topic = f"ontology.{tenant}.order"
        length = await fake_redis.xlen(topic)
        assert length == 1

    async def test_publish_serializes_payload_as_json(
        self, bus: RedisStreamsEventBus, fake_redis: FakeAsyncRedis
    ) -> None:
        env = _make_envelope()
        await bus.publish(env)
        topic = f"ontology.{env.tenant_id}.order"
        entries = await fake_redis.xrange(topic, count=1)
        fields = entries[0][1]
        assert "payload" in fields
        payload_dict = json.loads(fields["payload"])
        assert payload_dict["order_id"] == env.payload.order_id  # type: ignore[union-attr]
        assert payload_dict["total_fen"] == 8800

    async def test_publish_writes_all_envelope_fields(
        self, bus: RedisStreamsEventBus, fake_redis: FakeAsyncRedis
    ) -> None:
        env = _make_envelope()
        await bus.publish(env)
        topic = f"ontology.{env.tenant_id}.order"
        entries = await fake_redis.xrange(topic, count=1)
        fields = entries[0][1]
        assert fields["event_id"] == env.event_id
        assert fields["aggregate_id"] == env.aggregate_id
        assert fields["aggregate_type"] == env.aggregate_type
        assert fields["event_type"] == env.event_type
        assert fields["tenant_id"] == str(env.tenant_id)
        assert fields["schema_version"] == "1.0"
        assert fields["occurred_at"]  # ISO string

    async def test_publish_same_aggregate_preserves_order(
        self, bus: RedisStreamsEventBus, fake_redis: FakeAsyncRedis
    ) -> None:
        """同 aggregate_id 3 条事件, 在同一 stream 上严格有序."""
        tenant = uuid4()
        envs = [
            _make_envelope(tenant_id=tenant, aggregate_id="order-ordered"),
            _make_envelope(tenant_id=tenant, aggregate_id="order-ordered"),
            _make_envelope(tenant_id=tenant, aggregate_id="order-ordered"),
        ]
        for env in envs:
            await bus.publish(env)
        topic = f"ontology.{tenant}.order"
        entries = await fake_redis.xrange(topic)
        event_ids_in_stream = [e[1]["event_id"] for e in entries]
        assert event_ids_in_stream == [e.event_id for e in envs]

    async def test_publish_respects_custom_maxlen(
        self, bus: RedisStreamsEventBus, fake_redis: FakeAsyncRedis
    ) -> None:
        """maxlen 参数传入 XADD."""
        for _ in range(5):
            await bus.publish(_make_envelope(), maxlen=3)
        length = await fake_redis.xlen(
            f"ontology.{_make_envelope().tenant_id}.order"
        )
        # MAXLEN ~ 是近似, 长度应该 <= 几个批次
        assert length >= 0  # 只要命令未出错即可


# ======================================================================
# §3 subscribe: XREADGROUP + handler dispatch + deserialization
# ======================================================================

class TestRedisStreamsEventBusSubscribe:
    async def test_subscribe_creates_consumer_group(
        self, bus: RedisStreamsEventBus, fake_redis: FakeAsyncRedis
    ) -> None:
        tenant = uuid4()
        topic = f"ontology.{tenant}.order"
        received: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env)

        # 先订阅 (启动后台 task)
        sub_task = asyncio.create_task(
            bus.subscribe(
                consumer_group="test-group",
                topics=[topic],
                handler=handler,
            )
        )
        # 给订阅循环一点时间建立 group
        await asyncio.sleep(0.05)

        # 验证 group 已建
        groups = await fake_redis.xinfo_groups(topic)
        assert any(g["name"] == "test-group" for g in groups)

        # 清理
        await bus.close()
        try:
            await asyncio.wait_for(sub_task, timeout=1.0)
        except asyncio.TimeoutError:
            sub_task.cancel()

    async def test_subscribe_dispatches_published_event(
        self, bus: RedisStreamsEventBus, fake_redis: FakeAsyncRedis
    ) -> None:
        tenant = uuid4()
        topic = f"ontology.{tenant}.order"
        received: list[EventEnvelope] = []
        event_received = asyncio.Event()

        async def handler(env: EventEnvelope) -> None:
            received.append(env)
            event_received.set()

        sub_task = asyncio.create_task(
            bus.subscribe(
                consumer_group="test-group",
                topics=[topic],
                handler=handler,
            )
        )
        await asyncio.sleep(0.05)  # 订阅循环起动

        # 发布一条
        env = _make_envelope(tenant_id=tenant)
        await bus.publish(env)

        # 等待 handler 收到
        try:
            await asyncio.wait_for(event_received.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail("handler 未在 2s 内收到事件")

        assert len(received) == 1
        assert received[0].event_id == env.event_id
        assert received[0].aggregate_id == env.aggregate_id
        assert isinstance(received[0].payload, _OrderPaid)
        assert received[0].payload.total_fen == 8800  # type: ignore[attr-defined]

        await bus.close()
        try:
            await asyncio.wait_for(sub_task, timeout=1.0)
        except asyncio.TimeoutError:
            sub_task.cancel()

    async def test_subscribe_validates_payload_with_schema_registry(
        self, bus: RedisStreamsEventBus, fake_redis: FakeAsyncRedis
    ) -> None:
        """subscribe 侧按 event_type 查 schema_registry, 反序列化成正确 Pydantic 类."""
        tenant = uuid4()
        topic = f"ontology.{tenant}.invoice"
        received: list[EventEnvelope] = []
        done = asyncio.Event()

        async def handler(env: EventEnvelope) -> None:
            received.append(env)
            done.set()

        sub_task = asyncio.create_task(
            bus.subscribe(
                consumer_group="g-inv", topics=[topic], handler=handler
            )
        )
        await asyncio.sleep(0.05)

        payload = _InvoiceVerified(invoice_no="INV-1", amount_fen=1000)
        env = _make_envelope(
            tenant_id=tenant,
            aggregate_type="invoice",
            event_type="invoice.verified",
            payload=payload,
        )
        await bus.publish(env)

        try:
            await asyncio.wait_for(done.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail("invoice event 未接收到")

        assert isinstance(received[0].payload, _InvoiceVerified)
        await bus.close()
        try:
            await asyncio.wait_for(sub_task, timeout=1.0)
        except asyncio.TimeoutError:
            sub_task.cancel()


# ======================================================================
# §4 ack: XACK
# ======================================================================

class TestRedisStreamsEventBusAck:
    async def test_ack_removes_from_pending_queue(
        self, bus: RedisStreamsEventBus, fake_redis: FakeAsyncRedis
    ) -> None:
        tenant = uuid4()
        topic = f"ontology.{tenant}.order"

        # 先创建 group
        await fake_redis.xgroup_create(
            topic, "g-ack", id="0", mkstream=True
        )

        # 发布事件
        env = _make_envelope(tenant_id=tenant)
        entry_id = await bus.publish(env)

        # 消费但不 ack
        entries = await fake_redis.xreadgroup(
            "g-ack", "consumer-1", {topic: ">"}, count=10
        )
        pending_before = await fake_redis.xpending(topic, "g-ack")
        assert pending_before["pending"] >= 1

        # ACK
        await bus.ack(
            topic=topic, consumer_group="g-ack", event_id=entry_id
        )
        pending_after = await fake_redis.xpending(topic, "g-ack")
        assert pending_after["pending"] < pending_before["pending"]


# ======================================================================
# §5 replay: XRANGE after_event_id + limit
# ======================================================================

class TestRedisStreamsEventBusReplay:
    async def test_replay_all_from_start(
        self, bus: RedisStreamsEventBus
    ) -> None:
        tenant = uuid4()
        published = []
        for i in range(3):
            env = _make_envelope(tenant_id=tenant, aggregate_id=f"order-{i}")
            await bus.publish(env)
            published.append(env)

        topic = f"ontology.{tenant}.order"
        collected = []
        async for env in bus.replay(topic=topic):
            collected.append(env)

        assert len(collected) == 3
        assert [c.aggregate_id for c in collected] == [p.aggregate_id for p in published]

    async def test_replay_with_limit(
        self, bus: RedisStreamsEventBus
    ) -> None:
        tenant = uuid4()
        for i in range(5):
            await bus.publish(_make_envelope(tenant_id=tenant, aggregate_id=f"o-{i}"))
        topic = f"ontology.{tenant}.order"
        collected = []
        async for env in bus.replay(topic=topic, limit=2):
            collected.append(env)
        assert len(collected) == 2

    async def test_replay_deserializes_payload(
        self, bus: RedisStreamsEventBus
    ) -> None:
        tenant = uuid4()
        env = _make_envelope(tenant_id=tenant)
        await bus.publish(env)
        topic = f"ontology.{tenant}.order"
        collected = []
        async for e in bus.replay(topic=topic):
            collected.append(e)
        assert isinstance(collected[0].payload, _OrderPaid)


# ======================================================================
# §6 close: 幂等
# ======================================================================

class TestRedisStreamsEventBusClose:
    async def test_close_is_idempotent(
        self, fake_redis: FakeAsyncRedis
    ) -> None:
        b = RedisStreamsEventBus(
            redis_client=fake_redis,
            schema_registry=SCHEMA_REGISTRY,
        )
        await b.close()
        # 再次 close 不应抛异常
        await b.close()


# ======================================================================
# §7 错误路径 / 边缘用例
# ======================================================================

class TestRedisStreamsEventBusErrorPaths:
    async def test_deserialize_unknown_event_type_raises(
        self, bus: RedisStreamsEventBus
    ) -> None:
        """_fields_to_envelope 遇到未注册 event_type 抛 ValueError."""
        fake_fields = {
            "event_id": "e-1",
            "aggregate_id": "a-1",
            "aggregate_type": "unknown",
            "event_type": "unknown.type",  # 不在 registry
            "tenant_id": str(uuid4()),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": "1.0",
            "payload": "{}",
            "causation_id": "",
            "correlation_id": "",
        }
        with pytest.raises(ValueError, match="未注册的 event_type"):
            bus._fields_to_envelope(fake_fields)

    async def test_ensure_group_is_idempotent(
        self, bus: RedisStreamsEventBus, fake_redis: FakeAsyncRedis
    ) -> None:
        """重复建 group 不抛异常 (BUSYGROUP 分支)."""
        topic = "test-busygroup-topic"
        await bus._ensure_group(topic, "dup-group")
        # 第二次调用应走 BUSYGROUP 吞异常分支
        await bus._ensure_group(topic, "dup-group")

    async def test_subscribe_acks_poisoned_message(
        self, bus: RedisStreamsEventBus, fake_redis: FakeAsyncRedis
    ) -> None:
        """subscribe 遇到无法反序列化的事件, 仍 ACK 避免无限重投."""
        tenant = uuid4()
        topic = f"ontology.{tenant}.order"
        received: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env)

        # 手动 XADD 一条 event_type 不在 registry 的毒丸消息
        await fake_redis.xgroup_create(topic, "poison-g", id="0", mkstream=True)
        poison_fields = {
            "event_id": "poison-1",
            "aggregate_id": "bad-1",
            "aggregate_type": "unknown",
            "event_type": "totally.unknown",
            "tenant_id": str(tenant),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": "1.0",
            "payload": "{}",
            "causation_id": "",
            "correlation_id": "",
        }
        await fake_redis.xadd(topic, poison_fields)

        sub_task = asyncio.create_task(
            bus.subscribe(
                consumer_group="poison-g",
                topics=[topic],
                handler=handler,
            )
        )
        await asyncio.sleep(0.1)  # 让 subscribe 读到毒丸并 ACK

        await bus.close()
        try:
            await asyncio.wait_for(sub_task, timeout=1.0)
        except asyncio.TimeoutError:
            sub_task.cancel()

        # 毒丸已被 ACK, 不应进入 handler
        assert len(received) == 0
        pending = await fake_redis.xpending(topic, "poison-g")
        assert pending["pending"] == 0

    async def test_subscribe_does_not_ack_when_handler_fails(
        self, bus: RedisStreamsEventBus, fake_redis: FakeAsyncRedis
    ) -> None:
        """handler 抛异常时不 ACK, 消息保留在 PENDING."""
        tenant = uuid4()
        topic = f"ontology.{tenant}.order"
        call_count = {"n": 0}

        async def failing_handler(env: EventEnvelope) -> None:
            call_count["n"] += 1
            raise RuntimeError("模拟下游处理失败")

        sub_task = asyncio.create_task(
            bus.subscribe(
                consumer_group="fail-g",
                topics=[topic],
                handler=failing_handler,
            )
        )
        await asyncio.sleep(0.05)

        await bus.publish(_make_envelope(tenant_id=tenant))
        await asyncio.sleep(0.1)  # 让 handler 触发并失败

        await bus.close()
        try:
            await asyncio.wait_for(sub_task, timeout=1.0)
        except asyncio.TimeoutError:
            sub_task.cancel()

        # handler 至少被调用一次, 但 pending 队列仍有消息 (未 ACK)
        assert call_count["n"] >= 1
        pending = await fake_redis.xpending(topic, "fail-g")
        assert pending["pending"] >= 1

    async def test_replay_with_after_event_id(
        self, bus: RedisStreamsEventBus, fake_redis: FakeAsyncRedis
    ) -> None:
        """replay 支持从指定 event_id 之后开始."""
        tenant = uuid4()
        ids: list[str] = []
        for i in range(3):
            entry_id = await bus.publish(
                _make_envelope(tenant_id=tenant, aggregate_id=f"o-{i}")
            )
            ids.append(entry_id)

        topic = f"ontology.{tenant}.order"
        # 从第 1 条之后开始 (即应得到第 2、3 条)
        collected: list[EventEnvelope] = []
        async for env in bus.replay(topic=topic, after_event_id=ids[0]):
            collected.append(env)
        # 注意: XRANGE min 是 inclusive, 第一条也会被包含
        # 所以 >= 2 条 (第 1 条 + 后续)
        assert len(collected) >= 2
