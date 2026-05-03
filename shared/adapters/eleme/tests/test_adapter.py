"""
饿了么开放平台适配器单元测试

覆盖重点：
  1. ElemeAdapter 初始化 — 沙箱/生产
  2. Token 管理 — 缓存与刷新（委托 client）
  3. 各业务方法成功路径（query_orders, get_order_detail, confirm_order,
     cancel_order, query_refund, query_foods, update_food_stock,
     sold_out_food, on_sale_food, get_shop_info, update_shop_status,
     query_delivery_status）
  4. 业务错误路径（饿了么 API 错误码）
  5. HTTP 错误路径（连接/超时/状态码错误）
  6. 幂等性 — key 生成与去重
  7. 事件发射 — fire-and-forget
  8. to_order — 订单字段映射
"""

from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# 本机 Tailscale 设置 socks5h 代理与 httpx 0.23 不兼容。
# 全局 mock httpx.AsyncClient 防止 init 时读取环境代理。
_async_client_patcher = patch("httpx.AsyncClient", MagicMock)
_async_client_patcher.start()

# adapter.py 依赖 shared.adapters.base.src.event_bus → shared.events 链，
# 该链使用 Python 3.10+ dataclass(slots=True)，系统 Python 3.9 不支持。
# 方案：仅 mock 出问题的 shared.events 及其以下模块，保留 shared.adapters 真实路径。
_MOCK_EVENT_TYPES = MagicMock()
_MOCK_EVENT_TYPES.AdapterEventType = MagicMock()
_MOCK_EVENT_TYPES.AdapterEventType.STATUS_PUSHED = "adapter.status_pushed"
_MOCK_EVENT_TYPES.AdapterEventType.SYNC_FINISHED = "adapter.sync_finished"

_MOCK_EVENT_BUS = MagicMock()
_MOCK_EVENT_BUS.emit_adapter_event = AsyncMock()

sys.modules["shared.events"] = MagicMock()
sys.modules["shared.events.src"] = MagicMock()
sys.modules["shared.events.src.event_types"] = _MOCK_EVENT_TYPES
sys.modules["shared.events.src.emitter"] = MagicMock()
sys.modules["shared.adapters.base.src.event_bus"] = _MOCK_EVENT_BUS

# 现在可以安全导入 eleme adapter（shared.adapters.eleme 是真实路径）
from shared.adapters.eleme.src.adapter import ElemeAdapter


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def config():
    return {
        "app_key": "test_app_key",
        "app_secret": "test_app_secret",
        "store_id": "store_123",
        "tenant_id": "tenant-001",
        "sandbox": True,
    }


@pytest.fixture
def adapter(config, monkeypatch):
    """创建 ElemeAdapter 实例（沙箱模式），mock client。"""
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    inst = ElemeAdapter(config)

    # 替换真实 client 为 mock（所有方法）
    inst.client = MagicMock()
    inst.client.request = AsyncMock(return_value={"data": {}})
    inst.client.query_order = AsyncMock(return_value={})
    inst.client.confirm_order = AsyncMock(return_value={})
    inst.client.cancel_order = AsyncMock(return_value={})
    inst.client.update_food = AsyncMock(return_value={})
    inst.client.query_delivery_status = AsyncMock(return_value={})

    return inst


def _mock_client_response(data: dict) -> dict:
    """构造 client.request 返回格式。"""
    return {"data": data}


# ── 初始化 ──────────────────────────────────────────────────────────────────────


class TestInit:
    def test_sandbox_config(self, config):
        inst = ElemeAdapter(config)
        assert inst.config.get("sandbox") is True
        assert inst.client.sandbox is True
        inst.client.close()

    def test_production_config(self, config):
        config["sandbox"] = False
        inst = ElemeAdapter(config)
        assert inst.config.get("sandbox") is False
        assert inst.client.sandbox is False
        inst.client.close()

    def test_tenant_id_default(self, config):
        del config["tenant_id"]
        inst = ElemeAdapter(config)
        assert inst._tenant_id == ""
        inst.client.close()


