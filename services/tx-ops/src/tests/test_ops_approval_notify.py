"""审批中心 + 审批流 + 通知服务路由测试（共 13 个测试）

覆盖范围：
  approval_center_routes（4个测试）：
    GET  /api/v1/approval-center/pending          — 正常返回 / DB 错误降级
    GET  /api/v1/approval-center/stats            — 正常统计
    POST /api/v1/approval-center/pending/{id}/action — approve 成功 / 非法 action 400

  approval_workflow_routes（5个测试）：
    GET  /api/v1/ops/approvals/templates          — 返回模板列表
    POST /api/v1/ops/approvals/templates          — 新建模板
    GET  /api/v1/ops/approvals/instances/pending-mine — 待审列表
    GET  /api/v1/ops/approvals/instances/{id}    — 实例详情 / 404

  notification_routes（4个测试）：
    POST /api/v1/notifications/send               — SMS 成功 / 缺少 phone 400
    POST /api/v1/notifications/send               — WeChat 成功
    GET  /api/v1/notifications                    — 列表查询
    POST /api/v1/notifications/send               — WeCom 成功

技术约束：
  - sys.modules 存根注入隔离 shared.ontology / shared.events / asyncpg / structlog
  - app.dependency_overrides[get_db] 注入 mock AsyncSession
  - approval_workflow_routes 使用路由内置 get_db（local），通过 app.dependency_overrides 覆盖
  - approval_engine / NotificationService 全部 mock，不触发真实 DB
"""

from __future__ import annotations

import sys
import types
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── sys.modules 存根注入（必须在导入路由前完成） ────────────────────────────────


def _ensure_stub(module_path: str, attrs: dict | None = None) -> types.ModuleType:
    if module_path not in sys.modules:
        mod = types.ModuleType(module_path)
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[module_path] = mod
    return sys.modules[module_path]


# shared.ontology.*
_ensure_stub("shared")
_ensure_stub("shared.ontology")
_ensure_stub("shared.ontology.src")
_db_mod = _ensure_stub("shared.ontology.src.database")
if not hasattr(_db_mod, "get_db"):

    async def _placeholder_get_db():  # pragma: no cover
        yield None

    _db_mod.get_db = _placeholder_get_db

# shared.events.*
_ensure_stub("shared.events")
_ensure_stub("shared.events.src")
_ensure_stub("shared.events.src.emitter", {"emit_event": AsyncMock()})
_ev_types = _ensure_stub("shared.events.src.event_types")

if not hasattr(_ev_types, "SafetyEventType"):

    class _FakeSafetyEventType:
        SAMPLE_LOGGED = "safety.sample_logged"
        TEMPERATURE_RECORDED = "safety.temperature_recorded"
        INSPECTION_DONE = "safety.inspection_done"
        VIOLATION_FOUND = "safety.violation_found"

    _ev_types.SafetyEventType = _FakeSafetyEventType

if not hasattr(_ev_types, "SafetyInspectionEventType"):

    class _FakeSafetyInspectionEventType:
        INSPECTION_STARTED = "safety.inspection.started"
        INSPECTION_COMPLETED = "safety.inspection.completed"
        INSPECTION_FAILED = "safety.inspection.failed"
        CRITICAL_ITEM_FAILED = "safety.inspection.critical_item_failed"

    _ev_types.SafetyInspectionEventType = _FakeSafetyInspectionEventType

# structlog 存根
if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.get_logger = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    sys.modules["structlog"] = _sl
else:
    # 确保已有 structlog 的 get_logger 是 MagicMock
    _existing_sl = sys.modules["structlog"]
    if not isinstance(getattr(_existing_sl, "get_logger", None), MagicMock):
        _existing_sl.get_logger = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]

# asyncpg 存根
if "asyncpg" not in sys.modules:
    _apg = types.ModuleType("asyncpg")
    _apg.connect = AsyncMock()  # type: ignore[attr-defined]
    sys.modules["asyncpg"] = _apg

