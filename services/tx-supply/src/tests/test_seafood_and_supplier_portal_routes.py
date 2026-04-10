"""seafood_routes.py + supplier_portal_routes.py 路由层测试 — TestClient

覆盖路由：
  seafood_routes.py (12 端点):
    POST /api/v1/supply/seafood/track-status     — api_track_live_status
    POST /api/v1/supply/seafood/loss             — api_calculate_live_loss
    GET  /api/v1/supply/seafood/tanks/{store_id} — api_get_tank_inventory
    POST /api/v1/supply/seafood/price            — api_price_by_weight
    GET  /api/v1/supply/seafood/dashboard/{id}   — api_get_seafood_dashboard
    GET  /api/v1/supply/seafood/tanks            — api_list_tanks
    GET  /api/v1/supply/seafood/stock            — api_list_seafood_stock
    POST /api/v1/supply/seafood/stock/intake     — api_intake_stock
    POST /api/v1/supply/seafood/stock/mortality  — api_record_mortality
    GET  /api/v1/supply/seafood/mortality-rate   — api_get_mortality_rate
    POST /api/v1/supply/seafood/tank-reading     — api_record_tank_reading
    GET  /api/v1/supply/seafood/alerts           — api_get_alerts

  supplier_portal_routes.py (10 端点):
    POST /api/v1/suppliers                       — register_supplier
    GET  /api/v1/suppliers                       — list_suppliers
    GET  /api/v1/suppliers/risk-assessment       — get_risk_assessment
    GET  /api/v1/suppliers/{supplier_id}         — get_supplier
    PUT  /api/v1/suppliers/{supplier_id}         — update_supplier
    POST /api/v1/suppliers/{id}/delivery         — record_delivery
    POST /api/v1/suppliers/rfq                   — request_quotes
    POST /api/v1/suppliers/rfq/{id}/quotes       — submit_quote
    GET  /api/v1/suppliers/rfq/{id}/compare      — compare_quotes
    POST /api/v1/suppliers/rfq/{id}/accept       — accept_quote

测试数量: 27 个测试用例
"""
from __future__ import annotations

import sys
import types
import uuid

# ─── Stubs: shared modules ──────────────────────────────────────────────────────
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

_structlog = types.ModuleType("structlog")
_structlog.get_logger = lambda *a, **kw: types.SimpleNamespace(
    info=lambda *a, **kw: None,
    error=lambda *a, **kw: None,
    warning=lambda *a, **kw: None,
    debug=lambda *a, **kw: None,
)
sys.modules.setdefault("structlog", _structlog)

# ─── Stubs for seafood_routes absolute service imports ────────────────────────
# seafood_routes.py imports:
#   from services.tx_supply.src.services import live_seafood_v2
#   from services.tx_supply.src.services import seafood_management_service as svc

_live_seafood_v2_mod = types.ModuleType("services.tx_supply.src.services.live_seafood_v2")
_seafood_mgmt_mod = types.ModuleType("services.tx_supply.src.services.seafood_management_service")

for _pkg in [
    "services",
    "services.tx_supply",
    "services.tx_supply.src",
    "services.tx_supply.src.services",
]:
    sys.modules.setdefault(_pkg, types.ModuleType(_pkg))

sys.modules["services.tx_supply.src.services.live_seafood_v2"] = _live_seafood_v2_mod
sys.modules["services.tx_supply.src.services.seafood_management_service"] = _seafood_mgmt_mod

# ─── Stubs for supplier_portal_routes relative import ────────────────────────
# supplier_portal_routes.py: from ..services import supplier_portal_service as svc
# Loaded as `api.supplier_portal_routes`, parent package = `api` (no src wrapper).
# We stub src.services.supplier_portal_service to be safe, and also
# stub api package so __package__ = "api" resolves correctly.

_sp_svc_mod = types.ModuleType("src.services.supplier_portal_service")

# Ensure src package hierarchy exists (may already be registered)
for _pkg in ["src", "src.api", "src.services"]:
    if _pkg not in sys.modules:
        _m = types.ModuleType(_pkg)
        _m.__path__ = []
        sys.modules[_pkg] = _m

sys.modules["src.services.supplier_portal_service"] = _sp_svc_mod

import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import ProgrammingError

