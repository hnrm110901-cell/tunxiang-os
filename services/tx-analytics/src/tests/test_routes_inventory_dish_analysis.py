"""路由层测试 — inventory_analysis_routes.py + dish_analysis_routes.py

覆盖端点（共 15 个）：
  inventory_analysis_routes.py (8 个):
    POST /api/v1/analytics/inventory/stores/{store_id}/turnover
    POST /api/v1/analytics/inventory/price-fluctuation
    POST /api/v1/analytics/inventory/stores/{store_id}/waste-ranking
    POST /api/v1/analytics/inventory/stores/{store_id}/stocktake-variance
    POST /api/v1/analytics/inventory/stores/{store_id}/procurement-variance
    POST /api/v1/analytics/inventory/stores/{store_id}/dish-cost-variance
    POST /api/v1/analytics/inventory/stores/{store_id}/seafood-waste
    GET  /api/v1/analytics/inventory/stores/{store_id}/food-safety-risk

  dish_analysis_routes.py (7 个):
    GET /api/v1/analysis/dish/sales-ranking
    GET /api/v1/analysis/dish/return-rate
    GET /api/v1/analysis/dish/negative-reviews
    GET /api/v1/analysis/dish/stockout-frequency
    GET /api/v1/analysis/dish/structure
    GET /api/v1/analysis/dish/new-performance
    GET /api/v1/analysis/dish/optimization
"""
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── 预置假模块 ──────────────────────────────────────────────────────────────

sys.modules.setdefault("src", types.ModuleType("src"))
_fake_src_db = types.ModuleType("src.db")


async def _fake_get_db():
    yield None


_fake_src_db.get_db = _fake_get_db
sys.modules.setdefault("src.db", _fake_src_db)

if "structlog" not in sys.modules:
    _fake_structlog = types.ModuleType("structlog")
    _fake_structlog.get_logger = lambda *a, **kw: MagicMock()
    sys.modules["structlog"] = _fake_structlog

for _mod_name in [
    "shared",
    "shared.ontology",
    "shared.ontology.src",
    "shared.ontology.src.database",
]:
    sys.modules.setdefault(_mod_name, types.ModuleType(_mod_name))

# ─── inventory_analysis service stub ────────────────────────────────────────

sys.modules.setdefault("src.services", types.ModuleType("src.services"))
_fake_inv_svc = types.ModuleType("src.services.inventory_analysis")

_TURNOVER_RESULT = {"turnover_days": 3.5, "avg_stock_cost_fen": 50000}
_PRICE_RESULT = {"items": [{"ingredient": "猪肉", "change_pct": 5.2}]}
_WASTE_RESULT = {"items": [{"ingredient": "青菜", "waste_fen": 300}]}
_STOCKTAKE_RESULT = {"variance_items": []}
_PROCUREMENT_RESULT = {"variance_pct": 2.1}
_DISH_COST_RESULT = {"dishes": []}
_SEAFOOD_RESULT = {"alive_pct": 92.0, "dead_pct": 8.0}
_FOOD_SAFETY_RESULT = {"risk_items": [], "risk_level": "low"}

_fake_inv_svc.inventory_turnover = AsyncMock(return_value=_TURNOVER_RESULT)
_fake_inv_svc.price_fluctuation_monitor = AsyncMock(return_value=_PRICE_RESULT)
_fake_inv_svc.waste_ranking = AsyncMock(return_value=_WASTE_RESULT)
_fake_inv_svc.stocktake_variance_analysis = AsyncMock(return_value=_STOCKTAKE_RESULT)
_fake_inv_svc.procurement_variance = AsyncMock(return_value=_PROCUREMENT_RESULT)
_fake_inv_svc.dish_cost_variance_deep = AsyncMock(return_value=_DISH_COST_RESULT)
_fake_inv_svc.seafood_waste_analysis = AsyncMock(return_value=_SEAFOOD_RESULT)
_fake_inv_svc.food_safety_risk_graph = AsyncMock(return_value=_FOOD_SAFETY_RESULT)

