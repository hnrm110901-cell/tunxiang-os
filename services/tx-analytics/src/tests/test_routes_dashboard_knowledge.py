"""API 路由测试 — dashboard_routes + knowledge_query

覆盖端点：
  dashboard_routes (6 个):
    GET /api/v1/dashboard/today/{store_id}
    GET /api/v1/dashboard/stores
    GET /api/v1/dashboard/ranking
    GET /api/v1/dashboard/comparison
    GET /api/v1/dashboard/alerts/stats
    GET /api/v1/dashboard/alerts/{store_id}

  knowledge_query (5 个):
    POST /api/v1/knowledge/query
    GET  /api/v1/knowledge/graph/stats
    GET  /api/v1/knowledge/benchmarks/{metric}
    GET  /api/v1/knowledge/practices
    GET  /api/v1/knowledge/suggestions
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 预置假模块，阻断真实服务层导入 ───

def _make_async_service_mock(return_val):
    m = AsyncMock(return_value=return_val)
    return m


# Mock dashboard service modules before importing route
_fake_today_overview_mod = types.ModuleType("src.services.today_overview")
_fake_today_overview_mod.get_today_overview = AsyncMock(return_value={"revenue_fen": 100000, "order_count": 50})
_fake_today_overview_mod.get_multi_store_overview = AsyncMock(return_value=[{"store_id": "s1", "revenue_fen": 100000}])

_fake_store_ranking_mod = types.ModuleType("src.services.store_ranking")
_fake_store_ranking_mod.get_store_ranking = AsyncMock(return_value=[{"store_id": "s1", "rank": 1}])
_fake_store_ranking_mod.get_store_comparison = AsyncMock(return_value={"stores": []})

_fake_alert_summary_mod = types.ModuleType("src.services.alert_summary")
_fake_alert_summary_mod.get_today_alerts = AsyncMock(return_value=[])
_fake_alert_summary_mod.get_alert_stats = AsyncMock(return_value={"total": 0})

# knowledge_graph mock
_fake_kg_service = MagicMock()
_fake_nl_result = MagicMock()
_fake_nl_result.question = "翻台率多少？"
_fake_nl_result.answer = "平均翻台率3.2次"
_fake_nl_result.intent = MagicMock(
    intent_type="aggregate",
    entities={},
    metric="turnover_rate",
    aggregation="avg",
    time_range="month",
    filters={},
)
_fake_nl_result.data = {"value": 3.2}
_fake_nl_result.confidence = 0.92
_fake_nl_result.sources = []
_fake_nl_result.suggestions = []
_fake_nl_result.query_ms = 15.0

_fake_kg_service.query_natural_language = MagicMock(return_value=_fake_nl_result)
_fake_kg_service.generate_answer = MagicMock(return_value="表格格式答案")
_fake_kg_service.get_graph_stats = MagicMock(return_value={"entity_count": 100, "relation_count": 300})
_fake_kg_service.get_benchmark = MagicMock(return_value={"avg": 3.5, "top_10_pct": 5.0})
_fake_kg_service.get_applicable_practices = MagicMock(return_value=[])
_fake_kg_service.discover_best_practices = MagicMock(return_value=[{"id": "p1", "title": "提升翻台率"}])
_fake_kg_service._entities = {"best_practice": {"p1": {"id": "p1", "title": "实践1"}}}
_fake_kg_service.get_entity = MagicMock(return_value={"name": "旗舰店"})

_fake_knowledge_graph_mod = types.ModuleType("src.services.knowledge_graph")
_fake_knowledge_graph_mod.KnowledgeGraphService = MagicMock(return_value=_fake_kg_service)
_fake_knowledge_graph_mod.NLQueryResult = MagicMock
_fake_knowledge_graph_mod.seed_knowledge_graph = MagicMock(return_value=_fake_kg_service)


def _setup_sys_modules():
    """注入所有假模块，避免导入真实数据库/服务依赖"""
    # src package
    src_mod = sys.modules.setdefault("src", types.ModuleType("src"))

    # services sub-package
    svc_mod = types.ModuleType("src.services")
    sys.modules.setdefault("src.services", svc_mod)

    sys.modules["src.services.today_overview"] = _fake_today_overview_mod
    sys.modules["src.services.store_ranking"] = _fake_store_ranking_mod
    sys.modules["src.services.alert_summary"] = _fake_alert_summary_mod
    sys.modules["src.services.knowledge_graph"] = _fake_knowledge_graph_mod

    # api sub-package
    api_mod = types.ModuleType("src.api")
    sys.modules.setdefault("src.api", api_mod)


_setup_sys_modules()

# ─── 导入路由，构建 TestClient ───

import importlib
import os

# Add service root to sys.path so relative imports resolve
_svc_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _svc_root not in sys.path:
    sys.path.insert(0, _svc_root)

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Patch service functions at import time
with patch.dict(sys.modules, {
    "services.today_overview": _fake_today_overview_mod,
    "services.store_ranking": _fake_store_ranking_mod,
    "services.alert_summary": _fake_alert_summary_mod,
    "services.knowledge_graph": _fake_knowledge_graph_mod,
}):
    import api.dashboard_routes as _dashboard_mod
    import api.knowledge_query as _knowledge_mod

_app_dashboard = FastAPI()
_app_dashboard.include_router(_dashboard_mod.router)
_client_dash = TestClient(_app_dashboard)

_app_knowledge = FastAPI()
_app_knowledge.include_router(_knowledge_mod.router)
_client_kg = TestClient(_app_knowledge)

TENANT = "test-tenant"
HEADERS = {"X-Tenant-ID": TENANT}


# ═══════════════════════════════════════════════
# dashboard_routes 测试
# ═══════════════════════════════════════════════

class TestDashboardTodayOverview:
    def test_today_overview_success(self):
        """有效 tenant + store 返回 200 ok:True"""
        _fake_today_overview_mod.get_today_overview.return_value = {
            "revenue_fen": 80000,
            "order_count": 40,
        }
        resp = _client_dash.get("/api/v1/dashboard/today/store-abc", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "data" in body

    def test_today_overview_missing_tenant(self):
        """缺少 X-Tenant-ID 应返回 400"""
        resp = _client_dash.get("/api/v1/dashboard/today/store-abc")
        assert resp.status_code == 400

    def test_multi_store_overview_success(self):
        """多店概览正常返回"""
        resp = _client_dash.get("/api/v1/dashboard/stores", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_multi_store_overview_missing_tenant(self):
        """多店概览缺 header 返回 400"""
        resp = _client_dash.get("/api/v1/dashboard/stores")
        assert resp.status_code == 400


class TestDashboardRanking:
    def test_ranking_default_params(self):
        """默认参数门店排行正常返回"""
        _fake_store_ranking_mod.get_store_ranking.return_value = [
            {"store_id": "s1", "rank": 1, "metric_value": 100000}
        ]
        resp = _client_dash.get("/api/v1/dashboard/ranking", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_ranking_with_metric_param(self):
        """指定 metric 参数"""
        resp = _client_dash.get(
            "/api/v1/dashboard/ranking?metric=margin&date_range=week",
            headers=HEADERS,
        )
        assert resp.status_code == 200

    def test_ranking_missing_tenant(self):
        """缺 tenant 返回 400"""
        resp = _client_dash.get("/api/v1/dashboard/ranking")
        assert resp.status_code == 400

    def test_ranking_value_error_returns_422(self):
        """服务层抛 ValueError → HTTP 422"""
        _fake_store_ranking_mod.get_store_ranking.side_effect = ValueError("invalid metric")
        resp = _client_dash.get(
            "/api/v1/dashboard/ranking?metric=invalid", headers=HEADERS
        )
        assert resp.status_code == 422
        # restore
        _fake_store_ranking_mod.get_store_ranking.side_effect = None
        _fake_store_ranking_mod.get_store_ranking.return_value = []


class TestDashboardComparison:
    def test_comparison_success(self):
        """多店对比正常返回"""
        _fake_store_ranking_mod.get_store_comparison.return_value = {
            "stores": [{"store_id": "s1"}, {"store_id": "s2"}]
        }
        resp = _client_dash.get(
            "/api/v1/dashboard/comparison?store_ids=s1,s2&metrics=revenue",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_comparison_value_error_returns_422(self):
        """对比服务层 ValueError → 422"""
        _fake_store_ranking_mod.get_store_comparison.side_effect = ValueError("bad store")
        resp = _client_dash.get(
            "/api/v1/dashboard/comparison?store_ids=bad",
            headers=HEADERS,
        )
        assert resp.status_code == 422
        _fake_store_ranking_mod.get_store_comparison.side_effect = None
        _fake_store_ranking_mod.get_store_comparison.return_value = {"stores": []}


class TestDashboardAlerts:
    def test_alert_stats_success(self):
        """全租户告警统计正常"""
        resp = _client_dash.get("/api/v1/dashboard/alerts/stats", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_alert_stats_missing_tenant(self):
        """告警统计缺 tenant"""
        resp = _client_dash.get("/api/v1/dashboard/alerts/stats")
        assert resp.status_code == 400

    def test_store_alerts_success(self):
        """单店今日告警正常"""
        _fake_alert_summary_mod.get_today_alerts.return_value = [
            {"level": "warning", "message": "营收下降"}
        ]
        resp = _client_dash.get("/api/v1/dashboard/alerts/store-001", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_store_alerts_missing_tenant(self):
        """单店告警缺 tenant"""
        resp = _client_dash.get("/api/v1/dashboard/alerts/store-001")
        assert resp.status_code == 400


# ═══════════════════════════════════════════════
# knowledge_query 测试
# ═══════════════════════════════════════════════

class TestKnowledgeQuery:
    def test_query_success(self):
        """自然语言查询正常返回"""
        resp = _client_kg.post(
            "/api/v1/knowledge/query",
            json={"question": "翻台率多少？", "tenant_id": TENANT},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "data" in body
        assert "answer" in body["data"]

    def test_query_missing_question_returns_error(self):
        """缺少 question 字段返回 ok:False"""
        resp = _client_kg.post("/api/v1/knowledge/query", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "MISSING_QUESTION"

    def test_query_table_format(self):
        """format=table 触发 generate_answer"""
        resp = _client_kg.post(
            "/api/v1/knowledge/query",
            json={"question": "哪些门店人效最高？", "format": "table"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_graph_stats(self):
        """知识图谱统计信息"""
        resp = _client_kg.get("/api/v1/knowledge/graph/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "entity_count" in body["data"]

    def test_benchmarks_metric(self):
        """行业基准查询"""
        resp = _client_kg.get(
            "/api/v1/knowledge/benchmarks/turnover_rate?business_type=海鲜酒楼&city=长沙"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["metric"] == "turnover_rate"

    def test_benchmarks_no_filter(self):
        """基准无过滤参数"""
        resp = _client_kg.get("/api/v1/knowledge/benchmarks/avg_check")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_practices_by_metric(self):
        """按指标获取最佳实践"""
        resp = _client_kg.get("/api/v1/knowledge/practices?metric=turnover_rate")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "practices" in body["data"]

    def test_practices_by_store(self):
        """按门店获取最佳实践"""
        resp = _client_kg.get("/api/v1/knowledge/practices?store_id=store-001")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_practices_no_filter(self):
        """无过滤获取所有最佳实践"""
        resp = _client_kg.get("/api/v1/knowledge/practices")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert isinstance(body["data"]["practices"], list)

    def test_suggestions_general(self):
        """通用推荐问题列表"""
        resp = _client_kg.get("/api/v1/knowledge/suggestions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert len(body["data"]["general"]) > 0

    def test_suggestions_with_store(self):
        """带 store_id 的推荐问题"""
        resp = _client_kg.get("/api/v1/knowledge/suggestions?store_id=store-001")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "store_specific" in body["data"]
