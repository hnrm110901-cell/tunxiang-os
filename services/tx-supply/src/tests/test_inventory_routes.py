"""inventory.py 路由层测试 — TestClient + FastAPI dependency_overrides

覆盖路由 (inventory.py — 23 端点，选取 15 个):
  GET  /api/v1/supply/inventory                         — list_inventory
  GET  /api/v1/supply/inventory/{item_id}               — get_inventory_item (missing store_id / not found)
  POST /api/v1/supply/inventory/{item_id}/adjust        — adjust_inventory
  GET  /api/v1/supply/inventory/alerts                  — get_inventory_alerts
  POST /api/v1/supply/inventory/receive                 — receive_stock
  POST /api/v1/supply/inventory/issue                   — issue_stock
  GET  /api/v1/supply/inventory/balance/{ingredient_id} — get_balance
  GET  /api/v1/supply/inventory/store/{store_id}        — get_store_inventory
  GET  /api/v1/supply/inventory/expiry/{store_id}       — get_expiry_report
  GET  /api/v1/supply/inventory/safety/{store_id}       — get_safety_stock
  GET  /api/v1/supply/inventory/forecast/{store_id}/{}  — get_stockout_forecast
  GET  /api/v1/supply/inventory/reorder/{store_id}      — get_reorder_suggestions
  GET  /api/v1/supply/suppliers                         — list_suppliers
  GET  /api/v1/supply/waste/top5                        — get_waste_top5
  GET  /api/v1/supply/demand/forecast                   — forecast_demand

测试数量: 25 个测试用例
"""

from __future__ import annotations

import sys
import types
import uuid

# ─── Stubs: src package hierarchy ─────────────────────────────────────────────
# inventory.py uses `from ..services import expiry_monitor, inventory_io, stock_forecast`
# We register src, src.api, src.services as package stubs so relative imports work
# when we later import via `src.api.inventory`.

_src_pkg = types.ModuleType("src")
_src_api_pkg = types.ModuleType("src.api")
_src_svc_pkg = types.ModuleType("src.services")

# Service stubs under src.services
_inv_io_mod = types.ModuleType("src.services.inventory_io")
_exp_mod = types.ModuleType("src.services.expiry_monitor")
_forecast_mod = types.ModuleType("src.services.stock_forecast")
_repo_mod = types.ModuleType("src.services.supply_repository")
_transfer_mod = types.ModuleType("src.services.transfer_service")

# Stubs on the modules (functions filled in by patch/AsyncMock in tests)
_inv_io_mod.get_store_inventory = None
_inv_io_mod.get_stock_balance = None
_inv_io_mod.adjust_stock = None
_inv_io_mod.receive_stock = None
_inv_io_mod.issue_stock = None
_exp_mod.generate_expiry_report = None
_forecast_mod.check_safety_stock = None
_forecast_mod.predict_stockout = None
_forecast_mod.suggest_reorder = None
_transfer_mod.get_brand_ingredient_overview = None
_transfer_mod.get_brand_low_stock_alert = None

# Expose as attributes on the services package
_src_svc_pkg.inventory_io = _inv_io_mod
_src_svc_pkg.expiry_monitor = _exp_mod
_src_svc_pkg.stock_forecast = _forecast_mod


# SupplyRepository stub
class _FakeSupplyRepository:
    def __init__(self, db, tenant_id):
        pass

    async def list_suppliers(self, page=1, size=20):
        return {}

    async def get_supplier_rating(self, supplier_id):
        return None

    async def compare_supplier_prices(self, ingredient_id):
        return []

    async def get_waste_top5(self, store_id, period="month"):
        return []

    async def get_waste_rate(self, store_id):
        return {}

    async def forecast_demand(self, store_id, days=7):
        return []


_repo_mod.SupplyRepository = _FakeSupplyRepository

# Wire package __init__ attributes
_src_api_pkg.__package__ = "src.api"
_src_pkg.__path__ = []
_src_api_pkg.__path__ = []
_src_svc_pkg.__path__ = []

sys.modules["src"] = _src_pkg
sys.modules["src.api"] = _src_api_pkg
sys.modules["src.services"] = _src_svc_pkg
sys.modules["src.services.inventory_io"] = _inv_io_mod
sys.modules["src.services.expiry_monitor"] = _exp_mod
sys.modules["src.services.stock_forecast"] = _forecast_mod
sys.modules["src.services.supply_repository"] = _repo_mod
sys.modules["src.services.transfer_service"] = _transfer_mod

# ─── Stubs: shared modules ─────────────────────────────────────────────────────
_shared = types.ModuleType("shared")
_shared_ont = types.ModuleType("shared.ontology")
_shared_ont_src = types.ModuleType("shared.ontology.src")
_shared_db_mod = types.ModuleType("shared.ontology.src.database")


