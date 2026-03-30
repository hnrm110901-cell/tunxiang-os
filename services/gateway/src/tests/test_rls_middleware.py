"""RLS 安全中间件测试 — 验证 Phase 0 CRITICAL 修复

测试 TenantMiddleware 的安全行为：
- 无 X-Tenant-ID 的业务请求被拒绝 (403)
- 非法格式的 X-Tenant-ID 被拒绝 (400)
- 合法 UUID 的 X-Tenant-ID 通过
- 白名单路径（/health, /docs, /api/v1/auth/）免检
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from middleware import TenantMiddleware

VALID_TENANT = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


def _create_test_app():
    app = FastAPI()
    app.add_middleware(TenantMiddleware)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/docs")
    async def docs():
        return {"ok": True}

    @app.get("/api/v1/auth/login")
    async def auth_login():
        return {"ok": True}

    @app.get("/api/v1/trade/orders")
    async def list_orders(request: Request):
        return {"ok": True, "tenant_id": request.state.tenant_id}

    @app.get("/api/v1/menu/dishes")
    async def list_dishes(request: Request):
        return {"ok": True, "tenant_id": request.state.tenant_id}

    return app


@pytest.fixture
def client():
    return TestClient(_create_test_app())


class TestTenantMiddlewareSecurity:
    """CRITICAL-002 修复验证：无 tenant_id 的请求必须被拒绝"""

    def test_missing_tenant_id_returns_403(self, client):
        resp = client.get("/api/v1/trade/orders")
        assert resp.status_code == 403
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "MISSING_TENANT"

    def test_empty_tenant_id_returns_403(self, client):
        resp = client.get("/api/v1/trade/orders", headers={"X-Tenant-ID": ""})
        assert resp.status_code == 403

    def test_invalid_uuid_returns_400(self, client):
        resp = client.get("/api/v1/trade/orders", headers={"X-Tenant-ID": "not-a-uuid"})
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["code"] == "INVALID_TENANT"

    def test_valid_tenant_id_passes(self, client):
        resp = client.get(
            "/api/v1/trade/orders", headers={"X-Tenant-ID": VALID_TENANT}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["tenant_id"] == VALID_TENANT

    def test_valid_tenant_on_another_route(self, client):
        resp = client.get(
            "/api/v1/menu/dishes", headers={"X-Tenant-ID": VALID_TENANT}
        )
        assert resp.status_code == 200


class TestTenantExemptPaths:
    """白名单路径免检验证"""

    def test_health_no_tenant_required(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_docs_no_tenant_required(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_auth_no_tenant_required(self, client):
        resp = client.get("/api/v1/auth/login")
        assert resp.status_code == 200


class TestDatabaseTenantValidation:
    """database.py _validate_tenant_id 单元测试"""

    def test_none_raises(self):
        from shared.ontology.src.database import _validate_tenant_id
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_tenant_id(None)

    def test_empty_string_raises(self):
        from shared.ontology.src.database import _validate_tenant_id
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_tenant_id("")

    def test_whitespace_only_raises(self):
        from shared.ontology.src.database import _validate_tenant_id
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_tenant_id("   ")

    def test_invalid_uuid_raises(self):
        from shared.ontology.src.database import _validate_tenant_id
        with pytest.raises(ValueError, match="valid UUID"):
            _validate_tenant_id("not-a-uuid-at-all")

    def test_valid_uuid_passes(self):
        from shared.ontology.src.database import _validate_tenant_id
        result = _validate_tenant_id(VALID_TENANT)
        assert result == VALID_TENANT
