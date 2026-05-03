"""
诺诺开放平台适配器单元测试

覆盖重点：
  1. NuonuoAPIError — 自定义异常
  2. NuonuoAdapter 初始化 — 沙箱/生产 URL
  3. _get_access_token — 缓存与刷新
  4. _request — HMAC 签名 + 错误码处理
  5. 幂等性 — key 生成与去重
  6. issue_invoice / query_invoice / void_invoice / issue_red_invoice / download_pdf
  7. _emit_sync_event — fire-and-forget 事件
  8. NuonuoInvoiceClient — 异常安全封装层
"""

from __future__ import annotations

import json
import os
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
# adapter.py 导入 event_bus，而 event_bus 内部导入 shared.events.src.emitter，
# 该链引入 Python 3.10+ dataclass(slots=True)。直接 mock event_bus 模块。
sys.modules["shared.adapters.base.src.event_bus"] = _MOCK_EVENT_BUS

# 现在可以安全导入 nuonuo adapter（shared.adapters.nuonuo 是真实路径）
from shared.adapters.nuonuo.src.adapter import NuonuoAPIError, NuonuoAdapter


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def config():
    return {
        "app_key": "test_app_key",
        "app_secret": "test_app_secret",
        "tax_number": "91510100MA12345678",
        "tenant_id": "tenant-001",
        "sandbox": True,
    }


@pytest.fixture
def adapter(config, monkeypatch):
    """创建 NuonuoAdapter 实例（沙箱模式），mock httpx client。"""
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    inst = NuonuoAdapter(config)

    # 替换真实 httpx client 为 mock
    inst._client = MagicMock(spec=httpx.AsyncClient)

    # _get_access_token 不依赖网络 —— 返回固定 token
    inst._access_token = "mock-access-token-abc"
    inst._token_expires_at = 9999999999.0

    return inst


def _mock_response(data: dict, status_code: int = 200) -> MagicMock:
    """构造 httpx.Response 样式的 mock 对象。"""
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = data
    resp.status_code = status_code
    return resp


# ── NuonuoAPIError ─────────────────────────────────────────────────────────────


class TestNuonuoAPIError:
    def test_basic(self):
        err = NuonuoAPIError("网络超时")
        assert str(err) == "网络超时"
        assert err.code == "E_UNKNOWN"
        assert err.method == ""

    def test_with_code_and_method(self):
        err = NuonuoAPIError("余额不足", code="E1001", method="issue_invoice")
        assert err.code == "E1001"
        assert err.method == "issue_invoice"


# ── 初始化 ──────────────────────────────────────────────────────────────────────


class TestInit:
    def test_sandbox_url(self, config):
        inst = NuonuoAdapter(config)
        assert inst.sandbox is True
        assert inst.base_url == "https://sandbox.nuonuocs.cn/open/v1/services"
        assert inst.app_key == "test_app_key"
        assert inst.tax_number == "91510100MA12345678"
        inst._client.aclose()  # 清理 httpx client

    def test_production_url(self, config):
        config["sandbox"] = False
        inst = NuonuoAdapter(config)
        assert inst.sandbox is False
        assert inst.base_url == "https://sdk.nuonuo.com/open/v1/services"
        inst._client.aclose()


# ── Token ──────────────────────────────────────────────────────────────────────


class TestAccessToken:
    async def test_cached_token(self, adapter):
        """已有有效 token 时不应发起网络请求。"""
        adapter._client.post = AsyncMock()
        token = await adapter._get_access_token()
        assert token == "mock-access-token-abc"
        adapter._client.post.assert_not_called()

    async def test_expired_triggers_refresh(self, adapter):
        """token 过期后自动刷新。"""
        adapter._token_expires_at = 0  # 强制过期
        mock_resp = _mock_response({
            "access_token": "new-token-xyz",
            "expires_in": 7200,
        })
        adapter._client.post = AsyncMock(return_value=mock_resp)

        token = await adapter._get_access_token()
        assert token == "new-token-xyz"
        assert adapter._access_token == "new-token-xyz"


# ── _request ───────────────────────────────────────────────────────────────────


