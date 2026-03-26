"""Event Bus 测试 — 发布/处理/链路追踪/事件流"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio

import pytest

from agents.event_bus import (
    DEFAULT_EVENT_HANDLERS,
    AgentEvent,
    EventBus,
    create_default_event_bus,
)


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def sample_event():
    return AgentEvent(
        event_type="inventory_surplus",
        source_agent="inventory_alert",
        store_id="store_001",
        data={"item": "鱼头", "surplus_kg": 15},
    )


class TestEventPublish:
    """事件发布"""

    @pytest.mark.asyncio
    async def test_publish_stores_event(self, bus, sample_event):
        """发布事件后可在流中查到"""
        await bus.publish(sample_event)
        stream = bus.get_stream("inventory_surplus")
        assert len(stream) == 1
        assert stream[0].event_id == sample_event.event_id

    @pytest.mark.asyncio
    async def test_publish_triggers_handlers(self, bus, sample_event):
        """发布事件触发所有处理器"""
        called = []

        def handler_a(event: AgentEvent) -> dict:
            called.append("a")
            return {"action": "a"}

        def handler_b(event: AgentEvent) -> dict:
            called.append("b")
            return {"action": "b"}

        bus.register_handler("inventory_surplus", "agent_a", handler_a)
        bus.register_handler("inventory_surplus", "agent_b", handler_b)

        results = await bus.publish(sample_event)
        assert len(results) == 2
        assert all(r["success"] for r in results)
        assert set(called) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_publish_no_handlers(self, bus, sample_event):
        """没有处理器时事件仍存入流"""
        results = await bus.publish(sample_event)
        assert results == []
        assert len(bus.get_stream("inventory_surplus")) == 1


class TestHandlerErrors:
    """处理器异常处理"""

    @pytest.mark.asyncio
    async def test_handler_error_captured(self, bus, sample_event):
        """处理器抛异常不影响其他处理器"""
        def bad_handler(event: AgentEvent) -> dict:
            raise ValueError("模拟错误")

        def good_handler(event: AgentEvent) -> dict:
            return {"ok": True}

        bus.register_handler("inventory_surplus", "bad", bad_handler)
        bus.register_handler("inventory_surplus", "good", good_handler)

        results = await bus.publish(sample_event)
        assert len(results) == 2
        assert results[0]["success"] is False
        assert "模拟错误" in results[0]["error"]
        assert results[1]["success"] is True


class TestAsyncHandler:
    """异步处理器"""

    @pytest.mark.asyncio
    async def test_async_handler(self, bus, sample_event):
        """支持 async handler"""
        async def async_handler(event: AgentEvent) -> dict:
            return {"async": True, "event_type": event.event_type}

        bus.register_handler("inventory_surplus", "async_agent", async_handler)
        results = await bus.publish(sample_event)
        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["result"]["async"] is True


class TestEventChain:
    """事件链路追踪"""

    @pytest.mark.asyncio
    async def test_chain_by_correlation_id(self, bus):
        """同一 correlation_id 的事件可以追踪"""
        corr_id = "chain-001"
        e1 = AgentEvent(
            event_type="inventory_surplus",
            source_agent="inventory_alert",
            store_id="S1",
            correlation_id=corr_id,
        )
        e2 = AgentEvent(
            event_type="daily_plan_generated",
            source_agent="smart_menu",
            store_id="S1",
            correlation_id=corr_id,
        )
        e3 = AgentEvent(
            event_type="order_completed",
            source_agent="other",
            store_id="S1",
            correlation_id="other-chain",
        )

        await bus.publish(e1)
        await bus.publish(e2)
        await bus.publish(e3)

        chain = await bus.get_event_chain(corr_id)
        assert len(chain) == 2
        assert chain[0].event_type == "inventory_surplus"
        assert chain[1].event_type == "daily_plan_generated"

    @pytest.mark.asyncio
    async def test_chain_empty(self, bus):
        """不存在的 correlation_id 返回空"""
        chain = await bus.get_event_chain("nonexistent")
        assert chain == []


class TestGetStream:
    """事件流查询"""

    @pytest.mark.asyncio
    async def test_stream_limit(self, bus):
        """limit 参数限制返回条数"""
        for i in range(10):
            event = AgentEvent(
                event_type="order_completed",
                source_agent="trade",
                store_id="S1",
                data={"order_idx": i},
            )
            await bus.publish(event)

        stream = bus.get_stream("order_completed", limit=3)
        assert len(stream) == 3
        # 最新的在前
        assert stream[0].data["order_idx"] == 9

    @pytest.mark.asyncio
    async def test_stream_empty_type(self, bus):
        """未发布过的事件类型返回空列表"""
        stream = bus.get_stream("nonexistent_type")
        assert stream == []

    @pytest.mark.asyncio
    async def test_stream_max_capacity(self):
        """事件流自动截断到 max_per_stream"""
        small_bus = EventBus(max_per_stream=5)
        for i in range(10):
            event = AgentEvent(
                event_type="test",
                source_agent="a",
                store_id="S1",
                data={"idx": i},
            )
            await small_bus.publish(event)
        stream = small_bus.get_stream("test", limit=100)
        assert len(stream) == 5
        # 保留的是最后 5 条
        assert stream[0].data["idx"] == 9


class TestDefaultEventBus:
    """预注册处理器"""

    def test_default_handlers_registered(self):
        """create_default_event_bus 注册了所有默认处理器"""
        bus = create_default_event_bus()
        for event_type, handlers in DEFAULT_EVENT_HANDLERS.items():
            assert bus.get_handler_count(event_type) == len(handlers)

    @pytest.mark.asyncio
    async def test_default_bus_publish(self):
        """默认 bus 发布事件后处理器正常执行"""
        bus = create_default_event_bus()
        event = AgentEvent(
            event_type="vip_arrival",
            source_agent="member_insight",
            store_id="S1",
            data={"customer_id": "VIP001"},
        )
        results = await bus.publish(event)
        assert len(results) == 2
        assert all(r["success"] for r in results)
        assert results[0]["result"]["processed"] is True

    def test_default_event_handler_count(self):
        """默认处理器总数 = 配置中所有 handler 之和"""
        total = sum(len(v) for v in DEFAULT_EVENT_HANDLERS.values())
        assert total == 13  # 按当前配置

    def test_clear(self):
        """clear 清空所有数据"""
        bus = create_default_event_bus()
        bus.clear()
        assert bus.get_all_event_types() == []
