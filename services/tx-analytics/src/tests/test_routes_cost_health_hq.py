"""路由层测试 — cost_health_routes + hq_overview_routes

覆盖端点（共 8 个）：
  cost_health_routes (5 个):
    GET /api/v1/cost-health/store/{store_id}
    GET /api/v1/cost-health/group/heatmap
    GET /api/v1/cost-health/brand/{brand_id}/benchmark
    GET /api/v1/cost-health/alerts
    GET /api/v1/cost-health/store/{store_id}/suggestions

  hq_overview_routes (3 个):
    GET /api/v1/analytics/overview
    GET /api/v1/analytics/store-ranking
    GET /api/v1/analytics/category-sales
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── 预置假模块，阻断真实 DB / 服务层导入 ──────────────────────────────────

# src.db（通用兜底）
_fake_src = types.ModuleType("src")
_fake_src_db = types.ModuleType("src.db")
async def _fake_get_db():
    yield None
_fake_src_db.get_db = _fake_get_db
sys.modules.setdefault("src", _fake_src)
sys.modules.setdefault("src.db", _fake_src_db)

# structlog
_fake_structlog = types.ModuleType("structlog")
_fake_structlog.get_logger = lambda *a, **kw: MagicMock()
sys.modules.setdefault("structlog", _fake_structlog)

# shared.ontology
for _mod in [
    "shared", "shared.ontology", "shared.ontology.src",
    "shared.ontology.src.database", "shared.ontology.src.entities",
    "shared.ontology.src.enums",
]:
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

# async_session_factory — 被 hq_overview_routes 直接使用
_fake_db_mod = sys.modules["shared.ontology.src.database"]
_fake_db_mod.async_session_factory = MagicMock()
_fake_db_mod.get_db_with_tenant = MagicMock()

# entities / enums stub
_fake_entities = sys.modules["shared.ontology.src.entities"]
for _name in ["Dish", "DishCategory", "Order", "OrderItem", "Store"]:
    setattr(_fake_entities, _name, MagicMock())

_fake_enums = sys.modules["shared.ontology.src.enums"]
_fake_enum_val = MagicMock()
_fake_enum_val.value = "cancelled"
_fake_enums.OrderStatus = MagicMock(cancelled=_fake_enum_val)

# cost_health_engine stub
_fake_engine_mod = types.ModuleType("src.services.cost_health_engine")

class _FakeCostHealthEngine:
    async def calc_store_cost_health(self, **kw):
        return MagicMock(
            model_dump=lambda: {
                "store_id": kw.get("store_id", "s1"),
                "health_score": 72.0,
                "health_level": "warning",
                "store_name": "测试店",
                "brand_id": "brand-001",
                "ingredient_cost_rate": 0.38,
                "labor_cost_rate": 0.28,
                "waste_rate": 0.05,
                "benchmark_ingredient": 0.35,
                "benchmark_labor": 0.25,
                "benchmark_waste": 0.04,
                "ingredient_deviation": 0.08,
                "labor_deviation": 0.12,
                "waste_deviation": 0.25,
                "is_ingredient_anomaly": False,
                "is_labor_anomaly": False,
                "is_waste_anomaly": False,
            },
            health_score=72.0,
            health_level="warning",
            store_name="测试店",
            brand_id="brand-001",
            ingredient_cost_rate=0.38,
            labor_cost_rate=0.28,
            waste_rate=0.05,
            benchmark_ingredient=0.35,
            benchmark_labor=0.25,
            benchmark_waste=0.04,
            ingredient_deviation=0.08,
            labor_deviation=0.12,
            waste_deviation=0.25,
            is_ingredient_anomaly=False,
            is_labor_anomaly=False,
            is_waste_anomaly=False,
        )

    async def get_group_cost_heatmap(self, **kw):
        m = MagicMock(
            health_level="warning",
            is_ingredient_anomaly=True,
            is_labor_anomaly=False,
            is_waste_anomaly=False,
            store_id="s1",
            store_name="测试店",
            brand_id="brand-001",
            health_score=60.0,
            ingredient_cost_rate=0.42,
            labor_cost_rate=0.26,
            waste_rate=0.04,
            benchmark_ingredient=0.35,
            benchmark_labor=0.25,
            benchmark_waste=0.04,
            ingredient_deviation=0.2,
            labor_deviation=0.04,
            waste_deviation=0.0,
            model_dump=lambda: {
                "store_id": "s1",
                "health_score": 60.0,
                "health_level": "warning",
            },
        )
        return [m]

    async def get_brand_cost_benchmark(self, **kw):
        return MagicMock(
            model_dump=lambda: {
                "brand_id": kw.get("brand_id", "brand-001"),
                "store_count": 3,
                "median_ingredient_cost_rate": 0.35,
            }
        )

    async def generate_cost_optimization_suggestion(self, **kw):
        return "建议降低食材采购单价，加强损耗管控。"


_fake_engine_mod.CostHealthEngine = _FakeCostHealthEngine
_fake_engine_mod._cache_get = lambda key: None
_fake_engine_mod._cache_set = lambda key, val: None
sys.modules["src.services"] = types.ModuleType("src.services")
sys.modules["src.services.cost_health_engine"] = _fake_engine_mod

# ─── 导入路由 ────────────────────────────────────────────────────────────────

from src.api.cost_health_routes import router as cost_health_router  # noqa: E402

# hq_overview_routes uses async_session_factory internally — we'll patch it in tests
from src.api.hq_overview_routes import router as hq_router  # noqa: E402

# ─── TestClient 工厂 ─────────────────────────────────────────────────────────

def _make_client(router):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


_TENANT = "11111111-1111-1111-1111-111111111111"
_HEADERS = {"X-Tenant-ID": _TENANT}


# ════════════════════════════════════════════════════════════════════════════
# cost_health_routes 测试
# ════════════════════════════════════════════════════════════════════════════

class TestCostHealthStoreCostHealth:
    """GET /api/v1/cost-health/store/{store_id}"""

    def setup_method(self):
        self.client = _make_client(cost_health_router)

    def _override_tenant_db(self, app):
        from src.api.cost_health_routes import _get_tenant_db
        async def _fake_db():
            yield None
        app.dependency_overrides[_get_tenant_db] = _fake_db

    def test_missing_tenant_header_returns_400(self):
        resp = self.client.get("/api/v1/cost-health/store/store-001")
        assert resp.status_code == 400

    def test_valid_request_returns_200(self):
        resp = self.client.get(
            "/api/v1/cost-health/store/store-001",
            headers=_HEADERS,
        )
        assert resp.status_code == 200

    def test_response_structure(self):
        resp = self.client.get(
            "/api/v1/cost-health/store/store-001",
            headers=_HEADERS,
        )
        body = resp.json()
        assert body["ok"] is True
        assert "data" in body

    def test_days_param_accepted(self):
        resp = self.client.get(
            "/api/v1/cost-health/store/store-001?days=60",
            headers=_HEADERS,
        )
        assert resp.status_code == 200

    def test_days_below_min_returns_422(self):
        resp = self.client.get(
            "/api/v1/cost-health/store/store-001?days=3",
            headers=_HEADERS,
        )
        assert resp.status_code == 422


class TestCostHealthGroupHeatmap:
    """GET /api/v1/cost-health/group/heatmap"""

    def setup_method(self):
        self.client = _make_client(cost_health_router)

    def test_missing_tenant_header_returns_400(self):
        resp = self.client.get("/api/v1/cost-health/group/heatmap")
        assert resp.status_code == 400

    def test_returns_200_with_stores_key(self):
        resp = self.client.get(
            "/api/v1/cost-health/group/heatmap",
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "stores" in body["data"]
        assert "summary" in body["data"]

    def test_summary_counts_present(self):
        resp = self.client.get(
            "/api/v1/cost-health/group/heatmap",
            headers=_HEADERS,
        )
        summary = resp.json()["data"]["summary"]
        assert "total_stores" in summary
        assert "critical_count" in summary
        assert "warning_count" in summary
        assert "healthy_count" in summary


class TestCostHealthBrandBenchmark:
    """GET /api/v1/cost-health/brand/{brand_id}/benchmark"""

    def setup_method(self):
        self.client = _make_client(cost_health_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get("/api/v1/cost-health/brand/brand-001/benchmark")
        assert resp.status_code == 400

    def test_valid_returns_200(self):
        resp = self.client.get(
            "/api/v1/cost-health/brand/brand-001/benchmark",
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True


class TestCostHealthAlerts:
    """GET /api/v1/cost-health/alerts"""

    def setup_method(self):
        self.client = _make_client(cost_health_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get("/api/v1/cost-health/alerts")
        assert resp.status_code == 400

    def test_returns_alerts_list(self):
        resp = self.client.get(
            "/api/v1/cost-health/alerts",
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "alerts" in body["data"]
        assert "total_anomaly_stores" in body["data"]

    def test_filter_level_critical(self):
        resp = self.client.get(
            "/api/v1/cost-health/alerts?level=critical",
            headers=_HEADERS,
        )
        assert resp.status_code == 200

    def test_filter_level_warning(self):
        resp = self.client.get(
            "/api/v1/cost-health/alerts?level=warning",
            headers=_HEADERS,
        )
        assert resp.status_code == 200


class TestCostHealthSuggestions:
    """GET /api/v1/cost-health/store/{store_id}/suggestions"""

    def setup_method(self):
        self.client = _make_client(cost_health_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get("/api/v1/cost-health/store/store-001/suggestions")
        assert resp.status_code == 400

    def test_healthy_store_no_trigger(self):
        """health_score >= 65 → triggered=False（当前 mock 返回 72.0）"""
        resp = self.client.get(
            "/api/v1/cost-health/store/store-001/suggestions",
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        # health_score=72 → triggered=False
        assert body["data"]["triggered"] is False

    def test_response_has_required_fields(self):
        resp = self.client.get(
            "/api/v1/cost-health/store/store-001/suggestions",
            headers=_HEADERS,
        )
        body = resp.json()
        data = body["data"]
        assert "store_id" in data
        assert "health_score" in data
        assert "triggered" in data


# ════════════════════════════════════════════════════════════════════════════
# hq_overview_routes 测试 — 该路由内部异常时回退为 mock 数据，永远不返回 500
# ════════════════════════════════════════════════════════════════════════════

class TestHqOverview:
    """GET /api/v1/analytics/overview"""

    def setup_method(self):
        self.client = _make_client(hq_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get("/api/v1/analytics/overview")
        assert resp.status_code == 400

    def test_invalid_tenant_uuid_returns_400(self):
        resp = self.client.get(
            "/api/v1/analytics/overview",
            headers={"X-Tenant-ID": "not-a-uuid"},
        )
        assert resp.status_code == 400

    def test_db_error_falls_back_to_mock(self):
        """async_session_factory 抛异常时路由使用 mock 数据，仍返回 200"""
        import contextlib

        @contextlib.asynccontextmanager
        async def _failing_session():
            raise OSError("DB unavailable")
            yield  # make it a generator

        with patch(
            "src.api.hq_overview_routes.async_session_factory",
            return_value=_failing_session(),
        ):
            resp = self.client.get(
                "/api/v1/analytics/overview",
                headers=_HEADERS,
            )
        # Falls back to mock data — still 200
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "data" in body

    def test_mock_data_structure(self):
        """验证 mock 兜底数据包含必要字段"""
        import contextlib

        @contextlib.asynccontextmanager
        async def _failing_session():
            raise OSError("DB unavailable")
            yield

        with patch(
            "src.api.hq_overview_routes.async_session_factory",
            return_value=_failing_session(),
        ):
            resp = self.client.get(
                "/api/v1/analytics/overview",
                headers=_HEADERS,
            )
        data = resp.json()["data"]
        for field in ["revenue_fen", "order_count", "online_stores", "total_stores"]:
            assert field in data, f"missing field: {field}"

    def test_date_param_accepted(self):
        import contextlib

        @contextlib.asynccontextmanager
        async def _failing_session():
            raise Exception("no db")
            yield

        with patch(
            "src.api.hq_overview_routes.async_session_factory",
            return_value=_failing_session(),
        ):
            resp = self.client.get(
                "/api/v1/analytics/overview?date=2026-01-01",
                headers=_HEADERS,
            )
        assert resp.status_code == 200


class TestHqStoreRanking:
    """GET /api/v1/analytics/store-ranking"""

    def setup_method(self):
        self.client = _make_client(hq_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get("/api/v1/analytics/store-ranking")
        assert resp.status_code == 400

    def test_db_error_falls_back_to_mock(self):
        import contextlib

        @contextlib.asynccontextmanager
        async def _failing_session():
            raise OSError("DB unavailable")
            yield

        with patch(
            "src.api.hq_overview_routes.async_session_factory",
            return_value=_failing_session(),
        ):
            resp = self.client.get(
                "/api/v1/analytics/store-ranking",
                headers=_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "stores" in body["data"]

    def test_limit_param(self):
        import contextlib

        @contextlib.asynccontextmanager
        async def _failing_session():
            raise Exception("no db")
            yield

        with patch(
            "src.api.hq_overview_routes.async_session_factory",
            return_value=_failing_session(),
        ):
            resp = self.client.get(
                "/api/v1/analytics/store-ranking?limit=3",
                headers=_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]["stores"]) <= 3


class TestHqCategorySales:
    """GET /api/v1/analytics/category-sales"""

    def setup_method(self):
        self.client = _make_client(hq_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get("/api/v1/analytics/category-sales")
        assert resp.status_code == 400

    def test_db_error_falls_back_to_mock(self):
        import contextlib

        @contextlib.asynccontextmanager
        async def _failing_session():
            raise OSError("DB unavailable")
            yield

        with patch(
            "src.api.hq_overview_routes.async_session_factory",
            return_value=_failing_session(),
        ):
            resp = self.client.get(
                "/api/v1/analytics/category-sales",
                headers=_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "categories" in body["data"]