# shared.ontology.src.entities 存根
_entities_mod = _ensure_stub("shared.ontology.src.entities")
for _entity_name in ["DailySummary", "EmployeeDailyPerformance", "InspectionReport", "OpsIssue", "ShiftHandover"]:
    if not hasattr(_entities_mod, _entity_name):
        setattr(_entities_mod, _entity_name, MagicMock())

# ── 导入路由 ────────────────────────────────────────────────────────────────────
from shared.ontology.src.database import get_db as shared_get_db  # noqa: E402

from ..api.approval_center_routes import router as approval_center_router  # noqa: E402

# approval_workflow_routes 内置自己的 get_db，需要先导入再覆盖
# 为避免路由内 approval_engine 导入失败，先 mock services.approval_engine
_services_stub = _ensure_stub("src.services")
_ae_stub = _ensure_stub("src.services.approval_engine")
_mock_engine = MagicMock()
_mock_engine.create_instance = AsyncMock()
_mock_engine.get_pending_for_approver = AsyncMock(return_value=[])
_mock_engine.get_my_initiated = AsyncMock(return_value=[])
_mock_engine.act = AsyncMock()
_ae_stub.approval_engine = _mock_engine

from ..api.approval_workflow_routes import get_db as workflow_get_db  # noqa: E402
from ..api.approval_workflow_routes import router as workflow_router  # noqa: E402

# notification_routes 依赖 NotificationService — 预先 mock
_ns_stub = _ensure_stub("src.services.notification_service")
_mock_ns_class = MagicMock()
_ns_stub.NotificationService = _mock_ns_class

from ..api.notification_routes import router as notification_router  # noqa: E402

# ── FastAPI 应用 ────────────────────────────────────────────────────────────────
app = FastAPI()
app.include_router(approval_center_router)
app.include_router(workflow_router)
app.include_router(notification_router)

# ── 常量 ────────────────────────────────────────────────────────────────────────
TENANT_ID = str(uuid.uuid4())
APPROVAL_ID = str(uuid.uuid4())
INSTANCE_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ── 辅助函数 ────────────────────────────────────────────────────────────────────


def _mock_row(data: dict) -> MagicMock:
    row = MagicMock()
    row._mapping = data
    for k, v in data.items():
        setattr(row, k, v)
    # 支持 row["key"] 访问
    row.__getitem__ = lambda self, key: data[key]
    return row


def _make_db_with_effects(effects: list) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=effects)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _override_shared_get_db(db_mock: AsyncMock):
    async def _dep() -> AsyncGenerator:
        yield db_mock

    return _dep


def _override_workflow_get_db(db_mock: AsyncMock):
    async def _dep() -> AsyncGenerator:
        yield db_mock

    return _dep


def _scalar_result(value) -> MagicMock:
    r = MagicMock()
    r.scalar = MagicMock(return_value=value)
    r.fetchone = MagicMock(return_value=None)
    r.fetchall = MagicMock(return_value=[])
    return r


def _fetchone_result(row: dict | None) -> MagicMock:
    r = MagicMock()
    if row is not None:
        r.fetchone = MagicMock(return_value=_mock_row(row))
    else:
        r.fetchone = MagicMock(return_value=None)
    r.scalar = MagicMock(return_value=None)
    r.fetchall = MagicMock(return_value=[])
    return r


def _fetchall_result(rows: list[dict]) -> MagicMock:
    r = MagicMock()
    r.fetchall = MagicMock(return_value=[_mock_row(row) for row in rows])
    r.fetchone = MagicMock(return_value=None)
    r.scalar = MagicMock(return_value=0)
    return r


# ══════════════════════════════════════════════════════════════════════════════
#  approval_center_routes 测试（4个）
# ══════════════════════════════════════════════════════════════════════════════


