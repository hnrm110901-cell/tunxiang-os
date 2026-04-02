"""test_scan_pay.py — 扫码付款码收款路由测试

覆盖范围（/api/v1/payments/scan-pay）：
1. 付款码渠道自动识别：微信（10xx 前缀）、支付宝（28xx 前缀）、银联（其他前缀）
2. 正常提交返回 ok=True 及有效 transaction_id
3. 空付款码 → HTTP 422（Pydantic min_length=6 校验）
4. 过短付款码（1位）→ HTTP 422（不崩溃）
5. 支付状态轮询接口
6. 取消支付接口

依赖：
- scan_pay_routes.py 使用内存存储，无需 mock DB
- 路由内有 asyncio.sleep(1.5)，通过 mock 跳过等待
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")),
)

from unittest.mock import patch, AsyncMock
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# ─── 构建仅含 scan_pay 路由的轻量 app ────────────────────────────────────────

from fastapi import FastAPI
from src.api.scan_pay_routes import router as scan_pay_router, _payments

_app = FastAPI(title="scan-pay-test")
_app.include_router(scan_pay_router)

TENANT_HEADERS = {"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"}

# 基础有效请求体
_BASE_BODY = {
    "order_id": "order-001",
    "auth_code": "134567890123",   # 微信：13 前缀，12 位
    "amount_fen": 1000,
    "operator_id": "op-001",
    "store_id": "store-001",
}


@pytest_asyncio.fixture
async def client():
    """每个测试用独立 AsyncClient，并 patch asyncio.sleep 跳过 1.5s 延迟。"""
    async with AsyncClient(
        transport=ASGITransport(app=_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
def clear_payments():
    """每个测试前清空内存支付记录，避免状态污染。"""
    _payments.clear()
    yield
    _payments.clear()


# ─── 辅助：带 sleep mock 发起 scan-pay 请求 ──────────────────────────────────

async def _scan_pay(client: AsyncClient, body: dict) -> dict:
    """发起 POST /api/v1/payments/scan-pay，同时跳过内部 asyncio.sleep。"""
    with patch("src.api.scan_pay_routes.asyncio.sleep", new_callable=AsyncMock):
        resp = await client.post(
            "/api/v1/payments/scan-pay",
            json=body,
            headers=TENANT_HEADERS,
        )
    return resp


# ─── 渠道识别测试 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_pay_wechat(client: AsyncClient):
    """auth_code "10" 开头（12位）→ channel="wechat"，channel_label="微信支付"。"""
    body = {**_BASE_BODY, "auth_code": "101234567890"}
    resp = await _scan_pay(client, body)

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["pay_channel"] == "wechat"
    assert data["data"]["channel_label"] == "微信支付"


@pytest.mark.asyncio
async def test_scan_pay_alipay(client: AsyncClient):
    """auth_code "28" 开头 → channel="alipay"，channel_label="支付宝"。"""
    body = {**_BASE_BODY, "auth_code": "281234567890"}
    resp = await _scan_pay(client, body)

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["pay_channel"] == "alipay"
    assert data["data"]["channel_label"] == "支付宝"


@pytest.mark.asyncio
async def test_scan_pay_unionpay(client: AsyncClient):
    """auth_code "99" 开头 → channel="unionpay"，channel_label="银联云闪付"。"""
    body = {**_BASE_BODY, "auth_code": "991234567890"}
    resp = await _scan_pay(client, body)

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["pay_channel"] == "unionpay"
    assert data["data"]["channel_label"] == "银联云闪付"


# ─── 正常支付流程 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_pay_success(client: AsyncClient):
    """正常提交 → ok=True，transaction_id 非空，status=success，amount 一致。"""
    body = {**_BASE_BODY, "auth_code": "134567890123", "amount_fen": 8800}
    resp = await _scan_pay(client, body)

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True

    result = data["data"]
    assert result["transaction_id"]          # 非空
    assert result["payment_id"]              # 非空
    assert result["status"] == "success"
    assert result["amount_fen"] == 8800
    assert result["order_id"] == "order-001"


@pytest.mark.asyncio
async def test_scan_pay_success_returns_valid_payment_id(client: AsyncClient):
    """payment_id 以 'pay_' 开头，transaction_id 以 'txn_' 开头。"""
    body = {**_BASE_BODY, "auth_code": "256789012345"}
    resp = await _scan_pay(client, body)

    assert resp.status_code == 200
    result = resp.json()["data"]
    assert result["payment_id"].startswith("pay_")
    assert result["transaction_id"].startswith("txn_")


# ─── 校验边界 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_pay_empty_code(client: AsyncClient):
    """auth_code="" 空字符串 → HTTP 422（Pydantic min_length=6 拒绝）。"""
    body = {**_BASE_BODY, "auth_code": ""}
    with patch("src.api.scan_pay_routes.asyncio.sleep", new_callable=AsyncMock):
        resp = await client.post(
            "/api/v1/payments/scan-pay",
            json=body,
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_scan_pay_short_code(client: AsyncClient):
    """auth_code="1"（1位，不足 min_length=6）→ HTTP 422，不崩溃。"""
    body = {**_BASE_BODY, "auth_code": "1"}
    with patch("src.api.scan_pay_routes.asyncio.sleep", new_callable=AsyncMock):
        resp = await client.post(
            "/api/v1/payments/scan-pay",
            json=body,
            headers=TENANT_HEADERS,
        )

    # Pydantic min_length=6 校验失败
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_scan_pay_missing_tenant_id(client: AsyncClient):
    """不带 X-Tenant-ID header → HTTP 400。"""
    body = {**_BASE_BODY}
    with patch("src.api.scan_pay_routes.asyncio.sleep", new_callable=AsyncMock):
        resp = await client.post("/api/v1/payments/scan-pay", json=body)

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_scan_pay_zero_amount(client: AsyncClient):
    """amount_fen=0 → HTTP 422（Field gt=0 校验）。"""
    body = {**_BASE_BODY, "amount_fen": 0}
    with patch("src.api.scan_pay_routes.asyncio.sleep", new_callable=AsyncMock):
        resp = await client.post(
            "/api/v1/payments/scan-pay",
            json=body,
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 422


# ─── 状态轮询接口 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_payment_status_after_pay(client: AsyncClient):
    """先发起支付，再轮询状态 → status=success。"""
    body = {**_BASE_BODY, "auth_code": "121234567890"}
    resp = await _scan_pay(client, body)
    payment_id = resp.json()["data"]["payment_id"]

    status_resp = await client.get(
        f"/api/v1/payments/scan-pay/{payment_id}/status",
        headers=TENANT_HEADERS,
    )
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["ok"] is True
    assert status_data["data"]["status"] == "success"
    assert status_data["data"]["payment_id"] == payment_id


@pytest.mark.asyncio
async def test_get_payment_status_not_found(client: AsyncClient):
    """不存在的 payment_id → HTTP 404。"""
    resp = await client.get(
        "/api/v1/payments/scan-pay/nonexistent_pay_id/status",
        headers=TENANT_HEADERS,
    )
    assert resp.status_code == 404


# ─── 取消支付接口 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_payment_after_success_returns_409(client: AsyncClient):
    """已成功的支付取消 → HTTP 409 冲突。"""
    body = {**_BASE_BODY, "auth_code": "132345678901"}
    resp = await _scan_pay(client, body)
    payment_id = resp.json()["data"]["payment_id"]

    cancel_resp = await client.post(
        f"/api/v1/payments/scan-pay/{payment_id}/cancel",
        headers=TENANT_HEADERS,
    )
    assert cancel_resp.status_code == 409


@pytest.mark.asyncio
async def test_cancel_payment_not_found(client: AsyncClient):
    """取消不存在的支付 → HTTP 404。"""
    resp = await client.post(
        "/api/v1/payments/scan-pay/no_such_pay/cancel",
        headers=TENANT_HEADERS,
    )
    assert resp.status_code == 404


# ─── 前缀枚举覆盖 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("prefix,expected_channel", [
    ("10", "wechat"),
    ("11", "wechat"),
    ("12", "wechat"),
    ("13", "wechat"),
    ("14", "wechat"),
    ("15", "wechat"),
    ("25", "alipay"),
    ("26", "alipay"),
    ("27", "alipay"),
    ("28", "alipay"),
    ("29", "alipay"),
    ("30", "alipay"),
    ("99", "unionpay"),
    ("50", "unionpay"),
])
@pytest.mark.asyncio
async def test_channel_prefix_coverage(client: AsyncClient, prefix: str, expected_channel: str):
    """参数化测试：覆盖所有合法前缀对应的渠道识别。"""
    body = {**_BASE_BODY, "auth_code": f"{prefix}1234567890"}
    resp = await _scan_pay(client, body)

    assert resp.status_code == 200
    assert resp.json()["data"]["pay_channel"] == expected_channel
