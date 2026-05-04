"""聚合支付/分账 API 测试 — Y-B2

8 个测试用例，覆盖分账订单创建、幂等、异步通知（微信/支付宝）、调账、试算分润。
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from api.split_payment_routes import router
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ── 测试 App ──────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(router)

TENANT_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


def _make_mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    return db


async def _async_gen(value):
    yield value


def _make_receivers(total_fen: int = 10000) -> list[dict]:
    return [
        {"receiver_type": "brand", "receiver_id": "brand_001", "amount_fen": 2000},
        {"receiver_type": "franchise", "receiver_id": "store_001", "amount_fen": 7000},
        {"receiver_type": "platform_fee", "receiver_id": "platform", "amount_fen": 1000},
    ]


# ── 1. test_create_split_order ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_split_order():
    """POST /orders 发起分账应返回 201 和 split_order_id。"""
    mock_db = _make_mock_db()

    with patch("api.split_payment_routes.get_db_with_tenant", return_value=_async_gen(mock_db)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/finance/split/orders",
                json={
                    "order_id": str(uuid.uuid4()),
                    "total_fen": 10000,
                    "channel": "wechat",
                    "merchant_order_id": f"MO_{uuid.uuid4().hex[:8]}",
                    "receivers": _make_receivers(),
                },
                headers=HEADERS,
            )

    assert resp.status_code == 201
    d = resp.json()["data"]
    assert "split_order_id" in d
    assert d["split_status"] == "splitting"
    assert d["split_count"] == 3


# ── 2. test_split_idempotency ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_split_idempotency():
    """相同 merchant_order_id 重复发起应返回 409 Conflict。"""
    from sqlalchemy.exc import IntegrityError

    mock_db = _make_mock_db()
    # 第一次 execute（INSERT 主表）抛 IntegrityError 模拟重复键
    mock_db.execute = AsyncMock(side_effect=IntegrityError("", {}, Exception("duplicate key")))

    with patch("api.split_payment_routes.get_db_with_tenant", return_value=_async_gen(mock_db)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/finance/split/orders",
                json={
                    "order_id": str(uuid.uuid4()),
                    "total_fen": 10000,
                    "channel": "wechat",
                    "merchant_order_id": "DUPLICATE_ORDER_001",
                    "receivers": _make_receivers(),
                },
                headers=HEADERS,
            )

    assert resp.status_code == 409
    assert "已存在" in resp.json()["detail"]


# ── 3. test_async_notify_wechat ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_async_notify_wechat():
    """POST /orders/{id}/notify 携带微信签名头应处理成功。"""
    mock_db = _make_mock_db()
    split_order_id = uuid.uuid4()

    pending_mock = MagicMock()
    pending_mock.scalar_one.return_value = 0  # 无剩余 pending

    call_count = 0

    async def _execute_side_effect(stmt, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            return pending_mock
        return MagicMock()

    mock_db.execute = _execute_side_effect

    with patch("api.split_payment_routes.get_db_with_tenant", return_value=_async_gen(mock_db)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/api/v1/finance/split/orders/{split_order_id}/notify",
                json={
                    "notify_id": "WXNOTIFY_001",
                    "split_result": "success",
                    "receiver_id": "store_001",
                },
                headers={
                    **HEADERS,
                    "X-Wechat-Pay-Signature": "mock_wechat_signature_value",
                },
            )

    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["processed"] is True
    assert d["notify_id"] == "WXNOTIFY_001"


# ── 4. test_async_notify_alipay ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_async_notify_alipay():
    """POST /orders/{id}/notify 携带支付宝签名头应处理成功。"""
    mock_db = _make_mock_db()
    split_order_id = uuid.uuid4()

    call_count = 0

    async def _execute_side_effect(stmt, params=None):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 2:
            mock_result.scalar_one.return_value = 1  # 仍有 pending
        return mock_result

    mock_db.execute = _execute_side_effect

    with patch("api.split_payment_routes.get_db_with_tenant", return_value=_async_gen(mock_db)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/api/v1/finance/split/orders/{split_order_id}/notify",
                json={
                    "notify_id": "ALIPAY_NOTIFY_002",
                    "split_result": "success",
                    "receiver_id": "brand_001",
                },
                headers={
                    **HEADERS,
                    "X-Alipay-Sign": "mock_alipay_rsa2_signature",
                },
            )

    assert resp.status_code == 200
    assert resp.json()["data"]["notify_id"] == "ALIPAY_NOTIFY_002"


# ── 5. test_adjustment_create ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_adjustment_create():
    """POST /adjustments 创建调账记录应返回 201 和 original/adjusted 金额。"""
    mock_db = _make_mock_db()
    split_record_id = uuid.uuid4()

    orig_row = MagicMock()
    orig_row.amount_fen = 7000
    orig_row.id = str(split_record_id)

    call_count = 0

    async def _execute_side_effect(stmt, params=None):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            mock_result.fetchone.return_value = orig_row
        return mock_result

    mock_db.execute = _execute_side_effect

    with patch("api.split_payment_routes.get_db_with_tenant", return_value=_async_gen(mock_db)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/finance/split/adjustments",
                json={
                    "split_record_id": str(split_record_id),
                    "reason": "渠道实际到账金额有误，人工调整",
                    "adjusted_amount_fen": 6800,
                    "adjusted_by": "admin@tunxiang.com",
                },
                headers=HEADERS,
            )

    assert resp.status_code == 201
    d = resp.json()["data"]
    assert d["original_amount_fen"] == 7000
    assert d["adjusted_amount_fen"] == 6800
    assert "adjustment_id" in d


# ── 6. test_preview_split_rules ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_split_rules():
    """GET /rules/preview 各方金额之和必须等于总金额。"""
    rules = json.dumps(
        [
            {"receiver_type": "brand", "receiver_id": "brand_001", "ratio": 2000},
            {"receiver_type": "franchise", "receiver_id": "store_001", "ratio": 7000},
            {"receiver_type": "platform_fee", "receiver_id": "platform", "ratio": 1000},
        ]
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/finance/split/rules/preview?total_fen=10000&rules={rules}",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    d = resp.json()["data"]
    total = sum(item["amount_fen"] for item in d["preview_items"])
    assert total == 10000, f"各方金额之和 {total} != 10000"
    assert d["total_fen"] == 10000


# ── 7. test_preview_amounts_are_integers ──────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_amounts_are_integers():
    """试算分润各方金额必须是整数（无小数，无浮点精度问题）。"""
    # 选择一个无法整除的总金额，验证余数处理正确
    rules = json.dumps(
        [
            {"receiver_type": "brand", "receiver_id": "brand_001", "ratio": 3333},
            {"receiver_type": "franchise", "receiver_id": "store_001", "ratio": 3333},
            {"receiver_type": "platform_fee", "receiver_id": "platform", "ratio": 3334},
        ]
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/finance/split/rules/preview?total_fen=10001&rules={rules}",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    d = resp.json()["data"]
    for item in d["preview_items"]:
        assert isinstance(item["amount_fen"], int), (
            f"amount_fen 不是整数: {item['amount_fen']} ({type(item['amount_fen'])})"
        )
    total = sum(item["amount_fen"] for item in d["preview_items"])
    assert total == 10001, f"余数处理后总和 {total} != 10001"
    assert d["amounts_are_integers"] is True


# ── 8. test_split_records_list ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_split_records_list():
    """GET /orders/{id}/records 应返回分账明细列表。"""
    mock_db = _make_mock_db()
    split_order_id = uuid.uuid4()

    sample_records = [
        {
            "id": str(uuid.uuid4()),
            "split_order_id": str(split_order_id),
            "receiver_type": "brand",
            "receiver_id": "brand_001",
            "amount_fen": 2000,
            "split_result": "success",
        },
        {
            "id": str(uuid.uuid4()),
            "split_order_id": str(split_order_id),
            "receiver_type": "franchise",
            "receiver_id": "store_001",
            "amount_fen": 7000,
            "split_result": "pending",
        },
    ]

    mock_rows = []
    for rec in sample_records:
        r = MagicMock()
        r._mapping = rec
        mock_rows.append(r)

    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter(mock_rows))
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("api.split_payment_routes.get_db_with_tenant", return_value=_async_gen(mock_db)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/finance/split/orders/{split_order_id}/records",
                headers=HEADERS,
            )

    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["total"] == 2
    assert len(d["items"]) == 2
    assert d["items"][0]["receiver_type"] == "brand"
    assert d["items"][1]["amount_fen"] == 7000