TENANT_ID = str(uuid.uuid4())
STORE_ID = "store_furong_001"
HEADERS = {"X-Tenant-ID": TENANT_ID}


def _mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ═══════════════════════════════════════════════════════════════════════════════
# PART A — seafood_routes.py
# ═══════════════════════════════════════════════════════════════════════════════

import api.seafood_routes as _seafood_module
from api.seafood_routes import router as seafood_router, _get_db as seafood_get_db


def _seafood_client(db_mock):
    app = FastAPI()
    app.include_router(seafood_router)

    async def _override():
        yield db_mock

    app.dependency_overrides[seafood_get_db] = _override
    return TestClient(app, raise_server_exceptions=False)


class TestSeafoodTrackStatus:
    def test_track_status_success(self):
        db = _mock_db()
        result = {"record_id": "rec_001", "status": "alive"}
        with patch.object(
            _seafood_module.live_seafood_v2,
            "track_live_status",
            new=AsyncMock(return_value=result),
        ):
            resp = _seafood_client(db).post(
                "/api/v1/supply/seafood/track-status",
                json={
                    "ingredient_id": "ing_bass",
                    "store_id": STORE_ID,
                    "status": "alive",
                    "weight_g": 500.0,
                },
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["data"]["status"] == "alive"

    def test_track_status_value_error(self):
        db = _mock_db()
        with patch.object(
            _seafood_module.live_seafood_v2,
            "track_live_status",
            new=AsyncMock(side_effect=ValueError("invalid status transition")),
        ):
            resp = _seafood_client(db).post(
                "/api/v1/supply/seafood/track-status",
                json={
                    "ingredient_id": "ing_bass",
                    "store_id": STORE_ID,
                    "status": "dead",
                    "weight_g": 200.0,
                },
                headers=HEADERS,
            )
        assert resp.status_code == 400

    def test_track_status_missing_header(self):
        db = _mock_db()
        resp = _seafood_client(db).post(
            "/api/v1/supply/seafood/track-status",
            json={
                "ingredient_id": "ing_bass",
                "store_id": STORE_ID,
                "status": "weak",
                "weight_g": 300.0,
            },
        )
        assert resp.status_code == 422


class TestSeafoodLoss:
    def test_calculate_loss_success(self):
        db = _mock_db()
        result = {"total_loss_kg": 2.5, "loss_rate": 0.05}
        with patch.object(
            _seafood_module.live_seafood_v2,
            "calculate_live_loss",
            new=AsyncMock(return_value=result),
        ):
            resp = _seafood_client(db).post(
                "/api/v1/supply/seafood/loss",
                json={
                    "store_id": STORE_ID,
                    "start_date": "2026-04-01",
                    "end_date": "2026-04-06",
                },
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["total_loss_kg"] == 2.5


class TestSeafoodTanks:
    def test_get_tank_inventory(self):
        db = _mock_db()
        result = [{"tank_id": "tank_001", "species": "鲈鱼", "qty_kg": 50.0}]
        with patch.object(
            _seafood_module.live_seafood_v2,
            "get_tank_inventory",
            new=AsyncMock(return_value=result),
        ):
            resp = _seafood_client(db).get(
                f"/api/v1/supply/seafood/tanks/{STORE_ID}",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1

    def test_list_tanks_query(self):
        db = _mock_db()
        result = {"tanks": [{"tank_id": "tank_001", "temperature": 18.5}]}
        with patch.object(
            _seafood_module.svc,
            "list_tanks",
            new=AsyncMock(return_value=result),
        ):
            resp = _seafood_client(db).get(
                "/api/v1/supply/seafood/tanks",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestSeafoodPrice:
    def test_price_by_weight_success(self):
        db = _mock_db()
        result = {"price_fen": 8750, "unit_price_fen_per_kg": 17500}
        with patch.object(
            _seafood_module.live_seafood_v2,
            "price_by_weight",
            new=AsyncMock(return_value=result),
        ):
            resp = _seafood_client(db).post(
                "/api/v1/supply/seafood/price",
                json={"ingredient_id": "ing_bass", "weight_g": 500.0},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["price_fen"] == 8750

    def test_price_by_weight_not_found(self):
        db = _mock_db()
        with patch.object(
            _seafood_module.live_seafood_v2,
            "price_by_weight",
            new=AsyncMock(side_effect=ValueError("ingredient not found")),
        ):
            resp = _seafood_client(db).post(
                "/api/v1/supply/seafood/price",
                json={"ingredient_id": "nonexistent", "weight_g": 100.0},
                headers=HEADERS,
            )
        assert resp.status_code == 400


class TestSeafoodStock:
    def test_list_stock(self):
        db = _mock_db()
        result = [{"ingredient_id": "ing_bass", "qty_kg": 20.0}]
        with patch.object(
            _seafood_module.svc,
            "list_stock",
            new=AsyncMock(return_value=result),
        ):
            resp = _seafood_client(db).get(
                "/api/v1/supply/seafood/stock",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_intake_stock_success(self):
        db = _mock_db()
        result = {"stock_id": "stk_001", "qty_kg": 30.0}
        with patch.object(
            _seafood_module.svc,
            "intake_stock",
            new=AsyncMock(return_value=result),
        ):
            resp = _seafood_client(db).post(
                "/api/v1/supply/seafood/stock/intake",
                params={"store_id": STORE_ID},
                json={
                    "ingredient_id": "ing_bass",
                    "species": "鲈鱼",
                    "origin": "湖南湘潭",
                    "quantity_kg": 30.0,
                    "unit_price_fen": 3500,
                    "supplier_name": "湘江渔港",
                    "origin_certificate_no": "ORIG-2026-001",
                    "quarantine_certificate_no": "QUA-2026-001",
                    "operator_id": "emp_001",
                },
                headers=HEADERS,
            )
        assert resp.status_code == 201
        assert resp.json()["data"]["stock_id"] == "stk_001"

    def test_intake_stock_food_safety_violation(self):
        db = _mock_db()
        with patch.object(
            _seafood_module.svc,
            "intake_stock",
            new=AsyncMock(side_effect=ValueError("产地证明缺失，拒绝入库")),
        ):
            resp = _seafood_client(db).post(
                "/api/v1/supply/seafood/stock/intake",
                params={"store_id": STORE_ID},
                json={
                    "ingredient_id": "ing_bass",
                    "species": "鲈鱼",
                    "origin": "未知",
                    "quantity_kg": 5.0,
                    "unit_price_fen": 3500,
                    "supplier_name": "无证供应商",
                    "origin_certificate_no": "CERT-001",
                    "quarantine_certificate_no": "QUA-001",
                    "operator_id": "emp_001",
                },
                headers=HEADERS,
            )
        # ValueError in intake → 422 (food safety)
        assert resp.status_code == 422

    def test_record_mortality_success(self):
        db = _mock_db()
        result = {"mortality_id": "mort_001", "quantity_kg": 1.5}
        with patch.object(
            _seafood_module.svc,
            "record_mortality",
            new=AsyncMock(return_value=result),
        ):
            resp = _seafood_client(db).post(
                "/api/v1/supply/seafood/stock/mortality",
                params={"store_id": STORE_ID},
                json={
                    "ingredient_id": "ing_bass",
                    "species": "鲈鱼",
                    "quantity_kg": 1.5,
                    "reason": "水质异常",
                    "operator_id": "emp_001",
                },
                headers=HEADERS,
            )
        assert resp.status_code == 201
        assert resp.json()["data"]["mortality_id"] == "mort_001"


class TestSeafoodAlertsAndMonitoring:
    def test_get_mortality_rate(self):
        db = _mock_db()
        result = {"avg_rate": 0.02, "species": []}
        with patch.object(
            _seafood_module.svc,
            "get_mortality_rate",
            new=AsyncMock(return_value=result),
        ):
            resp = _seafood_client(db).get(
                "/api/v1/supply/seafood/mortality-rate",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_record_tank_reading(self):
        db = _mock_db()
        result = {"reading_id": "rd_001", "alerts": []}
        with patch.object(
            _seafood_module.svc,
            "record_tank_reading",
            new=AsyncMock(return_value=result),
        ):
            resp = _seafood_client(db).post(
                "/api/v1/supply/seafood/tank-reading",
                params={"store_id": STORE_ID},
                json={
                    "tank_id": "tank_001",
                    "temperature": 18.5,
                    "ph": 7.2,
                    "operator_id": "emp_001",
                },
                headers=HEADERS,
            )
        assert resp.status_code == 201

    def test_get_alerts(self):
        db = _mock_db()
        result = {"mortality_alerts": [], "water_alerts": [], "stock_alerts": []}
        with patch.object(
            _seafood_module.svc,
            "get_alerts",
            new=AsyncMock(return_value=result),
        ):
            resp = _seafood_client(db).get(
                "/api/v1/supply/seafood/alerts",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_get_seafood_dashboard(self):
        db = _mock_db()
        result = {"total_value_fen": 500000, "species_count": 3}
        with patch.object(
            _seafood_module.live_seafood_v2,
            "get_seafood_dashboard",
            new=AsyncMock(return_value=result),
        ):
            resp = _seafood_client(db).get(
                f"/api/v1/supply/seafood/dashboard/{STORE_ID}",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# PART B — supplier_portal_routes.py
# ═══════════════════════════════════════════════════════════════════════════════

import api.supplier_portal_routes as _portal_module
from api.supplier_portal_routes import router as portal_router, _get_db as portal_get_db

SUPPLIER_ID = str(uuid.uuid4())
RFQ_ID = "rfq_" + str(uuid.uuid4())[:8]


def _portal_client(db_mock):
    app = FastAPI()
    app.include_router(portal_router)

    async def _override():
        yield db_mock

    app.dependency_overrides[portal_get_db] = _override
    return TestClient(app, raise_server_exceptions=False)


class TestRegisterSupplier:
    def test_register_success(self):
        db = _mock_db()
        new_supplier = {
            "supplier_id": SUPPLIER_ID,
            "name": "湘江渔港",
            "category": "seafood",
            "status": "active",
        }
        with patch.object(
            _portal_module.svc,
            "register_supplier",
            new=AsyncMock(return_value=new_supplier),
        ):
            resp = _portal_client(db).post(
                "/api/v1/suppliers",
                json={"name": "湘江渔港", "category": "seafood"},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["data"]["name"] == "湘江渔港"

    def test_register_value_error(self):
        db = _mock_db()
        with patch.object(
            _portal_module.svc,
            "register_supplier",
            new=AsyncMock(side_effect=ValueError("无效供应商类别: invalid_cat")),
        ):
            resp = _portal_client(db).post(
                "/api/v1/suppliers",
                json={"name": "测试", "category": "invalid_cat"},
                headers=HEADERS,
            )
        assert resp.status_code == 400

    def test_register_table_not_ready(self):
        db = _mock_db()
        with patch.object(
            _portal_module.svc,
            "register_supplier",
            new=AsyncMock(
                side_effect=ProgrammingError("relation does not exist", None, None)
            ),
        ):
            resp = _portal_client(db).post(
                "/api/v1/suppliers",
                json={"name": "测试", "category": "seafood"},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is False
        assert resp.json()["error"]["code"] == "TABLE_NOT_READY"


class TestListAndGetSuppliers:
    def test_list_suppliers_success(self):
        db = _mock_db()
        items = [{"supplier_id": SUPPLIER_ID, "name": "湘江渔港", "category": "seafood"}]
        with patch.object(
            _portal_module.svc,
            "list_suppliers",
            new=AsyncMock(return_value=items),
        ):
            resp = _portal_client(db).get("/api/v1/suppliers", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 1

    def test_list_suppliers_empty(self):
        db = _mock_db()
        with patch.object(
            _portal_module.svc,
            "list_suppliers",
            new=AsyncMock(return_value=[]),
        ):
            resp = _portal_client(db).get("/api/v1/suppliers", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 0

    def test_get_supplier_success(self):
        db = _mock_db()
        profile = {
            "supplier_id": SUPPLIER_ID,
            "name": "湘江渔港",
            "total_deliveries": 20,
            "on_time_rate": 0.95,
        }
        with patch.object(
            _portal_module.svc,
            "get_supplier_profile",
            new=AsyncMock(return_value=profile),
        ):
            resp = _portal_client(db).get(
                f"/api/v1/suppliers/{SUPPLIER_ID}",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["supplier_id"] == SUPPLIER_ID

    def test_get_supplier_not_found(self):
        db = _mock_db()
        with patch.object(
            _portal_module.svc,
            "get_supplier_profile",
            new=AsyncMock(side_effect=ValueError("not found")),
        ):
            resp = _portal_client(db).get(
                "/api/v1/suppliers/nonexistent",
                headers=HEADERS,
            )
        assert resp.status_code == 404

    def test_get_risk_assessment(self):
        db = _mock_db()
        risk_data = {"risk_level": "medium", "risks": [], "risk_count": 0}
        with patch.object(
            _portal_module.svc,
            "assess_risk",
            new=AsyncMock(return_value=risk_data),
        ):
            resp = _portal_client(db).get(
                "/api/v1/suppliers/risk-assessment",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestUpdateAndDelivery:
    def test_update_supplier_status(self):
        db = _mock_db()
        updated = {"supplier_id": SUPPLIER_ID, "status": "inactive"}
        with patch.object(
            _portal_module.svc,
            "update_supplier",
            new=AsyncMock(return_value=updated),
        ):
            resp = _portal_client(db).put(
                f"/api/v1/suppliers/{SUPPLIER_ID}",
                json={"status": "inactive"},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "inactive"

    def test_record_delivery_on_time_pass(self):
        db = _mock_db()
        result = {"delivery_id": "dl_001", "new_score": 92.5}
        with patch.object(
            _portal_module.svc,
            "record_delivery",
            new=AsyncMock(return_value=result),
        ):
            resp = _portal_client(db).post(
                f"/api/v1/suppliers/{SUPPLIER_ID}/delivery",
                json={"on_time": True, "quality_result": "pass"},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestRFQWorkflow:
    def test_request_quotes_success(self):
        db = _mock_db()
        rfq_data = {"rfq_id": RFQ_ID, "item_name": "鲈鱼", "status": "open"}
        with patch.object(
            _portal_module.svc,
            "request_quotes",
            new=AsyncMock(return_value=rfq_data),
        ):
            resp = _portal_client(db).post(
                "/api/v1/suppliers/rfq",
                json={"item_name": "鲈鱼", "quantity": 100.0},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["rfq_id"] == RFQ_ID

    def test_submit_quote_success(self):
        db = _mock_db()
        with patch.object(
            _portal_module.svc,
            "submit_quote",
            new=AsyncMock(return_value=None),
        ):
            resp = _portal_client(db).post(
                f"/api/v1/suppliers/rfq/{RFQ_ID}/quotes",
                json={
                    "supplier_id": SUPPLIER_ID,
                    "unit_price_fen": 3500,
                    "delivery_days": 2,
                },
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["rfq_id"] == RFQ_ID

    def test_compare_quotes_success(self):
        db = _mock_db()
        comparison = {
            "item_name": "鲈鱼",
            "quotes": [
                {
                    "supplier_id": SUPPLIER_ID,
                    "unit_price_fen": 3500,
                    "price_score": 80,
                    "delivery_score": 90,
                    "reliability_score": 85,
                    "composite_score": 85,
                }
            ],
            "recommended": {"supplier_id": SUPPLIER_ID},
        }
        with patch.object(
            _portal_module.svc,
            "compare_quotes",
            new=AsyncMock(return_value=comparison),
        ):
            resp = _portal_client(db).get(
                f"/api/v1/suppliers/rfq/{RFQ_ID}/compare",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["recommended"]["supplier_id"] == SUPPLIER_ID

    def test_accept_quote_success(self):
        db = _mock_db()
        acceptance = {
            "status": "accepted",
            "supplier_id": SUPPLIER_ID,
            "unit_price_fen": 3500,
            "total_price_fen": 350000,
        }
        with patch.object(
            _portal_module.svc,
            "accept_quote",
            new=AsyncMock(return_value=acceptance),
        ):
            resp = _portal_client(db).post(
                f"/api/v1/suppliers/rfq/{RFQ_ID}/accept",
                json={"supplier_id": SUPPLIER_ID},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "accepted"

    def test_accept_quote_rfq_not_found(self):
        db = _mock_db()
        with patch.object(
            _portal_module.svc,
            "accept_quote",
            new=AsyncMock(side_effect=ValueError("rfq not found")),
        ):
            resp = _portal_client(db).post(
                "/api/v1/suppliers/rfq/nonexistent_rfq/accept",
                json={"supplier_id": SUPPLIER_ID},
                headers=HEADERS,
            )
        assert resp.status_code == 400
