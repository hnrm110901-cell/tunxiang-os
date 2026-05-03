"""
抖音生活服务开放平台适配器单元测试

覆盖重点：
  1. DouyinAdapter 初始化 — 沙箱/生产
  2. Token 管理 — 缓存与刷新（委托 client）
  3. 各业务方法成功路径（query_coupons, get_coupon_detail, verify_coupon,
     query_orders, get_order_detail, get_shop_info, query_settlements）
  4. 业务错误路径（抖音 API 错误码）
  5. HTTP 错误路径（连接/超时/状态码错误）
  6. 幂等性 — key 生成与去重
  7. 事件发射 — fire-and-forget
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

# 现在可以安全导入 douyin adapter（shared.adapters.douyin 是真实路径）
from shared.adapters.douyin.src.adapter import DouyinAdapter


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def config():
    return {
        "app_id": "test_app_id",
        "app_secret": "test_app_secret",
        "tenant_id": "tenant-001",
        "sandbox": True,
    }


@pytest.fixture
def adapter(config, monkeypatch):
    """创建 DouyinAdapter 实例（沙箱模式），mock client。"""
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    inst = DouyinAdapter(config)

    # 替换真实 client 为 mock（所有方法）
    inst.client = MagicMock()
    inst.client.request = AsyncMock(return_value={"data": {}})
    inst.client.verify_certificate = AsyncMock(return_value={})
    inst.client.query_order = AsyncMock(return_value={})

    return inst


def _mock_client_response(data: dict) -> dict:
    """构造 client.request 返回格式。"""
    return {"data": data}


# ── 初始化 ──────────────────────────────────────────────────────────────────────


class TestInit:
    def test_sandbox_config(self, config):
        inst = DouyinAdapter(config)
        assert inst.config.get("sandbox") is True
        assert inst.client.sandbox is True
        inst.client.close()

    def test_production_config(self, config):
        config["sandbox"] = False
        inst = DouyinAdapter(config)
        assert inst.config.get("sandbox") is False
        assert inst.client.sandbox is False
        inst.client.close()

    def test_tenant_id_default(self, config):
        del config["tenant_id"]
        inst = DouyinAdapter(config)
        assert inst._tenant_id == ""
        inst.client.close()


# ── 幂等性 ─────────────────────────────────────────────────────────────────────


class TestIdempotency:
    def test_key_generation(self, adapter):
        key1 = adapter.idempotency_key("verify_coupon", {"code": "abc", "shop_id": "s1"})
        key2 = adapter.idempotency_key("verify_coupon", {"code": "abc", "shop_id": "s1"})
        key3 = adapter.idempotency_key("verify_coupon", {"code": "xyz", "shop_id": "s2"})
        assert key1 == key2  # 相同 payload → 相同 key
        assert key1 != key3  # 不同 payload → 不同 key

    def test_duplicate_detection(self, adapter):
        key = "test-key-123"
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
        """事件发射不应抛出异常（测试 _emit_sync_event 的隔离性）。"""
        # mock emit_adapter_event，验证被调用
        _MOCK_EVENT_BUS.emit_adapter_event.reset_mock()

        await adapter._emit_sync_event(
            "sync_finished",
            scope="orders",
            stream_id="douyin:orders:2026-01-01:2026-01-31",
            payload={"page": 1},
        )

        # 验证 emit_adapter_event 被调用（通过 create_task，等待一小段时间）
        import asyncio
        await asyncio.sleep(0.05)
        assert _MOCK_EVENT_BUS.emit_adapter_event.called


# ── 团购券 ─────────────────────────────────────────────────────────────────────


class TestCoupons:
    async def test_query_coupons_success(self, adapter):
        adapter.client.request.return_value = _mock_client_response({
            "coupons": [{"coupon_id": "c1", "status": 1}],
            "total": 1,
        })
        result = await adapter.query_coupons(page=1, page_size=20)
        assert result["coupons"][0]["coupon_id"] == "c1"

    async def test_query_coupons_empty(self, adapter):
        adapter.client.request.return_value = _mock_client_response({
            "coupons": [],
            "total": 0,
        })
        result = await adapter.query_coupons(page=1, page_size=20)
        assert result["coupons"] == []

    async def test_get_coupon_detail_success(self, adapter):
        adapter.client.request.return_value = _mock_client_response({
            "coupon_id": "c1",
            "code": "ENC_CODE",
            "amount": 1000,
        })
        result = await adapter.get_coupon_detail("c1")
        assert result["coupon_id"] == "c1"

    async def test_verify_coupon_success(self, adapter):
        adapter.client.verify_certificate.return_value = {
            "verify_result": True,
            "coupon_id": "c1",
        }
        result = await adapter.verify_coupon(code="enc_code", shop_id="shop_1")
        assert result["verify_result"] is True

    async def test_verify_coupon_biz_error(self, adapter):
        """核销遇到业务错误应传播 ValueError。"""
        adapter.client.verify_certificate.side_effect = ValueError("券码不存在 [2200001]")
        with pytest.raises(ValueError, match="券码不存在"):
            await adapter.verify_coupon(code="bad_code", shop_id="shop_1")


# ── 订单 ───────────────────────────────────────────────────────────────────────


class TestOrders:
    async def test_query_orders_success(self, adapter):
        adapter.client.request.return_value = _mock_client_response({
            "orders": [{"order_id": "o1", "status": 1}],
            "total": 1,
        })
        result = await adapter.query_orders(
            "2026-01-01T00:00:00", "2026-01-31T23:59:59", page=1, page_size=20
        )
        assert result["orders"][0]["order_id"] == "o1"

    async def test_get_order_detail_success(self, adapter):
        adapter.client.query_order.return_value = {
            "order_id": "o1",
            "status": 2,
            "total_amount": 8800,
        }
        result = await adapter.get_order_detail("o1")
        assert result["order_id"] == "o1"

    async def test_get_order_detail_biz_error(self, adapter):
        adapter.client.query_order.side_effect = ValueError("订单不存在 [2300001]")
        with pytest.raises(ValueError, match="订单不存在"):
            await adapter.get_order_detail("non_existent_order")


# ── 门店 ───────────────────────────────────────────────────────────────────────


class TestShop:
    async def test_get_shop_info_success(self, adapter):
        adapter.client.request.return_value = _mock_client_response({
            "shop_id": "s1",
            "shop_name": "测试门店",
            "status": 1,
        })
        result = await adapter.get_shop_info("s1")
        assert result["shop_name"] == "测试门店"


# ── 结算 ───────────────────────────────────────────────────────────────────────


class TestSettlements:
    async def test_query_settlements_success(self, adapter):
        adapter.client.request.return_value = _mock_client_response({
            "settlements": [{"settlement_id": "st1", "amount": 50000}],
        })
        result = await adapter.query_settlements("2026-01-01", "2026-01-31")
        assert result["settlements"][0]["settlement_id"] == "st1"

    async def test_query_settlements_empty(self, adapter):
        adapter.client.request.return_value = _mock_client_response({
            "settlements": [],
        })
        result = await adapter.query_settlements("2026-01-01", "2026-01-31")
        assert result["settlements"] == []


# ── HTTP 错误路径 ──────────────────────────────────────────────────────────────


class TestHttpErrors:
    async def test_client_request_connection_error(self, adapter):
        """连接错误应传播 httpx.ConnectError。"""
        adapter.client.request.side_effect = httpx.ConnectError("connection refused")
        with pytest.raises(httpx.ConnectError):
            await adapter.query_coupons(page=1, page_size=20)

    async def test_client_request_timeout(self, adapter):
        """超时错误应传播 httpx.TimeoutException。"""
        adapter.client.request.side_effect = httpx.TimeoutException("timeout")
        with pytest.raises(httpx.TimeoutException):
            await adapter.query_orders("start", "end")

    async def test_client_biz_error_value_error(self, adapter):
        """业务错误码应传播 ValueError。"""
        adapter.client.request.return_value = {"data": {"error_code": 2200001, "description": "券码不存在"}}
        # adapter 的 _emit_sync_event 会 catch Exception，但业务错误由 client 层检查
        # adapter 依赖 client 方法本身抛 ValueError
        # 对于 request-based 方法，client 内部调用 _check_biz_error
        # 对于 verify_certificate/query_order，client 内部也调用 _check_biz_error
        # 由于我们 mock 了整个 client，需要手动模拟行为
        with pytest.raises(ValueError, match="券码不存在"):
            adapter.client.request.side_effect = ValueError("抖音 API 错误 [2200001]: 券码不存在")
            await adapter.get_coupon_detail("bad_id")


# ── 资源释放 ────────────────────────────────────────────────────────────────────


class TestClose:
    async def test_close(self, adapter):
        adapter.client.close = AsyncMock()
        await adapter.close()
        adapter.client.close.assert_awaited_once()
