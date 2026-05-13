"""马来西亚适配器集成测试 — MyInvois

使用 mock HTTP 服务器模拟外部 API 响应，不依赖真实沙箱环境。
"""
from __future__ import annotations

import importlib.util
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
            mock_post.return_value = AsyncMock(
                status_code=200,
                json=lambda: {
                    "access_token": "mock-token",
                    "expires_in": 3600,
                },
            )
            mock_request.return_value = AsyncMock(
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


