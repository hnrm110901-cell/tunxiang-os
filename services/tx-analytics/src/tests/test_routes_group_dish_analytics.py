"""路由层测试 — group_dashboard_routes + dish_analytics_routes

覆盖端点（共 7 个）：
  group_dashboard_routes (3 个):
    GET /api/v1/analytics/group/today
    GET /api/v1/analytics/group/trend
    GET /api/v1/analytics/group/alerts

  dish_analytics_routes (4 个):
    GET /api/v1/analytics/dishes/top-selling
    GET /api/v1/analytics/dishes/time-heatmap
    GET /api/v1/analytics/dishes/pairing-analysis
    GET /api/v1/analytics/dishes/underperforming
"""

import sys
import types
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── 预置假模块 ──────────────────────────────────────────────────────────────

# src
sys.modules.setdefault("src", types.ModuleType("src"))
_fake_src_db = types.ModuleType("src.db")


async def _fake_get_db():
    yield None


_fake_src_db.get_db = _fake_get_db
sys.modules.setdefault("src.db", _fake_src_db)

# structlog
if "structlog" not in sys.modules:
    _fake_structlog = types.ModuleType("structlog")
    _fake_structlog.get_logger = lambda *a, **kw: MagicMock()
    sys.modules["structlog"] = _fake_structlog

# shared.ontology stubs（dish_analytics_routes 需要 async_session_factory）
for _mod_name in [
    "shared",
    "shared.ontology",
    "shared.ontology.src",
    "shared.ontology.src.database",
]:
    sys.modules.setdefault(_mod_name, types.ModuleType(_mod_name))

_fake_db_mod = sys.modules["shared.ontology.src.database"]
# async_session_factory will be patched per-test; set a placeholder here
if not hasattr(_fake_db_mod, "async_session_factory"):
    _fake_db_mod.async_session_factory = MagicMock()
if not hasattr(_fake_db_mod, "get_db_with_tenant"):
    _fake_db_mod.get_db_with_tenant = MagicMock()

# ─── 导入路由 ────────────────────────────────────────────────────────────────

from src.api.dish_analytics_routes import router as dish_router  # noqa: E402
from src.api.group_dashboard_routes import router as group_router  # noqa: E402

# ─── 工具 ────────────────────────────────────────────────────────────────────


def _make_client(router):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


_TENANT = "22222222-2222-2222-2222-222222222222"
_HEADERS = {"X-Tenant-ID": _TENANT}
_BRAND = "brand-001"


# ════════════════════════════════════════════════════════════════════════════
# group_dashboard_routes 测试（纯 mock 数据，无 DB）
# ════════════════════════════════════════════════════════════════════════════


