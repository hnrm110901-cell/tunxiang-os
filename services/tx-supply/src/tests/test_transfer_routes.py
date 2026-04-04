"""transfer_routes.py — 门店调拨（DB版）路由测试

测试范围（8个测试）：
  - POST /api/v1/transfers                          — 创建调拨申请（正常 / 同门店 → 400）
  - GET  /api/v1/transfers                          — 调拨单列表（正常分页）
  - GET  /api/v1/transfers/{order_id}               — 调拨单详情（正常 / 不存在 → 404）
  - POST /api/v1/transfers/{order_id}/approve       — 审批（库存不足 → 422）
  - POST /api/v1/transfers/{order_id}/ship          — 发货（InsufficientStockError → 422 / 状态错误 → 400）
  - POST /api/v1/transfers/{order_id}/receive       — 收货（正常）
  - POST /api/v1/transfers/{order_id}/cancel        — 取消（正常 / 已发货不可取消 → 400）
  - GET  /api/v1/transfers/inventory-check          — 库存查询（正常 / 不存在 → 404）

技术说明：
  - transfer_routes 依赖 get_db（AsyncSession），通过 dependency_overrides 注入 mock DB
  - transfer_service 函数通过 patch 拦截，不访问真实数据库
  - receive_transfer_order 内有 asyncio.create_task(UniversalPublisher.publish(...))
    通过 patch transfer_service 验证路由层正确处理
"""
from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.transfer_routes import router as transfer_router
from services.transfer_service import InsufficientStockError
from shared.ontology.src.database import get_db

# ─── App 组装 ─────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(transfer_router)

# ─── 公共常量 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_FROM = str(uuid.uuid4())
STORE_TO = str(uuid.uuid4())
INGREDIENT_ID = str(uuid.uuid4())
ORDER_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}

_SVC_MOD = "services.transfer_service"

# ─── DB Mock 工厂 ─────────────────────────────────────────────────────────────


def _mock_db_factory():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


def _db_override():
    mock_db = _mock_db_factory()

    async def _dep():
        yield mock_db

    return _dep


