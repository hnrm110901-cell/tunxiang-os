"""路由层测试 — analytics.py + report_routes.py

覆盖端点（共 20 个）：
  analytics.py (14 个):
    GET /api/v1/analytics/stores/health
    GET /api/v1/analytics/stores/{store_id}/health/detail
    GET /api/v1/analytics/stores/{store_id}/brief
    GET /api/v1/analytics/kpi/alerts
    GET /api/v1/analytics/kpi/trend
    GET /api/v1/analytics/reports/daily
    GET /api/v1/analytics/reports/weekly
    GET /api/v1/analytics/decisions/top3
    GET /api/v1/analytics/decisions/behavior-report
    GET /api/v1/analytics/scenario
    GET /api/v1/analytics/cross-store/insights
    GET /api/v1/analytics/competitive
    GET /api/v1/analytics/bff/hq/{brand_id}
    GET /api/v1/analytics/bff/sm/{store_id}

  report_routes.py (6 个):
    GET  /api/v1/reports
    GET  /api/v1/reports/schedules
    GET  /api/v1/reports/{report_id}
    POST /api/v1/reports/{report_id}/execute
    GET  /api/v1/reports/{report_id}/export
    POST /api/v1/reports/schedule
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
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

# shared.ontology stubs
for _mod_name in [
    "shared",
    "shared.ontology",
    "shared.ontology.src",
    "shared.ontology.src.database",
]:
    sys.modules.setdefault(_mod_name, types.ModuleType(_mod_name))

_fake_db_mod = sys.modules["shared.ontology.src.database"]


async def _shared_get_db():
    yield None


if not hasattr(_fake_db_mod, "get_db"):
    _fake_db_mod.get_db = _shared_get_db
if not hasattr(_fake_db_mod, "async_session_factory"):
    _fake_db_mod.async_session_factory = MagicMock()


# ─── analytics.py 的 service 层 stub ──────────────────────────────────────

_HEALTH_DATA = {
    "overall_score": 88.0,
    "revenue_score": 90,
    "efficiency_score": 85,
}
_DAILY_DATA = {
    "revenue_fen": 100000,
    "order_count": 50,
    "avg_ticket_fen": 2000,
    "guest_count": 80,
}
_ALERTS_DATA = [{"kpi": "revenue", "level": "warn", "msg": "low revenue"}]
_DECISIONS_DATA = [{"id": "d1", "title": "降价", "priority": "high"}]


def _make_analytics_repo_mock():
    repo = MagicMock()
    repo.get_store_health = AsyncMock(return_value=_HEALTH_DATA.copy())
    repo.get_daily_report = AsyncMock(return_value=_DAILY_DATA.copy())
    repo.get_kpi_alerts = AsyncMock(return_value=list(_ALERTS_DATA))
    repo.get_top3_decisions = AsyncMock(return_value=list(_DECISIONS_DATA))
    repo.get_kpi_trend = AsyncMock(return_value=[{"date": "2026-04-01", "value": 100}])
    repo.get_weekly_report = AsyncMock(return_value={"revenue_fen": 700000})
    repo.get_behavior_report = AsyncMock(return_value={"sessions": 10})
    repo.identify_scenario = AsyncMock(return_value={"scenario": "peak"})
    repo.get_cross_store_insights = AsyncMock(return_value=[])
    repo.get_competitive_analysis = AsyncMock(return_value={"rank": 1})
    store_mock = MagicMock()
    store_mock.id = "store-001"
    store_mock.store_name = "测试门店"
    repo.get_brand_stores = AsyncMock(return_value=[store_mock])
    return repo


# ─── report_routes.py 的 service 层 stub ─────────────────────────────────

_REPORT_META = {
    "report_id": "daily_revenue",
    "name": "日营收报表",
    "category": "revenue",
    "is_active": True,
    "params": [],
}
_REPORT_RESULT_MOCK = MagicMock()
_REPORT_RESULT_MOCK.rows = [{"store_id": "s1", "revenue_fen": 50000}]
_REPORT_RESULT_MOCK.total_count = 1
_REPORT_RESULT_MOCK.page = 1
_REPORT_RESULT_MOCK.page_size = 100


def _make_renderer_dict():
    return {"rows": [{"store_id": "s1"}], "total": 1, "page": 1, "page_size": 100}


_SCHEDULE_CONFIG_MOCK = MagicMock()
_SCHEDULE_CONFIG_MOCK.schedule_id = "sch-001"
_SCHEDULE_CONFIG_MOCK.report_id = "daily_revenue"
_SCHEDULE_CONFIG_MOCK.cron_expression = "0 8 * * *"
_SCHEDULE_CONFIG_MOCK.channel = "webhook"
_SCHEDULE_CONFIG_MOCK.is_active = True


# ─── 导入路由（在 stub 设置后）──────────────────────────────────────────────

# analytics.py 需要 AnalyticsRepository, compose_brief, classify_health
with (
    patch.dict(
        "sys.modules",
        {
            "src.services.repository": MagicMock(),
            "src.services.narrative_engine": MagicMock(),
            "src.services.store_health_service": MagicMock(),
        },
    )
):
    # 在导入之前设置好 sys.modules 中的 services
    _fake_repo_mod = types.ModuleType("src.services.repository")
    _fake_narrative_mod = types.ModuleType("src.services.narrative_engine")
    _fake_health_mod = types.ModuleType("src.services.store_health_service")

    sys.modules.setdefault("src.services", types.ModuleType("src.services"))
    sys.modules["src.services.repository"] = _fake_repo_mod
    sys.modules["src.services.narrative_engine"] = _fake_narrative_mod
    sys.modules["src.services.store_health_service"] = _fake_health_mod

    # 提供 classify_health 和 compose_brief
    _fake_health_mod.classify_health = lambda score: "healthy" if score >= 80 else "warning"
    _fake_narrative_mod.compose_brief = lambda **kw: "门店今日运营正常，营收达标。"

    # AnalyticsRepository 工厂
    class _FakeRepo:
        def __init__(self, db, tenant_id):
            self._m = _make_analytics_repo_mock()

        def __getattr__(self, name):
            return getattr(self._m, name)

    _fake_repo_mod.AnalyticsRepository = _FakeRepo

from src.api.analytics import router as analytics_router  # noqa: E402

# report_routes 需要 report_engine, report_registry
_fake_re_mod = types.ModuleType("src.services.report_engine")
_fake_rr_mod = types.ModuleType("src.services.report_registry")
sys.modules["src.services.report_engine"] = _fake_re_mod
sys.modules["src.services.report_registry"] = _fake_rr_mod

# 定义 report_engine 中需要的类/异常
from enum import Enum as _Enum


class _ExportFormat(_Enum):
    json = "json"
    csv = "csv"
    excel = "excel"


class _SortDirection(_Enum):
    asc = "asc"
    desc = "desc"


class _ReportNotFoundError(ValueError):
    pass


class _ReportInactiveError(ValueError):
    pass


class _ReportParamError(ValueError):
    pass


_fake_re_mod.ExportFormat = _ExportFormat
_fake_re_mod.SortDirection = _SortDirection
_fake_re_mod.ReportNotFoundError = _ReportNotFoundError
_fake_re_mod.ReportInactiveError = _ReportInactiveError
_fake_re_mod.ReportParamError = _ReportParamError

# ReportEngine mock
_fake_engine_inst = MagicMock()
_fake_engine_inst.list_reports = AsyncMock(return_value=[_REPORT_META])
_fake_engine_inst.get_report_metadata = AsyncMock(return_value=_REPORT_META)
_fake_engine_inst.execute_report = AsyncMock(return_value=_REPORT_RESULT_MOCK)

_fake_re_mod.ReportEngine = MagicMock(return_value=_fake_engine_inst)

# ReportRenderer mock
_fake_renderer_inst = MagicMock()
_fake_renderer_inst.to_json = MagicMock(return_value=_make_renderer_dict())
_fake_renderer_inst.to_csv = MagicMock(return_value=b"col1,col2\nval1,val2")
_fake_renderer_inst.to_excel = MagicMock(return_value=b"PK excel binary")

_fake_re_mod.ReportRenderer = MagicMock(return_value=_fake_renderer_inst)

# ReportScheduler mock
_fake_scheduler_inst = MagicMock()
_fake_scheduler_inst.schedule_report = AsyncMock(return_value=_SCHEDULE_CONFIG_MOCK)
_fake_scheduler_inst.get_schedule_list = AsyncMock(return_value=[])

_fake_re_mod.ReportScheduler = MagicMock(return_value=_fake_scheduler_inst)

# create_default_registry mock
_fake_rr_mod.create_default_registry = MagicMock(return_value=MagicMock())

from src.api.report_routes import router as report_router  # noqa: E402

# ─── 工具 ────────────────────────────────────────────────────────────────────

_TENANT = "11111111-1111-1111-1111-111111111111"
_HEADERS = {"X-Tenant-ID": _TENANT}
_STORE_ID = "store-001"
_BRAND_ID = "brand-001"


def _make_client(router):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ════════════════════════════════════════════════════════════════════════════
# analytics.py 路由测试
# ════════════════════════════════════════════════════════════════════════════


class TestAnalyticsStoreHealth:
    """GET /api/v1/analytics/stores/health"""

    def setup_method(self):
        self.client = _make_client(analytics_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get(f"/api/v1/analytics/stores/health?store_id={_STORE_ID}")
        assert resp.status_code == 400

    def test_missing_store_id_returns_ok_false(self):
        resp = self.client.get(
            "/api/v1/analytics/stores/health",
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "MISSING_PARAM"

    def test_valid_request_returns_200(self):
        resp = self.client.get(
            f"/api/v1/analytics/stores/health?store_id={_STORE_ID}",
            headers=_HEADERS,
        )
        assert resp.status_code == 200

    def test_response_ok_true_with_scores(self):
        resp = self.client.get(
            f"/api/v1/analytics/stores/health?store_id={_STORE_ID}",
            headers=_HEADERS,
        )
        body = resp.json()
        assert body["ok"] is True
        assert "scores" in body["data"]

    def test_store_not_found_returns_ok_false(self):
        """当 AnalyticsRepository 抛出 ValueError（not found）时返回 ok=False"""
        repo_mock = _make_analytics_repo_mock()
        repo_mock.get_store_health = AsyncMock(side_effect=ValueError("store not found"))

        class _PatchedRepo:
            def __init__(self, db, tenant_id):
                self._m = repo_mock

            def __getattr__(self, name):
                return getattr(self._m, name)

        with patch.object(
            sys.modules["src.services.repository"],
            "AnalyticsRepository",
            _PatchedRepo,
        ):
            resp = self.client.get(
                f"/api/v1/analytics/stores/health?store_id=nonexistent",
                headers=_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is False
        assert resp.json()["error"]["code"] == "NOT_FOUND"


class TestAnalyticsKpiAlerts:
    """GET /api/v1/analytics/kpi/alerts"""

    def setup_method(self):
        self.client = _make_client(analytics_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get(
            f"/api/v1/analytics/kpi/alerts?store_id={_STORE_ID}"
        )
        assert resp.status_code == 400

    def test_missing_store_id_returns_422(self):
        resp = self.client.get("/api/v1/analytics/kpi/alerts", headers=_HEADERS)
        assert resp.status_code == 422

    def test_valid_request_returns_200(self):
        resp = self.client.get(
            f"/api/v1/analytics/kpi/alerts?store_id={_STORE_ID}",
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "alerts" in body["data"]


class TestAnalyticsKpiTrend:
    """GET /api/v1/analytics/kpi/trend"""

    def setup_method(self):
        self.client = _make_client(analytics_router)

    def test_missing_required_params_returns_422(self):
        resp = self.client.get("/api/v1/analytics/kpi/trend", headers=_HEADERS)
        assert resp.status_code == 422

    def test_valid_request_returns_200(self):
        resp = self.client.get(
            f"/api/v1/analytics/kpi/trend?store_id={_STORE_ID}&kpi_name=revenue",
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "trend" in body["data"]

    def test_days_param_accepted(self):
        resp = self.client.get(
            f"/api/v1/analytics/kpi/trend?store_id={_STORE_ID}&kpi_name=revenue&days=7",
            headers=_HEADERS,
        )
        assert resp.status_code == 200


class TestAnalyticsDailyReport:
    """GET /api/v1/analytics/reports/daily"""

    def setup_method(self):
        self.client = _make_client(analytics_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get(
            f"/api/v1/analytics/reports/daily?store_id={_STORE_ID}"
        )
        assert resp.status_code == 400

    def test_valid_request_returns_200(self):
        resp = self.client.get(
            f"/api/v1/analytics/reports/daily?store_id={_STORE_ID}",
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "report" in body["data"]


class TestAnalyticsBffHq:
    """GET /api/v1/analytics/bff/hq/{brand_id}"""

    def setup_method(self):
        self.client = _make_client(analytics_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get(f"/api/v1/analytics/bff/hq/{_BRAND_ID}")
        assert resp.status_code == 400

    def test_valid_request_returns_200(self):
        resp = self.client.get(
            f"/api/v1/analytics/bff/hq/{_BRAND_ID}",
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_response_has_health_scores_and_alerts(self):
        resp = self.client.get(
            f"/api/v1/analytics/bff/hq/{_BRAND_ID}",
            headers=_HEADERS,
        )
        data = resp.json()["data"]
        assert "health_scores" in data
        assert "alerts" in data
        assert "top_decisions" in data


# ════════════════════════════════════════════════════════════════════════════
# report_routes.py 路由测试
# ════════════════════════════════════════════════════════════════════════════


class TestReportsList:
    """GET /api/v1/reports"""

    def setup_method(self):
        self.client = _make_client(report_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get("/api/v1/reports")
        assert resp.status_code == 400

    def test_valid_request_returns_200(self):
        resp = self.client.get("/api/v1/reports", headers=_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]
        assert "total" in body["data"]

    def test_category_filter_param_accepted(self):
        resp = self.client.get(
            "/api/v1/reports?category=revenue", headers=_HEADERS
        )
        assert resp.status_code == 200


class TestReportMetadata:
    """GET /api/v1/reports/{report_id}"""

    def setup_method(self):
        self.client = _make_client(report_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get("/api/v1/reports/daily_revenue")
        assert resp.status_code == 400

    def test_valid_request_returns_200(self):
        resp = self.client.get("/api/v1/reports/daily_revenue", headers=_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["report_id"] == "daily_revenue"

    def test_not_found_report_returns_404(self):
        _fake_engine_inst.get_report_metadata = AsyncMock(
            side_effect=_ReportNotFoundError("not found")
        )
        resp = self.client.get("/api/v1/reports/nonexistent", headers=_HEADERS)
        assert resp.status_code == 404
        # 恢复正常状态
        _fake_engine_inst.get_report_metadata = AsyncMock(return_value=_REPORT_META)


class TestReportExecute:
    """POST /api/v1/reports/{report_id}/execute"""

    def setup_method(self):
        self.client = _make_client(report_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.post(
            "/api/v1/reports/daily_revenue/execute",
            json={"params": {}},
        )
        assert resp.status_code == 400

    def test_valid_request_returns_200(self):
        resp = self.client.post(
            "/api/v1/reports/daily_revenue/execute",
            headers=_HEADERS,
            json={"params": {"store_id": _STORE_ID}, "page": 1, "page_size": 50},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_invalid_sort_dir_returns_422(self):
        resp = self.client.post(
            "/api/v1/reports/daily_revenue/execute",
            headers=_HEADERS,
            json={"params": {}, "sort_dir": "invalid"},
        )
        assert resp.status_code == 422

    def test_valid_sort_dir_asc(self):
        resp = self.client.post(
            "/api/v1/reports/daily_revenue/execute",
            headers=_HEADERS,
            json={"params": {}, "sort_by": "revenue_fen", "sort_dir": "asc"},
        )
        assert resp.status_code == 200

    def test_report_not_found_returns_404(self):
        _fake_engine_inst.execute_report = AsyncMock(
            side_effect=_ReportNotFoundError("not found")
        )
        resp = self.client.post(
            "/api/v1/reports/nonexistent/execute",
            headers=_HEADERS,
            json={"params": {}},
        )
        assert resp.status_code == 404
        _fake_engine_inst.execute_report = AsyncMock(return_value=_REPORT_RESULT_MOCK)

    def test_inactive_report_returns_403(self):
        _fake_engine_inst.execute_report = AsyncMock(
            side_effect=_ReportInactiveError("inactive")
        )
        resp = self.client.post(
            "/api/v1/reports/inactive_report/execute",
            headers=_HEADERS,
            json={"params": {}},
        )
        assert resp.status_code == 403
        _fake_engine_inst.execute_report = AsyncMock(return_value=_REPORT_RESULT_MOCK)


class TestReportExport:
    """GET /api/v1/reports/{report_id}/export"""

    def setup_method(self):
        self.client = _make_client(report_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get("/api/v1/reports/daily_revenue/export")
        assert resp.status_code == 400

    def test_csv_export_returns_200(self):
        resp = self.client.get(
            "/api/v1/reports/daily_revenue/export?format=csv",
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_csv_export_content_disposition(self):
        resp = self.client.get(
            "/api/v1/reports/daily_revenue/export?format=csv",
            headers=_HEADERS,
        )
        assert "daily_revenue.csv" in resp.headers.get("content-disposition", "")


class TestReportScheduleCreate:
    """POST /api/v1/reports/schedule"""

    def setup_method(self):
        self.client = _make_client(report_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.post(
            "/api/v1/reports/schedule",
            json={
                "report_id": "daily_revenue",
                "cron_expression": "0 8 * * *",
                "recipients": ["admin@example.com"],
            },
        )
        assert resp.status_code == 400

    def test_valid_schedule_returns_200(self):
        resp = self.client.post(
            "/api/v1/reports/schedule",
            headers=_HEADERS,
            json={
                "report_id": "daily_revenue",
                "cron_expression": "0 8 * * *",
                "recipients": ["admin@example.com"],
                "channel": "webhook",
                "export_format": "csv",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["schedule_id"] == "sch-001"

    def test_invalid_export_format_returns_422(self):
        resp = self.client.post(
            "/api/v1/reports/schedule",
            headers=_HEADERS,
            json={
                "report_id": "daily_revenue",
                "cron_expression": "0 8 * * *",
                "recipients": ["admin@example.com"],
                "export_format": "pdf",  # 不支持的格式
            },
        )
        assert resp.status_code == 422


class TestReportSchedulesList:
    """GET /api/v1/reports/schedules"""

    def setup_method(self):
        self.client = _make_client(report_router)

    def test_missing_tenant_returns_400(self):
        resp = self.client.get("/api/v1/reports/schedules")
        assert resp.status_code == 400

    def test_valid_request_returns_200(self):
        resp = self.client.get("/api/v1/reports/schedules", headers=_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]
        assert "total" in body["data"]
