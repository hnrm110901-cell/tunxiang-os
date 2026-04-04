"""外卖接单流程集成测试 — 推单 / 接单 / 出餐 / 配送 / 完成 / 取消

使用 httpx.AsyncClient 直接调用 tx-trade FastAPI app（精简版），
DB 依赖通过 dependency_overrides 替换为 Mock。

测试场景:
  1. 外卖订单推入 → 接单
  2. 出餐标记 → 配送
  3. 完成 / 取消
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import (
    DEFAULT_HEADERS,
    MOCK_STORE_ID,
    MOCK_TENANT_ID,
    assert_err,
    assert_ok,
)

# ─── 测试用 App 构建 ──────────────────────────────────────────────────────────

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db


def _build_delivery_app(mock_session: AsyncMock) -> FastAPI:
    """构建仅挂载外卖路由的测试 app。"""
    app = FastAPI(title="test-delivery")

    from services.tx_trade.src.api.delivery_orders_routes import router as delivery_orders_router

    app.include_router(delivery_orders_router)

    async def _mock_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = _mock_get_db
    return app


# ─── Mock 数据 ────────────────────────────────────────────────────────────────

_ORDER_ID = uuid.uuid4()


def _mock_delivery_order(
    *,
    order_id: uuid.UUID = _ORDER_ID,
    status: str = "pending_accept",
    platform: str = "meituan",
) -> MagicMock:
    """创建一个模拟 DeliveryOrder ORM 对象。"""
    order = MagicMock()
    order.id = order_id
    order.tenant_id = uuid.UUID(MOCK_TENANT_ID)
    order.platform = platform
    order.platform_name = platform
    order.platform_order_id = f"MT{uuid.uuid4().hex[:10]}"
    order.platform_order_no = f"MT2026040200001"
    order.status = status
    order.store_id = uuid.UUID(MOCK_STORE_ID)
    order.customer_name = "张三"
    order.customer_phone = "138****1234"
    order.delivery_address = "长沙市岳麓区麓谷大道100号"
    order.items_json = [{"name": "宫保鸡丁", "qty": 1, "price_fen": 3800}]
    order.special_request = "少放辣"
    order.notes = None
    order.total_fen = 3800
    order.actual_revenue_fen = 3420
    order.commission_fen = 380
    order.estimated_delivery_min = 30
    order.estimated_prep_time = 15
    order.rider_name = "李四"
    order.rider_phone = "139****5678"
    order.accepted_at = None
    order.ready_at = None
    order.completed_at = None
    order.delivering_at = None
    order.created_at = datetime.now(tz=timezone.utc)
    return order


def _setup_mock_session_with_order(
    mock_session: AsyncMock,
    order: MagicMock,
) -> None:
    """配置 mock session 的 execute 返回指定 order。"""
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = order
    mock_session.execute = AsyncMock(return_value=result_mock)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. Mock 订单生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_mock_new_delivery_order(mock_db_session: AsyncMock) -> None:
    """通过 mock 端点生成外卖订单 → ok=True。"""
    app = _build_delivery_app(mock_db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/delivery/mock/new-order",
            json={"store_id": MOCK_STORE_ID, "platform": "meituan"},
            headers=DEFAULT_HEADERS,
        )
    # mock 端点可能返回 200 或 201
    assert resp.status_code in (200, 201)
    body = resp.json()
    assert body.get("ok") is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 状态流转 — accepted → cooking → ready → delivering → completed
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_status_accepted_to_cooking(mock_db_session: AsyncMock) -> None:
    """accepted → cooking 状态转换成功。"""
    order = _mock_delivery_order(status="accepted")
    _setup_mock_session_with_order(mock_db_session, order)

    app = _build_delivery_app(mock_db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            f"/api/v1/delivery/orders/{_ORDER_ID}/status",
            json={"status": "cooking"},
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert data["status"] == "cooking"


@pytest.mark.asyncio
async def test_status_cooking_to_ready(mock_db_session: AsyncMock) -> None:
    """cooking → ready 状态转换成功。"""
    order = _mock_delivery_order(status="cooking")
    _setup_mock_session_with_order(mock_db_session, order)

    app = _build_delivery_app(mock_db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            f"/api/v1/delivery/orders/{_ORDER_ID}/status",
            json={"status": "ready"},
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert data["status"] == "ready"


@pytest.mark.asyncio
async def test_status_ready_to_delivering(mock_db_session: AsyncMock) -> None:
    """ready → delivering 状态转换成功。"""
    order = _mock_delivery_order(status="ready")
    _setup_mock_session_with_order(mock_db_session, order)

    app = _build_delivery_app(mock_db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            f"/api/v1/delivery/orders/{_ORDER_ID}/status",
            json={"status": "delivering"},
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert data["status"] == "delivering"


@pytest.mark.asyncio
async def test_status_delivering_to_completed(mock_db_session: AsyncMock) -> None:
    """delivering → completed 状态转换成功。"""
    order = _mock_delivery_order(status="delivering")
    _setup_mock_session_with_order(mock_db_session, order)

    app = _build_delivery_app(mock_db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            f"/api/v1/delivery/orders/{_ORDER_ID}/status",
            json={"status": "completed"},
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert data["status"] == "completed"


@pytest.mark.asyncio
async def test_status_ready_to_completed_direct(mock_db_session: AsyncMock) -> None:
    """ready → completed 直接完成（自取场景）。"""
    order = _mock_delivery_order(status="ready")
    _setup_mock_session_with_order(mock_db_session, order)

    app = _build_delivery_app(mock_db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            f"/api/v1/delivery/orders/{_ORDER_ID}/status",
            json={"status": "completed"},
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert data["status"] == "completed"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 非法状态转换
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_invalid_status_transition(mock_db_session: AsyncMock) -> None:
    """cooking → completed 非法跳跃 → 409 Conflict。"""
    order = _mock_delivery_order(status="cooking")
    _setup_mock_session_with_order(mock_db_session, order)

    app = _build_delivery_app(mock_db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            f"/api/v1/delivery/orders/{_ORDER_ID}/status",
            json={"status": "completed"},
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_backward_status_transition(mock_db_session: AsyncMock) -> None:
    """ready → cooking 反向转换 → 拒绝（422 或 409）。"""
    order = _mock_delivery_order(status="ready")
    _setup_mock_session_with_order(mock_db_session, order)

    app = _build_delivery_app(mock_db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            f"/api/v1/delivery/orders/{_ORDER_ID}/status",
            json={"status": "cooking"},
            headers=DEFAULT_HEADERS,
        )
    # ready 的合法目标只有 delivering 和 completed
    assert resp.status_code in (409, 422)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 取消订单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_cancel_delivery_order(mock_db_session: AsyncMock) -> None:
    """取消外卖订单 → ok=True。"""
    order = _mock_delivery_order(status="accepted")
    _setup_mock_session_with_order(mock_db_session, order)

    app = _build_delivery_app(mock_db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/delivery/orders/{_ORDER_ID}/cancel",
            json={"reason": "顾客取消"},
            headers=DEFAULT_HEADERS,
        )
    # 取消端点返回 200
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True


@pytest.mark.asyncio
async def test_cancel_order_empty_reason(mock_db_session: AsyncMock) -> None:
    """取消原因为空 → 422 校验失败。"""
    app = _build_delivery_app(mock_db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/delivery/orders/{_ORDER_ID}/cancel",
            json={"reason": ""},
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 不存在的订单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_status_update_nonexistent_order(mock_db_session: AsyncMock) -> None:
    """更新不存在订单状态 → 404。"""
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    mock_db_session.execute = AsyncMock(return_value=result_mock)

    app = _build_delivery_app(mock_db_session)
    transport = ASGITransport(app=app)
    fake_id = uuid.uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            f"/api/v1/delivery/orders/{fake_id}/status",
            json={"status": "cooking"},
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. Webhook mock
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_meituan_webhook_mock(mock_db_session: AsyncMock) -> None:
    """美团 Webhook mock → 200。"""
    app = _build_delivery_app(mock_db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/delivery/webhook/meituan",
            json={"event": "order.new", "data": {}},
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_eleme_webhook_mock(mock_db_session: AsyncMock) -> None:
    """饿了么 Webhook mock → 200。"""
    app = _build_delivery_app(mock_db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/delivery/webhook/eleme",
            json={"event": "order.new", "data": {}},
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
