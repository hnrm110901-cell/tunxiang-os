"""Tests for Agent Observability API endpoints.

Tests all 6 endpoints of the observability router:
  - GET /api/v1/agent/observability/kpis
  - GET /api/v1/agent/observability/events
  - GET /api/v1/agent/observability/decisions
  - GET /api/v1/agent/observability/effectiveness
  - GET /api/v1/agent/observability/health
  - GET /api/v1/agent/observability/event-chain/{correlation_id}
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from api.observability import router

# Build a lightweight test app with only the observability router
_test_app = FastAPI()
_test_app.include_router(router)


@pytest.fixture
def client():
    transport = ASGITransport(app=_test_app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_kpis(client):
    """GET /api/v1/agent/observability/kpis returns correct KPI structure."""
    async with client as c:
        resp = await c.get("/api/v1/agent/observability/kpis")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "today_decisions" in data
    assert "adoption_rate" in data
    assert "avg_effectiveness_score" in data
    assert "constraint_blocks" in data
    assert "active_agents" in data
    assert "total_events_today" in data
    assert isinstance(data["today_decisions"], int)
    assert 0 <= data["adoption_rate"] <= 100
    assert 0 <= data["avg_effectiveness_score"] <= 100


@pytest.mark.asyncio
async def test_events_default(client):
    """GET /api/v1/agent/observability/events returns paginated event list."""
    async with client as c:
        resp = await c.get("/api/v1/agent/observability/events")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "size" in data
    assert isinstance(data["items"], list)
    assert data["total"] >= len(data["items"])
    if data["items"]:
        event = data["items"][0]
        assert "event_id" in event
        assert "timestamp" in event
        assert "source_agent" in event
        assert "event_type" in event
        assert "summary" in event


@pytest.mark.asyncio
async def test_events_filtered_by_agent(client):
    """GET /api/v1/agent/observability/events?agent=discount_guard filters correctly."""
    async with client as c:
        resp = await c.get("/api/v1/agent/observability/events?agent=discount_guard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    for event in body["data"]["items"]:
        assert event["source_agent"] == "discount_guard"


@pytest.mark.asyncio
async def test_events_filtered_by_type(client):
    """GET /api/v1/agent/observability/events?event_type=inventory_surplus filters correctly."""
    async with client as c:
        resp = await c.get("/api/v1/agent/observability/events?event_type=inventory_surplus")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    for event in body["data"]["items"]:
        assert event["event_type"] == "inventory_surplus"


@pytest.mark.asyncio
async def test_decisions_default(client):
    """GET /api/v1/agent/observability/decisions returns paginated decision list."""
    async with client as c:
        resp = await c.get("/api/v1/agent/observability/decisions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)
    if data["items"]:
        dec = data["items"][0]
        assert "decision_id" in dec
        assert "agent" in dec
        assert "agent_name" in dec
        assert "decision" in dec
        assert "confidence" in dec
        assert "status" in dec


@pytest.mark.asyncio
async def test_decisions_filtered_by_agent(client):
    """GET /api/v1/agent/observability/decisions?agent=discount_guard filters correctly."""
    async with client as c:
        resp = await c.get("/api/v1/agent/observability/decisions?agent=discount_guard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    for dec in body["data"]["items"]:
        assert dec["agent"] == "discount_guard"


@pytest.mark.asyncio
async def test_decisions_filtered_by_status(client):
    """GET /api/v1/agent/observability/decisions?status=auto_executed filters correctly."""
    async with client as c:
        resp = await c.get("/api/v1/agent/observability/decisions?status=auto_executed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    for dec in body["data"]["items"]:
        assert dec["status"] == "auto_executed"


@pytest.mark.asyncio
async def test_effectiveness(client):
    """GET /api/v1/agent/observability/effectiveness returns agent scores and distributions."""
    async with client as c:
        resp = await c.get("/api/v1/agent/observability/effectiveness")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "agents" in data
    assert "decision_type_distribution" in data
    assert "agent_monthly_stats" in data
    assert isinstance(data["agents"], list)
    assert len(data["agents"]) > 0
    agent = data["agents"][0]
    assert "agent_id" in agent
    assert "agent_name" in agent
    assert "current_score" in agent
    assert "trend" in agent
    assert "scores_30d" in agent
    assert len(agent["scores_30d"]) == 30
    for dist in data["decision_type_distribution"]:
        assert "type" in dist
        assert "label" in dist
        assert "count" in dist
    for stat in data["agent_monthly_stats"]:
        assert "agent_name" in stat
        assert "suggestions" in stat
        assert "adopted" in stat


@pytest.mark.asyncio
async def test_health(client):
    """GET /api/v1/agent/observability/health returns agent health status."""
    async with client as c:
        resp = await c.get("/api/v1/agent/observability/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "agents" in data
    assert "summary" in data
    assert isinstance(data["agents"], list)
    assert len(data["agents"]) > 0
    agent = data["agents"][0]
    assert "agent_id" in agent
    assert "agent_name" in agent
    assert "status" in agent
    assert agent["status"] in ("healthy", "warning", "error")
    assert "today_calls" in agent
    assert "avg_latency_ms" in agent
    assert "error_rate" in agent
    summary = data["summary"]
    assert "total_agents" in summary
    assert "healthy" in summary
    assert "warning" in summary
    assert "error" in summary
    assert summary["total_agents"] == summary["healthy"] + summary["warning"] + summary["error"]


@pytest.mark.asyncio
async def test_event_chain_existing(client):
    """GET /api/v1/agent/observability/event-chain/{id} returns chain for known correlation_id."""
    async with client as c:
        resp = await c.get("/api/v1/agent/observability/event-chain/chain-001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["correlation_id"] == "chain-001"
    assert "events" in data
    assert "count" in data
    assert data["count"] == len(data["events"])
    assert data["count"] > 0
    event = data["events"][0]
    assert "event_id" in event
    assert "source_agent" in event
    assert "summary" in event


@pytest.mark.asyncio
async def test_event_chain_unknown(client):
    """GET /api/v1/agent/observability/event-chain/{id} returns empty for unknown id."""
    async with client as c:
        resp = await c.get("/api/v1/agent/observability/event-chain/nonexistent")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["count"] == 0
    assert body["data"]["events"] == []
