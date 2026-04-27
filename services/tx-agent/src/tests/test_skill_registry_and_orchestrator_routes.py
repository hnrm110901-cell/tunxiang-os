"""Tests for skill_registry_routes.py and orchestrator_routes.py

Covered routes:
  GET /api/v1/skills/                   — 2 scenarios
  GET /api/v1/skills/health             — 1 scenario
  GET /api/v1/skills/ontology/report    — 1 scenario
  GET /api/v1/skills/route/{event_type} — 1 scenario
  GET /api/v1/skills/{skill_name}       — 2 scenarios (found / not-found)

  POST /api/v1/orchestrate              — 3 scenarios
  GET  /api/v1/orchestrate/skill-summary — 1 scenario
  GET  /api/v1/orchestrate/{plan_id}    — 1 scenario (always 404)

Total: 12 test cases
"""

import os
import sys
import types


# ── stub heavy transitive dependencies before importing route modules ────────
def _stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules.setdefault(name, mod)
    return mod


# shared.skill_registry
_sr = _stub("shared")
_sr_skill = _stub("shared.skill_registry")

# shared.ontology.src.database
_so = _stub("shared.ontology")
_so_src = _stub("shared.ontology.src")
_so_db = _stub("shared.ontology.src.database")


async def _fake_get_db_with_tenant(tenant_id):
    yield None


_so_db.get_db_with_tenant = _fake_get_db_with_tenant
sys.modules["shared.ontology.src.database"] = _so_db

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ─────────────────────────────────────────────────────────────────────────────
# Helpers — build mock SkillRegistry / OntologyRegistry
# ─────────────────────────────────────────────────────────────────────────────


def _make_skill(name: str, display_name: str = "", version: str = "1.0"):
    meta = MagicMock()
    meta.name = name
    meta.version = version
    meta.display_name = display_name or name
    meta.category = "core"
    meta.sub_category = "ops"
    meta.description = f"{name} description"
    meta.icon = "🔧"
    meta.maintainer = "team"

    trigger = MagicMock()
    trigger.type = "test.event"
    trigger.priority = 10
    trigger.condition = None
    trigger.description = "triggered by test.event"

    triggers = MagicMock()
    triggers.events = [trigger]

    skill = MagicMock()
    skill.meta = meta
    skill.triggers = triggers
    skill.data = None
    skill.degradation = None
    skill.scope = None
    return skill


def _make_mock_registry(skills=None):
    if skills is None:
        skills = [_make_skill("skill-a"), _make_skill("skill-b")]
    registry = MagicMock()
    registry.list_skills.return_value = skills
    registry.get.side_effect = lambda name: next((s for s in skills if s.meta.name == name), None)
    registry.get_all_owned_entities.return_value = {"Order": "skill-a"}
    registry.get_emitted_events.return_value = {"order.paid": "skill-a"}
    registry.find_by_event_type.return_value = (
        [(skills[0], MagicMock(priority=10, condition=None, description="desc"))] if skills else []
    )
    return registry


def _make_mock_ontology(registry):
    onto = MagicMock()
    onto.validate.return_value = ["[WARNING] minor"]
    onto.generate_report.return_value = "Ontology Report Text"
    return onto


