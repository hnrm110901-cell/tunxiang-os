"""API 路由测试 — realtime_routes + daily_report_routes

覆盖端点：
  realtime_routes (4 个):
    GET /api/v1/analytics/realtime/today
    GET /api/v1/analytics/realtime/hourly-trend
    GET /api/v1/analytics/realtime/store-comparison
    GET /api/v1/analytics/realtime/alerts

  daily_report_routes (4 个):
    GET  /api/v1/analytics/daily-reports
    GET  /api/v1/analytics/daily-reports/summary
    GET  /api/v1/analytics/daily-reports/{date}
    POST /api/v1/analytics/daily-reports/generate
"""

import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

# ─── Mock shared.ontology 数据库模块 ───


def _build_mapping_result(rows):
    """构造模拟 mappings().all() / mappings().one() / scalar() 返回"""
    mapping_mock = MagicMock()
    mapping_mock.all.return_value = rows
    if rows:
        mapping_mock.one.return_value = rows[0]
    else:
        mapping_mock.one.return_value = {}
    result_mock = MagicMock()
    result_mock.mappings.return_value = mapping_mock
    result_mock.scalar.return_value = 0
    return result_mock


def _make_fake_session():
    """构造可作为 async context manager 使用的假 session"""
    session = MagicMock()
    session.execute = AsyncMock()
    return session


# shared.ontology 模块树
_shared_mod = types.ModuleType("shared")
_shared_ontology_mod = types.ModuleType("shared.ontology")
_shared_ontology_src_mod = types.ModuleType("shared.ontology.src")
_shared_database_mod = types.ModuleType("shared.ontology.src.database")

# async_session_factory 返回一个异步上下文管理器
_fake_session = _make_fake_session()


class _FakeSessionCM:
    async def __aenter__(self):
        return _fake_session

    async def __aexit__(self, *args):
        pass


_shared_database_mod.async_session_factory = MagicMock(return_value=_FakeSessionCM())

sys.modules.setdefault("shared", _shared_mod)
sys.modules.setdefault("shared.ontology", _shared_ontology_mod)
sys.modules.setdefault("shared.ontology.src", _shared_ontology_src_mod)
sys.modules["shared.ontology.src.database"] = _shared_database_mod

# structlog mock
if "structlog" not in sys.modules:
    _structlog_mod = types.ModuleType("structlog")
    _fake_logger = MagicMock()
    _structlog_mod.get_logger = MagicMock(return_value=_fake_logger)
    sys.modules["structlog"] = _structlog_mod

import os

_svc_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _svc_root not in sys.path:
    sys.path.insert(0, _svc_root)

import api.daily_report_routes as _daily_mod
import api.realtime_routes as _realtime_mod
from fastapi import FastAPI
from fastapi.testclient import TestClient

_app_rt = FastAPI()
_app_rt.include_router(_realtime_mod.router)
_client_rt = TestClient(_app_rt, raise_server_exceptions=False)

_app_dr = FastAPI()
_app_dr.include_router(_daily_mod.router)
_client_dr = TestClient(_app_dr, raise_server_exceptions=False)

TENANT = "test-tenant"
HEADERS = {"X-Tenant-ID": TENANT}


def _configure_session_for_realtime_today():
    """为 realtime today 端点配置 session.execute 返回"""
    summary_row = {
        "revenue_fen": 50000,
        "order_count": 25,
        "refund_fen": 1000,
        "refund_count": 1,
    }
    new_members_result = MagicMock()
    new_members_result.scalar.return_value = 3

    top_dishes_rows = [{"item_name": "剁椒鱼头", "cnt": 15}]
    top_dishes_result = _build_mapping_result(top_dishes_rows)

    summary_result = _build_mapping_result([summary_row])

    # set_config call, summary, new_members, top_dishes
    _fake_session.execute.side_effect = [
        _build_mapping_result([]),  # set_config
        summary_result,  # main summary
        new_members_result,  # new members scalar
        top_dishes_result,  # top dishes
    ]


def _configure_session_for_hourly():
    rows = [{"hour": 11, "revenue_fen": 20000, "order_count": 10}]
    _fake_session.execute.side_effect = [
        _build_mapping_result([]),  # set_config
        _build_mapping_result(rows),  # hourly trend rows
    ]


def _configure_session_for_store_comparison():
    rows = [{"store_name": "旗舰店", "revenue_fen": 80000, "order_count": 40}]
    _fake_session.execute.side_effect = [
        _build_mapping_result([]),  # set_config
        _build_mapping_result(rows),  # stores
    ]


