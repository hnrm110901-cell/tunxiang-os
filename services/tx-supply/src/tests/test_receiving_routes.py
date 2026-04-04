"""receiving_routes.py — 收货验收 + 退货 + 调拨（旧接口）路由测试

测试范围（8个测试）：
  - POST /api/v1/supply/receiving              — 创建收货验收单（全pass / 含质量问题partial）
  - POST /api/v1/supply/receiving/{id}/reject  — 退货（正常 / 数量为负 → Pydantic 422）
  - POST /api/v1/supply/transfers              — 门店调拨（正常 / 同门店 → 400 / 空items → 400）
  - POST /api/v1/supply/transfers/{id}/confirm — 调拨确认（sender角色 / 非法角色 → 422）
  - GET  /api/v1/supply/warehouse/stock        — 中央仓库存查询（空数据返回汇总）

技术说明：
  - receiving_routes.py 路由调用 receiving_service.py
  - receiving_service 函数接受 db=None，全部业务逻辑在 Python 层，无真实 DB 依赖
  - 测试通过 TestClient 直接触发路由，service 层不 patch（直接运行真实 service 逻辑）
"""
from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.receiving_routes import router as receiving_router

# ─── App 组装 ─────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(receiving_router)
client = TestClient(app)

# ─── 公共常量 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_A = str(uuid.uuid4())
STORE_B = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/supply/receiving — 创建收货验收单
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateReceiving:
    """POST /api/v1/supply/receiving"""

    def test_create_receiving_all_pass(self):
        """所有原料质量 pass：status=accepted，all_pass=True，shortage 计算正确。"""
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
        assert data["total_received"] == 148.0
        assert data["shortage"] == 2.0  # ordered 150, received 148

    def test_create_receiving_with_quality_issue(self):
        """部分原料质量 fail：status=partial，quality_issue_count=1，receiving_id 格式 rcv_*。"""
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
        body = {
            "item_id": str(uuid.uuid4()),
            "reason": "变质无法使用",
            "quantity": 10.0,
        }
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
        assert data["reason"] == "变质无法使用"

    def test_reject_item_negative_quantity_422(self):
        """退货数量为负（违反 Field(gt=0)）：Pydantic 验证失败 → 422。"""
        receiving_id = f"rcv_{uuid.uuid4().hex[:8]}"
        body = {
            "item_id": str(uuid.uuid4()),
            "reason": "测试",
            "quantity": -1.0,  # Field(gt=0) 拦截
        }
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
        body = {
            "from_store_id": STORE_A,
            "to_store_id": STORE_B,
            "items": [
                {
                    "ingredient_id": str(uuid.uuid4()),
                    "name": "大米",
                    "quantity": 20.0,
                    "unit": "kg",
                },
            ],
        }
        resp = client.post("/api/v1/supply/transfers", json=body, headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["transfer_id"].startswith("tf_")
        assert data["status"] == "pending"
        assert data["sender_confirmed"] is False
        assert data["receiver_confirmed"] is False
        assert data["item_count"] == 1

    def test_create_transfer_same_store_400(self):
        """调出调入是同一门店：ValueError → 400。"""
        body = {
            "from_store_id": STORE_A,
            "to_store_id": STORE_A,  # 同一门店
            "items": [
                {
                    "ingredient_id": str(uuid.uuid4()),
                    "name": "大米",
                    "quantity": 5.0,
                    "unit": "kg",
                },
            ],
        }
        resp = client.post("/api/v1/supply/transfers", json=body, headers=HEADERS)
        assert resp.status_code == 400
        assert "same store" in resp.json()["detail"].lower()

    def test_create_transfer_empty_items_400(self):
        """空 items 列表：ValueError → 400。"""
        body = {
            "from_store_id": STORE_A,
            "to_store_id": STORE_B,
            "items": [],
        }
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
        body = {"confirmed_by": str(uuid.uuid4()), "role": "sender"}
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

    def test_warehouse_stock_empty_returns_summary(self):
        """无库存数据：total_items=0，low_stock_count=0，items=[]。"""
        resp = client.get("/api/v1/supply/warehouse/stock", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["summary"]["total_items"] == 0
        assert data["summary"]["low_stock_count"] == 0
        assert data["items"] == []