sys.modules["src.services.inventory_analysis"] = _fake_inv_svc

# ─── dish_analysis service stub ─────────────────────────────────────────────

_fake_dish_svc = types.ModuleType("src.services.dish_analysis")

_fake_dish_svc.sales_ranking = MagicMock(
    return_value=[{"dish_id": "d1", "dish_name": "红烧肉", "sales_qty": 100}]
)
_fake_dish_svc.return_rate_analysis = MagicMock(
    return_value={"items": [], "reasons": {}}
)
_fake_dish_svc.negative_review_dishes = MagicMock(return_value=[])
_fake_dish_svc.stockout_frequency = MagicMock(return_value=[])
_fake_dish_svc.dish_structure_analysis = MagicMock(
    return_value={"star": [], "cash_cow": [], "question": [], "dog": []}
)
_fake_dish_svc.new_dish_performance = MagicMock(return_value=[])
_fake_dish_svc.menu_optimization_suggestions = MagicMock(
    return_value={"suggestions": []}
)

sys.modules["src.services.dish_analysis"] = _fake_dish_svc

# dish_margin dep
_fake_dish_margin = types.ModuleType("src.services.dish_margin")
_fake_dish_margin.get_dish_margin_ranking = MagicMock(return_value=[])
sys.modules["src.services.dish_margin"] = _fake_dish_margin

# ─── 导入路由 ─────────────────────────────────────────────────────────────────

from src.api.inventory_analysis_routes import router as inventory_router  # noqa: E402
from src.api.dish_analysis_routes import router as dish_router  # noqa: E402

# ─── 工具函数 ─────────────────────────────────────────────────────────────────

_TENANT = "33333333-3333-3333-3333-333333333333"
_HEADERS = {"X-Tenant-ID": _TENANT}
_STORE_ID = "store-001"
_VALID_UUID = str(uuid.uuid4())
_DATE_BODY = {"start": "2026-03-01", "end": "2026-03-31"}


def _make_client(router):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ════════════════════════════════════════════════════════════════════════════
# inventory_analysis_routes 测试
# ════════════════════════════════════════════════════════════════════════════