class TestApprovalCenterPending:
    """GET /api/v1/approval-center/pending"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_list_pending_success(self):
        """正常返回 pending 列表：count=2，high_urgency_count=1，items 非空。"""
        # execute 调用顺序: set_config → count → rows → high_urgency_count
        set_rls_result = MagicMock()

        count_result = _scalar_result(2)

        row_data = {
            "id": APPROVAL_ID,
            "business_type": "discount",
            "business_id": "ORD-001",
            "title": "折扣审批",
            "description": "10%折扣",
            "amount_fen": 800,
            "initiator_id": "EMP-001",
            "initiator_name": "张三",
            "current_step": 1,
            "total_steps": 2,
            "status": "pending",
            "deadline_at": None,
            "created_at": None,
            "updated_at": None,
        }
        rows_result = _fetchall_result([row_data])

        high_result = _scalar_result(1)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                set_rls_result,  # _set_rls
                count_result,  # count query
                rows_result,  # rows query
                high_result,  # high urgency count
            ]
        )

        app.dependency_overrides[shared_get_db] = _override_shared_get_db(db)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/approval-center/pending",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["total"] == 2
        assert data["high_urgency_count"] == 1
        assert isinstance(data["items"], list)
        assert len(data["items"]) == 1

    def test_list_pending_db_error_graceful_degradation(self):
        """DB 异常时降级返回空列表，不抛 500。"""
        from sqlalchemy.exc import SQLAlchemyError

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=SQLAlchemyError("DB error"))

        app.dependency_overrides[shared_get_db] = _override_shared_get_db(db)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/approval-center/pending",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0

    def test_take_action_approve_success(self):
        """POST /pending/{id}/action — action=approve → 200，status=approved。"""
        set_rls_result = MagicMock()

        instance_row = _mock_row(
            {
                "id": APPROVAL_ID,
                "status": "pending",
                "current_step": 1,
                "total_steps": 2,
                "business_type": "discount",
                "title": "折扣审批",
            }
        )
        check_result = MagicMock()
        check_result.fetchone = MagicMock(return_value=instance_row)

        update_result = MagicMock()
        insert_result = MagicMock()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                set_rls_result,  # _set_rls
                check_result,  # SELECT check
                update_result,  # UPDATE status
                insert_result,  # INSERT step_record
            ]
        )

        app.dependency_overrides[shared_get_db] = _override_shared_get_db(db)

        payload = {
            "action": "approve",
            "comment": "同意",
            "approver_id": "MGR-001",
            "approver_name": "李四",
        }

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/approval-center/pending/{APPROVAL_ID}/action",
                json=payload,
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "approved"
        assert body["data"]["action"] == "approve"

    def test_take_action_invalid_action_400(self):
        """action 不在 approve/reject 范围内 → 400。"""
        app.dependency_overrides[shared_get_db] = _override_shared_get_db(AsyncMock())

        payload = {"action": "skip", "approver_id": "MGR-001", "approver_name": "李四"}

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/approval-center/pending/{APPROVAL_ID}/action",
                json=payload,
                headers=HEADERS,
            )

        assert resp.status_code == 400
        body = resp.json()
        assert "approve" in body["detail"] or "reject" in body["detail"]


class TestApprovalCenterStats:
    """GET /api/v1/approval-center/stats"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_stats_success(self):
        """正常返回统计数据：pending_count / today_approved / type_breakdown。"""
        set_rls_result = MagicMock()

        stats_row = _mock_row(
            {
                "pending_count": 5,
                "high_urgency_count": 2,
                "today_approved": 3,
                "today_rejected": 1,
            }
        )
        stats_result = MagicMock()
        stats_result.fetchone = MagicMock(return_value=stats_row)

        type_row1 = _mock_row({"business_type": "discount", "cnt": 3})
        type_row2 = _mock_row({"business_type": "refund", "cnt": 2})
        type_result = MagicMock()
        type_result.__iter__ = MagicMock(return_value=iter([type_row1, type_row2]))

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                set_rls_result,
                stats_result,
                type_result,
            ]
        )

        app.dependency_overrides[shared_get_db] = _override_shared_get_db(db)

        with TestClient(app) as client:
            resp = client.get("/api/v1/approval-center/stats", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["pending_count"] == 5
        assert data["high_urgency_count"] == 2
        assert data["today_approved"] == 3
        assert "type_breakdown" in data


# ══════════════════════════════════════════════════════════════════════════════
#  approval_workflow_routes 测试（5个）
# ══════════════════════════════════════════════════════════════════════════════


class TestApprovalWorkflowTemplates:
    """GET/POST /api/v1/ops/approvals/templates"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _make_db(self):
        db = AsyncMock()
        # fetch_all 返回空列表
        db.fetch_all = AsyncMock(return_value=[])
        db.fetch_one = AsyncMock(return_value=None)
        db.execute = AsyncMock(return_value=MagicMock())
        return db

    def test_list_templates_empty(self):
        """GET /templates — 无过滤条件，返回空列表。"""
        db = self._make_db()
        app.dependency_overrides[workflow_get_db] = _override_workflow_get_db(db)

        with TestClient(app) as client:
            resp = client.get("/api/v1/ops/approvals/templates", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0

    def test_list_templates_with_type_filter(self):
        """GET /templates?business_type=discount — 按类型过滤，返回 1 条。"""
        row = {
            "id": str(uuid.uuid4()),
            "template_name": "折扣模板",
            "business_type": "discount",
            "steps": [],
            "is_active": True,
            "created_at": None,
            "updated_at": None,
            "tenant_id": TENANT_ID,
        }
        db = self._make_db()
        db.fetch_all = AsyncMock(return_value=[row])
        app.dependency_overrides[workflow_get_db] = _override_workflow_get_db(db)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/approvals/templates",
                params={"business_type": "discount"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 1

    def test_create_template_new(self):
        """POST /templates — 新建模板，返回 template_id。"""
        db = self._make_db()
        # fetch_one 返回 None → 走新建分支
        db.fetch_one = AsyncMock(return_value=None)
        app.dependency_overrides[workflow_get_db] = _override_workflow_get_db(db)

        payload = {
            "template_name": "折扣审批流程",
            "business_type": "discount",
            "steps": [{"step_no": 1, "role": "manager", "approver_type": "role"}],
            "is_active": True,
        }

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/ops/approvals/templates",
                json=payload,
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "id" in body["data"]
        assert body["data"]["template_name"] == "折扣审批流程"


class TestApprovalWorkflowInstances:
    """审批实例相关端点"""

    def setup_method(self):
        app.dependency_overrides.clear()
        # 重置 mock_engine 的返回值
        _mock_engine.get_pending_for_approver.return_value = []
        _mock_engine.get_my_initiated.return_value = []

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _make_db(self):
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])
        db.fetch_one = AsyncMock(return_value=None)
        db.execute = AsyncMock(return_value=MagicMock())
        return db

    def test_pending_mine_returns_list(self):
        """GET /instances/pending-mine?approver_id=EMP-001 — 返回空列表。"""
        db = self._make_db()
        app.dependency_overrides[workflow_get_db] = _override_workflow_get_db(db)

        # patch approval_engine 在路由模块中的引用
        import src.api.approval_workflow_routes as _wr

        with patch.object(_wr, "approval_engine", _mock_engine):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/ops/approvals/instances/pending-mine",
                    params={"approver_id": "EMP-001"},
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert isinstance(body["data"]["items"], list)

    def test_get_instance_detail_404(self):
        """GET /instances/{id} — 实例不存在时返回 404。"""
        db = self._make_db()
        db.fetch_one = AsyncMock(return_value=None)
        app.dependency_overrides[workflow_get_db] = _override_workflow_get_db(db)

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/ops/approvals/instances/{INSTANCE_ID}",
                headers=HEADERS,
            )

        assert resp.status_code == 404
        body = resp.json()
        assert "不存在" in body["detail"]

    def test_cancel_instance_404(self):
        """DELETE /instances/{id} — 实例不存在时返回 404。"""
        db = self._make_db()
        db.fetch_one = AsyncMock(return_value=None)
        app.dependency_overrides[workflow_get_db] = _override_workflow_get_db(db)

        with TestClient(app) as client:
            resp = client.delete(
                f"/api/v1/ops/approvals/instances/{INSTANCE_ID}",
                headers=HEADERS,
            )

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  notification_routes 测试（4个）
# ══════════════════════════════════════════════════════════════════════════════


class TestNotificationSend:
    """POST /api/v1/notifications/send"""

    def setup_method(self):
        app.dependency_overrides.clear()
        # 每次测试重新配置 mock NotificationService 实例
        self._svc_instance = AsyncMock()
        self._svc_instance.send_sms = AsyncMock(
            return_value={
                "channel": "sms",
                "status": "sent",
                "message_id": str(uuid.uuid4()),
            }
        )
        self._svc_instance.send_wechat = AsyncMock(
            return_value={
                "channel": "wechat",
                "status": "sent",
                "message_id": str(uuid.uuid4()),
            }
        )
        self._svc_instance.send_wecom = AsyncMock(
            return_value={
                "channel": "wecom",
                "status": "sent",
                "message_id": str(uuid.uuid4()),
            }
        )
        self._svc_instance.list_notifications = AsyncMock(
            return_value={
                "items": [],
                "total": 0,
                "page": 1,
                "size": 20,
            }
        )
        _mock_ns_class.return_value = self._svc_instance

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _override_db(self):
        db = AsyncMock()
        app.dependency_overrides[shared_get_db] = _override_shared_get_db(db)

    def test_send_sms_success(self):
        """POST /send channel=sms — 正常发送，返回 ok=True。"""
        self._override_db()

        payload = {
            "channel": "sms",
            "phone": "13800138000",
            "template_id": "reservation_confirmed",
            "params": {"name": "张三"},
            "store_id": str(uuid.uuid4()),
        }

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/notifications/send",
                json=payload,
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["channel"] == "sms"

    def test_send_sms_missing_phone_400(self):
        """POST /send channel=sms 但缺少 phone → 400。"""
        self._override_db()

        payload = {
            "channel": "sms",
            "template_id": "reservation_confirmed",
            # phone 字段缺失
        }

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/notifications/send",
                json=payload,
                headers=HEADERS,
            )

        assert resp.status_code == 400
        body = resp.json()
        assert "phone" in body["detail"].lower() or "sms" in body["detail"].lower()

    def test_send_wechat_success(self):
        """POST /send channel=wechat — 微信模板消息发送成功。"""
        self._override_db()

        payload = {
            "channel": "wechat",
            "openid": "oXXXXX_user_openid",
            "template_id": "reservation_confirmed",
            "params": {"order_no": "ORD-20260405-001"},
            "store_id": str(uuid.uuid4()),
        }

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/notifications/send",
                json=payload,
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["channel"] == "wechat"

    def test_send_wecom_success(self):
        """POST /send channel=wecom — 企业微信 Webhook 发送成功。"""
        self._override_db()

        payload = {
            "channel": "wecom",
            "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx",
            "content": "折扣审批通知：有1笔折扣待审批",
            "store_id": str(uuid.uuid4()),
        }

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/notifications/send",
                json=payload,
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["channel"] == "wecom"


class TestNotificationList:
    """GET /api/v1/notifications — 通知历史列表"""

    def setup_method(self):
        app.dependency_overrides.clear()
        self._svc_instance = AsyncMock()
        self._svc_instance.list_notifications = AsyncMock(
            return_value={
                "items": [
                    {
                        "id": str(uuid.uuid4()),
                        "channel": "sms",
                        "status": "sent",
                        "created_at": "2026-04-05T10:00:00Z",
                    }
                ],
                "total": 1,
                "page": 1,
                "size": 20,
            }
        )
        _mock_ns_class.return_value = self._svc_instance

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_list_notifications_success(self):
        """GET /api/v1/notifications — 返回通知列表，total=1。"""
        db = AsyncMock()
        app.dependency_overrides[shared_get_db] = _override_shared_get_db(db)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/notifications",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_list_notifications_missing_tenant_id_400(self):
        """GET /api/v1/notifications 缺少 X-Tenant-ID → 400。"""
        db = AsyncMock()
        app.dependency_overrides[shared_get_db] = _override_shared_get_db(db)

        with TestClient(app) as client:
            resp = client.get("/api/v1/notifications")  # 不带 header

        assert resp.status_code == 400
        body = resp.json()
        assert "X-Tenant-ID" in body["detail"]
