"""Tests for master_agent_routes.py and daily_review_routes.py

Covered routes:
  POST /api/v1/agent/execute       — 4 scenarios
  GET  /api/v1/agent/tasks/{id}    — 2 scenarios
  GET  /api/v1/agent/health        — 2 scenarios
  POST /api/v1/agent/chat          — 3 scenarios
  GET  /api/v1/daily-review/today  — 2 scenarios
  POST /api/v1/daily-review/complete-node — 2 scenarios
  GET  /api/v1/daily-review/multi-store   — 1 scenario

Total: 16 test cases
"""
import os
import sys
import types

# ── fake src.db so imports inside the route modules don't fail ─────────────
_src_mod = types.ModuleType("src")
_db_mod = types.ModuleType("src.db")

async def _fake_get_db():
    yield None

_db_mod.get_db = _fake_get_db
sys.modules.setdefault("src", _src_mod)
sys.modules.setdefault("src.db", _db_mod)

# Ensure the tx-agent src directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# App fixture: master_agent_routes
# ─────────────────────────────────────────────────────────────────────────────

def _build_master_app():
    from api.master_agent_routes import router, _task_store
    app = FastAPI()
    app.include_router(router)
    return app, _task_store


@pytest.fixture
def master_client():
    app, _ = _build_master_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/agent/execute
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_no_intent_returns_failed(master_client):
    """When instruction contains no recognised keywords, ok=False."""
    payload = {
        "tenant_id": "t1",
        "store_id": "s1",
        "instruction": "这是一段无意义的指令",
    }
    async with master_client as c:
        resp = await c.post("/api/v1/agent/execute", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["data"]["status"] == "failed"
    assert body["data"]["agent_invoked"] == "unknown"


@pytest.mark.asyncio
async def test_execute_with_intent_calls_brain_agent(master_client):
    """When instruction contains '库存', the inventory agent is invoked."""
    fake_result = {"summary": "库存正常", "constraints_check": {"passed": True}}

    with patch(
        "api.master_agent_routes._call_brain_agent",
        new=AsyncMock(return_value=fake_result),
    ):
        payload = {
            "tenant_id": "t1",
            "store_id": "s1",
            "instruction": "请检查今日库存情况",
        }
        async with master_client as c:
            resp = await c.post("/api/v1/agent/execute", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "completed"
    assert body["data"]["agent_invoked"] == "库存预警"


@pytest.mark.asyncio
async def test_execute_async_mode_returns_pending(master_client):
    """async_mode=True returns immediately with status=pending."""
    payload = {
        "tenant_id": "t1",
        "store_id": "s1",
        "instruction": "分析折扣风险",
        "async_mode": True,
    }
    with patch("api.master_agent_routes._call_brain_agent", new=AsyncMock()):
        async with master_client as c:
            resp = await c.post("/api/v1/agent/execute", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "pending"
    assert "task_id" in body["data"]


@pytest.mark.asyncio
async def test_execute_brain_fallback_returns_failed(master_client):
    """When tx-brain returns fallback=True, status should be failed."""
    fallback_result = {"error": "tx-brain 请求超时", "fallback": True}

    with patch(
        "api.master_agent_routes._call_brain_agent",
        new=AsyncMock(return_value=fallback_result),
    ):
        payload = {
            "tenant_id": "t1",
            "store_id": "s1",
            "instruction": "分析今日库存风险",
        }
        async with master_client as c:
            resp = await c.post("/api/v1/agent/execute", json=payload)

    body = resp.json()
    assert body["ok"] is False
    assert body["data"]["status"] == "failed"


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/agent/tasks/{task_id}
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_task_status_not_found(master_client):
    """Non-existent task_id returns ok=False."""
    async with master_client as c:
        resp = await c.get("/api/v1/agent/tasks/nonexistent-id-12345")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["data"] is None


@pytest.mark.asyncio
async def test_get_task_status_found():
    """Existing task_id returns ok=True with task data."""
    from api.master_agent_routes import router, _task_store

    # Pre-populate the task store
    _task_store["test-task-99"] = {
        "task_id": "test-task-99",
        "status": "completed",
        "agent_invoked": "库存预警",
    }

    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/v1/agent/tasks/test-task-99")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["task_id"] == "test-task-99"
    assert body["data"]["status"] == "completed"

    # Cleanup
    _task_store.pop("test-task-99", None)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/agent/health
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_health_when_brain_reachable(master_client):
    """Health endpoint shows all agents ready when tx-brain is up."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"status": "ok"}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("api.master_agent_routes.httpx.AsyncClient", return_value=mock_client):
        async with master_client as c:
            resp = await c.get("/api/v1/agent/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["tx_brain_reachable"] is True
    assert body["data"]["total_agents"] == 9
    assert body["data"]["ready_count"] == 9


@pytest.mark.asyncio
async def test_agent_health_when_brain_unreachable(master_client):
    """Health endpoint shows agents degraded when tx-brain is down."""
    import httpx

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(
        side_effect=httpx.RequestError("connection refused")
    )

    with patch("api.master_agent_routes.httpx.AsyncClient", return_value=mock_client):
        async with master_client as c:
            resp = await c.get("/api/v1/agent/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["tx_brain_reachable"] is False
    assert body["data"]["ready_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/agent/chat
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_no_intent_returns_help_message(master_client):
    """Chat with no recognisable keywords returns generic help reply."""
    payload = {
        "message": "你好",
        "tenant_id": "t1",
        "store_id": "s1",
    }
    async with master_client as c:
        resp = await c.post("/api/v1/agent/chat", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "屯象OS" in body["data"]["reply"]


@pytest.mark.asyncio
async def test_chat_with_intent_calls_agent(master_client):
    """Chat with recognised keyword triggers agent and returns reply."""
    fake_result = {"summary": "折扣风险低", "constraints_check": {"passed": True}}

    with patch(
        "api.master_agent_routes._call_brain_agent",
        new=AsyncMock(return_value=fake_result),
    ):
        payload = {
            "message": "分析今日折扣情况",
            "tenant_id": "t1",
            "store_id": "s1",
        }
        async with master_client as c:
            resp = await c.post("/api/v1/agent/chat", json=payload)

    body = resp.json()
    assert body["ok"] is True
    assert "折扣守护" in body["data"]["reply"]
    assert len(body["data"]["actions_taken"]) > 0


@pytest.mark.asyncio
async def test_chat_brain_fallback_returns_error_message(master_client):
    """Chat with fallback from tx-brain shows error reply."""
    fallback = {"fallback": True, "error": "timeout"}

    with patch(
        "api.master_agent_routes._call_brain_agent",
        new=AsyncMock(return_value=fallback),
    ):
        payload = {
            "message": "分析库存",
            "tenant_id": "t1",
            "store_id": "s1",
        }
        async with master_client as c:
            resp = await c.post("/api/v1/agent/chat", json=payload)

    body = resp.json()
    assert body["ok"] is True
    assert "暂时无法" in body["data"]["reply"]


# ─────────────────────────────────────────────────────────────────────────────
# App fixture: daily_review_routes
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def daily_review_client():
    from api.daily_review_routes import router
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/daily-review/today
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_daily_review_today_returns_state(daily_review_client):
    """GET /today returns structured node list for given store."""
    async with daily_review_client as c:
        resp = await c.get(
            "/api/v1/daily-review/today",
            params={"store_id": "store-001"},
            headers={"X-Tenant-ID": "tenant-001"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["store_id"] == "store-001"
    assert "nodes" in data
    assert len(data["nodes"]) == 8   # E1-E8
    assert "completion_rate" in data
    assert "health_score" in data


@pytest.mark.asyncio
async def test_daily_review_today_nodes_have_required_fields(daily_review_client):
    """Each node in the response has all required fields."""
    async with daily_review_client as c:
        resp = await c.get(
            "/api/v1/daily-review/today",
            params={"store_id": "store-002"},
            headers={"X-Tenant-ID": "tenant-001"},
        )
    body = resp.json()
    assert body["ok"] is True
    for node in body["data"]["nodes"]:
        assert "node_id" in node
        assert "name" in node
        assert "deadline" in node
        assert "status" in node


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/daily-review/complete-node
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_complete_node_success(daily_review_client):
    """Marking a pending node as completed returns ok=True."""
    payload = {
        "store_id": "store-complete-test",
        "node_id": "E1",
        "operator_id": "mgr-001",
    }
    async with daily_review_client as c:
        resp = await c.post(
            "/api/v1/daily-review/complete-node",
            json=payload,
            headers={"X-Tenant-ID": "tenant-001"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "E1" in body["data"]["message"]


@pytest.mark.asyncio
async def test_complete_node_already_done_returns_400(daily_review_client):
    """Completing an already-completed node returns HTTP 400."""
    payload = {
        "store_id": "store-already-done",
        "node_id": "E2",
        "operator_id": "mgr-001",
    }
    # First completion should succeed
    async with daily_review_client as c:
        await c.post(
            "/api/v1/daily-review/complete-node",
            json=payload,
            headers={"X-Tenant-ID": "tenant-002"},
        )
        # Second completion on already-done node should return 400
        resp2 = await c.post(
            "/api/v1/daily-review/complete-node",
            json=payload,
            headers={"X-Tenant-ID": "tenant-002"},
        )
    assert resp2.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/daily-review/multi-store
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_store_summary_returns_list(daily_review_client):
    """GET /multi-store returns a list of store summaries."""
    async with daily_review_client as c:
        resp = await c.get(
            "/api/v1/daily-review/multi-store",
            params={"store_ids": "store-A,store-B"},
            headers={"X-Tenant-ID": "tenant-001"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "items" in body["data"]
    assert isinstance(body["data"]["items"], list)
