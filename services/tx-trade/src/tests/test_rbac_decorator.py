"""test_rbac_decorator — tx-trade 内部 RBAC 装饰器单元测试

覆盖 src.security.rbac 的 4 条契约：
  1. 无 JWT / 无 state.user_id → 401 AUTH_MISSING
  2. role 匹配允许列表 → 通过，返回 UserContext
  3. role 不在允许列表 → 403 ROLE_FORBIDDEN
  4. require_mfa 且 mfa_verified=False → 403 MFA_REQUIRED

强制 TX_AUTH_ENABLED=true，因为 rbac.py 在 false 时会走 dev bypass，
绕过测试覆盖的拦截分支。其他集成/路由测试在 TX_AUTH_ENABLED=false 下运行。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.security.rbac import (
    UserContext,
    extract_user_context,
    require_mfa,
    require_role,
)


@pytest.fixture(autouse=True)
def _force_auth_enabled(monkeypatch):
    """每个测试用例强制 TX_AUTH_ENABLED=true，确保 dev bypass 不生效。"""
    monkeypatch.setenv("TX_AUTH_ENABLED", "true")


def _mk_request(
    *,
    user_id: str | None = "u-1",
    tenant_id: str = "t-1",
    role: str = "cashier",
    mfa_verified: bool = False,
    client_ip: str = "127.0.0.1",
    store_id: str | None = None,
):
    state = SimpleNamespace(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        mfa_verified=mfa_verified,
        store_id=store_id,
    )
    client = SimpleNamespace(host=client_ip)
    headers = {}
    return SimpleNamespace(
        state=state,
        client=client,
        headers=headers,
        url=SimpleNamespace(path="/api/v1/test"),
    )


@pytest.mark.asyncio
async def test_require_role_missing_auth_raises_401():
    req = _mk_request(user_id=None)
    dep = require_role("cashier")
    with pytest.raises(HTTPException) as ei:
        await dep(req)
    assert ei.value.status_code == 401
    assert ei.value.detail == "AUTH_MISSING"


@pytest.mark.asyncio
async def test_require_role_allowed_returns_user_context():
    req = _mk_request(role="cashier")
    dep = require_role("cashier", "store_manager")
    result = await dep(req)
    assert isinstance(result, UserContext)
    assert result.role == "cashier"
    assert result.user_id == "u-1"


@pytest.mark.asyncio
async def test_require_role_denied_raises_403_role_forbidden():
    req = _mk_request(role="waiter")
    dep = require_role("cashier", "store_manager", "admin")
    with pytest.raises(HTTPException) as ei:
        await dep(req)
    assert ei.value.status_code == 403
    assert ei.value.detail == "ROLE_FORBIDDEN"


@pytest.mark.asyncio
async def test_require_mfa_not_verified_raises_403_mfa_required():
    req = _mk_request(role="store_manager", mfa_verified=False)
    dep = require_mfa("store_manager", "admin")
    with pytest.raises(HTTPException) as ei:
        await dep(req)
    assert ei.value.status_code == 403
    assert ei.value.detail == "MFA_REQUIRED"


def test_extract_user_context_populates_client_ip_and_fields():
    req = _mk_request(client_ip="10.0.0.5", store_id="s-9", mfa_verified=True)
    ctx = extract_user_context(req)
    assert ctx.user_id == "u-1"
    assert ctx.tenant_id == "t-1"
    assert ctx.role == "cashier"
    assert ctx.store_id == "s-9"
    assert ctx.client_ip == "10.0.0.5"
    assert ctx.mfa_verified is True
