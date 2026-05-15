"""CORS preflight 顺序验证测试

测试目标:
  T1 - OPTIONS preflight 不带 Authorization header，应返回 200/204（不被 Auth 拦截）
  T2 - 真实 GET 请求（非 OPTIONS）无认证信息，仍走 Auth 链，返回 401
"""

import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

# api_key_middleware.py 使用 dict | None 联合类型（Python 3.10+），本机 3.9 跳过
if sys.version_info < (3, 10):
    pytest.skip(
        "api_key_middleware 使用 dict | None 语法，需要 Python 3.10+，CI 环境（3.11）运行",
        allow_module_level=True,
    )

# 确保 gateway src 在 path 中
_gateway_src = os.path.join(os.path.dirname(__file__), "..", "src")
if _gateway_src not in sys.path:
    sys.path.insert(0, _gateway_src)


@pytest.fixture(autouse=True)
def cors_env(monkeypatch):
    """为所有测试注入安全 JWT 环境变量"""
    monkeypatch.setenv("TX_ENV", "test")
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("TX_AUTH_ENABLED", "true")
    monkeypatch.setenv("TX_JWT_SECRET_KEY", "x" * 64)
    monkeypatch.setenv("TX_JWT_ISSUER", "tunxiang-os-gateway")
    monkeypatch.setenv("TX_JWT_AUDIENCE", "tunxiang-os-api")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")


@pytest.fixture
def app():
    """构建带完整中间件链（含 CORS 最外层）的测试应用"""
    from middleware.api_key_middleware import ApiKeyMiddleware
    from middleware.auth_middleware import AuthMiddleware
    from middleware.domain_authz_middleware import DomainAuthzMiddleware
    from middleware.tenant_middleware import TenantMiddleware

    test_app = FastAPI()

    @test_app.api_route(
        "/api/v1/{domain}/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def fake_proxy(domain: str, path: str):
        return {"ok": True, "domain": domain, "path": path}

    # 中间件顺序与 main.py 对齐：CORS 最后 add = 最外层，OPTIONS preflight 直接响应。
    test_app.add_middleware(TenantMiddleware)
    test_app.add_middleware(DomainAuthzMiddleware)
    test_app.add_middleware(AuthMiddleware)
    test_app.add_middleware(ApiKeyMiddleware)
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return test_app


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ── T1: OPTIONS preflight 不带认证应直接返回，不被 Auth 拦截 ──────────


def test_options_preflight_no_auth_required(client):
    """OPTIONS preflight 不带 Authorization header，CORS 层直接 200/204 返回，不进认证链"""
    resp = client.options(
        "/api/v1/finance/reports",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    # CORSMiddleware 对合法 preflight 返回 200；不应返回 401/403
    assert resp.status_code in (200, 204), (
        f"OPTIONS preflight 应被 CORS 层直接响应，得到 {resp.status_code}。"
        "说明 CORSMiddleware 未在最外层，preflight 被 Auth 拦截了。"
    )


# ── T2: 真实 GET 请求无认证仍返回 401 ────────────────────────────────


def test_actual_get_still_requires_auth(client):
    """真实 GET 请求（非 OPTIONS）无认证信息，仍被 Auth 链拦截返回 401"""
    resp = client.get(
        "/api/v1/finance/reports",
        headers={"Origin": "http://localhost:5173"},
    )
    assert resp.status_code == 401, (
        f"无认证 GET 请求应返回 401，得到 {resp.status_code}。"
        "Auth 中间件可能被意外绕过。"
    )
