"""交易流程集成测试 — 开台 / 点餐 / 结账 / 退款 完整闭环

使用 httpx.AsyncClient 直接调用 tx-trade FastAPI app，
DB 依赖通过 dependency_overrides 替换为 Mock。

测试场景:
  1. 开台 → 获取桌台列表 → 选择空闲桌 → 开台
  2. 点餐 → 获取菜单 → 添加菜品 → 提交订单
  3. 结账 → 选择支付方式 → 确认支付 → 订单完成
  4. 退款 → 申请退款 → 审批退款
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
    MOCK_CUSTOMER_ID,
    MOCK_STORE_ID,
    MOCK_TENANT_ID,
    MOCK_USER_ID,
    assert_err,
    assert_ok,
    make_item_data,
    make_order_data,
    make_payment_data,
)

# ─── 测试用 App 构建 ──────────────────────────────────────────────────────────

# 为避免 lifespan（init_db 等）和真实 DB 依赖，
# 构建一个精简的 FastAPI app 只挂载需要测试的路由。

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db


def _build_trade_app(mock_session: AsyncMock) -> FastAPI:
    """构建测试用 tx-trade app，DB 依赖替换为 mock。"""
    app = FastAPI(title="test-tx-trade")

    # 注册核心路由
    from services.tx_trade.src.api.orders import router as orders_router
    from services.tx_trade.src.api.table_routes import router as table_router
    from services.tx_trade.src.api.refund_routes import router as refund_router

    app.include_router(orders_router)
    app.include_router(table_router)
    app.include_router(refund_router)

    # override DB 依赖
    async def _mock_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = _mock_get_db
    return app


# ─── Mock 数据工厂 ──────────────────────────────────────────────────────────

_ORDER_ID = str(uuid.uuid4())
_PAYMENT_ID = str(uuid.uuid4())
_ITEM_ID = str(uuid.uuid4())


def _mock_order_result(
    order_id: str = _ORDER_ID,
    status: str = "open",
    total_fen: int = 0,
) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "store_id": MOCK_STORE_ID,
        "order_type": "dine_in",
        "table_no": "A1",
        "status": status,
        "total_fen": total_fen,
        "items": [],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def _mock_item_result(item_id: str = _ITEM_ID) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "dish_id": "dish-001",
        "dish_name": "宫保鸡丁",
        "quantity": 1,
        "unit_price_fen": 3800,
        "subtotal_fen": 3800,
    }


def _mock_payment_result(payment_id: str = _PAYMENT_ID) -> dict[str, Any]:
    return {
        "payment_id": payment_id,
        "method": "wechat",
        "amount_fen": 3800,
        "status": "paid",
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 创建订单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_create_order_success(mock_db_session: AsyncMock) -> None:
    """创建堂食订单 → 返回 ok=True + 订单数据。"""
    with patch(
        "services.tx_trade.src.services.order_service.OrderService.create_order",
        new_callable=AsyncMock,
        return_value=_mock_order_result(),
    ):
        app = _build_trade_app(mock_db_session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/trade/orders",
                json=make_order_data(),
                headers=DEFAULT_HEADERS,
            )
        assert resp.status_code == 200
        data = assert_ok(resp.json())
        assert data["order_id"] == _ORDER_ID
        assert data["status"] == "open"


@pytest.mark.asyncio
async def test_create_order_missing_tenant() -> None:
    """缺少 X-Tenant-ID → 400。"""
    mock_session = AsyncMock()
    app = _build_trade_app(mock_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/trade/orders",
            json=make_order_data(),
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 400


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 添加菜品
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_add_item_to_order(mock_db_session: AsyncMock) -> None:
    """向订单添加菜品 → 返回 ok=True + 菜品明细。"""
    with patch(
        "services.tx_trade.src.services.order_service.OrderService.add_item",
        new_callable=AsyncMock,
        return_value=_mock_item_result(),
    ):
        app = _build_trade_app(mock_db_session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/v1/trade/orders/{_ORDER_ID}/items",
                json=make_item_data(),
                headers=DEFAULT_HEADERS,
            )
        assert resp.status_code == 200
        data = assert_ok(resp.json())
        assert data["dish_name"] == "宫保鸡丁"
        assert data["subtotal_fen"] == 3800


@pytest.mark.asyncio
async def test_add_multiple_items(mock_db_session: AsyncMock) -> None:
    """添加多个菜品 → 每次均返回成功。"""
    items = [
        make_item_data(dish_id="dish-001", dish_name="宫保鸡丁", unit_price_fen=3800),
        make_item_data(dish_id="dish-002", dish_name="水煮鱼", unit_price_fen=6800),
        make_item_data(dish_id="dish-003", dish_name="米饭", quantity=2, unit_price_fen=300),
    ]
    for i, item in enumerate(items):
        item_result = _mock_item_result(item_id=f"item-{i}")
        item_result["dish_name"] = item["dish_name"]
        item_result["unit_price_fen"] = item["unit_price_fen"]
        with patch(
            "services.tx_trade.src.services.order_service.OrderService.add_item",
            new_callable=AsyncMock,
            return_value=item_result,
        ):
            app = _build_trade_app(mock_db_session)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    f"/api/v1/trade/orders/{_ORDER_ID}/items",
                    json=item,
                    headers=DEFAULT_HEADERS,
                )
            assert resp.status_code == 200
            assert_ok(resp.json())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 结账
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_settle_order(mock_db_session: AsyncMock) -> None:
    """结算订单 → 返回 ok=True + 结算后订单（status=settled）。"""
    settled = _mock_order_result(status="settled", total_fen=10900)
    with patch(
        "services.tx_trade.src.services.order_service.OrderService.settle_order",
        new_callable=AsyncMock,
        return_value=settled,
    ):
        app = _build_trade_app(mock_db_session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/v1/trade/orders/{_ORDER_ID}/settle",
                headers=DEFAULT_HEADERS,
            )
        assert resp.status_code == 200
        data = assert_ok(resp.json())
        assert data["status"] == "settled"


@pytest.mark.asyncio
async def test_create_payment(mock_db_session: AsyncMock) -> None:
    """创建支付记录 → 返回 ok=True + 支付信息。"""
    with patch(
        "services.tx_trade.src.services.payment_service.PaymentService.create_payment",
        new_callable=AsyncMock,
        return_value=_mock_payment_result(),
    ):
        app = _build_trade_app(mock_db_session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/v1/trade/orders/{_ORDER_ID}/payments",
                json=make_payment_data(),
                headers=DEFAULT_HEADERS,
            )
        assert resp.status_code == 200
        data = assert_ok(resp.json())
        assert data["payment_id"] == _PAYMENT_ID
        assert data["status"] == "paid"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 退款
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_refund_full(mock_db_session: AsyncMock) -> None:
    """全额退款 → 返回 ok=True + 退款信息。"""
    refund_result = {
        "order_id": _ORDER_ID,
        "payment_id": _PAYMENT_ID,
        "refund_id": str(uuid.uuid4()),
        "amount_fen": 3800,
        "status": "refunded",
    }
    with patch(
        "services.tx_trade.src.services.payment_service.PaymentService.process_refund",
        new_callable=AsyncMock,
        return_value=refund_result,
    ):
        app = _build_trade_app(mock_db_session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/v1/trade/orders/{_ORDER_ID}/refund",
                json={
                    "payment_id": _PAYMENT_ID,
                    "amount_fen": 3800,
                    "refund_type": "full",
                    "reason": "顾客要求",
                },
                headers=DEFAULT_HEADERS,
            )
        assert resp.status_code == 200
        data = assert_ok(resp.json())
        assert data["status"] == "refunded"
        assert data["amount_fen"] == 3800


@pytest.mark.asyncio
async def test_refund_submit_via_refund_route() -> None:
    """通过退款路由提交退款申请（Mock 实现）→ 返回 ok=True。"""
    mock_session = AsyncMock()
    app = _build_trade_app(mock_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/trade/refunds",
            json={
                "order_id": _ORDER_ID,
                "refund_type": "full",
                "refund_amount_fen": 3800,
                "reasons": ["菜品不满意"],
                "description": "味道不好",
            },
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert "refund_id" in data
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_refund_invalid_amount() -> None:
    """退款金额为 0 → 400。"""
    mock_session = AsyncMock()
    app = _build_trade_app(mock_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/trade/refunds",
            json={
                "order_id": _ORDER_ID,
                "refund_type": "full",
                "refund_amount_fen": 0,
                "reasons": ["test"],
            },
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 400


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 获取订单详情
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_get_order_found(mock_db_session: AsyncMock) -> None:
    """获取已存在订单 → ok=True。"""
    with patch(
        "services.tx_trade.src.services.order_service.OrderService.get_order",
        new_callable=AsyncMock,
        return_value=_mock_order_result(),
    ):
        app = _build_trade_app(mock_db_session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/trade/orders/{_ORDER_ID}",
                headers=DEFAULT_HEADERS,
            )
        assert resp.status_code == 200
        assert_ok(resp.json())


@pytest.mark.asyncio
async def test_get_order_not_found(mock_db_session: AsyncMock) -> None:
    """获取不存在订单 → 404。"""
    with patch(
        "services.tx_trade.src.services.order_service.OrderService.get_order",
        new_callable=AsyncMock,
        return_value=None,
    ):
        app = _build_trade_app(mock_db_session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/trade/orders/{_ORDER_ID}",
                headers=DEFAULT_HEADERS,
            )
        assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 桌台操作
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_table_status_board(mock_db_session: AsyncMock) -> None:
    """获取桌台看板 → ok=True。"""
    board_data = {
        "total": 20,
        "occupied": 8,
        "available": 12,
        "tables": [],
    }
    with patch(
        "services.tx_trade.src.services.table_operations.get_table_status_board",
        new_callable=AsyncMock,
        return_value=board_data,
    ):
        app = _build_trade_app(mock_db_session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/tables/status-board?store_id={MOCK_STORE_ID}",
                headers=DEFAULT_HEADERS,
            )
        assert resp.status_code == 200
        data = assert_ok(resp.json())
        assert data["total"] == 20


@pytest.mark.asyncio
async def test_transfer_table(mock_db_session: AsyncMock) -> None:
    """转台 → ok=True。"""
    transfer_result = {"from_table": "A1", "to_table": "A2", "status": "transferred"}
    with patch(
        "services.tx_trade.src.services.table_operations.transfer_table",
        new_callable=AsyncMock,
        return_value=transfer_result,
    ):
        app = _build_trade_app(mock_db_session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/tables/transfer",
                json={
                    "from_table_id": str(uuid.uuid4()),
                    "to_table_id": str(uuid.uuid4()),
                    "order_id": str(uuid.uuid4()),
                },
                headers=DEFAULT_HEADERS,
            )
        assert resp.status_code == 200
        assert_ok(resp.json())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. 完整交易闭环 — 端到端
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_full_trade_cycle(mock_db_session: AsyncMock) -> None:
    """完整闭环: 创建订单 → 添加菜品 → 结算 → 支付 → 退款。

    每步验证返回格式 {"ok": true, "data": {...}}。
    """
    order_result = _mock_order_result()
    item_result = _mock_item_result()
    settled_result = _mock_order_result(status="settled", total_fen=3800)
    payment_result = _mock_payment_result()
    refund_result = {
        "order_id": _ORDER_ID,
        "payment_id": _PAYMENT_ID,
        "refund_id": str(uuid.uuid4()),
        "amount_fen": 3800,
        "status": "refunded",
    }

    app = _build_trade_app(mock_db_session)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: 创建订单
        with patch(
            "services.tx_trade.src.services.order_service.OrderService.create_order",
            new_callable=AsyncMock,
            return_value=order_result,
        ):
            resp = await client.post(
                "/api/v1/trade/orders",
                json=make_order_data(),
                headers=DEFAULT_HEADERS,
            )
            assert resp.status_code == 200
            step1 = assert_ok(resp.json())
            oid = step1["order_id"]

        # Step 2: 添加菜品
        with patch(
            "services.tx_trade.src.services.order_service.OrderService.add_item",
            new_callable=AsyncMock,
            return_value=item_result,
        ):
            resp = await client.post(
                f"/api/v1/trade/orders/{oid}/items",
                json=make_item_data(),
                headers=DEFAULT_HEADERS,
            )
            assert resp.status_code == 200
            assert_ok(resp.json())

        # Step 3: 结算
        with patch(
            "services.tx_trade.src.services.order_service.OrderService.settle_order",
            new_callable=AsyncMock,
            return_value=settled_result,
        ):
            resp = await client.post(
                f"/api/v1/trade/orders/{oid}/settle",
                headers=DEFAULT_HEADERS,
            )
            assert resp.status_code == 200
            step3 = assert_ok(resp.json())
            assert step3["status"] == "settled"

        # Step 4: 支付
        with patch(
            "services.tx_trade.src.services.payment_service.PaymentService.create_payment",
            new_callable=AsyncMock,
            return_value=payment_result,
        ):
            resp = await client.post(
                f"/api/v1/trade/orders/{oid}/payments",
                json=make_payment_data(),
                headers=DEFAULT_HEADERS,
            )
            assert resp.status_code == 200
            step4 = assert_ok(resp.json())
            pid = step4["payment_id"]

        # Step 5: 退款
        with patch(
            "services.tx_trade.src.services.payment_service.PaymentService.process_refund",
            new_callable=AsyncMock,
            return_value=refund_result,
        ):
            resp = await client.post(
                f"/api/v1/trade/orders/{oid}/refund",
                json={
                    "payment_id": pid,
                    "amount_fen": 3800,
                    "refund_type": "full",
                    "reason": "顾客要求退款",
                },
                headers=DEFAULT_HEADERS,
            )
            assert resp.status_code == 200
            step5 = assert_ok(resp.json())
            assert step5["status"] == "refunded"