async def _placeholder_get_db():
    yield None


_shared_db_mod.get_db = _placeholder_get_db
sys.modules.setdefault("shared", _shared)
sys.modules.setdefault("shared.ontology", _shared_ont)
sys.modules.setdefault("shared.ontology.src", _shared_ont_src)
sys.modules.setdefault("shared.ontology.src.database", _shared_db_mod)

_shared_events = types.ModuleType("shared.events")
_shared_events_src = types.ModuleType("shared.events.src")
_shared_emitter = types.ModuleType("shared.events.src.emitter")
_shared_event_types = types.ModuleType("shared.events.src.event_types")


async def _fake_emit_event(**kwargs):
    pass


_shared_emitter.emit_event = _fake_emit_event


class _FakeInventoryEventType:
    RECEIVED = "RECEIVED"
    CONSUMED = "CONSUMED"
    WASTED = "WASTED"
    ADJUSTED = "ADJUSTED"


_shared_event_types.InventoryEventType = _FakeInventoryEventType

sys.modules.setdefault("shared.events", _shared_events)
sys.modules.setdefault("shared.events.src", _shared_events_src)
sys.modules.setdefault("shared.events.src.emitter", _shared_emitter)
sys.modules.setdefault("shared.events.src.event_types", _shared_event_types)

_structlog = types.ModuleType("structlog")
_structlog.get_logger = lambda *a, **kw: types.SimpleNamespace(
    info=lambda *a, **kw: None,
    error=lambda *a, **kw: None,
    warning=lambda *a, **kw: None,
    debug=lambda *a, **kw: None,
)
sys.modules.setdefault("structlog", _structlog)

import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock, patch

# Patch the service attributes the router code resolves at call time
import api.inventory
from api.inventory import _get_db as inventory_get_db

# Import inventory module; because relative imports resolve via src.services stubs
# we import directly using the api package path
from api.inventory import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

api.inventory.inventory_io = _inv_io_mod
api.inventory.expiry_monitor = _exp_mod
api.inventory.stock_forecast = _forecast_mod
api.inventory.SupplyRepository = _FakeSupplyRepository

TENANT_ID = str(uuid.uuid4())
STORE_ID = "store_test_001"
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── App factory ───────────────────────────────────────────────────────────────


def _make_app(db_mock):
    app = FastAPI()
    app.include_router(router)

    async def _override():
        yield db_mock

    app.dependency_overrides[inventory_get_db] = _override
    return app


def _client(db_mock):
    return TestClient(_make_app(db_mock), raise_server_exceptions=False)


def _mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ─── List Inventory ─────────────────────────────────────────────────────────────


