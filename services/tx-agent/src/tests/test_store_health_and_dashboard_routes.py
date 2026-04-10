"""Tests for store_health_routes.py and dashboard_routes.py

Covered routes:
  GET /api/v1/store-health/overview           — 4 scenarios
  GET /api/v1/store-health/{store_id}         — 4 scenarios
  GET /api/v1/dashboard/summary               — 3 scenarios

Also covers pure-function helpers:
  _calc_health_score, _health_grade, _build_alerts, _calc_summary, _degraded_item

Total: 17 test cases
"""
import os
import sys
import types

# ── stub heavy shared dependencies before any local import ─────────────────
_src_mod = types.ModuleType("src")
_db_mod = types.ModuleType("src.db")

async def _fake_get_db():
    yield None

_db_mod.get_db = _fake_get_db
sys.modules.setdefault("src", _src_mod)
sys.modules.setdefault("src.db", _db_mod)

# stub shared.ontology.src.database
_shared = types.ModuleType("shared")
_shared_ont = types.ModuleType("shared.ontology")
_shared_ont_src = types.ModuleType("shared.ontology.src")
_shared_db = types.ModuleType("shared.ontology.src.database")

async def _fake_get_db_with_tenant(tenant_id: str):
    yield None

_shared_db.get_db_with_tenant = _fake_get_db_with_tenant
sys.modules.setdefault("shared", _shared)
sys.modules.setdefault("shared.ontology", _shared_ont)
sys.modules.setdefault("shared.ontology.src", _shared_ont_src)
sys.modules.setdefault("shared.ontology.src.database", _shared_db)

# stub structlog
import logging
_structlog = types.ModuleType("structlog")
_structlog.get_logger = lambda *a, **kw: logging.getLogger("test")
sys.modules.setdefault("structlog", _structlog)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Helper: stub DailyReviewService
# ─────────────────────────────────────────────────────────────────────────────

def _stub_daily_review_service(completion_rate: float = 0.8):
    """Return a MagicMock that mimics DailyReviewService.get_multi_store_summary."""
    mock_svc = MagicMock()
    mock_svc.get_multi_store_summary.return_value = [{"completion_rate": completion_rate}]
    return mock_svc


# ─────────────────────────────────────────────────────────────────────────────
# Pure-function unit tests (store_health_routes helpers)
# ─────────────────────────────────────────────────────────────────────────────

def test_calc_health_score_perfect():
    from api.store_health_routes import _calc_health_score
    score = _calc_health_score(revenue_rate=1.0, cost_rate=0.20, daily_review_rate=1.0)
    # revenue_score=100*0.4=40, cost_score=100*0.3=30, review_score=100*0.3=30 → 100
    assert score == 100


def test_calc_health_score_poor():
    from api.store_health_routes import _calc_health_score
    # revenue_rate=0.0 → revenue_score=0; cost_rate=0.60 → cost_score=0; review=0.0
    score = _calc_health_score(revenue_rate=0.0, cost_rate=0.60, daily_review_rate=0.0)
    assert score == 0


def test_health_grade_mapping():
    from api.store_health_routes import _health_grade
    assert _health_grade(100) == "A"
    assert _health_grade(80) == "A"
    assert _health_grade(79) == "B"
    assert _health_grade(60) == "B"
    assert _health_grade(59) == "C"
    assert _health_grade(40) == "C"
    assert _health_grade(39) == "D"


def test_build_alerts_offline_store():
    from api.store_health_routes import _build_alerts
    alerts = _build_alerts(revenue_rate=1.0, cost_rate=0.25, daily_review_rate=1.0, store_status="offline")
    assert "门店离线" in alerts


def test_build_alerts_high_cost_and_low_revenue():
    from api.store_health_routes import _build_alerts
    alerts = _build_alerts(revenue_rate=0.5, cost_rate=0.55, daily_review_rate=0.8, store_status="online")
    assert any("成本率过高" in a for a in alerts)
    assert any("营收仅达目标" in a for a in alerts)


