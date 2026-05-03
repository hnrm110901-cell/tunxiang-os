"""马来西亚适配器集成测试 — MyInvois / GrabFood / Foodpanda / ShopeeFood

使用 mock HTTP 服务器模拟外部 API 响应，不依赖真实沙箱环境。
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _load_module(name: str, path: str):
    """从文件路径加载 Python 模块。"""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ═══════════════════════════════════════════════════════════════════════════
# MyInvois Adapter (LHDN e-Invoice)
# ═══════════════════════════════════════════════════════════════════════════


class TestMyInvoisAdapter:
    """LHDN MyInvois 电子发票适配器 — 模拟 HTTP"""

    CONFIG = {
        "client_id": "mock-client-id",
        "client_secret": "mock-client-secret",
        "tax_id": "C01234567890",
        "id_type": "BRN",
        "sandbox": True,
    }

    @pytest.fixture
    def adapter(self):
        with patch("httpx.AsyncClient"):
            mod = _load_module(
                "myinvois_client",
                "shared/adapters/myinvois/src/client.py",
            )
            a = mod.MyInvoisAdapter(self.CONFIG)
            a._client = AsyncMock()
            return a

    @pytest.fixture
    def mock_http(self, adapter):
        """Mock httpx.AsyncClient 的 POST 和 GET 方法。"""
        with patch.object(adapter._client, "post") as mock_post, patch.object(
            adapter._client, "get"
        ) as mock_get, patch.object(adapter._client, "request") as mock_request:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "access_token": "mock-token",
                    "expires_in": 3600,
                },
            )
            mock_request.return_value = MagicMock(
                status_code=200,
                json=lambda: {"acceptedDocuments": [{"uuid": "doc-uuid-123"}], "rejectedDocuments": []},
            )
            yield {"post": mock_post, "get": mock_get, "request": mock_request}

    @pytest.mark.asyncio
    async def test_get_access_token(self, adapter, mock_http):
        """OAuth2 Client Credentials 获取 token"""
        token = await adapter._get_access_token()
        assert token == "mock-token"
        assert adapter._access_token == "mock-token"
        assert adapter._token_expires_at > 0

    @pytest.mark.asyncio
    async def test_submit_document(self, adapter, mock_http):
        """提交电子发票"""
        result = await adapter.submit_document(
            invoice_data={"invoice": {"total": 100.00}},
            document_format="JSON",
        )
        assert "acceptedDocuments" in result
        assert result["acceptedDocuments"][0]["uuid"] == "doc-uuid-123"

    @pytest.mark.asyncio
    async def test_get_document_status(self, adapter, mock_http):
        """查询发票状态"""
        mock_http["request"].return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": "Approved", "invoiceNo": "INV-001"},
        )
        result = await adapter.get_document_status("doc-uuid-123")
        assert result["status"] == "Approved"

    @pytest.mark.asyncio
    async def test_cancel_document(self, adapter, mock_http):
        """取消发票"""
        mock_http["request"].return_value = MagicMock(
            status_code=200,
            json=lambda: {"cancellation": {"status": "cancelled"}},
        )
        result = await adapter.cancel_document("doc-uuid-123", reason="Test cancel")
        assert result["cancellation"]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_health_check_ok(self, adapter, mock_http):
        """健康检查通过"""
        mock_http["get"].return_value = MagicMock(status_code=200)
        healthy = await adapter.health_check()
        assert healthy is True

    @pytest.mark.asyncio
    async def test_health_check_fail(self, adapter, mock_http):
        """健康检查失败"""
        mock_http["get"].return_value = MagicMock(status_code=503)
        healthy = await adapter.health_check()
        assert healthy is False

    @pytest.mark.asyncio
    async def test_search_documents(self, adapter, mock_http):
        """搜索发票"""
        mock_http["request"].return_value = MagicMock(
            status_code=200,
            json=lambda: {"documents": [], "totalCount": 0},
        )
        result = await adapter.search_documents(date_from="2026-01-01")
        assert "documents" in result


# ═══════════════════════════════════════════════════════════════════════════
# GrabFood Adapter (low-level client)
# ═══════════════════════════════════════════════════════════════════════════


class TestGrabFoodAdapter:
    """GrabFood HTTP API client"""

    @pytest.fixture
    def client_mod(self):
        return _load_module(
            "grabfood_client",
            "shared/adapters/grabfood/src/client.py",
        )

    @patch("httpx.AsyncClient")
    def test_client_initialization(self, mock_async_client, client_mod):
        """GrabFoodClient 初始化（sandbox 模式）"""
        client = client_mod.GrabFoodClient(
            merchant_id="mock-merchant",
            client_id="mock-client",
            client_secret="mock-secret",
            production=False,  # sandbox
        )
        assert client.base_url == "https://partner-api.stg-myteksi.com"
        assert not client.production


# ═══════════════════════════════════════════════════════════════════════════
# Service-Layer Delivery Adapters
# ═══════════════════════════════════════════════════════════════════════════


class TestGrabfoodAdapterService:
    """tx-trade 服务层 GrabFood 适配器"""

    @pytest.fixture
    def adapter_mod(self):
        _load_module(
            "services.tx_trade.src.services.delivery_adapters.base_adapter",
            "services/tx-trade/src/services/delivery_adapters/base_adapter.py",
        )
        return _load_module(
            "services.tx_trade.src.services.delivery_adapters.grabfood_adapter",
            "services/tx-trade/src/services/delivery_adapters/grabfood_adapter.py",
        )

    def test_verify_signature(self, adapter_mod):
        """HMAC-SHA256 签名验证"""
        adapter = adapter_mod.GrabFoodAdapter(
            app_id="test", app_secret="test-secret", shop_id="shop-1"
        )
        payload = b'{"test": "data"}'
        expected_sig = hmac.new(
            b"test-secret", payload, hashlib.sha256
        ).hexdigest()
        sig = adapter.verify_signature(payload=payload, signature=expected_sig)
        assert sig is True

    def test_parse_order(self, adapter_mod):
        """GrabFood 订单解析"""
        adapter = adapter_mod.GrabFoodAdapter(
            app_id="test", app_secret="test-secret", shop_id="shop-1"
        )
        raw_order = {
            "orderID": "GF-001",
            "orderState": "OrderState.Accepted",
            "currency": "MYR",
            "merchant": {"id": "merchant-1"},
        }
        result = adapter.parse_order(raw_order)
        assert result.platform_order_id == "GF-001"
        assert result.status == "accepted"


class TestFoodpandaAdapterService:
    """tx-trade 服务层 Foodpanda 适配器"""

    @pytest.fixture
    def adapter_mod(self):
        _load_module(
            "services.tx_trade.src.services.delivery_adapters.base_adapter",
            "services/tx-trade/src/services/delivery_adapters/base_adapter.py",
        )
        return _load_module(
            "services.tx_trade.src.services.delivery_adapters.foodpanda_adapter",
            "services/tx-trade/src/services/delivery_adapters/foodpanda_adapter.py",
        )

    def test_parse_order(self, adapter_mod):
        """Foodpanda 订单解析"""
        adapter = adapter_mod.FoodpandaAdapter(
            app_id="test", app_secret="test-secret", shop_id="shop-1"
        )
        raw = {
            "order_id": "FP-001",
            "status": "confirmed",
            "total": 50.00,
            "order_products": [],
            "customer": {},
        }
        result = adapter.parse_order(raw)
        assert result.platform_order_id == "FP-001"
        assert result.total_fen == 5000  # MYR 50.00 → 5000 fen


class TestShopeeFoodAdapterService:
    """tx-trade 服务层 ShopeeFood 适配器"""

    @pytest.fixture
    def adapter_mod(self):
        _load_module(
            "services.tx_trade.src.services.delivery_adapters.base_adapter",
            "services/tx-trade/src/services/delivery_adapters/base_adapter.py",
        )
        return _load_module(
            "services.tx_trade.src.services.delivery_adapters.shopeefood_adapter",
            "services/tx-trade/src/services/delivery_adapters/shopeefood_adapter.py",
        )

    def test_parse_order(self, adapter_mod):
        """ShopeeFood 订单解析"""
        adapter = adapter_mod.ShopeeFoodAdapter(
            app_id="test", app_secret="test-secret", shop_id="shop-1"
        )
        raw = {
            "order_id": "SF-001",
            "status": "CONFIRMED",
            "total_amount": 30.00,
            "items": [],
            "buyer": {},
        }
        result = adapter.parse_order(raw)
        assert result.platform_order_id == "SF-001"
        assert result.total_fen == 3000  # MYR 30.00 → 3000 fen
