"""dispatch_routes.py FastAPI 路由单元测试

测试范围：
  - POST /api/v1/dispatch/alert  — 成功创建派单任务（mock DB）
  - GET  /api/v1/dispatch/rules  — DB 报错时优雅降级返回空列表（graceful fallback）
  - PUT  /api/v1/dispatch/rules  — 新建规则（无已有记录时）
  - POST /api/v1/dispatch/sla-check — DB 报错时降级返回 escalated_count=0
  - GET  /api/v1/dispatch/dashboard — 正常返回统计数据
  - GET  /api/v1/dispatch/notifications — DB 报错时降级返回空列表

技术约束：
  - 使用 FastAPI TestClient + unittest.mock 覆盖 get_db 依赖
  - 不连接真实 PostgreSQL
  - AsyncSession 以 AsyncMock 替代
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

# ── 构建最小化 FastAPI 应用（只挂载 dispatch_router）──────────────────────────
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from shared.ontology.src.database import get_db

from ..api.dispatch_routes import router as dispatch_router

app = FastAPI()
app.include_router(dispatch_router)

# ── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ── Mock DB fixture ───────────────────────────────────────────────────────────


def _make_mock_db(
    fetchone_return=None,
    fetchall_return=None,
    scalar_return=0,
    raise_on_execute: bool = False,
) -> AsyncMock:
    """返回模拟 AsyncSession。

    raise_on_execute=True 时：第1次调用（set_config RLS）正常，第2次及之后抛出 SQLAlchemyError。
    这模拟了「RLS 设置成功，但业务查询失败」的真实场景，匹配路由中的异常捕获范围。
    """
    db = AsyncMock()

    if raise_on_execute:
        # set_config 调用正常，后续 SQL 操作抛出异常
        ok_result = MagicMock()
        ok_result.fetchone.return_value = None
        call_count = {"n": 0}

        async def _execute_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return ok_result  # 第1次：set_config 成功
            raise SQLAlchemyError("DB error")  # 第2次+：业务查询失败

        db.execute = AsyncMock(side_effect=_execute_side_effect)
    else:
        mock_result = MagicMock()
        mock_result.fetchone.return_value = fetchone_return
        mock_result.fetchall.return_value = fetchall_return or []
        mock_result.scalar.return_value = scalar_return
        # scalars().all() 用于列表查询
        mock_result.mappings.return_value = MagicMock()
        mock_result.mappings.return_value.__iter__ = MagicMock(return_value=iter([]))
        db.execute = AsyncMock(return_value=mock_result)

    db.commit = AsyncMock()
    return db


def _override_get_db(mock_db: AsyncMock):
    """替换 get_db 依赖，注入 mock AsyncSession。"""

    async def _dep():
        yield mock_db

    return _dep


# ══════════════════════════════════════════════════════════════════════════════
#  POST /api/v1/dispatch/alert
# ══════════════════════════════════════════════════════════════════════════════


class TestDispatchAlert:
    """测试 handle_agent_alert 端点。"""

    def test_creates_task_successfully(self):
        """正常情况下应返回 ok=True 并包含 task_id。"""
        mock_db = _make_mock_db(fetchone_return=None)  # 无匹配规则，使用默认值

        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/dispatch/alert",
                json={
                    "alert_type": "discount_anomaly",
                    "store_id": STORE_ID,
                    "source_agent": "discount_guardian",
                    "summary": "发现未授权折扣",
                    "severity": "high",
                },
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "task_id" in data["data"]
        assert data["data"]["alert_type"] == "discount_anomaly"
        assert data["data"]["status"] == "pending"

    def test_task_uses_rule_assignee_when_rule_exists(self):
        """存在派单规则时应使用规则中的 assignee_role。"""
        # 模拟返回一条规则
        mock_rule = MagicMock()
        mock_rule.severity = "critical"
        mock_rule.escalation_minutes = 10
        mock_rule.assignee_role = "finance_manager"

        mock_db = _make_mock_db(fetchone_return=mock_rule)
        app.dependency_overrides[get_db] = _override_get_db(mock_db)

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/dispatch/alert",
                json={
                    "alert_type": "cash_anomaly",
                    "store_id": STORE_ID,
                    "source_agent": "finance_auditor",
                    "summary": "现金差异超阈值",
                },
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "finance_manager" in data["data"]["assignee_roles"]

    def test_returns_500_on_db_error(self):
        """DB 故障时应返回 500。"""
        mock_db = _make_mock_db(raise_on_execute=True)
        app.dependency_overrides[get_db] = _override_get_db(mock_db)

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/dispatch/alert",
                json={
                    "alert_type": "safety_violation",
                    "store_id": STORE_ID,
                    "summary": "检测到违规",
                },
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 500


# ══════════════════════════════════════════════════════════════════════════════
#  GET /api/v1/dispatch/rules
# ══════════════════════════════════════════════════════════════════════════════


class TestDispatchRules:
    """测试 get_rules 端点。"""

    def test_returns_empty_list_on_db_error(self):
        """DB 故障时应优雅降级，返回 ok=True 及空规则列表（不抛出 500）。"""
        mock_db = _make_mock_db(raise_on_execute=True)
        app.dependency_overrides[get_db] = _override_get_db(mock_db)

        with TestClient(app) as client:
            resp = client.get("/api/v1/dispatch/rules", headers=HEADERS)
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["rules"] == []
        assert data["data"]["total"] == 0

    def test_returns_ok_on_success(self):
        """正常 DB 查询时应返回 ok=True。"""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = _override_get_db(mock_db)

        with TestClient(app) as client:
            resp = client.get("/api/v1/dispatch/rules", headers=HEADERS)
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ══════════════════════════════════════════════════════════════════════════════
#  PUT /api/v1/dispatch/rules
# ══════════════════════════════════════════════════════════════════════════════


class TestDispatchRuleUpdate:
    """测试 update_rule 端点。"""

    def test_creates_new_rule_when_not_exists(self):
        """不存在匹配规则时应 INSERT 新规则并返回 ok=True。"""
        mock_db = _make_mock_db(fetchone_return=None)  # 无已有规则
        app.dependency_overrides[get_db] = _override_get_db(mock_db)

        with TestClient(app) as client:
            resp = client.put(
                "/api/v1/dispatch/rules",
                json={
                    "alert_type": "inventory_shortage",
                    "assignee_role": "supply_manager",
                    "escalation_minutes": 45,
                    "severity": "high",
                },
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["alert_type"] == "inventory_shortage"
        assert data["data"]["assignee_role"] == "supply_manager"

    def test_returns_500_on_db_error(self):
        """DB 故障时应返回 500。"""
        mock_db = _make_mock_db(raise_on_execute=True)
        app.dependency_overrides[get_db] = _override_get_db(mock_db)

        with TestClient(app) as client:
            resp = client.put(
                "/api/v1/dispatch/rules",
                json={
                    "alert_type": "test_type",
                    "assignee_role": "manager",
                    "escalation_minutes": 30,
                    "severity": "normal",
                },
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 500


# ══════════════════════════════════════════════════════════════════════════════
#  POST /api/v1/dispatch/sla-check
# ══════════════════════════════════════════════════════════════════════════════


class TestDispatchSlaCheck:
    """测试 sla_check 端点。"""

    def test_returns_zero_escalated_on_db_error(self):
        """DB 故障时应优雅降级，返回 escalated_count=0（不抛出 500）。"""
        mock_db = _make_mock_db(raise_on_execute=True)
        app.dependency_overrides[get_db] = _override_get_db(mock_db)

        with TestClient(app) as client:
            resp = client.post("/api/v1/dispatch/sla-check", headers=HEADERS)
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["escalated_count"] == 0

    def test_returns_ok_structure_on_success(self):
        """正常情况下返回 ok=True 且包含 checked_at 字段。"""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = _override_get_db(mock_db)

        with TestClient(app) as client:
            resp = client.post("/api/v1/dispatch/sla-check", headers=HEADERS)
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "checked_at" in data["data"]


# ══════════════════════════════════════════════════════════════════════════════
#  GET /api/v1/dispatch/dashboard
# ══════════════════════════════════════════════════════════════════════════════


class TestDispatchDashboard:
    """测试 dispatch_dashboard 端点。"""

    def test_returns_graceful_fallback_on_db_error(self):
        """DB 故障时应返回全零统计而非 500。"""
        mock_db = _make_mock_db(raise_on_execute=True)
        app.dependency_overrides[get_db] = _override_get_db(mock_db)

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/dispatch/dashboard?store_id={STORE_ID}",
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        stats = data["data"]["stats"]
        assert stats["pending"] == 0
        assert stats["escalated"] == 0
        assert data["data"]["recent_tasks"] == []

    def test_returns_store_id_in_response(self):
        """正常请求时 response 应包含所查询的 store_id。"""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = _override_get_db(mock_db)

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/dispatch/dashboard?store_id={STORE_ID}",
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["store_id"] == STORE_ID
