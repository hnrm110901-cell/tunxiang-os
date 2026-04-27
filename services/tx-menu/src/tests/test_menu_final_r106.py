"""Round 106 — tx-menu 最终扫尾测试
涵盖端点最多的 3 个文件：
  - search_routes.py      (3 endpoints: GET /hot-keywords, GET /, POST /record)
  - publish.py            (4 endpoints: POST/GET publish-plans, POST/GET price-adjustments)
  - live_seafood_query_routes.py (2 endpoints: GET /tanks, GET /tanks/{zone_code}/dishes)
测试数量：≥ 12
"""

import sys
import types
import unittest.mock as _mock

# ── Mock structlog ────────────────────────────────────────────────────
_structlog = types.ModuleType("structlog")
_structlog.get_logger = lambda *a, **kw: _mock.MagicMock()
sys.modules.setdefault("structlog", _structlog)


# ── Mock shared.ontology.src.database ────────────────────────────────
async def _fake_get_db():
    yield None


_shared = types.ModuleType("shared")
_shared_onto = types.ModuleType("shared.ontology")
_shared_onto_src = types.ModuleType("shared.ontology.src")
_shared_onto_src_db = types.ModuleType("shared.ontology.src.database")
_shared_onto_src_db.get_db = _fake_get_db
sys.modules.setdefault("shared", _shared)
sys.modules.setdefault("shared.ontology", _shared_onto)
sys.modules.setdefault("shared.ontology.src", _shared_onto_src)
sys.modules.setdefault("shared.ontology.src.database", _shared_onto_src_db)

# ── Mock publish_service for publish.py ──────────────────────────────
_src_pkg = types.ModuleType("src")
_src_svc = types.ModuleType("src.services")
_pub_svc = types.ModuleType("src.services.publish_service")


def _fake_create_publish_plan(plan_name, dish_ids, target_store_ids, schedule_time=None):
    return {
        "plan_id": "plan-001",
        "plan_name": plan_name,
        "dish_ids": dish_ids,
        "target_store_ids": target_store_ids,
        "schedule_time": schedule_time,
        "status": "pending",
    }


def _fake_execute_publish(plan_id, dish_data, target_stores):
    return {"plan_id": plan_id, "published_count": len(target_stores), "status": "published"}


def _fake_create_price_adjustment(store_id, adjustment_type, rules):
    return {
        "adjustment_id": "adj-001",
        "store_id": store_id,
        "adjustment_type": adjustment_type,
        "rules": rules,
    }


_pub_svc.create_publish_plan = _fake_create_publish_plan
_pub_svc.execute_publish = _fake_execute_publish
_pub_svc.create_price_adjustment = _fake_create_price_adjustment
sys.modules.setdefault("src", _src_pkg)
sys.modules.setdefault("src.services", _src_svc)
sys.modules.setdefault("src.services.publish_service", _pub_svc)

import importlib.util
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

MENU_SRC = pathlib.Path(__file__).parent.parent

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
STORE_ID = "store-001"