class TestRequest:
    async def test_success(self, adapter):
        """正常响应返回 result 字段内容。"""
        mock_resp = _mock_response({"code": "E0000", "result": {"serialNo": "SN001"}})
        adapter._client.post = AsyncMock(return_value=mock_resp)

        result = await adapter._request("test.method", {"foo": "bar"})
        assert result == {"serialNo": "SN001"}

    async def test_business_error(self, adapter):
        """业务错误抛出 NuonuoAPIError。"""
        mock_resp = _mock_response({"code": "E1001", "describe": "参数异常"})
        adapter._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(NuonuoAPIError) as exc_info:
            await adapter._request("test.method", {})
        assert exc_info.value.code == "E1001"
        assert "参数异常" in str(exc_info.value)

    async def test_http_error_retry_then_raise(self, adapter):
        """HTTP 层错误向上传播 httpx.ConnectError。"""
        adapter._client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )

        with pytest.raises(httpx.ConnectError, match="connection refused"):
            await adapter._request("test.method", {})

    async def test_hmac_header_present(self, adapter):
        """请求包含 X-Nuonuo-Sign 等必要 Header。"""
        mock_resp = _mock_response({"code": "E0000", "result": {}})
        adapter._client.post = AsyncMock(return_value=mock_resp)

        await adapter._request("nuonuo.method", {})
        call_kwargs = adapter._client.post.call_args[1]
        headers = call_kwargs.get("headers", {})
        assert "X-Nuonuo-Sign" in headers
        assert headers["method"] == "nuonuo.method"
        assert headers["userTax"] == "91510100MA12345678"
        assert headers["accessToken"] == "mock-access-token-abc"


# ── 幂等性 ─────────────────────────────────────────────────────────────────────


class TestIdempotency:
    def test_key_generation(self, adapter):
        key1 = adapter.idempotency_key("issue", {"amount": 100})
        key2 = adapter.idempotency_key("issue", {"amount": 100})
        key3 = adapter.idempotency_key("issue", {"amount": 200})
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
        """事件发射失败不应抛出异常（fire-and-forget）。"""
        adapter._emit_sync_event = AsyncMock()

        # 调用后不应抛出任何异常
        await adapter._emit_sync_event(
            "adapter.status_pushed",
            scope="invoice",
            stream_id="nuonuo:invoice:SN001",
            payload={"serial_no": "SN001"},
        )


# ── 发票业务 ────────────────────────────────────────────────────────────────────


class TestInvoice:
    async def test_issue_invoice_success(self, adapter):
        mock_resp = _mock_response({
            "code": "E0000",
            "result": {"serialNo": "SN2024001"},
        })
        adapter._client.post = AsyncMock(return_value=mock_resp)

        result = await adapter.issue_invoice({"orderNo": "ORD001", "buyerName": "测试"})
        assert result["serialNo"] == "SN2024001"

    async def test_issue_invoice_error(self, adapter):
        mock_resp = _mock_response({"code": "E2001", "describe": "税号未登记"})
        adapter._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(NuonuoAPIError, match="税号未登记"):
            await adapter.issue_invoice({"orderNo": "ORD001"})

    async def test_query_invoice_success(self, adapter):
        mock_resp = _mock_response({
            "code": "E0000",
            "result": {
                "invoiceData": [{"invoiceNo": "12345678"}],
            },
        })
        adapter._client.post = AsyncMock(return_value=mock_resp)

        result = await adapter.query_invoice(["SN2024001"])
        assert result["invoiceData"][0]["invoiceNo"] == "12345678"

    async def test_query_invoice_empty(self, adapter):
        """查询时如果结果中无 invoiceData，也应正常返回。"""
        mock_resp = _mock_response({
            "code": "E0000",
            "result": {"invoiceData": []},
        })
        adapter._client.post = AsyncMock(return_value=mock_resp)

        result = await adapter.query_invoice(["SN999"])
        assert result["invoiceData"] == []

    async def test_void_invoice_success(self, adapter):
        mock_resp = _mock_response({"code": "E0000", "result": {"success": True}})
        adapter._client.post = AsyncMock(return_value=mock_resp)

        result = await adapter.void_invoice("inv-id-1", "12345678", "4400123456")
        assert result["success"] is True

    async def test_issue_red_invoice(self, adapter):
        """红字发票 —— 在原蓝字发票基础上开负数。"""
        mock_resp = _mock_response({
            "code": "E0000",
            "result": {"serialNo": "RED2024001"},
        })
        adapter._client.post = AsyncMock(return_value=mock_resp)

        result = await adapter.issue_red_invoice(
            original_invoice_code="4400123456",
            original_invoice_number="12345678",
            reason="退货",
            invoice_data={"amount": -100},
        )
        assert result["serialNo"] == "RED2024001"

    async def test_download_pdf_success(self, adapter):
        mock_resp = _mock_response({
            "code": "E0000",
            "result": {"pdfUrl": "https://nuonuo.com/pdf/123.pdf"},
        })
        adapter._client.post = AsyncMock(return_value=mock_resp)

        pdf_url = await adapter.download_pdf("4400123456", "12345678")
        assert pdf_url == "https://nuonuo.com/pdf/123.pdf"

    async def test_download_pdf_empty_url(self, adapter):
        """无 PDF 时返回空字符串。"""
        mock_resp = _mock_response({
            "code": "E0000",
            "result": {},
        })
        adapter._client.post = AsyncMock(return_value=mock_resp)

        pdf_url = await adapter.download_pdf("4400123456", "00000000")
        assert pdf_url == ""


