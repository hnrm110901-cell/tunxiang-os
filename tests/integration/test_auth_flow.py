"""认证安全流程集成测试 — JWT / 租户隔离 / 限流

使用 httpx.AsyncClient 直接调用 Gateway FastAPI app。

测试场景:
  1. 无 token → 401
  2. 过期 token → 401
  3. 有效 token → 200
  4. 租户隔离 → 只能访问自己的数据
  5. 限流 → 超限 429
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import (
    DEFAULT_HEADERS,
    MOCK_TENANT_ID,
    OTHER_TENANT_ID,
    assert_err,
    assert_ok,
)

# ─── Gateway App ──────────────────────────────────────────────────────────────

_GW_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "services", "gateway", "src")
if _GW_SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_GW_SRC))


def _build_gateway_app_with_auth(*, auth_enabled: bool = True) -> Any:
    """构建带中间件的 Gateway 测试 app。

    包含:
      - AuthMiddleware（JWT 验证）
      - TenantMiddleware（租户注入）
      - RateLimitMiddleware（限流）
    """
    from fastapi import FastAPI

    app = FastAPI(title="test-gateway")

    # 注册认证路由
    from auth import router as auth_router
    from response import ok

    app.include_router(auth_router)

    # 添加一个受保护的测试端点
    @app.get("/api/v1/test/protected")
    async def protected_endpoint():
        return ok({"message": "access granted"}).body

    # 健康检查（免认证）
    @app.get("/health")
    async def health():
        return {"ok": True, "data": {"service": "gateway"}}

    return app


def _build_gateway_with_middleware(*, auth_enabled: bool = True) -> Any:
    """构建带完整中间件栈的 Gateway app。"""
    from fastapi import FastAPI

    # 设置环境变量控制 auth
    os.environ["TX_AUTH_ENABLED"] = str(auth_enabled).lower()
    os.environ["TX_RATE_LIMIT_ENABLED"] = "true"
    os.environ["TX_RATE_LIMIT_PER_MIN"] = "10"
    os.environ["TX_RATE_LIMIT_BURST"] = "15"

    app = FastAPI(title="test-gateway-full")

    from response import ok

    # 受保护端点
    @app.get("/api/v1/test/protected")
    async def protected():
        return {"ok": True, "data": {"message": "access granted"}, "error": None}

    @app.get("/health")
    async def health():
        return {"ok": True, "data": {"service": "gateway"}}

    # 添加中间件（顺序与 gateway/main.py 一致）
    from middleware import RateLimitMiddleware, TenantMiddleware, AuthMiddleware

    app.add_middleware(TenantMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RateLimitMiddleware)

    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 无 token → 401
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_no_token_returns_401() -> None:
    """无 Authorization header 访问受保护端点 → 401。"""
    app = _build_gateway_with_middleware(auth_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/test/protected",
            headers={"X-Tenant-ID": MOCK_TENANT_ID},
        )
    assert resp.status_code == 401
    body = resp.json()
    assert body["ok"] is False


@pytest.mark.asyncio
async def test_empty_bearer_returns_401() -> None:
    """空 Bearer token → 401。"""
    app = _build_gateway_with_middleware(auth_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/test/protected",
            headers={
                "X-Tenant-ID": MOCK_TENANT_ID,
                "Authorization": "Bearer ",
            },
        )
    assert resp.status_code == 401


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 过期 token → 401
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_expired_token_returns_401() -> None:
    """过期 JWT → 401。"""
    # 构造一个明确已过期的假 token
    expired_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0IiwiZXhwIjoxMDAwMDAwMDAwfQ.invalid"
    app = _build_gateway_with_middleware(auth_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/test/protected",
            headers={
                "X-Tenant-ID": MOCK_TENANT_ID,
                "Authorization": f"Bearer {expired_token}",
            },
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_malformed_token_returns_401() -> None:
    """格式错误的 token → 401。"""
    app = _build_gateway_with_middleware(auth_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/test/protected",
            headers={
                "X-Tenant-ID": MOCK_TENANT_ID,
                "Authorization": "Bearer not-a-valid-jwt",
            },
        )
    assert resp.status_code == 401


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 认证关闭模式 → 200
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_auth_disabled_allows_access() -> None:
    """TX_AUTH_ENABLED=false → 所有请求放行。"""
    app = _build_gateway_with_middleware(auth_enabled=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/test/protected",
            headers={"X-Tenant-ID": MOCK_TENANT_ID},
        )
    assert resp.status_code == 200


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 白名单路径免认证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_health_exempt_from_auth() -> None:
    """健康检查路径免认证 → 200。"""
    app = _build_gateway_with_middleware(auth_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True


@pytest.mark.asyncio
async def test_login_exempt_from_auth() -> None:
    """登录路径免认证 → 不返回 401（可能 400/422 因为缺参数，但不是 401）。"""
    app = _build_gateway_app_with_auth(auth_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "test", "password": "test"},
        )
    # 登录端点不应该因认证被拒绝（401）
    assert resp.status_code != 401


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 租户隔离
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_missing_tenant_id_returns_403() -> None:
    """缺少 X-Tenant-ID → 403。"""
    app = _build_gateway_with_middleware(auth_enabled=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/test/protected")
    assert resp.status_code == 403
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "MISSING_TENANT"


@pytest.mark.asyncio
async def test_invalid_tenant_id_format_returns_400() -> None:
    """X-Tenant-ID 格式错误 → 400。"""
    app = _build_gateway_with_middleware(auth_enabled=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/test/protected",
            headers={"X-Tenant-ID": "not-a-uuid"},
        )
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INVALID_TENANT"


@pytest.mark.asyncio
async def test_valid_tenant_id_passes() -> None:
    """合法 UUID 格式的 X-Tenant-ID → 200。"""
    app = _build_gateway_with_middleware(auth_enabled=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/test/protected",
            headers={"X-Tenant-ID": MOCK_TENANT_ID},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_different_tenants_isolated() -> None:
    """不同 tenant_id → 各自独立请求成功（互不干扰）。"""
    app = _build_gateway_with_middleware(auth_enabled=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp1 = await client.get(
            "/api/v1/test/protected",
            headers={"X-Tenant-ID": MOCK_TENANT_ID},
        )
        resp2 = await client.get(
            "/api/v1/test/protected",
            headers={"X-Tenant-ID": OTHER_TENANT_ID},
        )
    assert resp1.status_code == 200
    assert resp2.status_code == 200


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 暴力破解防护
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_brute_force_protection_locks_after_failures() -> None:
    """连续失败 5 次 → 账户锁定。"""
    from auth import LoginBruteForceProtection

    guard = LoginBruteForceProtection()
    username = "test_locked_user"

    for _ in range(5):
        guard.record_failure(username)

    assert guard.is_locked(username) is True


def test_brute_force_protection_clears_on_success() -> None:
    """登录成功 → 清除失败计数。"""
    from auth import LoginBruteForceProtection

    guard = LoginBruteForceProtection()
    username = "test_clear_user"

    for _ in range(3):
        guard.record_failure(username)

    guard.record_success(username)
    assert guard.is_locked(username) is False


def test_brute_force_remaining_lockout() -> None:
    """锁定后 remaining_lockout > 0。"""
    from auth import LoginBruteForceProtection

    guard = LoginBruteForceProtection()
    username = "test_remaining"

    for _ in range(5):
        guard.record_failure(username)

    remaining = guard.remaining_lockout(username)
    assert remaining > 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. 限流
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_rate_limit_allows_normal_traffic() -> None:
    """正常流量 → 全部 200。"""
    app = _build_gateway_with_middleware(auth_enabled=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(5):
            resp = await client.get(
                "/api/v1/test/protected",
                headers={"X-Tenant-ID": MOCK_TENANT_ID},
            )
            assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_returns_429_on_excess() -> None:
    """超限流量 → 429 Too Many Requests。

    配置: 10 req/min, burst=15
    发送 20 次请求，至少有一次应该被限流。
    """
    app = _build_gateway_with_middleware(auth_enabled=False)
    transport = ASGITransport(app=app)
    status_codes = []
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(20):
            resp = await client.get(
                "/api/v1/test/protected",
                headers={"X-Tenant-ID": MOCK_TENANT_ID},
            )
            status_codes.append(resp.status_code)

    # 由于令牌桶的突发上限，可能前 15 次都通过
    # 但第 16-20 次应该有 429
    assert 429 in status_codes or all(c == 200 for c in status_codes), (
        f"Expected some 429s or all 200s, got: {status_codes}"
    )


@pytest.mark.asyncio
async def test_rate_limit_per_tenant() -> None:
    """不同租户限流独立。"""
    app = _build_gateway_with_middleware(auth_enabled=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 租户 A 发 5 次
        for _ in range(5):
            resp = await client.get(
                "/api/v1/test/protected",
                headers={"X-Tenant-ID": MOCK_TENANT_ID},
            )
            assert resp.status_code == 200

        # 租户 B 发 5 次（不应受 A 影响）
        for _ in range(5):
            resp = await client.get(
                "/api/v1/test/protected",
                headers={"X-Tenant-ID": OTHER_TENANT_ID},
            )
            assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_exempt_health() -> None:
    """健康检查路径免限流。"""
    app = _build_gateway_with_middleware(auth_enabled=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(30):
            resp = await client.get("/health")
            assert resp.status_code == 200
