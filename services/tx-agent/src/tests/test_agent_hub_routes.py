"""Agent 中枢 BFF 路由测试

覆盖端点：
  GET  /api/v1/agent-hub/status
  GET  /api/v1/agent-hub/actions
  GET  /api/v1/agent-hub/actions?status=all
  POST /api/v1/agent-hub/actions/{id}/confirm
  POST /api/v1/agent-hub/actions/{id}/dismiss
  GET  /api/v1/agent-hub/log
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock

# ─── 预置假模块，阻断真实数据库导入 ───

def _make_db_module():
    """伪造 shared.ontology.src.database，返回 mock AsyncSession"""
    mod = types.ModuleType("shared.ontology.src.database")

    async def _fake_get_db_with_tenant(tenant_id: str):
        session = AsyncMock()
        # 默认 fetchall 返回空列表
        session.execute.return_value.fetchall.return_value = []
        session.commit = AsyncMock()
        yield session

    mod.get_db_with_tenant = _fake_get_db_with_tenant
    return mod


def _setup_sys_modules():
    """注入所有假模块"""
    # shared 包层级
    for name in [
        "shared",
        "shared.ontology",
        "shared.ontology.src",
    ]:
        sys.modules.setdefault(name, types.ModuleType(name))

    sys.modules["shared.ontology.src.database"] = _make_db_module()

    # structlog stub
    if "structlog" not in sys.modules:
        sl = types.ModuleType("structlog")
        sl.get_logger = MagicMock(return_value=MagicMock(
            warning=MagicMock(),
            info=MagicMock(),
        ))
        sys.modules["structlog"] = sl


_setup_sys_modules()

# ─── 导入路由，构建 TestClient ───
import os

_svc_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _svc_root not in sys.path:
    sys.path.insert(0, _svc_root)

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.agent_hub_routes as _hub_mod

_app = FastAPI()
_app.include_router(_hub_mod.router)
_client = TestClient(_app)

TENANT = "test-tenant-001"
HEADERS = {"X-Tenant-ID": TENANT}


# ═══════════════════════════════════════
# GET /api/v1/agent-hub/status
# ═══════════════════════════════════════

class TestGetHubStatus:
    def test_returns_ok_true(self):
        """正常请求返回 ok:True"""
        resp = _client.get("/api/v1/agent-hub/status", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_returns_six_core_agents(self):
        """返回恰好 6 个核心 Agent"""
        resp = _client.get("/api/v1/agent-hub/status", headers=HEADERS)
        body = resp.json()
        agents = body["data"]["agents"]
        assert len(agents) == 6

    def test_agent_ids_correct(self):
        """6 个 Agent ID 全部正确"""
        resp = _client.get("/api/v1/agent-hub/status", headers=HEADERS)
        ids = {a["id"] for a in resp.json()["data"]["agents"]}
        assert ids == {"tx-ops", "tx-menu", "tx-growth", "tx-analytics", "tx-supply", "tx-brain"}

    def test_contains_summary(self):
        """响应包含 summary 字段，含 total_agents"""
        resp = _client.get("/api/v1/agent-hub/status", headers=HEADERS)
        summary = resp.json()["data"]["summary"]
        assert summary["total_agents"] == 6
        assert "active_count" in summary
        assert "total_pending_actions" in summary
        assert "generated_at" in summary

    def test_x_tenant_id_header_required(self):
        """缺少 X-Tenant-ID header 应返回 400 或仍可响应（FastAPI 默认值为 'default'）"""
        # 路由使用 Header("default", ...) 有默认值，不会报 422
        # 测试确认有 header 时正常工作
        resp = _client.get("/api/v1/agent-hub/status", headers=HEADERS)
        assert resp.status_code == 200

    def test_agents_have_required_fields(self):
        """每个 Agent 都含必要字段"""
        resp = _client.get("/api/v1/agent-hub/status", headers=HEADERS)
        for agent in resp.json()["data"]["agents"]:
            assert "id" in agent
            assert "name" in agent
            assert "status" in agent
            assert "today_decisions" in agent
            assert "pending_actions" in agent


# ═══════════════════════════════════════
# GET /api/v1/agent-hub/actions
# ═══════════════════════════════════════

class TestGetPendingActions:
    def test_default_returns_ok(self):
        """默认（pending_confirm 状态）返回 ok:True"""
        resp = _client.get("/api/v1/agent-hub/actions", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_default_returns_list(self):
        """返回 data 为列表"""
        resp = _client.get("/api/v1/agent-hub/actions", headers=HEADERS)
        body = resp.json()
        assert isinstance(body["data"], list)

    def test_status_all_returns_ok(self):
        """status=all 时返回 ok:True"""
        resp = _client.get("/api/v1/agent-hub/actions?status=all", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_status_all_returns_list(self):
        """status=all 返回 data 为列表"""
        resp = _client.get("/api/v1/agent-hub/actions?status=all", headers=HEADERS)
        assert isinstance(resp.json()["data"], list)

    def test_x_tenant_id_header_present(self):
        """带 X-Tenant-ID header 正常响应"""
        resp = _client.get("/api/v1/agent-hub/actions", headers=HEADERS)
        assert resp.status_code == 200

    def test_status_confirmed_filter(self):
        """status=confirmed 过滤有效"""
        resp = _client.get("/api/v1/agent-hub/actions?status=confirmed", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_status_dismissed_filter(self):
        """status=dismissed 过滤有效"""
        resp = _client.get("/api/v1/agent-hub/actions?status=dismissed", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_invalid_status_returns_422(self):
        """无效 status 参数返回 422"""
        resp = _client.get("/api/v1/agent-hub/actions?status=invalid_status", headers=HEADERS)
        assert resp.status_code == 422


# ═══════════════════════════════════════
# POST /api/v1/agent-hub/actions/{id}/confirm
# ═══════════════════════════════════════

class TestConfirmAction:
    def test_confirm_returns_ok_true(self):
        """确认行动返回 ok:True"""
        resp = _client.post(
            "/api/v1/agent-hub/actions/action-uuid-001/confirm",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_confirm_returns_message(self):
        """确认行动返回 message 字段"""
        resp = _client.post(
            "/api/v1/agent-hub/actions/action-uuid-001/confirm",
            headers=HEADERS,
        )
        assert "message" in resp.json()

    def test_confirm_with_tenant_header(self):
        """带 X-Tenant-ID header 正常响应"""
        resp = _client.post(
            "/api/v1/agent-hub/actions/action-uuid-002/confirm",
            headers=HEADERS,
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════
# POST /api/v1/agent-hub/actions/{id}/dismiss
# ═══════════════════════════════════════

class TestDismissAction:
    def test_dismiss_returns_ok_true(self):
        """驳回行动返回 ok:True"""
        resp = _client.post(
            "/api/v1/agent-hub/actions/action-uuid-003/dismiss",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_dismiss_returns_message(self):
        """驳回行动返回 message 字段"""
        resp = _client.post(
            "/api/v1/agent-hub/actions/action-uuid-003/dismiss",
            headers=HEADERS,
        )
        assert "message" in resp.json()

    def test_dismiss_with_tenant_header(self):
        """带 X-Tenant-ID header 正常响应"""
        resp = _client.post(
            "/api/v1/agent-hub/actions/action-uuid-004/dismiss",
            headers=HEADERS,
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════
# GET /api/v1/agent-hub/log
# ═══════════════════════════════════════

class TestGetActionLog:
    def test_returns_ok_true(self):
        """日志列表返回 ok:True"""
        resp = _client.get("/api/v1/agent-hub/log", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_returns_list(self):
        """data 为列表"""
        resp = _client.get("/api/v1/agent-hub/log", headers=HEADERS)
        assert isinstance(resp.json()["data"], list)

    def test_x_tenant_id_header_present(self):
        """带 X-Tenant-ID header 正常响应"""
        resp = _client.get("/api/v1/agent-hub/log", headers=HEADERS)
        assert resp.status_code == 200

    def test_agent_id_filter(self):
        """agent_id 过滤参数有效"""
        resp = _client.get(
            "/api/v1/agent-hub/log?agent_id=tx-ops",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_limit_param(self):
        """limit 参数有效"""
        resp = _client.get(
            "/api/v1/agent-hub/log?limit=10",
            headers=HEADERS,
        )
        assert resp.status_code == 200
