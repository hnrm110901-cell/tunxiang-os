"""菜单审批 API 路由测试

覆盖 menu_approval_routes.py 的主要端点：
  - POST /api/v1/menu/approvals              发起审批
  - GET  /api/v1/menu/approvals              审批列表
  - GET  /api/v1/menu/approvals/{id}         审批详情
  - POST /api/v1/menu/approvals/{id}/approve 通过审批
  - POST /api/v1/menu/approvals/{id}/reject  拒绝审批

使用 FastAPI TestClient + dependency_overrides，mock MenuApprovalService，不连真实数据库。
"""

import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from api.menu_approval_routes import router

from shared.ontology.src.database import get_db

# ─── 构建测试用 App ───────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(router)

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())
APPROVER_ID = str(uuid.uuid4())
OPERATOR_ID = str(uuid.uuid4())
APPROVAL_ID = str(uuid.uuid4())

HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── Mock 工厂 ────────────────────────────────────────────────────────────────


def _make_mock_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.close = AsyncMock()
    return db


def _mock_approval_item(approval_type: str = "price_change", status: str = "pending"):
    """创建一个模拟的审批记录 Pydantic model"""
    item = MagicMock()
    item.model_dump.return_value = {
        "id": APPROVAL_ID,
        "change_type": approval_type,
        "status": status,
        "tenant_id": TENANT_ID,
        "change_payload": {
            "dish_id": DISH_ID,
            "store_id": STORE_ID,
            "new_price_fen": 4200,
        },
        "created_by": OPERATOR_ID,
        "note": "",
    }
    item.change_type = approval_type
    item.change_payload = {
        "dish_id": DISH_ID,
        "store_id": STORE_ID,
        "new_price_fen": 4200,
    }
    return item


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def override_db():
    mock_db = _make_mock_db()
    # 默认 execute 返回空结果（不触发真实 SQL）
    default_result = MagicMock()
    default_result.fetchone.return_value = None
    default_result.fetchall.return_value = []
    mock_db.execute.return_value = default_result
    app.dependency_overrides[get_db] = lambda: mock_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ─── 1. 发起审批 ──────────────────────────────────────────────────────────────


