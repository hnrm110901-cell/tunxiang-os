"""A1 授权加固回归测试

测试目标:
  T1 - 无 JWT 访问业务 API 必须返回 401
  T2 - 随便传 X-API-Key 不能绕过 JWT
  T3 - 普通角色不能访问 finance 高危域（DomainAuthzMiddleware）
  T4 - API Key 必须校验格式（ApiKeyMiddleware 注册）
  T5 - 高危操作必须 MFA
  T6 - JWT 必须校验 iss/aud/type
  T7 - 生产环境缺少 TX_JWT_SECRET_KEY 必须启动失败
  T8 - 正常登录/刷新/普通 API 不能被误杀
"""

import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# 确保 gateway src 在 path 中
_gateway_src = os.path.join(os.path.dirname(__file__), "..", "src")
if _gateway_src not in sys.path:
    sys.path.insert(0, _gateway_src)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    """为所有测试注入安全 JWT 环境变量"""
    monkeypatch.setenv("TX_ENV", "test")
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("TX_AUTH_ENABLED", "true")
    monkeypatch.setenv("TX_JWT_SECRET_KEY", "x" * 64)
    monkeypatch.setenv("TX_JWT_ISSUER", "tunxiang-os-gateway")
    monkeypatch.setenv("TX_JWT_AUDIENCE", "tunxiang-os-api")


