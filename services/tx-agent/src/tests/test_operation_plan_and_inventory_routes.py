"""Tests for operation_plan_routes.py and inventory_routes.py

Covered routes:
  POST /api/v1/operation-plans                    — 3 scenarios
  GET  /api/v1/operation-plans/pending            — 2 scenarios
  GET  /api/v1/operation-plans/{plan_id}          — 3 scenarios
  POST /api/v1/operation-plans/{plan_id}/confirm  — 3 scenarios
  POST /api/v1/operation-plans/{plan_id}/cancel   — 2 scenarios
  GET  /api/v1/inventory/dashboard                — 3 scenarios
  POST /api/v1/inventory/restock-plan             — 2 scenarios
  GET  /api/v1/inventory/restock-plan             — 2 scenarios

Total: 20 test cases
"""

import os
import sys
import types
from datetime import datetime, timezone

# ── stub heavy shared dependencies before any local import ─────────────────
_src_mod = types.ModuleType("src")
_db_mod = types.ModuleType("src.db")


async def _fake_get_db():
    yield None


_db_mod.get_db = _fake_get_db
sys.modules.setdefault("src", _src_mod)
sys.modules.setdefault("src.db", _db_mod)

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

import logging

_structlog = types.ModuleType("structlog")
_structlog.get_logger = lambda *a, **kw: logging.getLogger("test")
sys.modules.setdefault("structlog", _structlog)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers: fake OperationPlan dataclass-like object
# ─────────────────────────────────────────────────────────────────────────────


def _make_fake_plan(
    plan_id="plan-001", tenant_id="t1", status="pending_confirm", confirmed_by=None, confirmed_at=None, executed_at=None
):
    """Build a minimal fake plan object that _plan_to_out() can consume."""
    impact = MagicMock()
    impact.affected_stores = 3
    impact.affected_employees = 10
    impact.affected_members = 50
    impact.financial_impact_fen = 30000
    impact.risk_level.value = "high"
    impact.impact_summary = "批量价格变更"
    impact.warnings = ["影响范围较大"]
    impact.reversible = False

    plan = MagicMock()
    plan.plan_id = plan_id
    plan.tenant_id = tenant_id
    plan.operation_type = "menu.price.bulk_update"
    plan.operation_params = {"delta_fen": 100}
    plan.impact = impact
    plan.status.value = status
    plan.operator_id = "op-001"
    plan.confirmed_by = confirmed_by
    plan.confirmed_at = confirmed_at
    plan.executed_at = executed_at
    plan.created_at = datetime.now(timezone.utc)
    plan.expires_at = None
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# App fixture: operation_plan_routes
# ─────────────────────────────────────────────────────────────────────────────


