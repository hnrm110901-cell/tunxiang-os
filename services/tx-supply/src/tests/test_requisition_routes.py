"""申购全流程路由测试 — test_requisition_routes.py

覆盖路由: requisition_routes.py (8 个端点)
  POST /api/v1/supply/requisitions
  POST /api/v1/supply/requisitions/replenishment/{store_id}
  POST /api/v1/supply/requisitions/{req_id}/submit
  POST /api/v1/supply/requisitions/{req_id}/approve
  POST /api/v1/supply/requisitions/{req_id}/convert
  POST /api/v1/supply/requisitions/returns
  GET  /api/v1/supply/requisitions/{req_id}/approval-log
  GET  /api/v1/supply/requisitions/flow/{store_id}

测试数: 24
"""

from __future__ import annotations

import sys
import types
import uuid

# ── fake src.db stub ──────────────────────────────────────────────────────────
fake_db = types.ModuleType("src.db")


async def fake_get_db():
    yield None


fake_db.get_db = fake_get_db
sys.modules.setdefault("src", types.ModuleType("src"))
sys.modules.setdefault("src.db", fake_db)

# ── 标准导入 ──────────────────────────────────────────────────────────────────
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, patch

from api.requisition_routes import router as req_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── App 组装 ──────────────────────────────────────────────────────────────────
app = FastAPI()
app.include_router(req_router)
client = TestClient(app)

# ── 公共常量 ──────────────────────────────────────────────────────────────────
TENANT = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT}
_MOD = "api.requisition_routes"


