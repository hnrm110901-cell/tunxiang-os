"""GDPR 工作流测试 — 5 个核心场景（Y-L6）

覆盖：
1. test_submit_deletion_request     — 提交删除申请（erasure）
2. test_submit_export_request       — 提交导出申请（portability）
3. test_list_requests               — 管理员分页查询请求列表
4. test_process_request_approve     — 批准请求（process endpoint）
5. test_retention_policy_update     — 更新数据保留期策略
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# ─── 应用 / 路由 mock 引导 ────────────────────────────────────────────────────
# tx-member 的 main.py 依赖多个重型模块（apscheduler、shared.ontology 等），
# 在单元测试中只需测路由逻辑，使用 mock 隔离外部依赖。

_TENANT_ID = "11111111-1111-1111-1111-111111111111"
_CUSTOMER_ID = str(uuid.uuid4())
_REQUEST_ID = str(uuid.uuid4())


def _mock_request(
    req_id: str = _REQUEST_ID,
    req_type: str = "erasure",
    status: str = "pending",
) -> dict[str, Any]:
    return {
        "request_id": req_id,
        "tenant_id": _TENANT_ID,
        "customer_id": _CUSTOMER_ID,
        "request_type": req_type,
        "status": status,
        "requested_by": "张三",
        "requested_at": "2026-04-07T10:00:00+00:00",
        "reviewed_by": None,
        "reviewed_at": None,
        "executed_by": None,
        "executed_at": None,
        "rejection_reason": None,
        "anonymization_log": None,
        "export_data_url": None,
        "note": None,
        "created_at": "2026-04-07T10:00:00+00:00",
        "updated_at": "2026-04-07T10:00:00+00:00",
    }


# ─── 单路由级测试（不启动完整 app） ─────────────────────────────────────────────


@pytest.fixture()
def gdpr_client():
    """只挂载 gdpr_router 的轻量 FastAPI 应用，mock 掉数据库依赖。"""
    from api.gdpr_routes import _get_tenant_db, router
    from fastapi import FastAPI

    mini_app = FastAPI()
    mini_app.include_router(router)

    # mock DB session（所有测试共用）
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()

    async def _override_db():
        yield mock_db

    mini_app.dependency_overrides[_get_tenant_db] = _override_db

    with TestClient(mini_app) as c:
        c._mock_db = mock_db  # 方便断言
        yield c


_HEADERS = {"X-Tenant-ID": _TENANT_ID}


# ─── 1. 提交删除申请 ───────────────────────────────────────────────────────────


class TestSubmitDeletionRequest:
    def test_submit_deletion_request(self, gdpr_client: TestClient):
        """POST /requests — erasure 类型"""
        with patch(
            "api.gdpr_routes.GDPRService.create_request",
            new_callable=AsyncMock,
            return_value=_mock_request(req_type="erasure", status="pending"),
        ):
            resp = gdpr_client.post(
                "/api/v1/member/gdpr/requests",
                json={
                    "customer_id": _CUSTOMER_ID,
                    "request_type": "erasure",
                    "requested_by": "张三",
                    "note": "本人申请注销账户",
                },
                headers=_HEADERS,
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["request_type"] == "erasure"
        assert body["data"]["status"] == "pending"

    def test_invalid_request_type_rejected(self, gdpr_client: TestClient):
        """不合法的 request_type 应返回 422"""
        resp = gdpr_client.post(
            "/api/v1/member/gdpr/requests",
            json={
                "customer_id": _CUSTOMER_ID,
                "request_type": "hack",
            },
            headers=_HEADERS,
        )
        assert resp.status_code == 422


# ─── 2. 提交导出申请 ───────────────────────────────────────────────────────────


class TestSubmitExportRequest:
    def test_submit_export_request(self, gdpr_client: TestClient):
        """POST /requests — portability 类型"""
        export_req = _mock_request(req_type="portability", status="pending")
        with patch(
            "api.gdpr_routes.GDPRService.create_request",
            new_callable=AsyncMock,
            return_value=export_req,
        ):
            resp = gdpr_client.post(
                "/api/v1/member/gdpr/requests",
                json={
                    "customer_id": _CUSTOMER_ID,
                    "request_type": "portability",
                },
                headers=_HEADERS,
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["request_type"] == "portability"

    def test_duplicate_request_returns_400(self, gdpr_client: TestClient):
        """重复提交同类型请求应返回 400"""
        with patch(
            "api.gdpr_routes.GDPRService.create_request",
            new_callable=AsyncMock,
            side_effect=ValueError("该客户已有进行中的 portability 申请，请等待处理完成"),
        ):
            resp = gdpr_client.post(
                "/api/v1/member/gdpr/requests",
                json={
                    "customer_id": _CUSTOMER_ID,
                    "request_type": "portability",
                },
                headers=_HEADERS,
            )
        assert resp.status_code == 400
        assert "portability" in resp.json()["detail"]


# ─── 3. 列出请求（管理员视角） ─────────────────────────────────────────────────


class TestListRequests:
    def test_list_requests(self, gdpr_client: TestClient):
        """GET /requests — 返回 items + total"""
        mock_items = [
            _mock_request(req_type="erasure"),
            _mock_request(req_id=str(uuid.uuid4()), req_type="portability"),
        ]
        with patch(
            "api.gdpr_routes.GDPRService.list_requests",
            new_callable=AsyncMock,
            return_value=mock_items,
        ):
            resp = gdpr_client.get(
                "/api/v1/member/gdpr/requests",
                headers=_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 2
        assert len(body["data"]["items"]) == 2

    def test_list_requests_with_status_filter(self, gdpr_client: TestClient):
        """GET /requests?status=pending — 仅返回 pending"""
        with patch(
            "api.gdpr_routes.GDPRService.list_requests",
            new_callable=AsyncMock,
            return_value=[_mock_request()],
        ):
            resp = gdpr_client.get(
                "/api/v1/member/gdpr/requests?status=pending",
                headers=_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 1


# ─── 4. 批准请求（process endpoint） ──────────────────────────────────────────


class TestProcessRequestApprove:
    def test_process_request_approve(self, gdpr_client: TestClient):
        """POST /requests/{id}/process — action=approve"""
        approved_req = _mock_request(status="reviewing")
        with patch(
            "api.gdpr_routes.GDPRService.review_request",
            new_callable=AsyncMock,
            return_value=approved_req,
        ):
            resp = gdpr_client.post(
                f"/api/v1/member/gdpr/requests/{_REQUEST_ID}/process",
                json={
                    "action": "approve",
                    "operator_id": str(uuid.uuid4()),
                    "reason": None,
                },
                headers=_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "reviewing"

    def test_process_request_reject(self, gdpr_client: TestClient):
        """POST /requests/{id}/process — action=reject"""
        rejected_req = _mock_request(status="rejected")
        with patch(
            "api.gdpr_routes.GDPRService.review_request",
            new_callable=AsyncMock,
            return_value=rejected_req,
        ):
            resp = gdpr_client.post(
                f"/api/v1/member/gdpr/requests/{_REQUEST_ID}/process",
                json={
                    "action": "reject",
                    "operator_id": str(uuid.uuid4()),
                    "reason": "资料不符合要求",
                },
                headers=_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "rejected"

    def test_invalid_action_returns_422(self, gdpr_client: TestClient):
        """非法 action 应返回 422"""
        resp = gdpr_client.post(
            f"/api/v1/member/gdpr/requests/{_REQUEST_ID}/process",
            json={"action": "delete_all", "operator_id": "op1"},
            headers=_HEADERS,
        )
        assert resp.status_code == 422


# ─── 5. 更新数据保留期策略 ─────────────────────────────────────────────────────


class TestRetentionPolicyUpdate:
    def test_retention_policy_update(self, gdpr_client: TestClient):
        """PUT /retention-policies/orders — 更新订单保留期"""
        resp = gdpr_client.put(
            "/api/v1/member/gdpr/retention-policies/orders",
            json={
                "retention_days": 730,
                "anonymize_after_days": 365,
                "legal_basis": "GDPR Art.6(1)(b) — 合同履行",
                "is_active": True,
            },
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["data_category"] == "orders"
        assert body["data"]["retention_days"] == 730

    def test_invalid_category_returns_400(self, gdpr_client: TestClient):
        """非法 category 应返回 400"""
        resp = gdpr_client.put(
            "/api/v1/member/gdpr/retention-policies/hack_table",
            json={"retention_days": 30, "is_active": True},
            headers=_HEADERS,
        )
        assert resp.status_code == 400

    def test_retention_days_out_of_range(self, gdpr_client: TestClient):
        """retention_days=0 应返回 422"""
        resp = gdpr_client.put(
            "/api/v1/member/gdpr/retention-policies/members",
            json={"retention_days": 0, "is_active": True},
            headers=_HEADERS,
        )
        assert resp.status_code == 422