def _configure_session_for_alerts():
    rows = [
        {
            "level": "warning",
            "type": "revenue_drop",
            "message": "营收下降10%",
            "store_name": "旗舰店",
            "at": datetime(2026, 4, 6, 10, 0, 0, tzinfo=timezone.utc),
        }
    ]
    _fake_session.execute.side_effect = [
        _build_mapping_result([]),  # set_config
        _build_mapping_result(rows),  # alerts
    ]


def _configure_session_for_daily_list():
    """list_daily_reports - 每次 _query_daily_report 做 4 次 execute"""

    def _make_daily_row():
        core = _build_mapping_result(
            [
                {
                    "order_count": 30,
                    "revenue_fen": 60000,
                    "store_count": 2,
                }
            ]
        )
        pay = _build_mapping_result([{"method": "wechat", "amount_fen": 60000}])
        channel = _build_mapping_result([{"channel": "dine_in", "amount_fen": 60000}])
        mem = MagicMock()
        mem.scalar.return_value = 5
        return [_build_mapping_result([]), core, pay, channel, mem]

    # set_config + one day × 4
    _fake_session.execute.side_effect = [_build_mapping_result([])] + _make_daily_row()


def _configure_session_for_daily_summary():
    summary_row = {"total_orders": 150, "total_revenue_fen": 300000}
    mem = MagicMock()
    mem.scalar.return_value = 20
    _fake_session.execute.side_effect = [
        _build_mapping_result([]),  # set_config
        _build_mapping_result([summary_row]),  # summary
        mem,  # new_members scalar
    ]


def _configure_session_for_daily_get():
    """get_daily_report: set_config + 4 queries"""
    core = _build_mapping_result([{"order_count": 20, "revenue_fen": 40000, "store_count": 1}])
    pay = _build_mapping_result([{"method": "alipay", "amount_fen": 40000}])
    channel = _build_mapping_result([{"channel": "takeaway", "amount_fen": 40000}])
    mem = MagicMock()
    mem.scalar.return_value = 2
    _fake_session.execute.side_effect = [_build_mapping_result([]), core, pay, channel, mem]


# ═══════════════════════════════════════════════
# realtime_routes 测试
# ═══════════════════════════════════════════════