def _client_with_db() -> TestClient:
    """创建带 mock db 覆盖的 TestClient。"""
    app.dependency_overrides[get_db] = _db_override()
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/transfers — 创建调拨申请
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateTransferOrder:
    """POST /api/v1/transfers"""

    def setup_method(self):
        app.dependency_overrides[get_db] = _db_override()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_transfer_success(self):
        """正常创建：返回 order_id + status=draft。"""
        with patch(
            f"{_SVC_MOD}.create_transfer_order",
            new_callable=AsyncMock,
            return_value={
                "order_id": ORDER_ID,
                "status": "draft",
                "from_store_id": STORE_FROM,
                "to_store_id": STORE_TO,
                "item_count": 1,
                "created_at": "2026-04-04T00:00:00+00:00",
            },
        ):
            resp = TestClient(app).post(
                "/api/v1/transfers",
                json={
                    "from_store_id": STORE_FROM,
                    "to_store_id": STORE_TO,
                    "items": [
                        {
                            "ingredient_id": INGREDIENT_ID,
                            "ingredient_name": "大米",
                            "requested_quantity": "20.0",
                            "unit": "kg",
                        }
                    ],
                },
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "draft"
        assert data["order_id"] == ORDER_ID

    def test_create_transfer_same_store_400(self):
        """调出调入门店相同 → ValueError → 400。"""
        with patch(
            f"{_SVC_MOD}.create_transfer_order",
            new_callable=AsyncMock,
            side_effect=ValueError("调出门店和调入门店不能是同一门店"),
        ):
            resp = TestClient(app).post(
                "/api/v1/transfers",
                json={
                    "from_store_id": STORE_FROM,
                    "to_store_id": STORE_FROM,
                    "items": [
                        {
                            "ingredient_id": INGREDIENT_ID,
                            "ingredient_name": "大米",
                            "requested_quantity": "10.0",
                            "unit": "kg",
                        }
                    ],
                },
                headers=HEADERS,
            )

        assert resp.status_code == 400
        assert "同一门店" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/transfers — 调拨单列表
# ═══════════════════════════════════════════════════════════════════════════════


class TestListTransferOrders:
    """GET /api/v1/transfers"""

    def setup_method(self):
        app.dependency_overrides[get_db] = _db_override()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_list_transfers_returns_paginated_result(self):
        """列表查询：返回 items + total + page + size 分页结构。"""
        with patch(
            f"{_SVC_MOD}.list_transfer_orders",
            new_callable=AsyncMock,
            return_value={
                "items": [{"order_id": ORDER_ID, "status": "draft"}],
                "total": 1,
                "page": 1,
                "size": 20,
            },
        ):
            resp = TestClient(app).get("/api/v1/transfers", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["page"] == 1
        assert data["size"] == 20


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/transfers/{order_id} — 调拨单详情
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetTransferOrder:
    """GET /api/v1/transfers/{order_id}"""

    def setup_method(self):
        app.dependency_overrides[get_db] = _db_override()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_get_transfer_found(self):
        """已存在的调拨单：返回详情含 items 列表。"""
        with patch(
            f"{_SVC_MOD}.get_transfer_order",
            new_callable=AsyncMock,
            return_value={
                "order_id": ORDER_ID,
                "status": "draft",
                "items": [],
            },
        ):
            resp = TestClient(app).get(f"/api/v1/transfers/{ORDER_ID}", headers=HEADERS)

        assert resp.status_code == 200
        assert resp.json()["data"]["order_id"] == ORDER_ID

    def test_get_transfer_not_found_404(self):
        """不存在的调拨单 → ValueError → 404。"""
        with patch(
            f"{_SVC_MOD}.get_transfer_order",
            new_callable=AsyncMock,
            side_effect=ValueError(f"调拨单 {ORDER_ID} 不存在"),
        ):
            resp = TestClient(app).get(f"/api/v1/transfers/{ORDER_ID}", headers=HEADERS)

        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/transfers/{order_id}/approve — 审批
# ═══════════════════════════════════════════════════════════════════════════════


class TestApproveTransferOrder:
    """POST /api/v1/transfers/{order_id}/approve"""

    def setup_method(self):
        app.dependency_overrides[get_db] = _db_override()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_approve_insufficient_stock_422(self):
        """from_store 库存不足 → InsufficientStockError → 422。"""
        with patch(
            f"{_SVC_MOD}.approve_transfer_order",
            new_callable=AsyncMock,
            side_effect=InsufficientStockError("大米 调出门店库存不足：现有 5kg，需要 20kg"),
        ):
            resp = TestClient(app).post(
                f"/api/v1/transfers/{ORDER_ID}/approve",
                json={"approved_by": str(uuid.uuid4()), "approved_items": []},
                headers=HEADERS,
            )

        assert resp.status_code == 422
        assert "库存不足" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/transfers/{order_id}/ship — 发货
# ═══════════════════════════════════════════════════════════════════════════════


class TestShipTransferOrder:
    """POST /api/v1/transfers/{order_id}/ship"""

    def setup_method(self):
        app.dependency_overrides[get_db] = _db_override()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_ship_insufficient_stock_422(self):
        """发货时库存不足 → InsufficientStockError → 422。"""
        with patch(
            f"{_SVC_MOD}.ship_transfer_order",
            new_callable=AsyncMock,
            side_effect=InsufficientStockError("大米 库存不足: 现有 3kg，发货需要 10kg"),
        ):
            resp = TestClient(app).post(
                f"/api/v1/transfers/{ORDER_ID}/ship",
                json={
                    "shipped_items": [
                        {"item_id": str(uuid.uuid4()), "shipped_quantity": "10.0"},
                    ],
                    "operator_id": str(uuid.uuid4()),
                },
                headers=HEADERS,
            )

        assert resp.status_code == 422

    def test_ship_wrong_status_400(self):
        """调拨单非 approved 状态发货 → ValueError → 400。"""
        with patch(
            f"{_SVC_MOD}.ship_transfer_order",
            new_callable=AsyncMock,
            side_effect=ValueError("调拨单状态为 draft，必须先审批才能发货"),
        ):
            resp = TestClient(app).post(
                f"/api/v1/transfers/{ORDER_ID}/ship",
                json={"shipped_items": [], "operator_id": None},
                headers=HEADERS,
            )

        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/transfers/{order_id}/receive — 确认收货
# ═══════════════════════════════════════════════════════════════════════════════


class TestReceiveTransferOrder:
    """POST /api/v1/transfers/{order_id}/receive"""

    def setup_method(self):
        app.dependency_overrides[get_db] = _db_override()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_receive_success_returns_received_status(self):
        """正常收货：返回 status=received，包含 inventory_results 和 transit_losses。"""
        with patch(
            f"{_SVC_MOD}.receive_transfer_order",
            new_callable=AsyncMock,
            return_value={
                "order_id": ORDER_ID,
                "status": "received",
                "received_at": "2026-04-04T12:00:00+00:00",
                "inventory_results": [
                    {
                        "ingredient_name": "大米",
                        "received_quantity": 18.0,
                        "qty_before": 10.0,
                        "qty_after": 28.0,
                    }
                ],
                "transit_losses": [],
            },
        ):
            resp = TestClient(app).post(
                f"/api/v1/transfers/{ORDER_ID}/receive",
                json={
                    "received_items": [
                        {"item_id": str(uuid.uuid4()), "received_quantity": "18.0"},
                    ],
                    "operator_id": str(uuid.uuid4()),
                },
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "received"
        assert data["order_id"] == ORDER_ID
        assert len(data["inventory_results"]) == 1
        assert data["transit_losses"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/transfers/{order_id}/cancel — 取消调拨
# ═══════════════════════════════════════════════════════════════════════════════


class TestCancelTransferOrder:
    """POST /api/v1/transfers/{order_id}/cancel"""

    def setup_method(self):
        app.dependency_overrides[get_db] = _db_override()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_cancel_success(self):
        """正常取消：返回 status=cancelled。"""
        with patch(
            f"{_SVC_MOD}.cancel_transfer_order",
            new_callable=AsyncMock,
            return_value={"order_id": ORDER_ID, "status": "cancelled"},
        ):
            resp = TestClient(app).post(
                f"/api/v1/transfers/{ORDER_ID}/cancel",
                json={"cancelled_by": str(uuid.uuid4()), "reason": "计划变更"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "cancelled"

    def test_cancel_shipped_order_400(self):
        """已发货的调拨单不可取消 → ValueError → 400。"""
        with patch(
            f"{_SVC_MOD}.cancel_transfer_order",
            new_callable=AsyncMock,
            side_effect=ValueError("调拨单状态为 shipped，已发货/收货的单据不能取消"),
        ):
            resp = TestClient(app).post(
                f"/api/v1/transfers/{ORDER_ID}/cancel",
                json={"cancelled_by": str(uuid.uuid4()), "reason": "测试"},
                headers=HEADERS,
            )

        assert resp.status_code == 400
        assert "不能取消" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/transfers/inventory-check — 库存查询
# ═══════════════════════════════════════════════════════════════════════════════


class TestInventoryCheck:
    """GET /api/v1/transfers/inventory-check"""

    def setup_method(self):
        app.dependency_overrides[get_db] = _db_override()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_inventory_check_success(self):
        """正常查询：返回门店食材库存详情。"""
        with patch(
            f"{_SVC_MOD}.get_store_ingredient_stock",
            new_callable=AsyncMock,
            return_value={
                "store_id": STORE_FROM,
                "ingredient_id": INGREDIENT_ID,
                "ingredient_name": "大米",
                "quantity": 50.0,
                "unit": "kg",
                "unit_price_fen": 800,
                "status": "normal",
                "min_quantity": 10.0,
            },
        ):
            resp = TestClient(app).get(
                f"/api/v1/transfers/inventory-check"
                f"?store_id={STORE_FROM}&ingredient_id={INGREDIENT_ID}",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["ingredient_name"] == "大米"
        assert data["quantity"] == 50.0
        assert data["status"] == "normal"

    def test_inventory_check_not_found_404(self):
        """食材不存在 → ValueError → 404。"""
        with patch(
            f"{_SVC_MOD}.get_store_ingredient_stock",
            new_callable=AsyncMock,
            side_effect=ValueError(f"原料 {INGREDIENT_ID} 在门店 {STORE_FROM} 不存在"),
        ):
            resp = TestClient(app).get(
                f"/api/v1/transfers/inventory-check"
                f"?store_id={STORE_FROM}&ingredient_id={INGREDIENT_ID}",
                headers=HEADERS,
            )

        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]