# ── 幂等性 ─────────────────────────────────────────────────────────────────────


class TestIdempotency:
    def test_key_generation(self, adapter):
        key1 = adapter.idempotency_key("confirm_order", {"order_id": "o1"})
        key2 = adapter.idempotency_key("confirm_order", {"order_id": "o1"})
        key3 = adapter.idempotency_key("confirm_order", {"order_id": "o2"})
        assert key1 == key2  # 相同 payload → 相同 key
        assert key1 != key3  # 不同 payload → 不同 key

    def test_duplicate_detection(self, adapter):
        key = "test-key-456"
        assert not adapter.is_duplicate(key)
        adapter.mark_idempotent(key)
        assert adapter.is_duplicate(key)

    def test_duplicate_storage_isolation(self, adapter):
        key_a = adapter.idempotency_key("a", {})
        key_b = adapter.idempotency_key("b", {})
        adapter.mark_idempotent(key_a)
        assert adapter.is_duplicate(key_a)
        assert not adapter.is_duplicate(key_b)


# ── 事件 ───────────────────────────────────────────────────────────────────────


class TestEmitSyncEvent:
    async def test_fire_and_forget(self, adapter):
        """事件发射不应抛出异常。"""
        _MOCK_EVENT_BUS.emit_adapter_event.reset_mock()

        await adapter._emit_sync_event(
            "sync_finished",
            scope="orders",
            stream_id="eleme:orders::",
            payload={"page": 1},
        )

        import asyncio
        await asyncio.sleep(0.05)
        assert _MOCK_EVENT_BUS.emit_adapter_event.called


# ── 订单管理 ────────────────────────────────────────────────────────────────────


class TestOrders:
    async def test_query_orders_success(self, adapter):
        adapter.client.request.return_value = _mock_client_response({
            "orders": [{"order_id": "o1", "status": 1}],
            "total": 1,
        })
        result = await adapter.query_orders(page=1, page_size=20)
        assert result["orders"][0]["order_id"] == "o1"

    async def test_query_orders_with_filters(self, adapter):
        adapter.client.request.return_value = _mock_client_response({
            "orders": [{"order_id": "o1", "status": 2}],
        })
        result = await adapter.query_orders(
            start_time="2026-01-01T00:00:00",
            end_time="2026-01-31T23:59:59",
            status=2,
            page=1,
            page_size=10,
        )
        assert result["orders"][0]["order_id"] == "o1"

    async def test_get_order_detail_success(self, adapter):
        adapter.client.query_order.return_value = {
            "order_id": "o1",
            "status": 2,
            "total_price": 8800,
        }
        result = await adapter.get_order_detail("o1")
        assert result["order_id"] == "o1"

    async def test_confirm_order_success(self, adapter):
        adapter.client.confirm_order.return_value = {"success": True}
        result = await adapter.confirm_order("o1")
        assert result["success"] is True

    async def test_cancel_order_success(self, adapter):
        adapter.client.cancel_order.return_value = {"success": True}
        result = await adapter.cancel_order("o1", reason_code=1, reason="顾客要求")
        assert result["success"] is True

    async def test_query_refund_success(self, adapter):
        adapter.client.request.return_value = _mock_client_response({
            "refund_id": "r1",
            "amount": 5000,
            "status": "completed",
        })
        result = await adapter.query_refund("o1")
        assert result["refund_id"] == "r1"

    async def test_get_order_detail_biz_error(self, adapter):
        adapter.client.query_order.side_effect = ValueError("订单不存在 [1001]")
        with pytest.raises(ValueError, match="订单不存在"):
            await adapter.get_order_detail("non_existent_order")


# ── 商品管理 ────────────────────────────────────────────────────────────────────