def _req_id() -> str:
    return f"req_{uuid.uuid4().hex[:8]}"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. POST /api/v1/supply/requisitions — 创建申购单
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateRequisition:
    """POST /api/v1/supply/requisitions"""

    def test_create_ok(self):
        """正常创建返回 requisition_id 和 status=draft。"""
        rid = _req_id()
        mock_ret = {"requisition_id": rid, "status": "draft", "item_count": 2, "total_estimated_fen": 70000}
        with patch(f"{_MOD}.svc", new_callable=AsyncMock, return_value=mock_ret):
            body = {
                "store_id": STORE_ID,
                "requester_id": "emp_001",
                "items": [
                    {
                        "ingredient_id": "i1",
                        "name": "猪肉",
                        "quantity": 10.0,
                        "unit": "kg",
                        "estimated_price_fen": 3500,
                    },
                    {
                        "ingredient_id": "i2",
                        "name": "白菜",
                        "quantity": 20.0,
                        "unit": "kg",
                        "estimated_price_fen": 1750,
                    },
                ],
            }
            with patch(f"{_MOD}.create_requisition", new_callable=AsyncMock, return_value=mock_ret):
                resp = client.post("/api/v1/supply/requisitions", json=body, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["data"]["requisition_id"] == rid

    def test_create_missing_tenant_header(self):
        """缺少 X-Tenant-ID header 时返回 422。"""
        body = {
            "store_id": STORE_ID,
            "requester_id": "emp_001",
            "items": [{"ingredient_id": "i1", "quantity": 5.0}],
        }
        resp = client.post("/api/v1/supply/requisitions", json=body)
        assert resp.status_code == 422

    def test_create_quantity_zero_rejected(self):
        """quantity=0 不符合 gt=0 约束，Pydantic 应返回 422。"""
        body = {
            "store_id": STORE_ID,
            "requester_id": "emp_001",
            "items": [{"ingredient_id": "i1", "quantity": 0.0}],
        }
        resp = client.post("/api/v1/supply/requisitions", json=body, headers=HEADERS)
        assert resp.status_code == 422

    def test_create_service_value_error_returns_400(self):
        """Service 层抛出 ValueError 时路由返回 400。"""
        with patch(f"{_MOD}.create_requisition", new_callable=AsyncMock, side_effect=ValueError("至少一项")):
            body = {
                "store_id": STORE_ID,
                "requester_id": "emp_001",
                "items": [{"ingredient_id": "i1", "quantity": 5.0}],
            }
            resp = client.post("/api/v1/supply/requisitions", json=body, headers=HEADERS)
        assert resp.status_code == 400
        assert "至少一项" in resp.json()["detail"]

    def test_create_negative_quantity_rejected(self):
        """quantity 为负数时 Pydantic 校验失败，返回 422。"""
        body = {
            "store_id": STORE_ID,
            "requester_id": "emp_001",
            "items": [{"ingredient_id": "i1", "quantity": -3.0}],
        }
        resp = client.post("/api/v1/supply/requisitions", json=body, headers=HEADERS)
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 2. POST /api/v1/supply/requisitions/replenishment/{store_id} — 自动补货
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateReplenishment:
    """POST /api/v1/supply/requisitions/replenishment/{store_id}"""

    def test_replenishment_ok(self):
        """自动补货返回申购单。"""
        rid = _req_id()
        mock_ret = {"requisition_id": rid, "status": "draft", "item_count": 3}
        with patch(f"{_MOD}.create_replenishment", new_callable=AsyncMock, return_value=mock_ret):
            resp = client.post(
                f"/api/v1/supply/requisitions/replenishment/{STORE_ID}",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["data"]["requisition_id"] == rid

    def test_replenishment_missing_header(self):
        """缺少 header 返回 422。"""
        resp = client.post(f"/api/v1/supply/requisitions/replenishment/{STORE_ID}")
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 3. POST /api/v1/supply/requisitions/{req_id}/submit — 提交审批
# ═══════════════════════════════════════════════════════════════════════════════


class TestSubmitForApproval:
    """POST /api/v1/supply/requisitions/{req_id}/submit"""

    def test_submit_ok(self):
        """正常提交返回 status=pending。"""
        rid = _req_id()
        mock_ret = {"requisition_id": rid, "status": "pending"}
        with patch(f"{_MOD}.submit_for_approval", new_callable=AsyncMock, return_value=mock_ret):
            resp = client.post(
                f"/api/v1/supply/requisitions/{rid}/submit",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "pending"

    def test_submit_value_error_returns_400(self):
        """申购单不存在时返回 400。"""
        rid = _req_id()
        with patch(f"{_MOD}.submit_for_approval", new_callable=AsyncMock, side_effect=ValueError("申购单不存在")):
            resp = client.post(
                f"/api/v1/supply/requisitions/{rid}/submit",
                headers=HEADERS,
            )
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# 4. POST /api/v1/supply/requisitions/{req_id}/approve — 审批
# ═══════════════════════════════════════════════════════════════════════════════


class TestApproveRequisition:
    """POST /api/v1/supply/requisitions/{req_id}/approve"""

    def test_approve_ok(self):
        """审批通过返回 status=approved。"""
        rid = _req_id()
        mock_ret = {"requisition_id": rid, "status": "approved", "decision": "approve"}
        with patch(f"{_MOD}.approve_requisition", new_callable=AsyncMock, return_value=mock_ret):
            body = {
                "approver_id": "mgr_001",
                "decision": "approve",
                "approver_role": "store_manager",
                "comment": "同意",
            }
            resp = client.post(
                f"/api/v1/supply/requisitions/{rid}/approve",
                json=body,
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["decision"] == "approve"

    def test_reject_ok(self):
        """驳回返回 status=rejected。"""
        rid = _req_id()
        mock_ret = {"requisition_id": rid, "status": "rejected", "decision": "reject"}
        with patch(f"{_MOD}.approve_requisition", new_callable=AsyncMock, return_value=mock_ret):
            body = {
                "approver_id": "mgr_001",
                "decision": "reject",
                "approver_role": "region_manager",
                "comment": "超预算",
            }
            resp = client.post(
                f"/api/v1/supply/requisitions/{rid}/approve",
                json=body,
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["decision"] == "reject"

    def test_invalid_decision_returns_422(self):
        """decision 不在枚举值内时 Pydantic 返回 422。"""
        rid = _req_id()
        body = {
            "approver_id": "mgr_001",
            "decision": "maybe",
            "approver_role": "store_manager",
        }
        resp = client.post(
            f"/api/v1/supply/requisitions/{rid}/approve",
            json=body,
            headers=HEADERS,
        )
        assert resp.status_code == 422

    def test_approve_value_error_returns_400(self):
        """Service 层 ValueError 时返回 400。"""
        rid = _req_id()
        with patch(
            f"{_MOD}.approve_requisition",
            new_callable=AsyncMock,
            side_effect=ValueError("无权审批"),
        ):
            body = {"approver_id": "mgr_001", "decision": "approve", "approver_role": "store_manager"}
            resp = client.post(
                f"/api/v1/supply/requisitions/{rid}/approve",
                json=body,
                headers=HEADERS,
            )
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# 5. POST /api/v1/supply/requisitions/{req_id}/convert — 转采购订单
# ═══════════════════════════════════════════════════════════════════════════════


class TestConvertToPurchase:
    """POST /api/v1/supply/requisitions/{req_id}/convert"""

    def test_convert_ok(self):
        """转采购订单成功。"""
        rid = _req_id()
        po_id = f"po_{uuid.uuid4().hex[:8]}"
        mock_ret = {"purchase_order_id": po_id, "requisition_id": rid, "status": "pending"}
        with patch(f"{_MOD}.convert_to_purchase", new_callable=AsyncMock, return_value=mock_ret):
            body = {
                "supplier_id": "sup_001",
                "supplier_name": "鲜生供应商",
                "delivery_date": "2026-04-10",
            }
            resp = client.post(
                f"/api/v1/supply/requisitions/{rid}/convert",
                json=body,
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["purchase_order_id"] == po_id

    def test_convert_empty_body_ok(self):
        """请求体可为空（字段均有默认值）。"""
        rid = _req_id()
        mock_ret = {"purchase_order_id": "po_xxx", "requisition_id": rid, "status": "pending"}
        with patch(f"{_MOD}.convert_to_purchase", new_callable=AsyncMock, return_value=mock_ret):
            resp = client.post(
                f"/api/v1/supply/requisitions/{rid}/convert",
                json={},
                headers=HEADERS,
            )
        assert resp.status_code == 200

    def test_convert_value_error_returns_400(self):
        """申购单未审批通过时返回 400。"""
        rid = _req_id()
        with patch(
            f"{_MOD}.convert_to_purchase",
            new_callable=AsyncMock,
            side_effect=ValueError("申购单尚未审批"),
        ):
            resp = client.post(
                f"/api/v1/supply/requisitions/{rid}/convert",
                json={},
                headers=HEADERS,
            )
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# 6. POST /api/v1/supply/requisitions/returns — 申退单
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateReturnRequest:
    """POST /api/v1/supply/requisitions/returns"""

    def test_create_return_ok(self):
        """正常创建申退单。"""
        ret_id = f"ret_{uuid.uuid4().hex[:8]}"
        mock_ret = {"return_id": ret_id, "status": "draft", "item_count": 1}
        with patch(f"{_MOD}.create_return_request", new_callable=AsyncMock, return_value=mock_ret):
            body = {
                "store_id": STORE_ID,
                "reason": "质量问题",
                "items": [
                    {"ingredient_id": "i1", "name": "猪肉", "quantity": 5.0, "unit": "kg", "batch_no": "B001"},
                ],
            }
            resp = client.post("/api/v1/supply/requisitions/returns", json=body, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["return_id"] == ret_id

    def test_create_return_value_error(self):
        """Service 层抛出 ValueError 时返回 400。"""
        with patch(
            f"{_MOD}.create_return_request",
            new_callable=AsyncMock,
            side_effect=ValueError("批次不存在"),
        ):
            body = {
                "store_id": STORE_ID,
                "reason": "损坏",
                "items": [{"ingredient_id": "i1", "quantity": 2.0}],
            }
            resp = client.post("/api/v1/supply/requisitions/returns", json=body, headers=HEADERS)
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# 7. GET /api/v1/supply/requisitions/{req_id}/approval-log — 审批日志
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetApprovalLog:
    """GET /api/v1/supply/requisitions/{req_id}/approval-log"""

    def test_get_log_ok(self):
        """正常返回审批日志列表。"""
        rid = _req_id()
        mock_ret = {
            "requisition_id": rid,
            "logs": [
                {"level": 1, "approver_id": "mgr_001", "decision": "approve", "comment": "同意"},
            ],
        }
        with patch(f"{_MOD}.get_approval_log", new_callable=AsyncMock, return_value=mock_ret):
            resp = client.get(f"/api/v1/supply/requisitions/{rid}/approval-log", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        logs = resp.json()["data"]["logs"]
        assert len(logs) == 1
        assert logs[0]["decision"] == "approve"

    def test_get_log_empty(self):
        """无审批日志时返回空列表。"""
        rid = _req_id()
        mock_ret = {"requisition_id": rid, "logs": []}
        with patch(f"{_MOD}.get_approval_log", new_callable=AsyncMock, return_value=mock_ret):
            resp = client.get(f"/api/v1/supply/requisitions/{rid}/approval-log", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["logs"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# 8. GET /api/v1/supply/requisitions/flow/{store_id} — 申购商品流水
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetRequisitionFlow:
    """GET /api/v1/supply/requisitions/flow/{store_id}"""

    def test_get_flow_ok(self):
        """正常返回流水记录列表。"""
        mock_ret = {
            "store_id": STORE_ID,
            "items": [
                {"ingredient_id": "i1", "name": "猪肉", "total_qty": 50.0},
                {"ingredient_id": "i2", "name": "白菜", "total_qty": 100.0},
            ],
        }
        with patch(f"{_MOD}.get_requisition_flow", new_callable=AsyncMock, return_value=mock_ret):
            resp = client.get(f"/api/v1/supply/requisitions/flow/{STORE_ID}", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert len(resp.json()["data"]["items"]) == 2

    def test_get_flow_empty_store(self):
        """新门店无流水记录时返回空列表。"""
        mock_ret = {"store_id": STORE_ID, "items": []}
        with patch(f"{_MOD}.get_requisition_flow", new_callable=AsyncMock, return_value=mock_ret):
            resp = client.get(f"/api/v1/supply/requisitions/flow/{STORE_ID}", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []

    def test_get_flow_missing_header_returns_422(self):
        """缺少 X-Tenant-ID 时返回 422。"""
        resp = client.get(f"/api/v1/supply/requisitions/flow/{STORE_ID}")
        assert resp.status_code == 422