class TestRealtimeToday:
    def setup_method(self):
        _shared_database_mod.async_session_factory.return_value = _FakeSessionCM()

    def test_today_success(self):
        """正常返回当日实时数据"""
        _configure_session_for_realtime_today()
        resp = _client_rt.get("/api/v1/analytics/realtime/today", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "data" in body

    def test_today_with_store_id(self):
        """指定 store_id 过滤"""
        _configure_session_for_realtime_today()
        resp = _client_rt.get(
            "/api/v1/analytics/realtime/today?store_id=store-001",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_today_db_error_graceful(self):
        """DB 抛异常时容错返回空结构"""
        from sqlalchemy.exc import SQLAlchemyError

        _fake_session.execute.side_effect = SQLAlchemyError("connection failed")
        resp = _client_rt.get("/api/v1/analytics/realtime/today", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"].get("_error") == "db_unavailable"

    def test_today_default_tenant(self):
        """不传 X-Tenant-ID 使用默认 demo-tenant"""
        _configure_session_for_realtime_today()
        resp = _client_rt.get("/api/v1/analytics/realtime/today")
        assert resp.status_code == 200


class TestRealtimeHourlyTrend:
    def setup_method(self):
        _shared_database_mod.async_session_factory.return_value = _FakeSessionCM()

    def test_hourly_trend_success(self):
        """今日每小时趋势正常返回"""
        _configure_session_for_hourly()
        resp = _client_rt.get("/api/v1/analytics/realtime/hourly-trend", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "hours" in body["data"]

    def test_hourly_trend_db_error_graceful(self):
        """DB 错误容错"""
        from sqlalchemy.exc import SQLAlchemyError

        _fake_session.execute.side_effect = SQLAlchemyError("timeout")
        resp = _client_rt.get("/api/v1/analytics/realtime/hourly-trend", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"].get("_error") == "db_unavailable"


class TestRealtimeStoreComparison:
    def setup_method(self):
        _shared_database_mod.async_session_factory.return_value = _FakeSessionCM()

    def test_store_comparison_success(self):
        """多店实时对比正常返回"""
        _configure_session_for_store_comparison()
        resp = _client_rt.get("/api/v1/analytics/realtime/store-comparison", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "stores" in body["data"]

    def test_store_comparison_db_error(self):
        """容错测试"""
        from sqlalchemy.exc import SQLAlchemyError

        _fake_session.execute.side_effect = SQLAlchemyError("err")
        resp = _client_rt.get("/api/v1/analytics/realtime/store-comparison", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"].get("_error") == "db_unavailable"


class TestRealtimeAlerts:
    def setup_method(self):
        _shared_database_mod.async_session_factory.return_value = _FakeSessionCM()

    def test_alerts_success(self):
        """实时告警正常返回"""
        _configure_session_for_alerts()
        resp = _client_rt.get("/api/v1/analytics/realtime/alerts", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "alerts" in body["data"]

    def test_alerts_db_error(self):
        """alerts 表不存在时容错"""
        from sqlalchemy.exc import SQLAlchemyError

        _fake_session.execute.side_effect = SQLAlchemyError("table not found")
        resp = _client_rt.get("/api/v1/analytics/realtime/alerts", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"].get("_error") == "db_unavailable"


# ═══════════════════════════════════════════════
# daily_report_routes 测试
# ═══════════════════════════════════════════════


class TestDailyReportList:
    def setup_method(self):
        _shared_database_mod.async_session_factory.return_value = _FakeSessionCM()

    def test_list_default_range(self):
        """默认7天日报列表"""
        _configure_session_for_daily_list()
        resp = _client_dr.get("/api/v1/analytics/daily-reports", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]

    def test_list_invalid_date_range(self):
        """start > end 返回 400"""
        resp = _client_dr.get(
            "/api/v1/analytics/daily-reports?start_date=2026-04-06&end_date=2026-04-01",
            headers=HEADERS,
        )
        assert resp.status_code == 400

    def test_list_db_error_graceful(self):
        """DB 错误容错"""
        from sqlalchemy.exc import SQLAlchemyError

        _fake_session.execute.side_effect = SQLAlchemyError("db error")
        resp = _client_dr.get("/api/v1/analytics/daily-reports", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["_error"] == "db_unavailable"


class TestDailyReportSummary:
    def setup_method(self):
        _shared_database_mod.async_session_factory.return_value = _FakeSessionCM()

    def test_summary_week_dimension(self):
        """周维度汇总"""
        _configure_session_for_daily_summary()
        resp = _client_dr.get(
            "/api/v1/analytics/daily-reports/summary?dimension=week",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["dimension"] == "week"

    def test_summary_month_dimension(self):
        """月维度汇总"""
        _configure_session_for_daily_summary()
        resp = _client_dr.get(
            "/api/v1/analytics/daily-reports/summary?dimension=month",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["dimension"] == "month"

    def test_summary_db_error(self):
        """汇总 DB 错误容错"""
        from sqlalchemy.exc import SQLAlchemyError

        _fake_session.execute.side_effect = SQLAlchemyError("timeout")
        resp = _client_dr.get(
            "/api/v1/analytics/daily-reports/summary",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["_error"] == "db_unavailable"


class TestDailyReportGet:
    def setup_method(self):
        _shared_database_mod.async_session_factory.return_value = _FakeSessionCM()

    def test_get_past_date(self):
        """查询历史日报正常"""
        _configure_session_for_daily_get()
        resp = _client_dr.get(
            "/api/v1/analytics/daily-reports/2026-04-05",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "report_date" in body["data"]

    def test_get_future_date_returns_400(self):
        """查询未来日期返回 400"""
        resp = _client_dr.get(
            "/api/v1/analytics/daily-reports/2099-12-31",
            headers=HEADERS,
        )
        assert resp.status_code == 400

    def test_get_db_error_graceful(self):
        """单日报表 DB 错误容错"""
        from sqlalchemy.exc import SQLAlchemyError

        _fake_session.execute.side_effect = SQLAlchemyError("err")
        resp = _client_dr.get(
            "/api/v1/analytics/daily-reports/2026-04-05",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["_error"] == "db_unavailable"


class TestDailyReportGenerate:
    def test_generate_yesterday(self):
        """手动触发生成，默认昨天，立即返回 completed"""
        resp = _client_dr.post(
            "/api/v1/analytics/daily-reports/generate",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "completed"

    def test_generate_specific_date(self):
        """指定历史日期生成"""
        resp = _client_dr.post(
            "/api/v1/analytics/daily-reports/generate?report_date=2026-04-01",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["report_date"] == "2026-04-01"

    def test_generate_future_date_returns_400(self):
        """生成未来日期返回 400"""
        resp = _client_dr.post(
            "/api/v1/analytics/daily-reports/generate?report_date=2099-01-01",
            headers=HEADERS,
        )
        assert resp.status_code == 400