class TestCreateApproval:
    def test_create_approval_price_change_returns_201(self, client):
        """POST /api/v1/menu/approvals 发起价格变更审批返回 201"""
        mock_item = _mock_approval_item("price_change", "pending")

        with patch("api.menu_approval_routes.MenuApprovalService") as MockSvc:
            instance = MockSvc.return_value
            instance.create_publish_request = AsyncMock(return_value=mock_item)

            resp = client.post(
                "/api/v1/menu/approvals",
                json={
                    "approval_type": "price_change",
                    "store_id": STORE_ID,
                    "dish_id": DISH_ID,
                    "payload": {"new_price_fen": 4200},
                    "created_by": OPERATOR_ID,
                    "note": "旺季调价",
                },
                headers=HEADERS,
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True

    def test_create_approval_invalid_type_returns_400(self, client):
        """POST 不支持的审批类型返回 400"""
        resp = client.post(
            "/api/v1/menu/approvals",
            json={
                "approval_type": "invalid_type",
                "store_id": STORE_ID,
                "dish_id": DISH_ID,
                "payload": {},
                "created_by": OPERATOR_ID,
            },
            headers=HEADERS,
        )
        assert resp.status_code == 400

    def test_create_approval_new_dish_type(self, client):
        """POST new_dish 类型审批发起成功"""
        mock_item = _mock_approval_item("new_dish", "pending")

        with patch("api.menu_approval_routes.MenuApprovalService") as MockSvc:
            instance = MockSvc.return_value
            instance.create_publish_request = AsyncMock(return_value=mock_item)

            resp = client.post(
                "/api/v1/menu/approvals",
                json={
                    "approval_type": "new_dish",
                    "store_id": STORE_ID,
                    "dish_id": DISH_ID,
                    "payload": {},
                    "created_by": OPERATOR_ID,
                },
                headers=HEADERS,
            )

        assert resp.status_code == 201


# ─── 2. 审批列表 ──────────────────────────────────────────────────────────────


class TestListApprovals:
    def test_list_approvals_returns_200(self, client):
        """GET /api/v1/menu/approvals 返回 200 和分页结构"""
        mock_item = _mock_approval_item("price_change", "pending")

        with patch("api.menu_approval_routes.MenuApprovalService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_requests = AsyncMock(return_value=([mock_item], 1))

            resp = client.get("/api/v1/menu/approvals", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]
        assert "total" in body["data"]

    def test_list_approvals_with_status_filter(self, client):
        """GET /api/v1/menu/approvals?status=pending 状态筛选有效"""
        with patch("api.menu_approval_routes.MenuApprovalService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_requests = AsyncMock(return_value=([], 0))

            resp = client.get(
                "/api/v1/menu/approvals",
                params={"status": "pending"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 0

    def test_list_approvals_with_type_filter(self, client):
        """GET /api/v1/menu/approvals?approval_type=price_change 类型筛选有效"""
        mock_item = _mock_approval_item("price_change", "pending")

        with patch("api.menu_approval_routes.MenuApprovalService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_requests = AsyncMock(return_value=([mock_item], 1))

            resp = client.get(
                "/api/v1/menu/approvals",
                params={"approval_type": "price_change"},
                headers=HEADERS,
            )

        assert resp.status_code == 200


# ─── 3. 审批详情 ──────────────────────────────────────────────────────────────


class TestGetApproval:
    def test_get_approval_returns_200(self, client):
        """GET /api/v1/menu/approvals/{id} 存在时返回 200"""
        mock_item = _mock_approval_item("soldout", "pending")

        with patch("api.menu_approval_routes.MenuApprovalService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_request_by_id = AsyncMock(return_value=mock_item)

            resp = client.get(
                f"/api/v1/menu/approvals/{APPROVAL_ID}",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_get_approval_not_found_returns_404(self, client):
        """GET /api/v1/menu/approvals/{id} 不存在时返回 404"""
        with patch("api.menu_approval_routes.MenuApprovalService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_request_by_id = AsyncMock(return_value=None)

            resp = client.get(
                f"/api/v1/menu/approvals/{APPROVAL_ID}",
                headers=HEADERS,
            )

        assert resp.status_code == 404


# ─── 4. 通过审批 ──────────────────────────────────────────────────────────────


class TestApproveApproval:
    def test_approve_price_change_returns_200(self, client):
        """POST /api/v1/menu/approvals/{id}/approve 价格变更审批通过，自动执行更新"""
        mock_approved = _mock_approval_item("price_change", "approved")

        with patch("api.menu_approval_routes.MenuApprovalService") as MockSvc:
            instance = MockSvc.return_value
            instance.approve_request = AsyncMock(return_value=mock_approved)

            resp = client.post(
                f"/api/v1/menu/approvals/{APPROVAL_ID}/approve",
                json={"approver_id": APPROVER_ID, "note": "价格合理，同意"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "action_applied" in body["data"]
        assert body["data"]["action_applied"] == "price_change"

    def test_approve_already_processed_returns_400(self, client):
        """POST approve 已处理的审批返回 400"""
        with patch("api.menu_approval_routes.MenuApprovalService") as MockSvc:
            instance = MockSvc.return_value
            instance.approve_request = AsyncMock(side_effect=ValueError("审批申请已处理，无法重复操作"))

            resp = client.post(
                f"/api/v1/menu/approvals/{APPROVAL_ID}/approve",
                json={"approver_id": APPROVER_ID, "note": ""},
                headers=HEADERS,
            )

        assert resp.status_code == 400


# ─── 5. 拒绝审批 ──────────────────────────────────────────────────────────────


class TestRejectApproval:
    def test_reject_approval_returns_200(self, client):
        """POST /api/v1/menu/approvals/{id}/reject 拒绝审批返回 200"""
        mock_rejected = _mock_approval_item("price_change", "rejected")

        with patch("api.menu_approval_routes.MenuApprovalService") as MockSvc:
            instance = MockSvc.return_value
            instance.reject_request = AsyncMock(return_value=mock_rejected)

            resp = client.post(
                f"/api/v1/menu/approvals/{APPROVAL_ID}/reject",
                json={"approver_id": APPROVER_ID, "note": "价格调整幅度过大，暂不同意"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_reject_without_note_returns_422(self, client):
        """POST reject 未填拒绝原因（note为空）返回 422（Pydantic 校验）"""
        resp = client.post(
            f"/api/v1/menu/approvals/{APPROVAL_ID}/reject",
            json={"approver_id": APPROVER_ID, "note": ""},
            headers=HEADERS,
        )
        # note min_length=1，空字符串应被拒绝
        assert resp.status_code == 422

    def test_reject_already_processed_returns_400(self, client):
        """POST reject 已处理的审批返回 400"""
        with patch("api.menu_approval_routes.MenuApprovalService") as MockSvc:
            instance = MockSvc.return_value
            instance.reject_request = AsyncMock(side_effect=ValueError("审批申请状态不是 pending，无法拒绝"))

            resp = client.post(
                f"/api/v1/menu/approvals/{APPROVAL_ID}/reject",
                json={"approver_id": APPROVER_ID, "note": "不同意"},
                headers=HEADERS,
            )

        assert resp.status_code == 400
