"""receiving_routes.py — 收货验收 + 退货 + 调拨（旧接口）路由测试

测试范围（9个测试）：
  - POST /api/v1/supply/receiving              — 创建收货验收单（全pass / 含质量问题partial）
  - POST /api/v1/supply/receiving/{id}/reject  — 退货（正常 / 数量为负 → Pydantic 422）
  - POST /api/v1/supply/transfers              — 门店调拨（正常 / 同门店 → 400 / 空items → 400）
  - POST /api/v1/supply/transfers/{id}/confirm — 调拨确认（sender角色 / 非法角色 → 422）
  - GET  /api/v1/supply/warehouse/stock        — 中央仓库存查询（空数据 / 有低库存数据）

技术说明：
  - receiving_routes.py 已修复为顶层导入（from ..services.receiving_service import ...）
  - patch 路径：api.receiving_routes.<func_name>（路由模块已绑定的名称）
"""

from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.receiving_routes import router as receiving_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── App 组装 ─────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(receiving_router)
client = TestClient(app)

# ─── 公共常量 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_A = str(uuid.uuid4())
STORE_B = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}

# patch 路径：路由模块已绑定的顶层名称
_ROUTE_MOD = "api.receiving_routes"


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/supply/receiving — 创建收货验收单
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateReceiving:
    """POST /api/v1/supply/receiving"""

    def test_create_receiving_all_pass(self):
        """所有原料质量 pass：status=accepted，all_pass=True，shortage=2.0。"""
        mock_result = {
            "receiving_id": f"rcv_{uuid.uuid4().hex[:8]}",
            "purchase_order_id": str(uuid.uuid4()),
            "receiver_id": str(uuid.uuid4()),
            "tenant_id": TENANT_ID,
            "items": [],
            "total_ordered": 150.0,
            "total_received": 148.0,
            "shortage": 2.0,
            "quality_issues": [],
            "quality_issue_count": 0,
            "all_pass": True,
            "status": "accepted",
            "created_at": _now_iso(),
        }
        with patch(f"{_ROUTE_MOD}.create_receiving", new_callable=AsyncMock, return_value=mock_result):
            body = {
                "purchase_order_id": str(uuid.uuid4()),
                "receiver_id": str(uuid.uuid4()),
                "items": [
                    {
                        "ingredient_id": str(uuid.uuid4()),
                        "name": "猪肉",
                        "ordered_qty": 100.0,
                        "received_qty": 98.0,
                        "quality": "pass",
                        "notes": "",
                    },
                    {
                        "ingredient_id": str(uuid.uuid4()),
                        "name": "白菜",
                        "ordered_qty": 50.0,
                        "received_qty": 50.0,
                        "quality": "pass",
                        "notes": "",
                    },
                ],
            }
            resp = client.post("/api/v1/supply/receiving", json=body, headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["all_pass"] is True
        assert data["status"] == "accepted"
        assert data["quality_issue_count"] == 0
        assert data["shortage"] == 2.0

    def test_create_receiving_with_quality_issue(self):
        """部分原料质量 fail：status=partial，quality_issue_count=1。"""
        mock_result = {
            "receiving_id": f"rcv_{uuid.uuid4().hex[:8]}",
            "purchase_order_id": str(uuid.uuid4()),
            "receiver_id": str(uuid.uuid4()),
            "tenant_id": TENANT_ID,
            "items": [],
            "total_ordered": 50.0,
            "total_received": 40.0,
            "shortage": 10.0,
            "quality_issues": [{"ingredient_id": "i1", "quality": "fail"}],
            "quality_issue_count": 1,
            "all_pass": False,
            "status": "partial",
            "created_at": _now_iso(),
        }
        with patch(f"{_ROUTE_MOD}.create_receiving", new_callable=AsyncMock, return_value=mock_result):
            body = {
                "purchase_order_id": str(uuid.uuid4()),
                "receiver_id": str(uuid.uuid4()),
                "items": [
                    {
                        "ingredient_id": str(uuid.uuid4()),
                        "name": "牛肉",
                        "ordered_qty": 50.0,
                        "received_qty": 40.0,
                        "quality": "fail",
                        "notes": "变质",
                    },
                ],
            }
            resp = client.post("/api/v1/supply/receiving", json=body, headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["all_pass"] is False
        assert data["status"] == "partial"
        assert data["quality_issue_count"] == 1
        assert data["receiving_id"].startswith("rcv_")


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/supply/receiving/{id}/reject — 退货
# ═══════════════════════════════════════════════════════════════════════════════


class TestRejectItem:
    """POST /api/v1/supply/receiving/{receiving_id}/reject"""

    def test_reject_item_success(self):
        """正常退货：rejection_id 以 rej_ 开头，status=pending_return。"""
        receiving_id = f"rcv_{uuid.uuid4().hex[:8]}"
        item_id = str(uuid.uuid4())
        mock_result = {
            "rejection_id": f"rej_{uuid.uuid4().hex[:8]}",
            "receiving_id": receiving_id,
            "item_id": item_id,
            "reason": "变质无法使用",
            "quantity": 10.0,
            "tenant_id": TENANT_ID,
            "status": "pending_return",
            "created_at": _now_iso(),
        }
        with patch(f"{_ROUTE_MOD}.reject_item", new_callable=AsyncMock, return_value=mock_result):
            body = {"item_id": item_id, "reason": "变质无法使用", "quantity": 10.0}
            resp = client.post(
                f"/api/v1/supply/receiving/{receiving_id}/reject",
                json=body,
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["rejection_id"].startswith("rej_")
        assert data["status"] == "pending_return"
        assert data["receiving_id"] == receiving_id

    def test_reject_item_negative_quantity_422(self):
        """退货数量为负（违反 Field(gt=0)）：Pydantic 验证失败 → 422。"""
        receiving_id = f"rcv_{uuid.uuid4().hex[:8]}"
        body = {"item_id": str(uuid.uuid4()), "reason": "测试", "quantity": -1.0}
        resp = client.post(
            f"/api/v1/supply/receiving/{receiving_id}/reject",
            json=body,
            headers=HEADERS,
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/supply/transfers — 门店调拨（旧接口）
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateTransferOld:
    """POST /api/v1/supply/transfers（老版本 receiving_service）"""

    def test_create_transfer_success(self):
        """正常创建调拨单：transfer_id 以 tf_ 开头，status=pending，item_count=1。"""
        mock_result = {
            "transfer_id": f"tf_{uuid.uuid4().hex[:8]}",
            "from_store_id": STORE_A,
            "to_store_id": STORE_B,
            "items": [],
            "item_count": 1,
            "tenant_id": TENANT_ID,
            "status": "pending",
            "sender_confirmed": False,
            "receiver_confirmed": False,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        with patch(f"{_ROUTE_MOD}.create_transfer", new_callable=AsyncMock, return_value=mock_result):
            body = {
                "from_store_id": STORE_A,
                "to_store_id": STORE_B,
                "items": [{"ingredient_id": str(uuid.uuid4()), "name": "大米", "quantity": 20.0, "unit": "kg"}],
            }
            resp = client.post("/api/v1/supply/transfers", json=body, headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["transfer_id"].startswith("tf_")
        assert data["status"] == "pending"
        assert data["sender_confirmed"] is False
        assert data["receiver_confirmed"] is False

    def test_create_transfer_same_store_400(self):
        """调出调入是同一门店：ValueError → 400。"""
        with patch(
            f"{_ROUTE_MOD}.create_transfer",
            new_callable=AsyncMock,
            side_effect=ValueError("Cannot transfer to the same store"),
        ):
            body = {
                "from_store_id": STORE_A,
                "to_store_id": STORE_A,
                "items": [{"ingredient_id": str(uuid.uuid4()), "name": "大米", "quantity": 5.0, "unit": "kg"}],
            }
            resp = client.post("/api/v1/supply/transfers", json=body, headers=HEADERS)

        assert resp.status_code == 400
        assert "same store" in resp.json()["detail"].lower()

    def test_create_transfer_empty_items_400(self):
        """空 items 列表：ValueError → 400。"""
        with patch(
            f"{_ROUTE_MOD}.create_transfer",
            new_callable=AsyncMock,
            side_effect=ValueError("Transfer must include at least one item"),
        ):
            body = {"from_store_id": STORE_A, "to_store_id": STORE_B, "items": []}
            resp = client.post("/api/v1/supply/transfers", json=body, headers=HEADERS)

        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/supply/transfers/{id}/confirm — 调拨确认
# ═══════════════════════════════════════════════════════════════════════════════


class TestConfirmTransferOld:
    """POST /api/v1/supply/transfers/{transfer_id}/confirm"""

    def test_confirm_sender_role_success(self):
        """sender 确认：返回 role=sender，transfer_id 一致。"""
        transfer_id = f"tf_{uuid.uuid4().hex[:8]}"
        confirmed_by = str(uuid.uuid4())
        mock_result = {
            "transfer_id": transfer_id,
            "role": "sender",
            "confirmed_by": confirmed_by,
            "status": "sender_confirmed",
            "updated_at": _now_iso(),
        }
        with patch(f"{_ROUTE_MOD}.confirm_transfer", new_callable=AsyncMock, return_value=mock_result):
            body = {"confirmed_by": confirmed_by, "role": "sender"}
            resp = client.post(
                f"/api/v1/supply/transfers/{transfer_id}/confirm",
                json=body,
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["role"] == "sender"
        assert data["transfer_id"] == transfer_id

    def test_confirm_invalid_role_422(self):
        """role 不符合 pattern(^(sender|receiver)$)：Pydantic 422。"""
        transfer_id = f"tf_{uuid.uuid4().hex[:8]}"
        body = {"confirmed_by": str(uuid.uuid4()), "role": "admin"}
        resp = client.post(
            f"/api/v1/supply/transfers/{transfer_id}/confirm",
            json=body,
            headers=HEADERS,
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/supply/warehouse/stock — 中央仓库存查询
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetWarehouseStock:
    """GET /api/v1/supply/warehouse/stock"""

    def test_warehouse_stock_empty_returns_zero_summary(self):
        """无库存数据：total_items=0，low_stock_count=0，items=[]。"""
        mock_result = {
            "tenant_id": TENANT_ID,
            "items": [],
            "summary": {
                "total_items": 0,
                "low_stock_count": 0,
                "low_stock_items": [],
                "total_value_fen": 0,
            },
        }
        with patch(f"{_ROUTE_MOD}.get_central_warehouse_stock", new_callable=AsyncMock, return_value=mock_result):
            resp = client.get("/api/v1/supply/warehouse/stock", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["summary"]["total_items"] == 0
        assert data["summary"]["low_stock_count"] == 0
        assert data["items"] == []

    def test_warehouse_stock_detects_low_stock(self):
        """有低库存食材：low_stock_count=1，total_items=2。"""
        mock_result = {
            "tenant_id": TENANT_ID,
            "items": [
                {"ingredient_name": "盐", "quantity": 2.0, "min_quantity": 10.0, "unit": "kg"},
                {"ingredient_name": "糖", "quantity": 20.0, "min_quantity": 5.0, "unit": "kg"},
            ],
            "summary": {
                "total_items": 2,
                "low_stock_count": 1,
                "low_stock_items": [{"ingredient_name": "盐"}],
                "total_value_fen": 6400,
            },
        }
        with patch(f"{_ROUTE_MOD}.get_central_warehouse_stock", new_callable=AsyncMock, return_value=mock_result):
            resp = client.get("/api/v1/supply/warehouse/stock", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["summary"]["low_stock_count"] == 1
        assert data["summary"]["total_items"] == 2