# ── InvoiceClient（安全封装层） ─────────────────────────────────────────────────


class TestInvoiceClient:
    """NuonuoInvoiceClient 异常处理 —— 不向上抛异常，转为 NuonuoResponse。"""

    @pytest.fixture
    def client(self):
        from shared.adapters.nuonuo.src.invoice_client import NuonuoInvoiceClient

        c = NuonuoInvoiceClient()
        mock_adapter = MagicMock()
        mock_adapter.issue_invoice = AsyncMock(return_value={"serialNo": "SN001"})
        mock_adapter.query_invoice = AsyncMock(
            return_value={"invoiceData": [{"invoiceNo": "1"}]}
        )
        mock_adapter.issue_red_invoice = AsyncMock(return_value={"serialNo": "RED001"})
        mock_adapter.void_invoice = AsyncMock(return_value={"success": True})
        mock_adapter.download_pdf = AsyncMock(
            return_value="https://nuonuo.com/pdf/1.pdf"
        )
        c._adapter = mock_adapter
        return c

    async def test_apply_invoice_ok(self, client):
        resp = await client.apply_invoice({"orderNo": "O1"})
        assert resp.success is True
        assert resp.data["serialNo"] == "SN001"

    async def test_apply_invoice_fail(self, client):
        client._adapter.issue_invoice = AsyncMock(
            side_effect=NuonuoAPIError("余额不足", code="E1001")
        )
        resp = await client.apply_invoice({"orderNo": "O1"})
        assert resp.success is False
        assert "余额不足" in resp.error_msg

    async def test_query_invoice_ok(self, client):
        resp = await client.query_invoice("SN001")
        assert resp.success is True

    async def test_red_flush_ok(self, client):
        resp = await client.red_flush_invoice(
            invoice_no="12345678",
            invoice_code="4400123456",
            reason="退货",
            invoice_data={"amount": -100},
        )
        assert resp.success is True
        assert resp.data["serialNo"] == "RED001"

    async def test_void_ok(self, client):
        resp = await client.void_invoice(
            invoice_id="inv-1",
            invoice_no="12345678",
            invoice_code="4400123456",
        )
        assert resp.success is True

    async def test_pdf_url_ok(self, client):
        resp = await client.get_pdf_url("4400123456", "12345678")
        assert resp.success is True
        assert resp.data["pdf_url"] == "https://nuonuo.com/pdf/1.pdf"

    async def test_apply_invoice_httpx_error(self, client):
        error = httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())
        client._adapter.issue_invoice = AsyncMock(side_effect=error)
        resp = await client.apply_invoice({"orderNo": "O1"})
        assert resp.success is False

    async def test_query_invoice_httpx_error(self, client):
        error = httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())
        client._adapter.query_invoice = AsyncMock(side_effect=error)
        resp = await client.query_invoice("SN001")
        assert resp.success is False

    async def test_red_flush_httpx_error(self, client):
        error = httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())
        client._adapter.issue_red_invoice = AsyncMock(side_effect=error)
        resp = await client.red_flush_invoice("12345678", "4400123456", "退货", {})
        assert resp.success is False

    async def test_void_httpx_error(self, client):
        error = httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())
        client._adapter.void_invoice = AsyncMock(side_effect=error)
        resp = await client.void_invoice("inv-1", "12345678", "4400123456")
        assert resp.success is False

    async def test_pdf_url_httpx_error(self, client):
        error = httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())
        client._adapter.download_pdf = AsyncMock(side_effect=error)
        resp = await client.get_pdf_url("4400123456", "12345678")
        assert resp.success is False
