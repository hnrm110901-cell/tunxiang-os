"""UniversalPublisher 测试套件

覆盖：
  - _resolve_stream_key()：域路由正确性
  - publish()：正常路由到对应 Stream、Redis 故障降级、unknown domain 返回 None
  - Redis 连接单例管理

运行：
  pytest shared/events/tests/test_universal_publisher.py -v
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from supply_events import SupplyEventType
from trade_events import TradeEventType
from universal_publisher import STREAM_KEYS, UniversalPublisher

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_redis_singleton():
    """每个测试前重置 Redis 单例，避免状态污染"""
    UniversalPublisher._redis = None
    yield
    UniversalPublisher._redis = None


# ─────────────────────────────────────────────────────────────────────────────
# 1. _resolve_stream_key()
# ─────────────────────────────────────────────────────────────────────────────


class TestResolveStreamKey:
    """_resolve_stream_key() 域路由"""

    def test_trade_event_resolves_to_trade_events_stream(self):
        key = UniversalPublisher._resolve_stream_key("trade.order.paid")
        assert key == "trade_events"

    def test_supply_event_resolves_to_supply_events_stream(self):
        key = UniversalPublisher._resolve_stream_key("supply.stock.zero")
        assert key == "supply_events"

    def test_finance_event_resolves_to_finance_events_stream(self):
        key = UniversalPublisher._resolve_stream_key("finance.settlement.done")
        assert key == "finance_events"

    def test_org_event_resolves_to_org_events_stream(self):
        key = UniversalPublisher._resolve_stream_key("org.employee.created")
        assert key == "org_events"

    def test_menu_event_resolves_to_menu_events_stream(self):
        key = UniversalPublisher._resolve_stream_key("menu.dish.updated")
        assert key == "menu_events"

    def test_ops_event_resolves_to_ops_events_stream(self):
        key = UniversalPublisher._resolve_stream_key("ops.store.opened")
        assert key == "ops_events"

    def test_unknown_domain_returns_none(self):
        key = UniversalPublisher._resolve_stream_key("unknown.some.event")
        assert key is None

    def test_empty_string_returns_none(self):
        key = UniversalPublisher._resolve_stream_key("")
        assert key is None

    def test_stream_keys_covers_all_domains(self):
        """STREAM_KEYS 中所有域都能正确解析"""
        for domain, expected_key in STREAM_KEYS.items():
            key = UniversalPublisher._resolve_stream_key(f"{domain}.some.action")
            assert key == expected_key, f"domain={domain} 路由到 {key}，期望 {expected_key}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. publish() — 正常路径
# ─────────────────────────────────────────────────────────────────────────────


class TestPublishNormalPath:
    """publish() 正常发布路径"""

    @pytest.mark.asyncio
    async def test_trade_event_routes_to_trade_stream(self):
        """交易事件应调用 xadd('trade_events', ...)"""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1234-0")

        with patch.object(UniversalPublisher, "get_redis", return_value=mock_redis):
            result = await UniversalPublisher.publish(
                event_type=TradeEventType.ORDER_PAID,
                tenant_id=uuid4(),
                store_id=uuid4(),
                entity_id=uuid4(),
                event_data={"total_fen": 10000},
                source_service="tx-trade",
            )

        assert result == "1234-0"
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "trade_events"

    @pytest.mark.asyncio
    async def test_supply_event_routes_to_supply_stream(self):
        """供应链事件应调用 xadd('supply_events', ...)"""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="5678-0")

        with patch.object(UniversalPublisher, "get_redis", return_value=mock_redis):
            result = await UniversalPublisher.publish(
                event_type=SupplyEventType.STOCK_ZERO,
                tenant_id=uuid4(),
                store_id=uuid4(),
                entity_id=uuid4(),
                event_data={"ingredient_id": "abc", "current_qty": 0},
                source_service="tx-supply",
            )

        assert result == "5678-0"
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "supply_events"

    @pytest.mark.asyncio
    async def test_publish_returns_entry_id_string(self):
        """成功发布应返回 Redis Stream entry_id 字符串"""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1699000000000-0")

        with patch.object(UniversalPublisher, "get_redis", return_value=mock_redis):
            result = await UniversalPublisher.publish(
                event_type=TradeEventType.ORDER_CREATED,
                tenant_id=uuid4(),
                store_id=uuid4(),
                entity_id=uuid4(),
                event_data={},
                source_service="tx-trade",
            )

        assert result == "1699000000000-0"

    @pytest.mark.asyncio
    async def test_publish_passes_correct_fields_to_xadd(self):
        """xadd 调用应包含 event_type/tenant_id/source_service 等字段"""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="abc-0")
        tenant_id = uuid4()

        with patch.object(UniversalPublisher, "get_redis", return_value=mock_redis):
            await UniversalPublisher.publish(
                event_type=TradeEventType.ORDER_PAID,
                tenant_id=tenant_id,
                store_id=uuid4(),
                entity_id=uuid4(),
                event_data={"total_fen": 8800},
                source_service="tx-trade",
            )

        call_args = mock_redis.xadd.call_args
        fields: dict = call_args[0][1]
        assert fields["event_type"] == TradeEventType.ORDER_PAID.value
        assert fields["tenant_id"] == str(tenant_id)
        assert fields["source_service"] == "tx-trade"
        assert "event_id" in fields
        assert "occurred_at" in fields
        assert "event_data" in fields

    @pytest.mark.asyncio
    async def test_publish_with_extra_fields(self):
        """extra_fields 中的键值应被写入 xadd fields"""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="xyz-0")

        with patch.object(UniversalPublisher, "get_redis", return_value=mock_redis):
            await UniversalPublisher.publish(
                event_type=TradeEventType.ORDER_PAID,
                tenant_id=uuid4(),
                store_id=uuid4(),
                entity_id=uuid4(),
                event_data={},
                source_service="tx-trade",
                extra_fields={"table_no": "A3"},
            )

        call_args = mock_redis.xadd.call_args
        fields: dict = call_args[0][1]
        assert fields.get("table_no") == "A3"

    @pytest.mark.asyncio
    async def test_publish_store_id_none_uses_empty_string(self):
        """store_id=None 时 xadd fields 中 store_id 应为空字符串"""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="abc-0")

        with patch.object(UniversalPublisher, "get_redis", return_value=mock_redis):
            await UniversalPublisher.publish(
                event_type=TradeEventType.ORDER_PAID,
                tenant_id=uuid4(),
                store_id=None,
                entity_id=None,
                event_data={},
                source_service="tx-trade",
            )

        call_args = mock_redis.xadd.call_args
        fields: dict = call_args[0][1]
        assert fields["store_id"] == ""
        assert fields["entity_id"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# 3. publish() — 未知域
# ─────────────────────────────────────────────────────────────────────────────


class TestPublishUnknownDomain:
    """未知域事件处理"""

    @pytest.mark.asyncio
    async def test_unknown_domain_returns_none(self):
        """无法路由到 Stream 时返回 None，不抛异常"""

        class UnknownEventType:
            value = "unknown.some.action"

        result = await UniversalPublisher.publish(
            event_type=UnknownEventType(),
            tenant_id=uuid4(),
            store_id=uuid4(),
            entity_id=uuid4(),
            event_data={},
            source_service="tx-unknown",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_domain_does_not_call_xadd(self):
        """未知域不应调用 Redis xadd"""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="abc-0")

        class UnknownEventType:
            value = "xyz.foo.bar"

        with patch.object(UniversalPublisher, "get_redis", return_value=mock_redis):
            await UniversalPublisher.publish(
                event_type=UnknownEventType(),
                tenant_id=uuid4(),
                store_id=uuid4(),
                entity_id=uuid4(),
                event_data={},
                source_service="tx-test",
            )

        mock_redis.xadd.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 4. publish() — Redis 故障降级
# ─────────────────────────────────────────────────────────────────────────────


class TestPublishRedisFault:
    """Redis 故障降级行为"""

    @pytest.mark.asyncio
    async def test_os_error_returns_none_not_raises(self):
        """Redis OSError（连接失败）时返回 None，不抛异常"""
        with patch.object(UniversalPublisher, "get_redis", side_effect=OSError("connection refused")):
            result = await UniversalPublisher.publish(
                event_type=TradeEventType.ORDER_PAID,
                tenant_id=uuid4(),
                store_id=uuid4(),
                entity_id=uuid4(),
                event_data={},
                source_service="tx-trade",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_os_error_resets_redis_singleton(self):
        """OSError 后 _redis 单例应被重置为 None，触发下次重连"""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(side_effect=OSError("write failed"))

        # 先注入一个已有的 redis 实例
        UniversalPublisher._redis = mock_redis

        with patch.object(UniversalPublisher, "get_redis", return_value=mock_redis):
            await UniversalPublisher.publish(
                event_type=TradeEventType.ORDER_PAID,
                tenant_id=uuid4(),
                store_id=uuid4(),
                entity_id=uuid4(),
                event_data={},
                source_service="tx-trade",
            )

        assert UniversalPublisher._redis is None

    @pytest.mark.asyncio
    async def test_runtime_error_returns_none_not_raises(self):
        """Redis RuntimeError 时返回 None，不抛异常"""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(side_effect=RuntimeError("event loop closed"))

        with patch.object(UniversalPublisher, "get_redis", return_value=mock_redis):
            result = await UniversalPublisher.publish(
                event_type=TradeEventType.ORDER_PAID,
                tenant_id=uuid4(),
                store_id=uuid4(),
                entity_id=uuid4(),
                event_data={},
                source_service="tx-trade",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_xadd_os_error_returns_none(self):
        """xadd 本身抛 OSError 时也应降级返回 None"""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(side_effect=OSError("broken pipe"))

        with patch.object(UniversalPublisher, "get_redis", return_value=mock_redis):
            result = await UniversalPublisher.publish(
                event_type=SupplyEventType.STOCK_LOW,
                tenant_id=uuid4(),
                store_id=uuid4(),
                entity_id=uuid4(),
                event_data={"qty": 5},
                source_service="tx-supply",
            )
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# 5. close()
# ─────────────────────────────────────────────────────────────────────────────


class TestClose:
    """close() Redis 连接关闭"""

    @pytest.mark.asyncio
    async def test_close_calls_aclose_on_redis(self):
        """关闭时应调用 redis.aclose()"""
        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()
        UniversalPublisher._redis = mock_redis

        await UniversalPublisher.close()

        mock_redis.aclose.assert_called_once()
        assert UniversalPublisher._redis is None

    @pytest.mark.asyncio
    async def test_close_when_no_redis_is_noop(self):
        """_redis 为 None 时 close() 不报错"""
        UniversalPublisher._redis = None
        # 不应抛出任何异常
        await UniversalPublisher.close()