def test_calc_summary_basic():
    from api.store_health_routes import _calc_summary
    items = [
        {"status": "online",  "health_score": 80, "today_revenue_fen": 10000},
        {"status": "offline", "health_score": 50, "today_revenue_fen": 0},
        {"status": "online",  "health_score": -1, "today_revenue_fen": 5000},
    ]
    summary = _calc_summary(items)
    assert summary["total_stores"] == 3
    assert summary["online_stores"] == 2
    assert summary["avg_health_score"] == 65   # (80+50)/2, -1 excluded
    assert summary["total_revenue_fen"] == 15000


def test_degraded_item_structure():
    from api.store_health_routes import _degraded_item
    item = _degraded_item({"store_id": "s1", "store_name": "测试店"})
    assert item["health_score"] == -1
    assert item["health_grade"] == "-"
    assert "数据加载失败" in item["alerts"]


# ─────────────────────────────────────────────────────────────────────────────
# Integration: GET /api/v1/store-health/overview
# ─────────────────────────────────────────────────────────────────────────────

def _build_store_health_app():
    from api.store_health_routes import router
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def store_health_client():
    app = _build_store_health_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_overview_no_stores(store_health_client):
    """When _fetch_all_stores returns [], summary has total_stores=0."""
    with patch("api.store_health_routes._fetch_all_stores", new=AsyncMock(return_value=[])):
        async with store_health_client as c:
            resp = await c.get("/api/v1/store-health/overview", headers={"X-Tenant-ID": "t1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["summary"]["total_stores"] == 0
    assert body["data"]["stores"] == []


@pytest.mark.asyncio
async def test_overview_with_stores(store_health_client):
    """Happy path: two stores, results returned in data.stores."""
    fake_stores = [
        {"store_id": "s1", "store_name": "北京店", "status": "online", "daily_target_fen": 100000},
        {"store_id": "s2", "store_name": "上海店", "status": "online", "daily_target_fen": 80000},
    ]
    fake_item = {
        "store_id": "s1", "store_name": "北京店", "status": "online",
        "health_score": 85, "health_grade": "A", "today_revenue_fen": 90000,
        "revenue_rate": 0.9, "cost_rate": 0.28, "daily_review_completion": 0.9, "alerts": [],
    }

    async def fake_build_item(*args, **kwargs):
        return fake_item

    with patch("api.store_health_routes._fetch_all_stores", new=AsyncMock(return_value=fake_stores)), \
         patch("api.store_health_routes._build_store_health_item", side_effect=fake_build_item):
        async with store_health_client as c:
            resp = await c.get("/api/v1/store-health/overview", headers={"X-Tenant-ID": "t1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["stores"]) == 2


@pytest.mark.asyncio
async def test_overview_db_error_returns_empty(store_health_client):
    """When _fetch_all_stores raises SQLAlchemyError, return empty summary gracefully."""
    from sqlalchemy.exc import SQLAlchemyError
    with patch("api.store_health_routes._fetch_all_stores", new=AsyncMock(side_effect=SQLAlchemyError("db err"))):
        async with store_health_client as c:
            resp = await c.get("/api/v1/store-health/overview", headers={"X-Tenant-ID": "t1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["summary"]["total_stores"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Integration: GET /api/v1/store-health/{store_id}
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_detail_store_not_found(store_health_client):
    """404 when store row not returned from DB."""
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("api.store_health_routes._get_db_with_tenant", return_value=mock_db):
        async with store_health_client as c:
            resp = await c.get("/api/v1/store-health/nonexistent-id", headers={"X-Tenant-ID": "t1"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_detail_happy_path(store_health_client):
    """Happy path: store found, health item returned."""
    fake_row = MagicMock()
    fake_row.store_id = "s1"
    fake_row.store_name = "测试店"
    fake_row.status = "online"
    fake_row.daily_target_fen = 100000

    mock_result = MagicMock()
    mock_result.fetchone.return_value = fake_row
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    fake_item = {
        "store_id": "s1", "store_name": "测试店", "status": "online",
        "health_score": 88, "health_grade": "A", "today_revenue_fen": 88000,
        "revenue_rate": 0.88, "cost_rate": 0.28, "daily_review_completion": 0.9, "alerts": [],
    }
    with patch("api.store_health_routes._get_db_with_tenant", return_value=mock_db), \
         patch("api.store_health_routes._build_store_health_item", new=AsyncMock(return_value=fake_item)):
        async with store_health_client as c:
            resp = await c.get("/api/v1/store-health/s1", headers={"X-Tenant-ID": "t1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["health_score"] == 88


# ─────────────────────────────────────────────────────────────────────────────
# Integration: GET /api/v1/dashboard/summary
# ─────────────────────────────────────────────────────────────────────────────

def _build_dashboard_app():
    from api.dashboard_routes import router
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def dashboard_client():
    app = _build_dashboard_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _make_fetch_kpi_mock(revenue_fen=50000, order_count=30, avg_order_fen=1666, cost_rate=0.32):
    async def _mock(*args, **kwargs):
        return {
            "revenue_fen": revenue_fen,
            "order_count": order_count,
            "avg_order_fen": avg_order_fen,
            "cost_rate": cost_rate,
        }
    return _mock


@pytest.mark.asyncio
async def test_dashboard_summary_happy_path(dashboard_client):
    """Happy path: kpi + stores + decisions all returned."""
    with patch("api.dashboard_routes._fetch_today_kpi", side_effect=_make_fetch_kpi_mock()), \
         patch("api.dashboard_routes._fetch_store_health", new=AsyncMock(return_value=[])), \
         patch("api.dashboard_routes._fetch_recent_decisions", new=AsyncMock(return_value=[])):
        async with dashboard_client as c:
            resp = await c.get("/api/v1/dashboard/summary", headers={"X-Tenant-ID": "t1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["kpi"]["revenue_fen"] == 50000
    assert "generated_at" in body["data"]


@pytest.mark.asyncio
async def test_dashboard_summary_with_store_data(dashboard_client):
    """Stores list populated when _fetch_store_health returns data."""
    fake_stores = [
        {"store_id": "s1", "store_name": "店A", "today_revenue_fen": 30000, "today_orders": 20, "status": "online"},
    ]
    with patch("api.dashboard_routes._fetch_today_kpi", side_effect=_make_fetch_kpi_mock()), \
         patch("api.dashboard_routes._fetch_store_health", new=AsyncMock(return_value=fake_stores)), \
         patch("api.dashboard_routes._fetch_recent_decisions", new=AsyncMock(return_value=[])):
        async with dashboard_client as c:
            resp = await c.get("/api/v1/dashboard/summary", headers={"X-Tenant-ID": "t1"})
    body = resp.json()
    assert len(body["data"]["stores"]) == 1
    assert body["data"]["stores"][0]["store_name"] == "店A"


@pytest.mark.asyncio
async def test_dashboard_summary_decisions_included(dashboard_client):
    """Recent agent decisions are included in the response."""
    from datetime import datetime, timezone
    fake_decisions = [
        {"id": "d1", "agent_id": "inventory_alert", "action": "restock",
         "decision_type": "generate_restock_alerts", "confidence": 0.92,
         "created_at": datetime.now(timezone.utc).isoformat()},
    ]
    with patch("api.dashboard_routes._fetch_today_kpi", side_effect=_make_fetch_kpi_mock()), \
         patch("api.dashboard_routes._fetch_store_health", new=AsyncMock(return_value=[])), \
         patch("api.dashboard_routes._fetch_recent_decisions", new=AsyncMock(return_value=fake_decisions)):
        async with dashboard_client as c:
            resp = await c.get("/api/v1/dashboard/summary", headers={"X-Tenant-ID": "t1"})
    body = resp.json()
    assert len(body["data"]["decisions"]) == 1
    assert body["data"]["decisions"][0]["agent_id"] == "inventory_alert"
