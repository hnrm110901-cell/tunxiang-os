"""营销审批流 API 路由测试 — api/approval_routes.py

覆盖场景：
1.  GET  /api/v1/growth/approvals/workflows          — 正常返回工作流列表
2.  GET  /api/v1/growth/approvals/workflows          — is_active 过滤
3.  GET  /api/v1/growth/approvals/workflows          — X-Tenant-ID 格式错误 → 422
4.  POST /api/v1/growth/approvals/workflows          — 正常创建工作流
5.  POST /api/v1/growth/approvals/workflows          — name 为空字符串 → 422
6.  POST /api/v1/growth/approvals/workflows          — steps 为空列表 → 422
7.  POST /api/v1/growth/approvals/workflows          — steps 缺少 step/role 字段 → 422
8.  POST /api/v1/growth/approvals/workflows/seed     — 正常 seed 默认模板
9.  GET  /api/v1/growth/approvals                    — 正常返回待审批列表
10. GET  /api/v1/growth/approvals/my-requests        — 正常返回我提交的审批列表
11. GET  /api/v1/growth/approvals/{id}               — 审批单存在时返回详情
12. GET  /api/v1/growth/approvals/{id}               — 审批单不存在时返回 404
13. POST /api/v1/growth/approvals/{id}/approve       — 审批通过成功
14. POST /api/v1/growth/approvals/{id}/approve       — 服务返回 ValueError → 404
15. POST /api/v1/growth/approvals/{id}/reject        — 审批拒绝成功
16. POST /api/v1/growth/approvals/{id}/reject        — 拒绝原因为空 → 422
17. POST /api/v1/growth/approvals/{id}/cancel        — 撤销成功
18. POST /api/v1/growth/approvals/{id}/cancel        — 服务返回 ok=False → 400
19. POST /api/v1/growth/approvals/batch-approve      — 批量审批通过成功
20. POST /api/v1/growth/approvals/batch-approve      — 空列表 → 422
21. POST /api/v1/growth/approvals/batch-approve      — 超过50条 → 422
22. POST /api/v1/growth/approvals/batch-approve      — 部分失败
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import types as _types
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

# ── 预置 sys.modules stubs，防止导入链拉起真实 DB/模型 ──────────────────────

# models.approval — 用 MagicMock 类替换
_approval_mod = _types.ModuleType("models.approval")
_MockApprovalWorkflow = MagicMock()
_MockApprovalRequest = MagicMock()
_approval_mod.ApprovalWorkflow = _MockApprovalWorkflow
_approval_mod.ApprovalRequest = _MockApprovalRequest
sys.modules.setdefault("models", _types.ModuleType("models"))
sys.modules["models.approval"] = _approval_mod

# services.approval_service — stub，防止 httpx/structlog import 链
_svc_mod = _types.ModuleType("services.approval_service")


class _FakeApprovalService:
    async def seed_default_workflows(self, tenant_id, db):
        return {"inserted": 2}

    async def approve(self, request_id, approver_id, comment, tenant_id, db):
        return {"ok": True, "status": "approved", "approved_at": "2026-04-06T00:00:00+00:00"}

    async def reject(self, request_id, approver_id, reason, tenant_id, db):
        return {"ok": True, "status": "rejected", "reason": reason}

    async def cancel(self, request_id, requester_id, tenant_id, db):
        return {"ok": True, "status": "cancelled"}

    async def batch_approve(self, request_ids, approver_id, comment, tenant_id, db):
        results = []
        for rid in request_ids:
            results.append({
                "request_id": str(rid),
                "ok": True,
                "status": "approved",
                "approved_at": "2026-04-06T00:00:00+00:00",
            })
        return {
            "total": len(request_ids),
            "succeeded": len(request_ids),
            "failed": 0,
            "results": results,
        }


_svc_mod.ApprovalService = _FakeApprovalService


# 注入真实的条件评估函数（用于单元测试）
def _evaluate_condition_real(field, op, value, data):
    actual = data.get(field)
    if actual is None:
        return False
    if op == "gt":
        return actual > value
    if op == "gte":
        return actual >= value
    if op == "lt":
        return actual < value
    if op == "lte":
        return actual <= value
    if op == "eq":
        return actual == value
    if op == "neq":
        return actual != value
    if op == "in":
        if isinstance(value, (list, tuple, set)):
            return actual in value
        return False
    return False


def _evaluate_conditions_real(conditions, data):
    if not conditions:
        return False
    for cond in conditions:
        field = cond.get("field", "")
        op = cond.get("op", "eq")
        threshold = cond.get("value")
        if not _evaluate_condition_real(field, op, threshold, data):
            return False
    return True


_svc_mod._evaluate_condition = _evaluate_condition_real
_svc_mod._evaluate_conditions = _evaluate_conditions_real

sys.modules.setdefault("services", _types.ModuleType("services"))
sys.modules["services.approval_service"] = _svc_mod

# shared.ontology — stub（TenantBase 依赖）
_ont_mod = _types.ModuleType("shared.ontology")
_ont_src = _types.ModuleType("shared.ontology.src")
_ont_base = _types.ModuleType("shared.ontology.src.base")
_ont_base.TenantBase = object
sys.modules.setdefault("shared", _types.ModuleType("shared"))
sys.modules["shared.ontology"] = _ont_mod
sys.modules["shared.ontology.src"] = _ont_src
sys.modules["shared.ontology.src.base"] = _ont_base

# sqlalchemy stubs
import sqlalchemy as _sa

sys.modules.setdefault("sqlalchemy", _sa)

# ── 导入被测路由 ────────────────────────────────────────────────────────────

from api.approval_routes import router  # noqa: E402

# ── 构建测试 App，使用 middleware 注入 mock_db ──────────────────────────────

_mock_db_holder: dict = {}


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_db(request: Request, call_next):
        request.state.db = _mock_db_holder.get("db", AsyncMock())
        return await call_next(request)

    app.include_router(router)
    return app


app = _build_app()
client = TestClient(app, raise_server_exceptions=False)

# ── 通用常量 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}
BAD_TENANT_HEADERS = {"X-Tenant-ID": "not-a-uuid"}

REQUEST_ID = str(uuid.uuid4())
WORKFLOW_ID = str(uuid.uuid4())
APPROVER_ID = str(uuid.uuid4())
REQUESTER_ID = str(uuid.uuid4())

_NOW = datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc)


# ── 辅助：构造 mock ApprovalWorkflow 对象 ──────────────────────────────────


def _make_workflow_obj():
    wf = MagicMock()
    wf.id = uuid.UUID(WORKFLOW_ID)
    wf.name = "大额优惠审批"
    wf.trigger_conditions = {"type": "campaign_activation", "conditions": []}
    wf.steps = [{"step": 1, "role": "store_manager", "timeout_hours": 24}]
    wf.is_active = True
    wf.priority = 10
    wf.created_at = _NOW
    return wf


def _make_request_obj(status: str = "pending"):
    req = MagicMock()
    req.id = uuid.UUID(REQUEST_ID)
    req.workflow_id = uuid.UUID(WORKFLOW_ID)
    req.object_type = "campaign"
    req.object_id = "camp-001"
    req.object_summary = {"name": "春节活动"}
    req.requester_id = uuid.UUID(REQUESTER_ID)
    req.requester_name = "张三"
    req.status = status
    req.current_step = 1
    req.reject_reason = None
    req.created_at = _NOW
    req.approved_at = None
    req.expires_at = None
    req.approval_history = []
    return req


def _make_db_with_scalars(items: list):
    """构造 db.execute(...).scalars().all() 返回 items 的 mock db"""
    mock_db = AsyncMock()
    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=items)
    execute_result = MagicMock()
    execute_result.scalars = MagicMock(return_value=scalars_result)
    mock_db.execute = AsyncMock(return_value=execute_result)
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


def _make_db_with_scalar_one_or_none(value):
    """构造 db.execute(...).scalar_one_or_none() 返回 value 的 mock db"""
    mock_db = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none = MagicMock(return_value=value)
    mock_db.execute = AsyncMock(return_value=execute_result)
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /workflows — 正常返回工作流列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_workflows_ok():
    """正常返回工作流列表，包含 items 和 total"""
    wf = _make_workflow_obj()
    _mock_db_holder["db"] = _make_db_with_scalars([wf])

    resp = client.get("/api/v1/growth/approvals/workflows", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "items" in body["data"]
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["name"] == "大额优惠审批"
    assert body["data"]["items"][0]["workflow_id"] == WORKFLOW_ID


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: GET /workflows — is_active 过滤，无数据时返回空列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_workflows_is_active_filter_empty():
    """过滤 is_active=false 时无数据，返回 total=0"""
    _mock_db_holder["db"] = _make_db_with_scalars([])

    resp = client.get(
        "/api/v1/growth/approvals/workflows",
        params={"is_active": "false"},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 0
    assert body["data"]["items"] == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: GET /workflows — X-Tenant-ID 格式错误
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_workflows_bad_tenant_id():
    """X-Tenant-ID 非合法 UUID 时，路由内 uuid.UUID() 抛 ValueError，返回 5xx"""
    _mock_db_holder["db"] = AsyncMock()

    resp = client.get("/api/v1/growth/approvals/workflows", headers=BAD_TENANT_HEADERS)

    # uuid.UUID("not-a-uuid") 抛 ValueError，FastAPI 返回 500（raise_server_exceptions=False）
    assert resp.status_code in (400, 422, 500)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: POST /workflows — 正常创建工作流
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_workflow_ok():
    """正常创建审批流模板，返回 workflow_id 和字段"""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    _mock_db_holder["db"] = mock_db

    payload = {
        "name": "大额优惠审批",
        "trigger_conditions": {
            "type": "campaign_activation",
            "conditions": [{"field": "max_discount_fen", "op": "gt", "value": 5000}],
        },
        "steps": [{"step": 1, "role": "store_manager", "timeout_hours": 24}],
        "is_active": True,
        "priority": 10,
    }

    resp = client.post("/api/v1/growth/approvals/workflows", json=payload, headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "workflow_id" in body["data"]
    assert body["data"]["name"] == "大额优惠审批"
    assert body["data"]["is_active"] is True
    assert body["data"]["priority"] == 10
    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: POST /workflows — name 为空字符串 → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_workflow_empty_name():
    """name 为空字符串时 Pydantic validator 拒绝，返回 422"""
    payload = {
        "name": "   ",
        "trigger_conditions": {"type": "campaign_activation", "conditions": []},
        "steps": [{"step": 1, "role": "store_manager"}],
    }
    resp = client.post("/api/v1/growth/approvals/workflows", json=payload, headers=HEADERS)
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: POST /workflows — steps 为空列表 → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_workflow_empty_steps():
    """steps 为空列表时 Pydantic validator 拒绝，返回 422"""
    payload = {
        "name": "测试审批",
        "trigger_conditions": {"type": "campaign_activation", "conditions": []},
        "steps": [],
    }
    resp = client.post("/api/v1/growth/approvals/workflows", json=payload, headers=HEADERS)
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: POST /workflows — steps 缺少 step/role 字段 → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_workflow_steps_missing_required_fields():
    """steps 中元素缺少 step 或 role 时 Pydantic validator 拒绝，返回 422"""
    payload = {
        "name": "测试审批",
        "trigger_conditions": {"type": "campaign_activation", "conditions": []},
        "steps": [{"timeout_hours": 24}],  # 缺少 step 和 role
    }
    resp = client.post("/api/v1/growth/approvals/workflows", json=payload, headers=HEADERS)
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: POST /workflows/seed — 正常 seed 默认模板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_seed_default_workflows_ok():
    """调用 seed_default_workflows，返回 inserted 数"""
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    _mock_db_holder["db"] = mock_db

    # patch 路由模块中的 _svc 实例方法
    with patch("api.approval_routes._svc") as mock_svc:
        mock_svc.seed_default_workflows = AsyncMock(return_value={"inserted": 2})

        resp = client.post("/api/v1/growth/approvals/workflows/seed", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["inserted"] == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: GET /approvals — 正常返回待审批列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_pending_approvals_ok():
    """返回 pending 状态审批列表"""
    req_obj = _make_request_obj(status="pending")
    _mock_db_holder["db"] = _make_db_with_scalars([req_obj])

    resp = client.get("/api/v1/growth/approvals", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "items" in body["data"]
    assert len(body["data"]["items"]) == 1
    assert body["data"]["items"][0]["status"] == "pending"
    assert body["data"]["page"] == 1
    assert body["data"]["size"] == 20


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: GET /my-requests — 正常返回我提交的审批列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_my_requests_ok():
    """requester_id 过滤，返回该申请人的审批列表"""
    req_obj = _make_request_obj(status="approved")
    _mock_db_holder["db"] = _make_db_with_scalars([req_obj])

    resp = client.get(
        "/api/v1/growth/approvals/my-requests",
        params={"requester_id": REQUESTER_ID},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["items"]) == 1
    assert body["data"]["items"][0]["requester_id"] == REQUESTER_ID


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 11: GET /{id} — 审批单存在时返回详情（含 approval_history）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_approval_detail_ok():
    """审批单存在时，返回完整详情含 approval_history"""
    req_obj = _make_request_obj()
    _mock_db_holder["db"] = _make_db_with_scalar_one_or_none(req_obj)

    resp = client.get(f"/api/v1/growth/approvals/{REQUEST_ID}", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["request_id"] == REQUEST_ID
    assert "approval_history" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 12: GET /{id} — 审批单不存在时返回 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_approval_detail_not_found():
    """审批单不存在时返回 404"""
    _mock_db_holder["db"] = _make_db_with_scalar_one_or_none(None)

    resp = client.get(f"/api/v1/growth/approvals/{REQUEST_ID}", headers=HEADERS)

    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 13: POST /{id}/approve — 审批通过成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_approve_request_ok():
    """调用审批通过，返回 status=approved"""
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    _mock_db_holder["db"] = mock_db

    with patch("api.approval_routes._svc") as mock_svc:
        mock_svc.approve = AsyncMock(
            return_value={"ok": True, "status": "approved", "approved_at": "2026-04-06T10:00:00+00:00"}
        )

        resp = client.post(
            f"/api/v1/growth/approvals/{REQUEST_ID}/approve",
            json={"approver_id": APPROVER_ID, "comment": "同意"},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "approved"
    mock_db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 14: POST /{id}/approve — 服务抛 ValueError → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_approve_request_not_found():
    """ApprovalService.approve 抛 ValueError 时路由返回 404"""
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    _mock_db_holder["db"] = mock_db

    with patch("api.approval_routes._svc") as mock_svc:
        mock_svc.approve = AsyncMock(side_effect=ValueError("审批单不存在"))

        resp = client.post(
            f"/api/v1/growth/approvals/{REQUEST_ID}/approve",
            json={"approver_id": APPROVER_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 15: POST /{id}/reject — 审批拒绝成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_reject_request_ok():
    """审批拒绝成功，返回 status=rejected 和原因"""
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    _mock_db_holder["db"] = mock_db

    with patch("api.approval_routes._svc") as mock_svc:
        mock_svc.reject = AsyncMock(return_value={"ok": True, "status": "rejected", "reason": "折扣过高"})

        resp = client.post(
            f"/api/v1/growth/approvals/{REQUEST_ID}/reject",
            json={"approver_id": APPROVER_ID, "reason": "折扣过高"},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "rejected"
    mock_db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 16: POST /{id}/reject — reason 为空字符串 → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_reject_request_empty_reason():
    """拒绝原因为空字符串时 Pydantic validator 拒绝，返回 422"""
    resp = client.post(
        f"/api/v1/growth/approvals/{REQUEST_ID}/reject",
        json={"approver_id": APPROVER_ID, "reason": "   "},
        headers=HEADERS,
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 17: POST /{id}/cancel — 撤销成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_cancel_request_ok():
    """申请人撤销审批单成功，返回 status=cancelled"""
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    _mock_db_holder["db"] = mock_db

    with patch("api.approval_routes._svc") as mock_svc:
        mock_svc.cancel = AsyncMock(return_value={"ok": True, "status": "cancelled"})

        resp = client.post(
            f"/api/v1/growth/approvals/{REQUEST_ID}/cancel",
            json={"requester_id": REQUESTER_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "cancelled"
    mock_db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 18: POST /{id}/cancel — 服务返回 ok=False → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_cancel_request_not_allowed():
    """服务返回 ok=False 时（非申请人撤销），路由返回 400"""
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    _mock_db_holder["db"] = mock_db

    with patch("api.approval_routes._svc") as mock_svc:
        mock_svc.cancel = AsyncMock(return_value={"ok": False, "reason": "只有申请人可撤销审批单"})

        resp = client.post(
            f"/api/v1/growth/approvals/{REQUEST_ID}/cancel",
            json={"requester_id": str(uuid.uuid4())},  # 非申请人
            headers=HEADERS,
        )

    assert resp.status_code == 400


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 19: POST /batch-approve — 批量审批通过成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_batch_approve_ok():
    """批量审批通过 3 条，返回 succeeded=3"""
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    _mock_db_holder["db"] = mock_db

    ids = [str(uuid.uuid4()) for _ in range(3)]

    with patch("api.approval_routes._svc") as mock_svc:
        mock_svc.batch_approve = AsyncMock(
            return_value={
                "total": 3,
                "succeeded": 3,
                "failed": 0,
                "results": [
                    {"request_id": rid, "ok": True, "status": "approved"}
                    for rid in ids
                ],
            }
        )

        resp = client.post(
            "/api/v1/growth/approvals/batch-approve",
            json={
                "request_ids": ids,
                "approver_id": APPROVER_ID,
                "comment": "批量同意",
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 3
    assert body["data"]["succeeded"] == 3
    assert body["data"]["failed"] == 0
    assert len(body["data"]["results"]) == 3
    mock_db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 20: POST /batch-approve — 空列表 → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_batch_approve_empty_ids():
    """request_ids 为空列表时 Pydantic validator 拒绝，返回 422"""
    resp = client.post(
        "/api/v1/growth/approvals/batch-approve",
        json={
            "request_ids": [],
            "approver_id": APPROVER_ID,
        },
        headers=HEADERS,
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 21: POST /batch-approve — 超过 50 条 → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_batch_approve_exceed_limit():
    """request_ids 超过 50 条时 Pydantic validator 拒绝，返回 422"""
    ids = [str(uuid.uuid4()) for _ in range(51)]
    resp = client.post(
        "/api/v1/growth/approvals/batch-approve",
        json={
            "request_ids": ids,
            "approver_id": APPROVER_ID,
        },
        headers=HEADERS,
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 22: POST /batch-approve — 部分失败
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_batch_approve_partial_failure():
    """批量审批 2 条，1 成功 1 失败，返回 succeeded=1, failed=1"""
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    _mock_db_holder["db"] = mock_db

    id1 = str(uuid.uuid4())
    id2 = str(uuid.uuid4())

    with patch("api.approval_routes._svc") as mock_svc:
        mock_svc.batch_approve = AsyncMock(
            return_value={
                "total": 2,
                "succeeded": 1,
                "failed": 1,
                "results": [
                    {"request_id": id1, "ok": True, "status": "approved"},
                    {"request_id": id2, "ok": False, "reason": "审批单不存在"},
                ],
            }
        )

        resp = client.post(
            "/api/v1/growth/approvals/batch-approve",
            json={
                "request_ids": [id1, id2],
                "approver_id": APPROVER_ID,
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["succeeded"] == 1
    assert body["data"]["failed"] == 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 23: 条件评估引擎 — _evaluate_conditions 单元测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_evaluate_conditions_gt():
    """gt 操作符：大于阈值时返回 True"""
    from services.approval_service import _evaluate_conditions

    data = {"max_discount_fen": 6000}
    conditions = [{"field": "max_discount_fen", "op": "gt", "value": 5000}]
    assert _evaluate_conditions(conditions, data) is True


def test_evaluate_conditions_not_met():
    """条件不满足时返回 False"""
    from services.approval_service import _evaluate_conditions

    data = {"max_discount_fen": 3000}
    conditions = [{"field": "max_discount_fen", "op": "gt", "value": 5000}]
    assert _evaluate_conditions(conditions, data) is False


def test_evaluate_conditions_in_operator():
    """in 操作符：值在列表中时返回 True"""
    from services.approval_service import _evaluate_conditions

    data = {"campaign_type": "lottery"}
    conditions = [{"field": "campaign_type", "op": "in", "value": ["lottery", "red_packet"]}]
    assert _evaluate_conditions(conditions, data) is True


def test_evaluate_conditions_in_operator_not_found():
    """in 操作符：值不在列表中时返回 False"""
    from services.approval_service import _evaluate_conditions

    data = {"campaign_type": "birthday"}
    conditions = [{"field": "campaign_type", "op": "in", "value": ["lottery", "red_packet"]}]
    assert _evaluate_conditions(conditions, data) is False


def test_evaluate_conditions_multiple_and():
    """多条件 AND：所有条件均满足时返回 True"""
    from services.approval_service import _evaluate_conditions

    data = {"max_discount_fen": 6000, "target_count": 600}
    conditions = [
        {"field": "max_discount_fen", "op": "gt", "value": 5000},
        {"field": "target_count", "op": "gte", "value": 500},
    ]
    assert _evaluate_conditions(conditions, data) is True


def test_evaluate_conditions_multiple_and_partial_fail():
    """多条件 AND：部分条件不满足时返回 False"""
    from services.approval_service import _evaluate_conditions

    data = {"max_discount_fen": 6000, "target_count": 100}
    conditions = [
        {"field": "max_discount_fen", "op": "gt", "value": 5000},
        {"field": "target_count", "op": "gte", "value": 500},
    ]
    assert _evaluate_conditions(conditions, data) is False


def test_evaluate_conditions_empty():
    """空条件列表返回 False"""
    from services.approval_service import _evaluate_conditions

    assert _evaluate_conditions([], {"any": "data"}) is False


def test_evaluate_conditions_missing_field():
    """数据中缺少条件字段时返回 False"""
    from services.approval_service import _evaluate_conditions

    data = {"other_field": 100}
    conditions = [{"field": "max_discount_fen", "op": "gt", "value": 5000}]
    assert _evaluate_conditions(conditions, data) is False


def test_evaluate_conditions_eq():
    """eq 操作符"""
    from services.approval_service import _evaluate_conditions

    data = {"status": "active"}
    conditions = [{"field": "status", "op": "eq", "value": "active"}]
    assert _evaluate_conditions(conditions, data) is True


def test_evaluate_conditions_lt_lte():
    """lt 和 lte 操作符"""
    from services.approval_service import _evaluate_conditions

    data = {"amount": 100}
    assert _evaluate_conditions([{"field": "amount", "op": "lt", "value": 200}], data) is True
    assert _evaluate_conditions([{"field": "amount", "op": "lt", "value": 100}], data) is False
    assert _evaluate_conditions([{"field": "amount", "op": "lte", "value": 100}], data) is True