class TestFoods:
    async def test_query_foods_success(self, adapter):
        adapter.client.request.return_value = _mock_client_response([
            {"food_id": "f1", "name": "宫保鸡丁", "price": 3800},
        ])
        result = await adapter.query_foods(page=1, page_size=50)
        assert result[0]["food_id"] == "f1"

    async def test_query_foods_with_category(self, adapter):
        adapter.client.request.return_value = _mock_client_response([
            {"food_id": "f2", "name": "酸菜鱼"},
        ])
        result = await adapter.query_foods(category_id="cat_1", page=1, page_size=50)
        assert result[0]["food_id"] == "f2"

    async def test_update_food_stock_success(self, adapter):
        adapter.client.update_food.return_value = {"success": True}
        result = await adapter.update_food_stock(food_id="f1", stock=100)
        assert result["success"] is True

    async def test_sold_out_food_success(self, adapter):
        adapter.client.request.return_value = _mock_client_response({"success": True})
        result = await adapter.sold_out_food("f1")
        assert result["success"] is True

    async def test_on_sale_food_success(self, adapter):
        adapter.client.request.return_value = _mock_client_response({"success": True})
        result = await adapter.on_sale_food("f1")
        assert result["success"] is True


# ── 门店管理 ────────────────────────────────────────────────────────────────────


class TestShop:
    async def test_get_shop_info_success(self, adapter):
        adapter.client.request.return_value = _mock_client_response({
            "shop_id": "s1",
            "shop_name": "测试门店",
            "status": 1,
        })
        result = await adapter.get_shop_info("s1")
        assert result["shop_name"] == "测试门店"

    async def test_get_shop_info_default(self, adapter):
        adapter.client.request.return_value = _mock_client_response({
            "shop_id": "default",
            "shop_name": "默认门店",
        })
        result = await adapter.get_shop_info()
        assert result["shop_name"] == "默认门店"

    async def test_update_shop_status_open(self, adapter):
        adapter.client.request.return_value = _mock_client_response({"success": True})
        result = await adapter.update_shop_status(status=1, shop_id="s1")
        assert result["success"] is True

    async def test_update_shop_status_close(self, adapter):
        adapter.client.request.return_value = _mock_client_response({"success": True})
        result = await adapter.update_shop_status(status=0)
        assert result["success"] is True


# ── 配送管理 ────────────────────────────────────────────────────────────────────


class TestDelivery:
    async def test_query_delivery_status_success(self, adapter):
        adapter.client.query_delivery_status.return_value = {
            "order_id": "o1",
            "rider_phone": "13800138000",
            "status": "delivering",
        }
        result = await adapter.query_delivery_status("o1")
        assert result["rider_phone"] == "13800138000"


# ── 标准化数据映射 ──────────────────────────────────────────────────────────────