def _build_op_plan_app():
    from api.operation_plan_routes import router

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def op_plan_client():
    app = _build_op_plan_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/operation-plans
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_operation_no_plan_needed(op_plan_client):
    """When planner.submit returns None, needs_plan=False."""
    mock_planner = MagicMock()
    mock_planner.submit = AsyncMock(return_value=None)

    with patch("api.operation_plan_routes._get_planner", return_value=mock_planner):
        async with op_plan_client as c:
            resp = await c.post(
                "/api/v1/operation-plans",
                json={"operation_type": "menu.price.single_update", "params": {}, "operator_id": "op-001"},
                headers={"X-Tenant-ID": "t1"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["needs_plan"] is False


@pytest.mark.asyncio
async def test_submit_operation_plan_triggered(op_plan_client):
    """When planner.submit returns a plan, needs_plan=True and plan is included."""
    fake_plan = _make_fake_plan()
    mock_planner = MagicMock()
    mock_planner.submit = AsyncMock(return_value=fake_plan)

    with patch("api.operation_plan_routes._get_planner", return_value=mock_planner):
        async with op_plan_client as c:
            resp = await c.post(
                "/api/v1/operation-plans",
                json={
                    "operation_type": "menu.price.bulk_update",
                    "params": {"delta_fen": 100},
                    "operator_id": "op-001",
                },
                headers={"X-Tenant-ID": "t1"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["needs_plan"] is True
    assert body["data"]["plan"]["plan_id"] == "plan-001"
    assert body["data"]["plan"]["impact"]["risk_level"] == "high"


@pytest.mark.asyncio
async def test_submit_operation_validates_required_fields(op_plan_client):
    """Missing operator_id returns 422."""
    async with op_plan_client as c:
        resp = await c.post(
            "/api/v1/operation-plans",
            json={"operation_type": "menu.price.bulk_update"},
            headers={"X-Tenant-ID": "t1"},
        )
    assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/operation-plans/pending
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_pending_plans_empty(op_plan_client):
    """Returns empty list when no pending plans."""
    mock_planner = MagicMock()
    mock_planner.get_pending_plans = AsyncMock(return_value=[])

    with patch("api.operation_plan_routes._get_planner", return_value=mock_planner):
        async with op_plan_client as c:
            resp = await c.get("/api/v1/operation-plans/pending", headers={"X-Tenant-ID": "t1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 0
    assert body["data"]["items"] == []


@pytest.mark.asyncio
async def test_list_pending_plans_with_results(op_plan_client):
    """Returns plans list correctly."""
    fake_plans = [_make_fake_plan("plan-001"), _make_fake_plan("plan-002")]
    mock_planner = MagicMock()
    mock_planner.get_pending_plans = AsyncMock(return_value=fake_plans)

    with patch("api.operation_plan_routes._get_planner", return_value=mock_planner):
        async with op_plan_client as c:
            resp = await c.get("/api/v1/operation-plans/pending", headers={"X-Tenant-ID": "t1"})
    body = resp.json()
    assert body["data"]["total"] == 2
    plan_ids = [p["plan_id"] for p in body["data"]["items"]]
    assert "plan-001" in plan_ids and "plan-002" in plan_ids


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/operation-plans/{plan_id}
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_plan_not_found(op_plan_client):
    """404 when plan does not exist."""
    mock_planner = MagicMock()
    mock_planner.get_plan = AsyncMock(return_value=None)

    with patch("api.operation_plan_routes._get_planner", return_value=mock_planner):
        async with op_plan_client as c:
            resp = await c.get("/api/v1/operation-plans/no-such-plan", headers={"X-Tenant-ID": "t1"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_plan_tenant_mismatch(op_plan_client):
    """403 when plan belongs to different tenant."""
    fake_plan = _make_fake_plan(tenant_id="other-tenant")
    mock_planner = MagicMock()
    mock_planner.get_plan = AsyncMock(return_value=fake_plan)

    with patch("api.operation_plan_routes._get_planner", return_value=mock_planner):
        async with op_plan_client as c:
            resp = await c.get("/api/v1/operation-plans/plan-001", headers={"X-Tenant-ID": "t1"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_plan_happy_path(op_plan_client):
    """Returns plan when tenant matches."""
    fake_plan = _make_fake_plan(tenant_id="t1")
    mock_planner = MagicMock()
    mock_planner.get_plan = AsyncMock(return_value=fake_plan)

    with patch("api.operation_plan_routes._get_planner", return_value=mock_planner):
        async with op_plan_client as c:
            resp = await c.get("/api/v1/operation-plans/plan-001", headers={"X-Tenant-ID": "t1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["plan_id"] == "plan-001"


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/operation-plans/{plan_id}/confirm
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_plan_success(op_plan_client):
    """Happy path: plan confirmed, updated plan returned."""
    fake_plan = _make_fake_plan(tenant_id="t1")
    confirmed_plan = _make_fake_plan(tenant_id="t1", status="confirmed")
    mock_planner = MagicMock()
    mock_planner.get_plan = AsyncMock(side_effect=[fake_plan, confirmed_plan])
    mock_planner.confirm = AsyncMock(return_value=True)

    with patch("api.operation_plan_routes._get_planner", return_value=mock_planner):
        async with op_plan_client as c:
            resp = await c.post(
                "/api/v1/operation-plans/plan-001/confirm",
                json={"operator_id": "op-002"},
                headers={"X-Tenant-ID": "t1"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "confirmed"


@pytest.mark.asyncio
async def test_confirm_plan_already_expired(op_plan_client):
    """Returns ok=False when planner.confirm returns False."""
    fake_plan = _make_fake_plan(tenant_id="t1")
    mock_planner = MagicMock()
    mock_planner.get_plan = AsyncMock(return_value=fake_plan)
    mock_planner.confirm = AsyncMock(return_value=False)

    with patch("api.operation_plan_routes._get_planner", return_value=mock_planner):
        async with op_plan_client as c:
            resp = await c.post(
                "/api/v1/operation-plans/plan-001/confirm",
                json={"operator_id": "op-002"},
                headers={"X-Tenant-ID": "t1"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "确认失败" in body["error"]["message"]


@pytest.mark.asyncio
async def test_confirm_plan_not_found(op_plan_client):
    """404 when plan not found during confirm."""
    mock_planner = MagicMock()
    mock_planner.get_plan = AsyncMock(return_value=None)

    with patch("api.operation_plan_routes._get_planner", return_value=mock_planner):
        async with op_plan_client as c:
            resp = await c.post(
                "/api/v1/operation-plans/ghost-plan/confirm",
                json={"operator_id": "op-002"},
                headers={"X-Tenant-ID": "t1"},
            )
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/operation-plans/{plan_id}/cancel
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_plan_success(op_plan_client):
    """Happy path: plan cancelled successfully."""
    fake_plan = _make_fake_plan(tenant_id="t1")
    cancelled_plan = _make_fake_plan(tenant_id="t1", status="cancelled")
    mock_planner = MagicMock()
    mock_planner.get_plan = AsyncMock(side_effect=[fake_plan, cancelled_plan])
    mock_planner.cancel = AsyncMock(return_value=True)

    with patch("api.operation_plan_routes._get_planner", return_value=mock_planner):
        async with op_plan_client as c:
            resp = await c.post(
                "/api/v1/operation-plans/plan-001/cancel",
                json={"operator_id": "op-001"},
                headers={"X-Tenant-ID": "t1"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_plan_already_executed(op_plan_client):
    """Returns ok=False when cancel is rejected by planner."""
    fake_plan = _make_fake_plan(tenant_id="t1", status="executed")
    mock_planner = MagicMock()
    mock_planner.get_plan = AsyncMock(return_value=fake_plan)
    mock_planner.cancel = AsyncMock(return_value=False)

    with patch("api.operation_plan_routes._get_planner", return_value=mock_planner):
        async with op_plan_client as c:
            resp = await c.post(
                "/api/v1/operation-plans/plan-001/cancel",
                json={"operator_id": "op-001"},
                headers={"X-Tenant-ID": "t1"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "取消失败" in body["error"]["message"]


# ─────────────────────────────────────────────────────────────────────────────
# App fixture: inventory_routes
# ─────────────────────────────────────────────────────────────────────────────


def _build_inventory_app():
    from api.inventory_routes import router

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def inventory_client():
    app = _build_inventory_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/inventory/dashboard
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inventory_dashboard_happy_path(inventory_client):
    """Returns summary and low_items on success."""
    summary_row = MagicMock()
    summary_row.out_of_stock = 2
    summary_row.critical = 3
    summary_row.low_stock = 5
    summary_row.normal = 90
    summary_row.expiring_soon = 4
    summary_row.expired = 1

    summary_result = MagicMock()
    summary_result.fetchone.return_value = summary_row

    low_result = MagicMock()
    low_result.fetchall.return_value = []

    mock_db = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[summary_result, low_result])

    with patch("api.inventory_routes.get_db_with_tenant", return_value=mock_db):
        async with inventory_client as c:
            resp = await c.get(
                "/api/v1/inventory/dashboard?store_id=s1",
                headers={"X-Tenant-ID": "t1"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["summary"]["out_of_stock"] == 2
    assert body["data"]["summary"]["normal"] == 90
    assert body["data"]["low_items"] == []


@pytest.mark.asyncio
async def test_inventory_dashboard_with_low_items(inventory_client):
    """Low stock items are serialized correctly."""
    from datetime import date

    summary_row = MagicMock()
    summary_row.out_of_stock = 1
    summary_row.critical = 0
    summary_row.low_stock = 1
    summary_row.normal = 50
    summary_row.expiring_soon = 0
    summary_row.expired = 0

    summary_result = MagicMock()
    summary_result.fetchone.return_value = summary_row

    low_row = MagicMock()
    low_row.id = "ing-001"
    low_row.name = "猪肉"
    low_row.current_qty = 2.5
    low_row.unit = "kg"
    low_row.safety_stock_qty = 5.0
    low_row.status = "low"
    low_row.expiry_date = date(2026, 4, 10)
    low_row.preferred_supplier = "肉类供应商"
    low_row.last_price_fen = 2500

    low_result = MagicMock()
    low_result.fetchall.return_value = [low_row]

    mock_db = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[summary_result, low_result])

    with patch("api.inventory_routes.get_db_with_tenant", return_value=mock_db):
        async with inventory_client as c:
            resp = await c.get(
                "/api/v1/inventory/dashboard?store_id=s1",
                headers={"X-Tenant-ID": "t1"},
            )
    body = resp.json()
    assert len(body["data"]["low_items"]) == 1
    item = body["data"]["low_items"][0]
    assert item["name"] == "猪肉"
    assert item["current_qty"] == 2.5
    assert item["last_price_fen"] == 2500


@pytest.mark.asyncio
async def test_inventory_dashboard_db_error_graceful(inventory_client):
    """DB error returns ok=True with empty summary (graceful degradation)."""
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(side_effect=Exception("db connection failed"))

    with patch("api.inventory_routes.get_db_with_tenant", return_value=mock_db):
        async with inventory_client as c:
            resp = await c.get(
                "/api/v1/inventory/dashboard?store_id=s1",
                headers={"X-Tenant-ID": "t1"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["summary"] == {}
    assert body["data"]["low_items"] == []


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/inventory/restock-plan
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_restock_plan_happy_path(inventory_client):
    """Happy path: restock plan generated via MasterAgent dispatch."""
    alert_result = MagicMock()
    alert_result.success = True
    alert_result.data = [{"ingredient_id": "ing-001", "qty_needed": 10}]
    alert_result.reasoning = "库存不足"
    alert_result.confidence = 0.9
    alert_result.constraints_passed = True
    alert_result.execution_ms = 120

    severity_result = MagicMock()
    severity_result.success = True
    severity_result.data = {"level": "high"}

    mock_master = MagicMock()
    mock_master.dispatch = AsyncMock(side_effect=[alert_result, severity_result])
    mock_master.register = MagicMock()

    with (
        patch("api.inventory_routes.MasterAgent", return_value=mock_master),
        patch("api.inventory_routes.ALL_SKILL_AGENTS", []),
        patch("api.inventory_routes.ModelRouter", side_effect=ValueError("no key")),
    ):
        async with inventory_client as c:
            resp = await c.post(
                "/api/v1/inventory/restock-plan?store_id=s1",
                headers={"X-Tenant-ID": "t1"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["restock_alerts"]) == 1
    assert body["data"]["severity"]["level"] == "high"


@pytest.mark.asyncio
async def test_generate_restock_plan_agent_error(inventory_client):
    """Agent dispatch failure returns ok=False with error message."""
    mock_master = MagicMock()
    mock_master.dispatch = AsyncMock(side_effect=RuntimeError("agent crashed"))
    mock_master.register = MagicMock()

    with (
        patch("api.inventory_routes.MasterAgent", return_value=mock_master),
        patch("api.inventory_routes.ALL_SKILL_AGENTS", []),
        patch("api.inventory_routes.ModelRouter", side_effect=ValueError("no key")),
    ):
        async with inventory_client as c:
            resp = await c.post(
                "/api/v1/inventory/restock-plan?store_id=s1",
                headers={"X-Tenant-ID": "t1"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "agent crashed" in body["error"]["message"]


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/inventory/restock-plan
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_latest_restock_plan_found(inventory_client):
    """Returns plan data when DB row found."""
    fake_row = MagicMock()
    fake_row.id = "log-001"
    fake_row.output_action = {"items": []}
    fake_row.reasoning = "库存不足触发补货"
    fake_row.confidence = 0.88
    fake_row.created_at = datetime.now(timezone.utc)

    mock_result = MagicMock()
    mock_result.fetchone.return_value = fake_row
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("api.inventory_routes.get_db_with_tenant", return_value=mock_db):
        async with inventory_client as c:
            resp = await c.get(
                "/api/v1/inventory/restock-plan?store_id=s1",
                headers={"X-Tenant-ID": "t1"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["plan_id"] == "log-001"
    assert body["data"]["confidence"] == pytest.approx(0.88)


@pytest.mark.asyncio
async def test_get_latest_restock_plan_not_found(inventory_client):
    """Returns data=None when no plan in DB."""
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("api.inventory_routes.get_db_with_tenant", return_value=mock_db):
        async with inventory_client as c:
            resp = await c.get(
                "/api/v1/inventory/restock-plan?store_id=s1",
                headers={"X-Tenant-ID": "t1"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"] is None
