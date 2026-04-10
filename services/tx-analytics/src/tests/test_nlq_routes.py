"""自然语言问数（NLQ）路由测试

覆盖端点：
  POST /api/v1/nlq/query       — 正常请求 / 空 query
  GET  /api/v1/nlq/suggestions — 返回 6 条建议
  GET  /api/v1/nlq/history     — 返回空列表
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock

# ─── 预置假模块 ───

def _make_db_module():
    mod = types.ModuleType("shared.ontology.src.database")

    async def _fake_get_db_with_tenant(tenant_id: str):
        session = AsyncMock()
        session.execute.return_value.fetchall.return_value = []
        session.commit = AsyncMock()
        yield session

    mod.get_db_with_tenant = _fake_get_db_with_tenant
    return mod


def _setup_sys_modules():
    for name in ["shared", "shared.ontology", "shared.ontology.src"]:
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["shared.ontology.src.database"] = _make_db_module()

    if "structlog" not in sys.modules:
        sl = types.ModuleType("structlog")
        sl.get_logger = MagicMock(return_value=MagicMock(
            warning=MagicMock(), info=MagicMock(),
        ))
        sys.modules["structlog"] = sl


_setup_sys_modules()

# ─── 导入路由 ───
import os

_svc_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _svc_root not in sys.path:
    sys.path.insert(0, _svc_root)

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.nlq_routes as _nlq_mod

_app = FastAPI()
_app.include_router(_nlq_mod.router)
_client = TestClient(_app)

TENANT = "test-tenant-analytics"
HEADERS = {"X-Tenant-ID": TENANT}


# ═══════════════════════════════════════
# POST /api/v1/nlq/query
# ═══════════════════════════════════════

class TestNLQQuery:
    def test_normal_query_returns_ok_true(self):
        """正常问题返回 ok:True"""
        resp = _client.post(
            "/api/v1/nlq/query",
            json={"query": "今天各门店营业额对比"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_normal_query_returns_data_query(self):
        """返回 data.query 与请求一致"""
        question = "本周翻台率最高的门店"
        resp = _client.post(
            "/api/v1/nlq/query",
            json={"query": question},
            headers=HEADERS,
        )
        body = resp.json()
        assert body["data"]["query"] == question

    def test_normal_query_contains_required_fields(self):
        """data 包含 intent, sql, columns, rows, chart_type, summary"""
        resp = _client.post(
            "/api/v1/nlq/query",
            json={"query": "毛利率低于30%的菜品有哪些"},
            headers=HEADERS,
        )
        data = resp.json()["data"]
        for field in ["intent", "sql", "columns", "rows", "chart_type", "summary", "generated_at"]:
            assert field in data, f"缺少字段: {field}"

    def test_empty_query_returns_ok_false(self):
        """空字符串 query 返回 ok:False"""
        resp = _client.post(
            "/api/v1/nlq/query",
            json={"query": ""},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False

    def test_whitespace_only_query_returns_ok_false(self):
        """纯空白 query 返回 ok:False"""
        resp = _client.post(
            "/api/v1/nlq/query",
            json={"query": "   "},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is False

    def test_x_tenant_id_header_present(self):
        """带 X-Tenant-ID header 正常响应"""
        resp = _client.post(
            "/api/v1/nlq/query",
            json={"query": "测试问题"},
            headers=HEADERS,
        )
        assert resp.status_code == 200

    def test_query_with_optional_store_id(self):
        """携带可选 store_id 也正常工作"""
        resp = _client.post(
            "/api/v1/nlq/query",
            json={"query": "今日营业额", "store_id": "store-001"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_query_with_date_range(self):
        """携带 date_range 正常工作"""
        resp = _client.post(
            "/api/v1/nlq/query",
            json={
                "query": "本周收入",
                "date_range": {"start": "2026-03-31", "end": "2026-04-06"},
            },
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ═══════════════════════════════════════
# GET /api/v1/nlq/suggestions
# ═══════════════════════════════════════

class TestNLQSuggestions:
    def test_returns_ok_true(self):
        """返回 ok:True"""
        resp = _client.get("/api/v1/nlq/suggestions", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_returns_six_suggestions(self):
        """返回恰好 6 条建议"""
        resp = _client.get("/api/v1/nlq/suggestions", headers=HEADERS)
        data = resp.json()["data"]
        assert len(data) == 6

    def test_suggestions_have_id_and_text(self):
        """每条建议含 id 和 text 字段"""
        resp = _client.get("/api/v1/nlq/suggestions", headers=HEADERS)
        for item in resp.json()["data"]:
            assert "id" in item
            assert "text" in item
            assert "category" in item

    def test_x_tenant_id_header_present(self):
        """带 X-Tenant-ID header 正常响应"""
        resp = _client.get("/api/v1/nlq/suggestions", headers=HEADERS)
        assert resp.status_code == 200


# ═══════════════════════════════════════
# GET /api/v1/nlq/history
# ═══════════════════════════════════════

class TestNLQHistory:
    def test_returns_ok_true(self):
        """返回 ok:True"""
        resp = _client.get("/api/v1/nlq/history", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_returns_empty_list(self):
        """Phase 1 返回空列表"""
        resp = _client.get("/api/v1/nlq/history", headers=HEADERS)
        body = resp.json()
        assert body["data"] == []
        assert body["total"] == 0

    def test_x_tenant_id_header_present(self):
        """带 X-Tenant-ID header 正常响应"""
        resp = _client.get("/api/v1/nlq/history", headers=HEADERS)
        assert resp.status_code == 200
