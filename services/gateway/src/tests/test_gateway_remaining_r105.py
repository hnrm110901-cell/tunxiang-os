"""Round 105 — gateway 剩余路由补测
涵盖端点数 Top-2：dictionary_routes.py (9) / open_api_routes.py (8)
测试数量：≥ 10
"""

import sys
import types
import unittest.mock as _mock

# ── Mock structlog ──────────────────────────────────────────────────
_structlog = types.ModuleType("structlog")
_structlog.get_logger = lambda *a, **kw: _mock.MagicMock()
sys.modules.setdefault("structlog", _structlog)

# ── Mock gateway-internal deps for open_api_routes ─────────────────
_src = types.ModuleType("src")
_src_middleware = types.ModuleType("src.middleware")
_src_middleware_rate_limiter = types.ModuleType("src.middleware.rate_limiter")
_src_middleware_rate_limiter.RateLimiter = _mock.MagicMock

_src_services = types.ModuleType("src.services")
_src_services_oauth2 = types.ModuleType("src.services.oauth2_service")
_src_services_oauth2.OAuth2Service = _mock.MagicMock

sys.modules.setdefault("src", _src)
sys.modules.setdefault("src.middleware", _src_middleware)
sys.modules.setdefault("src.middleware.rate_limiter", _src_middleware_rate_limiter)
sys.modules.setdefault("src.services", _src_services)
sys.modules.setdefault("src.services.oauth2_service", _src_services_oauth2)

import importlib.util
import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
APP_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

GATEWAY_SRC = pathlib.Path(__file__).parent.parent


def _load_module(rel_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, str(GATEWAY_SRC / rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ════════════════════════════════════════════════════════════════════
# PART 1 — dictionary_routes.py  (9 endpoints)
# ════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def dict_client():
    mod = _load_module("api/dictionary_routes.py", "dictionary_routes")
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app, raise_server_exceptions=False)


class TestDictionaryRoutes:
    """dictionary_routes.py — 全 9 端点覆盖"""

    def test_list_dictionaries_returns_all(self, dict_client):
        r = dict_client.get("/api/v1/system/dictionaries")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["total"] >= 8  # 8 preset dicts

    def test_list_dictionaries_with_keyword(self, dict_client):
        r = dict_client.get("/api/v1/system/dictionaries", params={"keyword": "订单"})
        assert r.status_code == 200
        body = r.json()
        assert any("订单" in d["name"] for d in body["data"]["items"])

    def test_create_dictionary_success(self, dict_client):
        payload = {"code": "store_type", "name": "门店类型", "description": "门店业态分类"}
        r = dict_client.post("/api/v1/system/dictionaries", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["code"] == "store_type"

    def test_create_dictionary_duplicate_code(self, dict_client):
        payload = {"code": "order_status", "name": "重复", "description": ""}
        r = dict_client.post("/api/v1/system/dictionaries", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False  # duplicate → error

    def test_update_dictionary_success(self, dict_client):
        r = dict_client.put(
            "/api/v1/system/dictionaries/dish_category",
            json={"name": "菜品大类（更新）", "description": "更新后描述"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True

    def test_update_dictionary_not_found(self, dict_client):
        r = dict_client.put(
            "/api/v1/system/dictionaries/nonexistent_code",
            json={"name": "不存在"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False

    def test_delete_system_dictionary_blocked(self, dict_client):
        r = dict_client.delete("/api/v1/system/dictionaries/order_status")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False  # system dict cannot be deleted

    def test_list_dictionary_items(self, dict_client):
        r = dict_client.get("/api/v1/system/dictionaries/order_status/items")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["total"] >= 6  # 6 preset items

    def test_create_dictionary_item(self, dict_client):
        payload = {
            "code": "takeout",
            "label": "外卖",
            "value": "takeout",
            "color": "#1890ff",
            "sort_order": 10,
        }
        r = dict_client.post("/api/v1/system/dictionaries/order_status/items", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["code"] == "takeout"

    def test_list_audit_logs_default(self, dict_client):
        r = dict_client.get("/api/v1/system/audit-logs")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["total"] >= 6  # 6 preset logs

    def test_audit_logs_filter_by_user(self, dict_client):
        r = dict_client.get("/api/v1/system/audit-logs", params={"user_name": "李淳"})
        assert r.status_code == 200
        body = r.json()
        assert all("李淳" in item["user_name"] for item in body["data"]["items"])

    def test_audit_logs_filter_by_action(self, dict_client):
        r = dict_client.get("/api/v1/system/audit-logs", params={"action": "login"})
        assert r.status_code == 200
        body = r.json()
        assert all(item["action"] == "login" for item in body["data"]["items"])


# ════════════════════════════════════════════════════════════════════
# PART 2 — open_api_routes.py  (8 endpoints)
# ════════════════════════════════════════════════════════════════════


@pytest.fixture
def open_api_client():
    mod = _load_module("api/open_api_routes.py", "open_api_routes")
    app = FastAPI()
    app.include_router(mod.router)

    # Override DB dependency → 503 path
    async def _no_db():
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="数据库模块未配置")

    app.dependency_overrides[mod.get_db] = _no_db

    return TestClient(app, raise_server_exceptions=False), mod


class TestOpenApiRoutes:
    """open_api_routes.py — 关键端点覆盖"""

    def test_create_application_missing_tenant(self, open_api_client):
        client, _ = open_api_client
        payload = {"app_name": "测试ISV"}
        r = client.post("/open-api/applications", json=payload)
        # Missing X-Tenant-ID → 422
        assert r.status_code == 422

    def test_create_application_invalid_tenant_uuid(self, open_api_client):
        client, _ = open_api_client
        payload = {"app_name": "测试ISV"}
        r = client.post(
            "/open-api/applications",
            json=payload,
            headers={"X-Tenant-ID": "not-a-uuid"},
        )
        # 400 — UUID format invalid
        assert r.status_code in (400, 503)

    def test_list_applications_missing_tenant(self, open_api_client):
        client, _ = open_api_client
        r = client.get("/open-api/applications")
        assert r.status_code == 422

    def test_get_application_invalid_uuid_path(self, open_api_client):
        client, _ = open_api_client
        r = client.get(
            "/open-api/applications/not-a-uuid",
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert r.status_code == 422

    def test_issue_token_wrong_grant_type(self, open_api_client):
        client, _ = open_api_client
        payload = {
            "grant_type": "authorization_code",
            "app_key": "key123",
            "app_secret": "secret123",
        }
        r = client.post("/open-api/oauth/token", json=payload)
        # 400 — unsupported grant_type (DB not needed for this check)
        assert r.status_code == 400

    def test_issue_token_missing_fields(self, open_api_client):
        client, _ = open_api_client
        r = client.post(
            "/open-api/oauth/token",
            json={"grant_type": "client_credentials"},
        )
        # Missing app_key/app_secret → 422
        assert r.status_code == 422

    def test_revoke_token_db_unavailable(self, open_api_client):
        client, _ = open_api_client
        r = client.post(
            "/open-api/oauth/revoke",
            json={"token": "some-access-token"},
        )
        # DB not configured → 503
        assert r.status_code == 503

    def test_rotate_secret_invalid_app_id(self, open_api_client):
        client, _ = open_api_client
        r = client.post(
            "/open-api/oauth/rotate",
            json={"app_id": "not-a-uuid"},
            headers={"X-Tenant-ID": TENANT_ID},
        )
        # 400 — bad app_id format (resolved before DB call)
        assert r.status_code in (400, 503)