@pytest.fixture
def app():
    """构建最小 Gateway 测试应用（完整中间件链）"""
    from middleware.api_key_middleware import ApiKeyMiddleware
    from middleware.auth_middleware import AuthMiddleware
    from middleware.domain_authz_middleware import DomainAuthzMiddleware
    from middleware.tenant_middleware import TenantMiddleware

    app = FastAPI()

    # 模拟代理通配路由
    @app.api_route(
        "/api/v1/{domain}/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )
    async def fake_proxy(domain: str, path: str):
        return {"ok": True, "domain": domain, "path": path}

    # 模拟 auth 路由（白名单）
    @app.post("/api/v1/auth/login")
    async def fake_login():
        return {"ok": True, "data": {"token": "fake"}}

    @app.post("/api/v1/auth/refresh")
    async def fake_refresh():
        return {"ok": True, "data": {"token": "fake"}}

    @app.get("/health")
    async def fake_health():
        return {"ok": True}

    # 中间件顺序：后 add 的先执行。
    # 请求流: ApiKey → Auth → DomainAuthz → Tenant → Route
    app.add_middleware(TenantMiddleware)
    app.add_middleware(DomainAuthzMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(ApiKeyMiddleware)

    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def _make_token(role="tenant_owner", tenant_id="a0000000-0000-0000-0000-000000000001", mfa=False):
    """签发测试用 access token"""
    from services.jwt_service import JWTService

    return JWTService().create_access_token(
        user_id="u-test",
        tenant_id=tenant_id,
        role=role,
        mfa_verified=mfa,
    )


# ── T1: 无 JWT 访问业务 API 必须返回 401 ─────────────────────────────

def test_t1_missing_jwt_returns_401(client):
    """无任何认证信息访问业务 API → 401"""
    resp = client.get("/api/v1/finance/reports")
    assert resp.status_code == 401


def test_t1_missing_jwt_post_returns_401(client):
    """无认证 POST 业务 API → 401"""
    resp = client.post("/api/v1/finance/splits/execute")
    assert resp.status_code == 401


# ── T2: 随便传 X-API-Key 不能绕过 JWT ────────────────────────────────

def test_t2_random_api_key_without_tenant_returns_401(client):
    """随机 X-API-Key 无 X-Tenant-ID → 401（格式校验失败）"""
    resp = client.get(
        "/api/v1/finance/reports",
        headers={"X-API-Key": "anything"},
    )
    # "anything" 不匹配 txapp_/txat_ 前缀 → ApiKeyMiddleware 返回 401
    assert resp.status_code == 401


def test_t2_random_api_key_with_tenant_blocked(client):
    """随机 X-API-Key + X-Tenant-ID → 401（api_key_pending 已修复）"""
    resp = client.get(
        "/api/v1/finance/reports",
        headers={
            "X-API-Key": "anything",
            "X-Tenant-ID": "a0000000-0000-0000-0000-000000000001",
        },
    )
    # 绝对不能是 200 — 修复后 api_key_pending 不再绕过
    assert resp.status_code != 200, (
        f"BYPASS STILL ACTIVE! Got {resp.status_code}: {resp.json()}"
    )
    # 格式不对的 key → ApiKeyMiddleware 返回 401
    assert resp.status_code == 401


def test_t2_api_key_wrong_format_returns_401(client):
    """错误格式的 X-API-Key → 401（格式校验）"""
    resp = client.get(
        "/api/v1/finance/reports",
        headers={
            "X-API-Key": "wrong-format-key",
            "X-Tenant-ID": "a0000000-0000-0000-0000-000000000001",
        },
    )
    assert resp.status_code == 401


# ── T3: 普通角色不能访问 finance 高危域 ───────────────────────────────

def test_t3_cashier_access_finance_blocked(client):
    """收银员访问 finance 域 → 403（DomainAuthzMiddleware）"""
    token = _make_token(role="cashier")
    resp = client.get(
        "/api/v1/finance/reports",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "RBAC_DENIED"


def test_t3_cashier_access_trade_allowed(client):
    """收银员访问 trade 域 → 200"""
    token = _make_token(role="cashier")
    resp = client.get(
        "/api/v1/trade/orders",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


# ── T4: API Key 必须校验格式 ──────────────────────────────────────────

def test_t4_api_key_format_enforced(client):
    """ApiKeyMiddleware 拒绝错误格式的 key"""
    resp = client.get(
        "/api/v1/trade/orders",
        headers={
            "X-API-Key": "bad-format",
            "X-Tenant-ID": "a0000000-0000-0000-0000-000000000001",
        },
    )
    assert resp.status_code == 401


# ── T5: 高危操作必须 MFA ─────────────────────────────────────────────

def test_t5_finance_split_no_mfa_blocked(client):
    """无 MFA 执行分账 → 403 MFA_REQUIRED"""
    token = _make_token(role="finance_staff", mfa=False)
    resp = client.post(
        "/api/v1/finance/splits/execute",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "MFA_REQUIRED"


def test_t5_finance_split_with_mfa(client):
    """有 MFA 执行分账 → 200"""
    token = _make_token(role="tenant_owner", mfa=True)
    resp = client.post(
        "/api/v1/finance/splits/execute",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


@pytest.mark.parametrize("mfa_path,role", [
    ("/api/v1/finance/refunds/123", "finance_staff"),
    ("/api/v1/ops/daily-settlement/close", "store_manager"),
    ("/api/v1/org/salary/compute", "tenant_admin"),
    ("/api/v1/analytics/export/report", "tenant_owner"),
    ("/api/v1/member/export/csv", "tenant_owner"),
])
def test_t5_mfa_required_paths_blocked_without_mfa(client, mfa_path, role):
    """所有 MFA 路径在无 MFA 时返回 403"""
    token = _make_token(role=role, mfa=False)
    resp = client.post(
        mfa_path,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "MFA_REQUIRED"


# ── T6: JWT 必须校验 iss/aud/type ────────────────────────────────────

def test_t6_refresh_token_used_as_access_blocked():
    """refresh token 不能当作 access token 使用"""
    from services.jwt_service import JWTService

    svc = JWTService()
    refresh_token, _ = svc.create_refresh_token("u-test")
    result = svc.verify_access_token(refresh_token)

    assert result is None, "verify_access_token must reject refresh tokens"


def test_t6_jwt_wrong_issuer_rejected():
    """iss 不匹配的 JWT 应被拒绝"""
    import uuid
    from datetime import datetime, timedelta, timezone

    import jwt as pyjwt

    from services.jwt_service import JWTService

    svc = JWTService()

    payload = {
        "iss": "wrong-issuer",
        "type": "access",
        "sub": "u-test",
        "tenant_id": "a0000000-0000-0000-0000-000000000001",
        "role": "tenant_owner",
        "jti": str(uuid.uuid4()),
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
    }
    bad_token = pyjwt.encode(payload, "x" * 64, algorithm="HS256")
    result = svc.verify_access_token(bad_token)

    assert result is None, (
        "verify_access_token must reject tokens with mismatched iss claim"
    )


def test_t6_jwt_wrong_audience_rejected():
    """aud 不匹配的 JWT 应被拒绝"""
    import uuid
    from datetime import datetime, timedelta, timezone

    import jwt as pyjwt

    from services.jwt_service import JWTService

    svc = JWTService()

    payload = {
        "type": "access",
        "sub": "u-test",
        "tenant_id": "a0000000-0000-0000-0000-000000000001",
        "role": "tenant_owner",
        "jti": str(uuid.uuid4()),
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        "iss": "tunxiang-os-gateway",         # 正确的 iss
        "aud": "wrong-audience",               # 不匹配 TX_JWT_AUDIENCE
    }
    bad_token = pyjwt.encode(payload, "x" * 64, algorithm="HS256")
    result = svc.verify_access_token(bad_token)

    assert result is None, (
        "verify_access_token must reject tokens with mismatched aud claim"
    )


# ── T7: 生产环境缺少 TX_JWT_SECRET_KEY 必须启动失败 ──────────────────

def test_t7_prod_without_jwt_secret_raises(monkeypatch):
    """生产环境缺少密钥 → RuntimeError"""
    monkeypatch.setenv("TX_ENV", "production")
    monkeypatch.delenv("TX_JWT_SECRET_KEY", raising=False)

    from services.jwt_service import JWTService

    with pytest.raises(RuntimeError, match="TX_JWT_SECRET_KEY is required"):
        JWTService()


def test_t7_dev_without_jwt_secret_uses_fallback(monkeypatch):
    """开发环境缺少密钥 → 使用 fallback 不崩溃"""
    monkeypatch.setenv("TX_ENV", "development")
    monkeypatch.delenv("TX_JWT_SECRET_KEY", raising=False)

    from services.jwt_service import JWTService

    svc = JWTService()
    assert svc._secret is not None


# ── T8: 正常登录/刷新/普通 API 不能被误杀 ─────────────────────────────

def test_t8_health_endpoint_no_auth(client):
    """健康检查端点免认证"""
    resp = client.get("/health")
    assert resp.status_code == 200


def test_t8_auth_login_no_auth(client):
    """登录端点免认证"""
    resp = client.post("/api/v1/auth/login")
    assert resp.status_code == 200


def test_t8_auth_refresh_no_auth(client):
    """刷新 token 端点免认证"""
    resp = client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200


def test_t8_normal_api_with_valid_token(client):
    """合法 token 访问普通 API → 200"""
    token = _make_token(role="tenant_owner")
    resp = client.get(
        "/api/v1/trade/orders",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


def test_t8_expired_token_returns_401(client):
    """过期 token → 401"""
    from datetime import datetime, timedelta, timezone

    import jwt as pyjwt

    payload = {
        "sub": "u-test",
        "tenant_id": "a0000000-0000-0000-0000-000000000001",
        "role": "tenant_owner",
        "jti": "expired-jti",
        "iat": datetime.now(timezone.utc) - timedelta(hours=1),
        "exp": datetime.now(timezone.utc) - timedelta(minutes=30),
    }
    expired_token = pyjwt.encode(payload, "x" * 64, algorithm="HS256")

    resp = client.get(
        "/api/v1/trade/orders",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp.status_code == 401