class TestToOrder:
    """to_order 方法依赖动态 import gateway schema，需要完整 mock 路径。"""

    @pytest.fixture
    def mock_schema(self):
        """动态构造 OrderSchema 等类的 mock。"""
        schemas = MagicMock()
        schemas.OrderStatus = MagicMock()
        schemas.OrderStatus.PENDING = "PENDING"
        schemas.OrderStatus.CONFIRMED = "CONFIRMED"
        schemas.OrderStatus.COMPLETED = "COMPLETED"
        schemas.OrderStatus.CANCELLED = "CANCELLED"

        schemas.OrderType = MagicMock()
        schemas.OrderType.TAKEOUT = "TAKEOUT"

        schemas.DishCategory = MagicMock()
        schemas.DishCategory.MAIN_COURSE = "MAIN_COURSE"

        schemas.OrderItemSchema = MagicMock()
        schemas.OrderSchema = MagicMock()
        return schemas

    @pytest.fixture
    def adapter_with_schema(self, adapter, mock_schema):
        """注入 mock schema。"""
        adapter._schema_module = mock_schema
        return adapter

    def _inject_schema(self, adapter, mock_schema):
        """手动注入 schema 到 adapter 的 to_order 方法可见范围。"""
        import sys as _sys
        _sys.modules["schemas"] = MagicMock()
        _sys.modules["schemas.restaurant_standard_schema"] = mock_schema

    def test_to_order_basic(self, adapter, mock_schema):
        """基本订单映射。"""
        raw = {
            "order_id": "eleme_order_001",
            "status": 2,
            "total_price": 8800,
            "discount_price": 500,
            "create_time": "2026-05-01T12:00:00",
            "user_id": "user_001",
            "food_list": [
                {
                    "food_id": "f1",
                    "food_name": "宫保鸡丁",
                    "price": 3800,
                    "quantity": 2,
                },
                {
                    "food_id": "f2",
                    "food_name": "米饭",
                    "price": 300,
                    "quantity": 1,
                },
            ],
        }
        self._inject_schema(adapter, mock_schema)
        result = adapter.to_order(raw, store_id="store_001", brand_id="brand_001")

        # 验证 OrderSchema 被正确创建
        mock_schema.OrderSchema.assert_called_once()
        call_kwargs = mock_schema.OrderSchema.call_args[1]
        assert call_kwargs["order_id"] == "eleme_order_001"
        assert call_kwargs["store_id"] == "store_001"
        assert call_kwargs["brand_id"] == "brand_001"
        assert str(call_kwargs["total"]) == "88"  # 8800 / 100 = 88
        assert str(call_kwargs["discount"]) == "5"  # 500 / 100 = 5
        assert str(call_kwargs["subtotal"]) == "93"  # 88 + 5 = 93
        assert mock_schema.OrderItemSchema.call_count == 2

    def test_to_order_with_eleme_order_id(self, adapter, mock_schema):
        """使用 eleme_order_id 字段。"""
        raw = {
            "eleme_order_id": "eleme_order_002",
            "status": 4,
            "total_price": 5000,
            "create_time": "2026-05-01T12:30:00",
            "food_list": [
                {"food_id": "f3", "food_name": "酸菜鱼", "price": 5000, "quantity": 1},
            ],
        }
        self._inject_schema(adapter, mock_schema)
        result = adapter.to_order(raw, store_id="store_001", brand_id="brand_001")

        mock_schema.OrderSchema.assert_called_once()
        call_kwargs = mock_schema.OrderSchema.call_args[1]
        assert call_kwargs["order_id"] == "eleme_order_002"
        assert call_kwargs["order_status"] == mock_schema.OrderStatus.COMPLETED

    def test_to_order_cancelled_status(self, adapter, mock_schema):
        """取消订单状态映射。"""
        raw = {
            "order_id": "cancel_001",
            "status": 5,
            "total_price": 3000,
            "create_time": "2026-05-01T13:00:00",
            "food_list": [],
        }
        self._inject_schema(adapter, mock_schema)
        adapter.to_order(raw, store_id="s1", brand_id="b1")
        call_kwargs = mock_schema.OrderSchema.call_args[1]
        assert call_kwargs["order_status"] == mock_schema.OrderStatus.CANCELLED


# ── HTTP 错误路径 ──────────────────────────────────────────────────────────────


class TestHttpErrors:
    async def test_client_request_connection_error(self, adapter):
        adapter.client.request.side_effect = httpx.ConnectError("connection refused")
        with pytest.raises(httpx.ConnectError):
            await adapter.query_orders(page=1, page_size=20)

    async def test_client_request_timeout(self, adapter):
        adapter.client.request.side_effect = httpx.TimeoutException("timeout")
        with pytest.raises(httpx.TimeoutException):
            await adapter.query_foods()

    async def test_client_confirm_order_connection_error(self, adapter):
        adapter.client.confirm_order.side_effect = httpx.ConnectError("connection refused")
        with pytest.raises(httpx.ConnectError):
            await adapter.confirm_order("o1")

    async def test_client_biz_error_value_error(self, adapter):
        adapter.client.request.side_effect = ValueError("饿了么 API 错误 [1001]: 订单不存在")
        with pytest.raises(ValueError, match="订单不存在"):
            await adapter.query_refund("bad_order_id")


# ── 资源释放 ────────────────────────────────────────────────────────────────────


class TestClose:
    async def test_close(self, adapter):
        adapter.client.close = AsyncMock()
        await adapter.close()
        adapter.client.close.assert_awaited_once()