class TestInventoryTurnover:
    """POST /api/v1/analytics/inventory/stores/{store_id}/turnover"""

    def setup_method(self):
        self.client = _make_client(inventory_router)

    def test_missing_tenant_returns_422(self):
        """X-Tenant-ID 为 Header(...) 必填，缺少时应 422"""
        resp = self.client.post(
            f"/api/v1/analytics/inventory/stores/{_STORE_ID}/turnover",
            json=_DATE_BODY,
        )
        assert resp.status_code == 422

    def test_valid_request_returns_200(self):
        resp = self.client.post(
            f"/api/v1/analytics/inventory/stores/{_STORE_ID}/turnover",
            headers=_HEADERS,
            json=_DATE_BODY,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "turnover_days" in body["data"]

    def test_missing_body_returns_422(self):
        resp = self.client.post(
            f"/api/v1/analytics/inventory/stores/{_STORE_ID}/turnover",
            headers=_HEADERS,
        )
        assert resp.status_code == 422

    def test_service_value_error_returns_400(self):
        _fake_inv_svc.inventory_turnover = AsyncMock(
            side_effect=ValueError("invalid date range")
        )
        resp = self.client.post(
            f"/api/v1/analytics/inventory/stores/{_STORE_ID}/turnover",
            headers=_HEADERS,
            json=_DATE_BODY,
        )
        assert resp.status_code == 400
        # 恢复
        _fake_inv_svc.inventory_turnover = AsyncMock(return_value=_TURNOVER_RESULT)


class TestInventoryPriceFluctuation:
    """POST /api/v1/analytics/inventory/price-fluctuation"""

    def setup_method(self):
        self.client = _make_client(inventory_router)

    def test_missing_tenant_returns_422(self):
        resp = self.client.post(
            "/api/v1/analytics/inventory/price-fluctuation",
            json=_DATE_BODY,
        )
        assert resp.status_code == 422

    def test_valid_request_returns_200(self):
        resp = self.client.post(
            "/api/v1/analytics/inventory/price-fluctuation",
            headers=_HEADERS,
            json=_DATE_BODY,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]


class TestInventoryWasteRanking:
    """POST /api/v1/analytics/inventory/stores/{store_id}/waste-ranking"""

    def setup_method(self):
        self.client = _make_client(inventory_router)

    def test_valid_request_returns_200(self):
        resp = self.client.post(
            f"/api/v1/analytics/inventory/stores/{_STORE_ID}/waste-ranking",
            headers=_HEADERS,
            json=_DATE_BODY,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_missing_tenant_returns_422(self):
        resp = self.client.post(
            f"/api/v1/analytics/inventory/stores/{_STORE_ID}/waste-ranking",
            json=_DATE_BODY,
        )
        assert resp.status_code == 422


class TestInventoryStocktakeVariance:
    """POST /api/v1/analytics/inventory/stores/{store_id}/stocktake-variance"""

    def setup_method(self):
        self.client = _make_client(inventory_router)

    def test_valid_request_returns_200(self):
        resp = self.client.post(
            f"/api/v1/analytics/inventory/stores/{_STORE_ID}/stocktake-variance",
            headers=_HEADERS,
            json=_DATE_BODY,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "variance_items" in body["data"]


class TestInventoryFoodSafetyRisk:
    """GET /api/v1/analytics/inventory/stores/{store_id}/food-safety-risk"""

    def setup_method(self):
        self.client = _make_client(inventory_router)

    def test_missing_tenant_returns_422(self):
        resp = self.client.get(
            f"/api/v1/analytics/inventory/stores/{_STORE_ID}/food-safety-risk"
        )
        assert resp.status_code == 422

    def test_valid_request_returns_200(self):
        resp = self.client.get(
            f"/api/v1/analytics/inventory/stores/{_STORE_ID}/food-safety-risk",
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "risk_items" in body["data"]
        assert "risk_level" in body["data"]

    def test_service_value_error_returns_400(self):
        _fake_inv_svc.food_safety_risk_graph = AsyncMock(
            side_effect=ValueError("store not found")
        )
        resp = self.client.get(
            f"/api/v1/analytics/inventory/stores/{_STORE_ID}/food-safety-risk",
            headers=_HEADERS,
        )
        assert resp.status_code == 400
        _fake_inv_svc.food_safety_risk_graph = AsyncMock(return_value=_FOOD_SAFETY_RESULT)


# ════════════════════════════════════════════════════════════════════════════
# dish_analysis_routes 测试
# ════════════════════════════════════════════════════════════════════════════


class TestDishSalesRanking:
    """GET /api/v1/analysis/dish/sales-ranking"""

    def setup_method(self):
        self.client = _make_client(dish_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get(
            f"/api/v1/analysis/dish/sales-ranking?store_id={_VALID_UUID}"
        )
        assert resp.status_code == 400

    def test_missing_store_id_returns_422(self):
        resp = self.client.get(
            "/api/v1/analysis/dish/sales-ranking",
            headers={"X-Tenant-ID": _VALID_UUID},
        )
        assert resp.status_code == 422

    def test_invalid_uuid_store_id_returns_400(self):
        resp = self.client.get(
            "/api/v1/analysis/dish/sales-ranking?store_id=not-a-uuid",
            headers={"X-Tenant-ID": _VALID_UUID},
        )
        assert resp.status_code == 400

    def test_valid_request_returns_200(self):
        resp = self.client.get(
            f"/api/v1/analysis/dish/sales-ranking?store_id={_VALID_UUID}",
            headers={"X-Tenant-ID": _VALID_UUID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]
        assert "total" in body["data"]

    def test_sort_by_param_accepted(self):
        resp = self.client.get(
            f"/api/v1/analysis/dish/sales-ranking?store_id={_VALID_UUID}&sort_by=sales_amount_fen",
            headers={"X-Tenant-ID": _VALID_UUID},
        )
        assert resp.status_code == 200

    def test_limit_param_respected(self):
        resp = self.client.get(
            f"/api/v1/analysis/dish/sales-ranking?store_id={_VALID_UUID}&limit=5",
            headers={"X-Tenant-ID": _VALID_UUID},
        )
        assert resp.status_code == 200


class TestDishReturnRate:
    """GET /api/v1/analysis/dish/return-rate"""

    def setup_method(self):
        self.client = _make_client(dish_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get(
            f"/api/v1/analysis/dish/return-rate?store_id={_VALID_UUID}"
        )
        assert resp.status_code == 400

    def test_valid_request_returns_200(self):
        resp = self.client.get(
            f"/api/v1/analysis/dish/return-rate?store_id={_VALID_UUID}",
            headers={"X-Tenant-ID": _VALID_UUID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True


class TestDishNegativeReviews:
    """GET /api/v1/analysis/dish/negative-reviews"""

    def setup_method(self):
        self.client = _make_client(dish_router)

    def test_valid_request_returns_200(self):
        resp = self.client.get(
            f"/api/v1/analysis/dish/negative-reviews?store_id={_VALID_UUID}",
            headers={"X-Tenant-ID": _VALID_UUID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]
        assert "total" in body["data"]

    def test_min_rating_param_accepted(self):
        resp = self.client.get(
            f"/api/v1/analysis/dish/negative-reviews?store_id={_VALID_UUID}&min_rating=2.5",
            headers={"X-Tenant-ID": _VALID_UUID},
        )
        assert resp.status_code == 200

    def test_invalid_date_range_returns_422(self):
        resp = self.client.get(
            f"/api/v1/analysis/dish/negative-reviews?store_id={_VALID_UUID}"
            "&start_date=2026-04-01&end_date=2026-03-01",
            headers={"X-Tenant-ID": _VALID_UUID},
        )
        assert resp.status_code == 422


class TestDishStructure:
    """GET /api/v1/analysis/dish/structure"""

    def setup_method(self):
        self.client = _make_client(dish_router)

    def test_valid_request_returns_200(self):
        resp = self.client.get(
            f"/api/v1/analysis/dish/structure?store_id={_VALID_UUID}",
            headers={"X-Tenant-ID": _VALID_UUID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        # 四象限分析结果应包含 star/cash_cow/question/dog
        for quadrant in ["star", "cash_cow", "question", "dog"]:
            assert quadrant in data, f"missing quadrant: {quadrant}"

    def test_margin_threshold_param_accepted(self):
        resp = self.client.get(
            f"/api/v1/analysis/dish/structure?store_id={_VALID_UUID}&margin_threshold=60",
            headers={"X-Tenant-ID": _VALID_UUID},
        )
        assert resp.status_code == 200


class TestDishNewPerformance:
    """GET /api/v1/analysis/dish/new-performance"""

    def setup_method(self):
        self.client = _make_client(dish_router)

    def test_valid_request_returns_200(self):
        resp = self.client.get(
            f"/api/v1/analysis/dish/new-performance?store_id={_VALID_UUID}",
            headers={"X-Tenant-ID": _VALID_UUID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]
        assert "total" in body["data"]

    def test_days_since_launch_param_accepted(self):
        resp = self.client.get(
            f"/api/v1/analysis/dish/new-performance?store_id={_VALID_UUID}&days_since_launch=60",
            headers={"X-Tenant-ID": _VALID_UUID},
        )
        assert resp.status_code == 200


class TestDishMenuOptimization:
    """GET /api/v1/analysis/dish/optimization"""

    def setup_method(self):
        self.client = _make_client(dish_router)

    def test_valid_request_returns_200(self):
        resp = self.client.get(
            f"/api/v1/analysis/dish/optimization?store_id={_VALID_UUID}",
            headers={"X-Tenant-ID": _VALID_UUID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "suggestions" in body["data"]

    def test_missing_tenant_returns_400(self):
        resp = self.client.get(
            f"/api/v1/analysis/dish/optimization?store_id={_VALID_UUID}"
        )
        assert resp.status_code == 400