# ─────────────────────────────────────────────────────────────────────────────
# App fixture: skill_registry_routes
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def skill_app():
    from api.skill_registry_routes import router

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def skill_client(skill_app):
    transport = ASGITransport(app=skill_app)
    return AsyncClient(transport=transport, base_url="http://test")


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/skills/
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_skills_returns_all(skill_client):
    """GET / returns ok=True with skill list."""
    mock_registry = _make_mock_registry()
    with patch("api.skill_registry_routes._get_registry", return_value=mock_registry):
        async with skill_client as c:
            resp = await c.get("/api/v1/skills/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 2
    assert len(body["data"]["skills"]) == 2


@pytest.mark.asyncio
async def test_list_skills_empty_registry(skill_client):
    """GET / with no skills registered returns total=0."""
    mock_registry = _make_mock_registry(skills=[])
    with patch("api.skill_registry_routes._get_registry", return_value=mock_registry):
        async with skill_client as c:
            resp = await c.get("/api/v1/skills/")
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 0
    assert body["data"]["skills"] == []


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/skills/health
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_health_all_healthy(skill_client):
    """GET /health lists every skill as healthy."""
    mock_registry = _make_mock_registry()
    with patch("api.skill_registry_routes._get_registry", return_value=mock_registry):
        async with skill_client as c:
            resp = await c.get("/api/v1/skills/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["healthy"] == 2
    assert data["degraded"] == 0
    for s in data["skills"]:
        assert s["status"] == "healthy"


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/skills/ontology/report
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ontology_report_structure(skill_client):
    """GET /ontology/report returns entity_ownership and conflicts."""
    mock_registry = _make_mock_registry()
    mock_onto = _make_mock_ontology(mock_registry)

    with (
        patch("api.skill_registry_routes._get_registry", return_value=mock_registry),
        patch("api.skill_registry_routes.OntologyRegistry", return_value=mock_onto),
    ):
        async with skill_client as c:
            resp = await c.get("/api/v1/skills/ontology/report")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "entity_ownership" in data
    assert "conflicts" in data
    assert "warnings" in data
    assert "is_consistent" in data
    # No [CONFLICT] issues → consistent
    assert data["is_consistent"] is True


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/skills/route/{event_type}
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_event_returns_matched_skills(skill_client):
    """GET /route/{event_type} lists skills that handle the event."""
    mock_registry = _make_mock_registry()
    with patch("api.skill_registry_routes._get_registry", return_value=mock_registry):
        async with skill_client as c:
            resp = await c.get("/api/v1/skills/route/test.event")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["event_type"] == "test.event"
    assert isinstance(body["data"]["matched_skills"], list)
    assert len(body["data"]["matched_skills"]) >= 1
    first = body["data"]["matched_skills"][0]
    assert "skill" in first
    assert "priority" in first


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/skills/{skill_name}
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_skill_found(skill_client):
    """GET /{skill_name} returns full skill details when skill exists."""
    mock_registry = _make_mock_registry()
    with patch("api.skill_registry_routes._get_registry", return_value=mock_registry):
        async with skill_client as c:
            resp = await c.get("/api/v1/skills/skill-a")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["name"] == "skill-a"
    assert "version" in data
    assert "event_triggers" in data
    assert "emitted_events" in data


@pytest.mark.asyncio
async def test_get_skill_not_found(skill_client):
    """GET /{skill_name} returns HTTP 404 for unknown skill."""
    mock_registry = _make_mock_registry()
    with patch("api.skill_registry_routes._get_registry", return_value=mock_registry):
        async with skill_client as c:
            resp = await c.get("/api/v1/skills/does-not-exist")
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# App fixture: orchestrator_routes
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def orchestrator_app():
    from api.orchestrator_routes import _get_db_with_tenant, router

    app = FastAPI()
    # Override the DB dependency so no real DB is needed

    async def _override():
        yield None

    app.dependency_overrides[_get_db_with_tenant] = _override
    app.include_router(router)
    return app


@pytest.fixture
def orchestrator_client(orchestrator_app):
    transport = ASGITransport(app=orchestrator_app)
    return AsyncClient(transport=transport, base_url="http://test")


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/orchestrate
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_orchestrate_missing_intent_and_event_returns_422(orchestrator_client):
    """POST without intent or trigger_event raises HTTP 422."""
    payload = {"tenant_id": "t1", "store_id": "s1"}
    async with orchestrator_client as c:
        resp = await c.post(
            "/api/v1/orchestrate",
            json=payload,
            headers={"X-Tenant-ID": "t1"},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_orchestrate_with_intent_returns_plan(orchestrator_client):
    """POST with intent triggers orchestration and returns plan_id."""
    from datetime import datetime

    mock_result = MagicMock()
    mock_result.plan_id = "plan-abc-123"
    mock_result.success = True
    mock_result.completed_steps = ["step1"]
    mock_result.failed_steps = []
    mock_result.synthesis = "completed"
    mock_result.recommended_actions = []
    mock_result.constraints_passed = True
    mock_result.confidence = 0.9
    mock_result.created_at = datetime(2026, 4, 6, 12, 0, 0)

    mock_master = AsyncMock()
    mock_master.orchestrate = AsyncMock(return_value=mock_result)

    mock_log_service = MagicMock()
    mock_log_service.log_orchestrator_result = AsyncMock()

    with (
        patch("api.orchestrator_routes.MasterAgent", return_value=mock_master),
        patch("api.orchestrator_routes.DecisionLogService", mock_log_service),
        patch("api.orchestrator_routes.AgentEvent", MagicMock()),
    ):
        payload = {
            "intent": "分析门店整体运营状态",
            "tenant_id": "t1",
            "store_id": "s1",
        }
        async with orchestrator_client as c:
            resp = await c.post(
                "/api/v1/orchestrate",
                json=payload,
                headers={"X-Tenant-ID": "t1"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["plan_id"] == "plan-abc-123"
    assert body["data"]["success"] is True


@pytest.mark.asyncio
async def test_orchestrate_with_trigger_event(orchestrator_client):
    """POST with trigger_event (no intent) also orchestrates successfully."""
    from datetime import datetime

    mock_result = MagicMock()
    mock_result.plan_id = "plan-event-456"
    mock_result.success = True
    mock_result.completed_steps = []
    mock_result.failed_steps = []
    mock_result.synthesis = "ok"
    mock_result.recommended_actions = []
    mock_result.constraints_passed = True
    mock_result.confidence = 0.8
    mock_result.created_at = datetime(2026, 4, 6, 12, 0, 0)

    mock_master = AsyncMock()
    mock_master.orchestrate = AsyncMock(return_value=mock_result)

    mock_log_service = MagicMock()
    mock_log_service.log_orchestrator_result = AsyncMock()

    with (
        patch("api.orchestrator_routes.MasterAgent", return_value=mock_master),
        patch("api.orchestrator_routes.DecisionLogService", mock_log_service),
        patch("api.orchestrator_routes.AgentEvent", MagicMock()) as MockEvent,
    ):
        payload = {
            "trigger_event": {
                "event_type": "inventory.low_stock",
                "source_agent": "inventory_agent",
                "store_id": "s1",
                "data": {},
            },
            "tenant_id": "t1",
            "store_id": "s1",
        }
        async with orchestrator_client as c:
            resp = await c.post(
                "/api/v1/orchestrate",
                json=payload,
                headers={"X-Tenant-ID": "t1"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "plan_id" in body["data"]


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/orchestrate/skill-summary
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_summary_returns_total(orchestrator_client):
    """GET /skill-summary returns ok=True with total_skills."""
    mock_summary = {"total_skills": 5, "skills": []}
    with patch("api.orchestrator_routes.SkillAwareOrchestrator") as MockOrch:
        MockOrch.get_ontology_summary.return_value = mock_summary
        async with orchestrator_client as c:
            resp = await c.get("/api/v1/orchestrate/skill-summary")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total_skills"] == 5


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/orchestrate/{plan_id}
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_plan_history_always_404(orchestrator_client):
    """GET /{plan_id} always returns HTTP 404 (not yet implemented)."""
    async with orchestrator_client as c:
        resp = await c.get("/api/v1/orchestrate/plan-xyz-999")
    assert resp.status_code == 404