class TestGroupDashboardToday:
    """GET /api/v1/analytics/group/today"""

    def setup_method(self):
        self.client = _make_client(group_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get(f"/api/v1/analytics/group/today?brand_id={_BRAND}")
        assert resp.status_code == 400

    def test_missing_brand_id_returns_422(self):
        resp = self.client.get(
            "/api/v1/analytics/group/today",
            headers=_HEADERS,
        )
        assert resp.status_code == 422

    def test_valid_request_returns_200(self):
        resp = self.client.get(
            f"/api/v1/analytics/group/today?brand_id={_BRAND}",
            headers=_HEADERS,
        )
        assert resp.status_code == 200

    def test_response_ok_true(self):
        resp = self.client.get(
            f"/api/v1/analytics/group/today?brand_id={_BRAND}",
            headers=_HEADERS,
        )
        body = resp.json()
        assert body["ok"] is True

    def test_data_has_summary_and_stores(self):
        resp = self.client.get(
            f"/api/v1/analytics/group/today?brand_id={_BRAND}",
            headers=_HEADERS,
        )
        data = resp.json()["data"]
        assert "summary" in data
        assert "stores" in data

    def test_summary_fields_present(self):
        resp = self.client.get(
            f"/api/v1/analytics/group/today?brand_id={_BRAND}",
            headers=_HEADERS,
        )
        summary = resp.json()["data"]["summary"]
        for field in [
            "total_revenue_fen",
            "total_orders",
            "avg_table_turnover",
            "active_stores",
            "total_stores",
        ]:
            assert field in summary, f"missing field: {field}"

    def test_stores_list_nonempty(self):
        resp = self.client.get(
            f"/api/v1/analytics/group/today?brand_id={_BRAND}",
            headers=_HEADERS,
        )
        stores = resp.json()["data"]["stores"]
        assert isinstance(stores, list)
        assert len(stores) > 0


class TestGroupDashboardTrend:
    """GET /api/v1/analytics/group/trend"""

    def setup_method(self):
        self.client = _make_client(group_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get(f"/api/v1/analytics/group/trend?brand_id={_BRAND}")
        assert resp.status_code == 400

    def test_valid_7_days(self):
        resp = self.client.get(
            f"/api/v1/analytics/group/trend?brand_id={_BRAND}&days=7",
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_valid_30_days(self):
        resp = self.client.get(
            f"/api/v1/analytics/group/trend?brand_id={_BRAND}&days=30",
            headers=_HEADERS,
        )
        assert resp.status_code == 200

    def test_dates_length_matches_days(self):
        resp = self.client.get(
            f"/api/v1/analytics/group/trend?brand_id={_BRAND}&days=7",
            headers=_HEADERS,
        )
        data = resp.json()["data"]
        assert len(data["dates"]) == 7
        assert len(data["total_revenue"]) == 7

    def test_by_store_dict_present(self):
        resp = self.client.get(
            f"/api/v1/analytics/group/trend?brand_id={_BRAND}&days=7",
            headers=_HEADERS,
        )
        data = resp.json()["data"]
        assert "by_store" in data
        assert isinstance(data["by_store"], dict)

    def test_days_out_of_range_returns_422(self):
        resp = self.client.get(
            f"/api/v1/analytics/group/trend?brand_id={_BRAND}&days=31",
            headers=_HEADERS,
        )
        assert resp.status_code == 422


class TestGroupDashboardAlerts:
    """GET /api/v1/analytics/group/alerts"""

    def setup_method(self):
        self.client = _make_client(group_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get(f"/api/v1/analytics/group/alerts?brand_id={_BRAND}")
        assert resp.status_code == 400

    def test_valid_returns_200(self):
        resp = self.client.get(
            f"/api/v1/analytics/group/alerts?brand_id={_BRAND}",
            headers=_HEADERS,
        )
        assert resp.status_code == 200

    def test_response_has_alerts_list(self):
        resp = self.client.get(
            f"/api/v1/analytics/group/alerts?brand_id={_BRAND}",
            headers=_HEADERS,
        )
        body = resp.json()
        assert body["ok"] is True
        assert "alerts" in body["data"]
        assert isinstance(body["data"]["alerts"], list)

    def test_alert_item_fields(self):
        resp = self.client.get(
            f"/api/v1/analytics/group/alerts?brand_id={_BRAND}",
            headers=_HEADERS,
        )
        alerts = resp.json()["data"]["alerts"]
        if alerts:
            first = alerts[0]
            for field in ["severity", "store_name", "type", "title", "body"]:
                assert field in first, f"missing field: {field}"


# ════════════════════════════════════════════════════════════════════════════
# dish_analytics_routes 测试（DB 异常时回退空数组）
# ════════════════════════════════════════════════════════════════════════════


def _patched_dish_client():
    """返回 TestClient，并让 async_session_factory 抛出 SQLAlchemyError"""
    import contextlib

    from sqlalchemy.exc import SQLAlchemyError

    @contextlib.asynccontextmanager
    async def _failing_session():
        raise SQLAlchemyError("DB unavailable")
        yield

    app = FastAPI()
    app.include_router(dish_router)
    client = TestClient(app, raise_server_exceptions=False)
    return client, _failing_session


class TestDishTopSelling:
    """GET /api/v1/analytics/dishes/top-selling"""

    def setup_method(self):
        self.client, self._failing_session = _patched_dish_client()

    def test_db_error_returns_ok_true_with_empty_dishes(self):
        with patch(
            "src.api.dish_analytics_routes.async_session_factory",
            return_value=self._failing_session(),
        ):
            resp = self.client.get("/api/v1/analytics/dishes/top-selling")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["dishes"] == []

    def test_days_param_reflected_in_response(self):
        with patch(
            "src.api.dish_analytics_routes.async_session_factory",
            return_value=self._failing_session(),
        ):
            resp = self.client.get("/api/v1/analytics/dishes/top-selling?days=14")
        assert resp.status_code == 200
        assert resp.json()["data"]["period_days"] == 14

    def test_limit_param_accepted(self):
        with patch(
            "src.api.dish_analytics_routes.async_session_factory",
            return_value=self._failing_session(),
        ):
            resp = self.client.get("/api/v1/analytics/dishes/top-selling?limit=5")
        assert resp.status_code == 200

    def test_store_id_filter_param_accepted(self):
        with patch(
            "src.api.dish_analytics_routes.async_session_factory",
            return_value=self._failing_session(),
        ):
            resp = self.client.get("/api/v1/analytics/dishes/top-selling?store_id=store-001")
        assert resp.status_code == 200


class TestDishTimeHeatmap:
    """GET /api/v1/analytics/dishes/time-heatmap"""

    def setup_method(self):
        self.client, self._failing_session = _patched_dish_client()

    def test_db_error_returns_ok_true_with_empty_heatmap(self):
        with patch(
            "src.api.dish_analytics_routes.async_session_factory",
            return_value=self._failing_session(),
        ):
            resp = self.client.get("/api/v1/analytics/dishes/time-heatmap")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "heatmap" in body["data"]

    def test_dish_id_filter_accepted(self):
        with patch(
            "src.api.dish_analytics_routes.async_session_factory",
            return_value=self._failing_session(),
        ):
            resp = self.client.get("/api/v1/analytics/dishes/time-heatmap?dish_id=dish-001")
        assert resp.status_code == 200


class TestDishPairingAnalysis:
    """GET /api/v1/analytics/dishes/pairing-analysis"""

    def setup_method(self):
        self.client, self._failing_session = _patched_dish_client()

    def test_missing_dish_id_returns_422(self):
        with patch(
            "src.api.dish_analytics_routes.async_session_factory",
            return_value=self._failing_session(),
        ):
            resp = self.client.get("/api/v1/analytics/dishes/pairing-analysis")
        assert resp.status_code == 422

    def test_db_error_returns_ok_with_empty_pairings(self):
        with patch(
            "src.api.dish_analytics_routes.async_session_factory",
            return_value=self._failing_session(),
        ):
            resp = self.client.get("/api/v1/analytics/dishes/pairing-analysis?dish_id=dish-001")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["pairings"] == []
        assert body["data"]["dish_id"] == "dish-001"


class TestDishUnderperforming:
    """GET /api/v1/analytics/dishes/underperforming"""

    def setup_method(self):
        self.client, self._failing_session = _patched_dish_client()

    def test_db_error_returns_ok_with_empty_items(self):
        with patch(
            "src.api.dish_analytics_routes.async_session_factory",
            return_value=self._failing_session(),
        ):
            resp = self.client.get("/api/v1/analytics/dishes/underperforming")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["items"] == []

    def test_threshold_param_accepted(self):
        with patch(
            "src.api.dish_analytics_routes.async_session_factory",
            return_value=self._failing_session(),
        ):
            resp = self.client.get("/api/v1/analytics/dishes/underperforming?min_sales_threshold=50")
        assert resp.status_code == 200

    def test_period_days_in_response(self):
        with patch(
            "src.api.dish_analytics_routes.async_session_factory",
            return_value=self._failing_session(),
        ):
            resp = self.client.get("/api/v1/analytics/dishes/underperforming?days=14")
        assert resp.json()["data"]["period_days"] == 14