def _load_module(rel_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, str(MENU_SRC / rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ════════════════════════════════════════════════════════════════════
# PART A — search_routes.py  (3 endpoints)
# ════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def search_client():
    mod = _load_module("api/search_routes.py", "search_routes")
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app, raise_server_exceptions=False)


class TestSearchRoutes:
    """search_routes.py — 3 端点全覆盖"""

    def test_hot_keywords_missing_tenant(self, search_client):
        """缺少 X-Tenant-ID header → 422"""
        r = search_client.get("/api/v1/menu/search/hot-keywords")
        assert r.status_code == 422

    def test_hot_keywords_db_fallback(self, search_client):
        """DB不可用时应降级返回空列表，ok=True"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("db error"))

        async def fake_get_db():
            yield mock_db

        with patch.object(sys.modules["shared.ontology.src.database"], "get_db", fake_get_db):
            r = search_client.get(
                "/api/v1/menu/search/hot-keywords",
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["items"] == []
        assert body["data"].get("_fallback") is True

    def test_search_dishes_missing_tenant(self, search_client):
        """缺少 X-Tenant-ID + q → 422"""
        r = search_client.get("/api/v1/menu/search", params={"q": "鱼"})
        assert r.status_code == 422

    def test_search_dishes_missing_query(self, search_client):
        """缺少 q 参数 → 422"""
        r = search_client.get(
            "/api/v1/menu/search",
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert r.status_code == 422

    def test_search_dishes_db_fallback(self, search_client):
        """DB不可用时应降级返回空列表"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("db error"))

        async def fake_get_db():
            yield mock_db

        with patch.object(sys.modules["shared.ontology.src.database"], "get_db", fake_get_db):
            r = search_client.get(
                "/api/v1/menu/search",
                params={"q": "海鲜"},
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["query"] == "海鲜"
        assert body["data"]["items"] == []
        assert body["data"].get("_fallback") is True

    def test_record_search_missing_tenant(self, search_client):
        """缺少 X-Tenant-ID → 422"""
        r = search_client.post(
            "/api/v1/menu/search/record",
            json={"keyword": "鱼", "source": "pos"},
        )
        assert r.status_code == 422

    def test_record_search_db_fallback(self, search_client):
        """DB不可用时静默降级，recorded=False"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("db error"))

        async def fake_get_db():
            yield mock_db

        with patch.object(sys.modules["shared.ontology.src.database"], "get_db", fake_get_db):
            r = search_client.post(
                "/api/v1/menu/search/record",
                json={"keyword": "清蒸鱼", "source": "miniapp"},
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["keyword"] == "清蒸鱼"
        assert body["data"]["recorded"] is False


# ════════════════════════════════════════════════════════════════════
# PART B — publish.py  (4 endpoints)
# ════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def publish_client():
    mod = _load_module("api/publish.py", "publish_routes")
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app, raise_server_exceptions=False)


class TestPublishRoutes:
    """publish.py — 4 端点全覆盖"""

    def test_create_publish_plan_success(self, publish_client):
        payload = {
            "plan_name": "春季菜单发布",
            "dish_ids": ["dish-001", "dish-002"],
            "target_store_ids": ["store-001", "store-002"],
        }
        r = publish_client.post("/api/v1/menu/publish-plans", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["plan_name"] == "春季菜单发布"
        assert body["data"]["plan_id"] == "plan-001"

    def test_create_publish_plan_with_schedule(self, publish_client):
        payload = {
            "plan_name": "定时发布方案",
            "dish_ids": ["dish-003"],
            "target_store_ids": ["store-003"],
            "schedule_time": "2026-05-01T10:00:00",
        }
        r = publish_client.post("/api/v1/menu/publish-plans", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["schedule_time"] == "2026-05-01T10:00:00"

    def test_execute_publish_plan(self, publish_client):
        # 先创建一个方案
        publish_client.post(
            "/api/v1/menu/publish-plans",
            json={"plan_name": "执行测试", "dish_ids": ["d1"], "target_store_ids": ["s1"]},
        )
        payload = {
            "dish_data": [{"id": "dish-001", "name": "清蒸鱼"}],
            "target_stores": ["store-001"],
        }
        r = publish_client.post("/api/v1/menu/publish-plans/plan-001/execute", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "published"

    def test_list_publish_plans(self, publish_client):
        r = publish_client.get("/api/v1/menu/publish-plans")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "items" in body["data"]
        assert "total" in body["data"]

    def test_create_price_adjustment_success(self, publish_client):
        payload = {
            "store_id": STORE_ID,
            "adjustment_type": "percentage",
            "rules": [{"condition": "weekend", "price_modifier": 10, "description": "周末加价10%"}],
        }
        r = publish_client.post("/api/v1/menu/price-adjustments", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["store_id"] == STORE_ID
        assert body["data"]["adjustment_type"] == "percentage"

    def test_list_price_adjustments(self, publish_client):
        r = publish_client.get("/api/v1/menu/price-adjustments")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "items" in body["data"]

    def test_list_price_adjustments_by_store_filter(self, publish_client):
        r = publish_client.get(
            "/api/v1/menu/price-adjustments",
            params={"store_id": STORE_ID},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        # 只返回指定门店的
        for item in body["data"]["items"]:
            assert item["store_id"] == STORE_ID


# ════════════════════════════════════════════════════════════════════
# PART C — live_seafood_query_routes.py  (2 endpoints)
# ════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def seafood_query_client():
    mod = _load_module("api/live_seafood_query_routes.py", "live_seafood_query_routes")
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app, raise_server_exceptions=False)


class TestLiveSeafoodQueryRoutes:
    """live_seafood_query_routes.py — 2 端点覆盖"""

    def test_list_tanks_missing_tenant(self, seafood_query_client):
        """缺少 X-Tenant-ID → 400"""
        r = seafood_query_client.get(
            "/api/v1/live-seafood/tanks",
            params={"store_id": STORE_ID},
        )
        assert r.status_code == 400

    def test_list_tanks_db_error_returns_empty(self, seafood_query_client):
        """DB错误时降级返回空列表，ok=True"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("db down"))

        async def fake_get_db():
            yield mock_db

        with patch.object(sys.modules["shared.ontology.src.database"], "get_db", fake_get_db):
            r = seafood_query_client.get(
                "/api/v1/live-seafood/tanks",
                params={"store_id": STORE_ID},
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["tanks"] == []

    def test_list_tank_dishes_missing_tenant(self, seafood_query_client):
        """缺少 X-Tenant-ID → 400"""
        r = seafood_query_client.get(
            "/api/v1/live-seafood/tanks/A1/dishes",
            params={"store_id": STORE_ID},
        )
        assert r.status_code == 400

    def test_list_tank_dishes_zone_not_found(self, seafood_query_client):
        """鱼缸不存在 → 404"""
        mock_db = AsyncMock()

        # zone query returns None
        async def _execute(sql, params=None):
            result = MagicMock()
            result.fetchone = MagicMock(return_value=None)
            return result

        mock_db.execute = _execute

        async def fake_get_db():
            yield mock_db

        with patch.object(sys.modules["shared.ontology.src.database"], "get_db", fake_get_db):
            r = seafood_query_client.get(
                "/api/v1/live-seafood/tanks/NOTEXIST/dishes",
                params={"store_id": STORE_ID},
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert r.status_code == 404