class TestListInventory:
    def test_list_inventory_success(self):
        db = _mock_db()
        expected = [{"ingredient_id": "ing_001", "quantity": 500.0}]
        with patch.object(api.inventory.inventory_io, "get_store_inventory", new=AsyncMock(return_value=expected)):
            resp = _client(db).get(
                "/api/v1/supply/inventory",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["data"] == expected

    def test_list_inventory_missing_header(self):
        db = _mock_db()
        resp = _client(db).get(
            "/api/v1/supply/inventory",
            params={"store_id": STORE_ID},
        )
        assert resp.status_code == 422


# ─── Get Inventory Item ─────────────────────────────────────────────────────────


class TestGetInventoryItem:
    def test_get_item_success(self):
        db = _mock_db()
        result = {"ingredient_id": "ing_bass", "quantity": 200.0}
        with patch.object(api.inventory.inventory_io, "get_stock_balance", new=AsyncMock(return_value=result)):
            resp = _client(db).get(
                "/api/v1/supply/inventory/ing_bass",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["ingredient_id"] == "ing_bass"

    def test_get_item_missing_store_id(self):
        db = _mock_db()
        resp = _client(db).get(
            "/api/v1/supply/inventory/ing_bass",
            headers=HEADERS,
        )
        # store_id defaults to "" — route raises HTTP 400
        assert resp.status_code == 400

    def test_get_item_not_found(self):
        db = _mock_db()
        with patch.object(
            api.inventory.inventory_io, "get_stock_balance", new=AsyncMock(side_effect=ValueError("not found"))
        ):
            resp = _client(db).get(
                "/api/v1/supply/inventory/nonexistent",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )
        assert resp.status_code == 404


# ─── Receive Stock ──────────────────────────────────────────────────────────────


class TestReceiveStock:
    def test_receive_success(self):
        db = _mock_db()
        result = {"batch_id": "batch_001", "quantity": 50.0}
        with (
            patch.object(api.inventory.inventory_io, "receive_stock", new=AsyncMock(return_value=result)),
            patch("api.inventory.asyncio.create_task", return_value=None),
        ):
            resp = _client(db).post(
                "/api/v1/supply/inventory/receive",
                json={
                    "ingredient_id": "ing_bass",
                    "quantity": 50.0,
                    "unit_cost_fen": 3500,
                    "batch_no": "B20260406",
                    "store_id": STORE_ID,
                },
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_receive_value_error(self):
        db = _mock_db()
        with (
            patch.object(
                api.inventory.inventory_io, "receive_stock", new=AsyncMock(side_effect=ValueError("duplicate batch"))
            ),
            patch("api.inventory.asyncio.create_task", return_value=None),
        ):
            resp = _client(db).post(
                "/api/v1/supply/inventory/receive",
                json={
                    "ingredient_id": "ing_bass",
                    "quantity": 10.0,
                    "unit_cost_fen": 3500,
                    "batch_no": "B_DUP",
                    "store_id": STORE_ID,
                },
                headers=HEADERS,
            )
        assert resp.status_code == 400

    def test_receive_invalid_quantity(self):
        db = _mock_db()
        resp = _client(db).post(
            "/api/v1/supply/inventory/receive",
            json={
                "ingredient_id": "ing_bass",
                "quantity": 0,  # gt=0 constraint
                "unit_cost_fen": 3500,
                "batch_no": "B001",
                "store_id": STORE_ID,
            },
            headers=HEADERS,
        )
        assert resp.status_code == 422


# ─── Issue Stock ────────────────────────────────────────────────────────────────


class TestIssueStock:
    def test_issue_success(self):
        db = _mock_db()
        result = {"issued": True, "quantity": 10.0}
        with (
            patch.object(api.inventory.inventory_io, "issue_stock", new=AsyncMock(return_value=result)),
            patch("api.inventory.asyncio.create_task", return_value=None),
        ):
            resp = _client(db).post(
                "/api/v1/supply/inventory/issue",
                json={
                    "ingredient_id": "ing_bass",
                    "quantity": 10.0,
                    "reason": "usage",
                    "store_id": STORE_ID,
                },
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_issue_insufficient_stock(self):
        db = _mock_db()
        with (
            patch.object(
                api.inventory.inventory_io, "issue_stock", new=AsyncMock(side_effect=ValueError("insufficient stock"))
            ),
            patch("api.inventory.asyncio.create_task", return_value=None),
        ):
            resp = _client(db).post(
                "/api/v1/supply/inventory/issue",
                json={
                    "ingredient_id": "ing_bass",
                    "quantity": 99999.0,
                    "reason": "usage",
                    "store_id": STORE_ID,
                },
                headers=HEADERS,
            )
        assert resp.status_code == 400


# ─── Adjust Inventory ───────────────────────────────────────────────────────────


class TestAdjustInventory:
    def test_adjust_success(self):
        db = _mock_db()
        result = {"adjusted": True}
        with (
            patch.object(api.inventory.inventory_io, "adjust_stock", new=AsyncMock(return_value=result)),
            patch("api.inventory.asyncio.create_task", return_value=None),
        ):
            resp = _client(db).post(
                "/api/v1/supply/inventory/ing_bass/adjust",
                json={
                    "ingredient_id": "ing_bass",
                    "quantity": -5.0,
                    "reason": "盘点盘亏",
                    "store_id": STORE_ID,
                },
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_adjust_error(self):
        db = _mock_db()
        with (
            patch.object(
                api.inventory.inventory_io, "adjust_stock", new=AsyncMock(side_effect=ValueError("item not found"))
            ),
            patch("api.inventory.asyncio.create_task", return_value=None),
        ):
            resp = _client(db).post(
                "/api/v1/supply/inventory/fake_item/adjust",
                json={
                    "ingredient_id": "fake_item",
                    "quantity": -1.0,
                    "reason": "error",
                    "store_id": STORE_ID,
                },
                headers=HEADERS,
            )
        assert resp.status_code == 400


# ─── Alerts ─────────────────────────────────────────────────────────────────────


class TestInventoryAlerts:
    def test_alerts_filters_low_stock(self):
        db = _mock_db()
        safety_result = [
            {"ingredient_id": "ing_001", "status": "low"},
            {"ingredient_id": "ing_002", "status": "ok"},
        ]
        expiry_result = [{"ingredient_id": "ing_001", "days_left": 2}]
        with (
            patch.object(api.inventory.stock_forecast, "check_safety_stock", new=AsyncMock(return_value=safety_result)),
            patch.object(
                api.inventory.expiry_monitor, "generate_expiry_report", new=AsyncMock(return_value=expiry_result)
            ),
        ):
            resp = _client(db).get(
                "/api/v1/supply/inventory/alerts",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "alerts" in data
        # Only 1 item with status != "ok" should be in low_stock
        assert len(data["alerts"]["low_stock"]) == 1
        assert len(data["alerts"]["expiry"]) == 1


# ─── Balance / Store ────────────────────────────────────────────────────────────


class TestGetBalance:
    def test_get_balance_success(self):
        db = _mock_db()
        result = {"total_qty": 300.0, "batches": []}
        with patch.object(api.inventory.inventory_io, "get_stock_balance", new=AsyncMock(return_value=result)):
            resp = _client(db).get(
                "/api/v1/supply/inventory/balance/ing_bass",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["total_qty"] == 300.0

    def test_get_balance_missing_store_id(self):
        db = _mock_db()
        resp = _client(db).get(
            "/api/v1/supply/inventory/balance/ing_bass",
            headers=HEADERS,
        )
        assert resp.status_code == 400

    def test_get_store_inventory_success(self):
        db = _mock_db()
        result = [{"ingredient_id": "ing_001", "qty": 100}]
        with patch.object(api.inventory.inventory_io, "get_store_inventory", new=AsyncMock(return_value=result)):
            resp = _client(db).get(
                f"/api/v1/supply/inventory/store/{STORE_ID}",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ─── Expiry / Safety / Forecast / Reorder ───────────────────────────────────────


class TestExpiryAndForecast:
    def test_get_expiry_report(self):
        db = _mock_db()
        result = [{"ingredient_id": "ing_001", "days_left": 1}]
        with patch.object(api.inventory.expiry_monitor, "generate_expiry_report", new=AsyncMock(return_value=result)):
            resp = _client(db).get(
                f"/api/v1/supply/inventory/expiry/{STORE_ID}",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_get_safety_stock(self):
        db = _mock_db()
        result = [{"ingredient_id": "ing_001", "status": "low"}]
        with patch.object(api.inventory.stock_forecast, "check_safety_stock", new=AsyncMock(return_value=result)):
            resp = _client(db).get(
                f"/api/v1/supply/inventory/safety/{STORE_ID}",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == result

    def test_get_stockout_forecast_success(self):
        db = _mock_db()
        result = {"days_remaining": 5}
        with patch.object(api.inventory.stock_forecast, "predict_stockout", new=AsyncMock(return_value=result)):
            resp = _client(db).get(
                f"/api/v1/supply/inventory/forecast/{STORE_ID}/ing_bass",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["days_remaining"] == 5

    def test_get_stockout_forecast_not_found(self):
        db = _mock_db()
        with patch.object(
            api.inventory.stock_forecast, "predict_stockout", new=AsyncMock(side_effect=ValueError("no data"))
        ):
            resp = _client(db).get(
                f"/api/v1/supply/inventory/forecast/{STORE_ID}/nonexistent",
                headers=HEADERS,
            )
        assert resp.status_code == 404

    def test_get_reorder_suggestions(self):
        db = _mock_db()
        result = [{"ingredient_id": "ing_001", "suggested_qty": 50}]
        with patch.object(api.inventory.stock_forecast, "suggest_reorder", new=AsyncMock(return_value=result)):
            resp = _client(db).get(
                f"/api/v1/supply/inventory/reorder/{STORE_ID}",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["suggestions"] == result


# ─── Suppliers / Waste / Demand ─────────────────────────────────────────────────


class TestSuppliersAndWaste:
    def _make_repo(self, method: str, value):
        repo = MagicMock()
        setattr(repo, method, AsyncMock(return_value=value))
        return repo

    def test_list_suppliers_success(self):
        db = _mock_db()
        data = {"items": [{"supplier_id": "sup_001"}], "total": 1}
        with patch.object(api.inventory, "SupplyRepository", return_value=self._make_repo("list_suppliers", data)):
            resp = _client(db).get(
                "/api/v1/supply/suppliers",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_get_waste_top5(self):
        db = _mock_db()
        top5 = [{"ingredient": "鲈鱼", "waste_fen": 15000}]
        with patch.object(api.inventory, "SupplyRepository", return_value=self._make_repo("get_waste_top5", top5)):
            resp = _client(db).get(
                "/api/v1/supply/waste/top5",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["top5"] == top5

    def test_forecast_demand(self):
        db = _mock_db()
        forecast = [{"ingredient_id": "ing_001", "predicted_qty": 300}]
        with patch.object(api.inventory, "SupplyRepository", return_value=self._make_repo("forecast_demand", forecast)):
            resp = _client(db).get(
                "/api/v1/supply/demand/forecast",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["forecast"] == forecast
