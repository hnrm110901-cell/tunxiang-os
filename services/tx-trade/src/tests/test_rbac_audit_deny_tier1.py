"""Tier 1 — Sprint A4 R-补1-1 RBAC deny 审计装饰器（徐记海鲜场景）

§19 独立审查发现：tx-trade 9 路由的 require_role / require_mfa 装饰器
**只在 allow 路径写审计**，cashier 被 403 拒绝时 trade_audit_logs 无记录。
本测试验证修复包：require_role_audited / require_mfa_audited 在拒绝路径
**先写 deny 审计再抛 HTTPException**，且响应形状与状态码完全等价 require_role。

7 条徐记场景：
  1. 收银员小王试图 /refund → 403 + audit deny + reason=ROLE_FORBIDDEN
  2. 店长李姐改高额折扣未 MFA → 403 + audit deny + severity=error
  3. 401 AUTH_MISSING 路径 user_id="(unauthenticated)" 仍能写一条
  4. dev_bypass 模式（TX_AUTH_ENABLED=false）短路通过，**不写** deny 审计
  5. allow 路径不污染 idx_trade_audit_deny（不调用 audit_deny）
  6. audit_deny 内部抛错时不影响 403 抛出（审计绝不阻塞业务）
  7. cross-tenant probe 场景：长沙 cashier 探韶山 order，severity 升级 error
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

# 强制非 dev_bypass 路径
os.environ["TX_AUTH_ENABLED"] = "true"

from src.security import rbac  # noqa: E402
from src.security.rbac import (  # noqa: E402
    require_mfa_audited,
    require_role_audited,
)

# ──────────────── 租户 / 用户常量 ────────────────

XUJI_CHANGSHA_TENANT = "00000000-0000-0000-0000-0000000000a1"
XUJI_SHAOSHAN_TENANT = "00000000-0000-0000-0000-0000000000b1"
XUJI_CHANGSHA_STORE = "00000000-0000-0000-0000-0000000000a2"
CASHIER_XIAOWANG_ID = "00000000-0000-0000-0000-000000000011"
MANAGER_LIJIE_ID = "00000000-0000-0000-0000-000000000012"


@pytest.fixture(autouse=True)
def _force_auth_enabled(monkeypatch):
    monkeypatch.setenv("TX_AUTH_ENABLED", "true")


def _mk_request(
    *,
    user_id: str | None,
    tenant_id: str,
    role: str,
    mfa_verified: bool = False,
    store_id: str | None = XUJI_CHANGSHA_STORE,
    client_ip: str = "10.0.0.5",
    path: str = "/api/v1/trade/orders/O-1/refund",
    request_id: str = "req-xj-001",
):
    state = SimpleNamespace(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        mfa_verified=mfa_verified,
        store_id=store_id,
    )
    client = SimpleNamespace(host=client_ip)
    return SimpleNamespace(
        state=state,
        client=client,
        headers={"X-Request-Id": request_id},
        url=SimpleNamespace(path=path),
    )


@pytest.fixture
def stub_db():
    """伪 db 对象 — _audit_deny_safe 内部 await write_audit 时会调到 .execute / .commit。"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.fixture
def captured_deny_calls(monkeypatch):
    """拦截 _audit_deny_safe 调用，捕获其参数。

    返回一个 list，每个元素是一份 audit_deny 的 kwargs 副本。
    """
    captured: list[dict] = []

    async def _fake_audit_deny_safe(**kwargs):
        captured.append(dict(kwargs))

    # _audit_deny_safe 接受 **kwargs，monkeypatch 包装让它捕获参数
    def _shim(**kwargs):
        return _fake_audit_deny_safe(**kwargs)

    monkeypatch.setattr(rbac, "_audit_deny_safe", _shim)
    return captured


# ──────────────────────────────────────────────────────────────────────────
# 场景 1：收银员小王 refund → 403 + audit deny
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_xujihaixian_cashier_refund_403_writes_deny_audit(stub_db, captured_deny_calls):
    """徐记河西店收银员小王调 /refund → require_role_audited("refund.apply", "store_manager", "admin")
    必须在抛 403 之前写一条 trade_audit_logs result=deny reason=ROLE_FORBIDDEN。
    """
    dep = require_role_audited(
        "refund.apply", "store_manager", "admin", db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=CASHIER_XIAOWANG_ID,
        tenant_id=XUJI_CHANGSHA_TENANT,
        role="cashier",
    )

    with pytest.raises(HTTPException) as ei:
        await dep(req, db=stub_db)
    assert ei.value.status_code == 403
    assert ei.value.detail == "ROLE_FORBIDDEN"

    # 关键断言：拒绝前已写一条 deny 审计
    assert len(captured_deny_calls) == 1
    call = captured_deny_calls[0]
    assert call["action"] == "refund.apply"
    assert call["tenant_id"] == XUJI_CHANGSHA_TENANT
    assert call["user_id"] == CASHIER_XIAOWANG_ID
    assert call["user_role"] == "cashier"
    assert call["reason"] == "ROLE_FORBIDDEN"
    assert call["severity"] == "warn"
    assert call["client_ip"] == "10.0.0.5"
    assert call["request_id"] == "req-xj-001"


# ──────────────────────────────────────────────────────────────────────────
# 场景 2：店长李姐高额折扣 MFA 缺失 → 403 + severity=error
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_xujihaixian_manager_discount_no_mfa_writes_deny_with_error_severity(
    stub_db, captured_deny_calls,
):
    """徐记河西店店长李姐对 ¥500 订单打 35% 折（高于 30% 阈值），未 MFA。
    require_mfa_audited 必须默认 severity='error'（高敏感场景）。
    """
    dep = require_mfa_audited(
        "discount.apply.over_threshold", "store_manager", "admin",
        db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=MANAGER_LIJIE_ID,
        tenant_id=XUJI_CHANGSHA_TENANT,
        role="store_manager",
        mfa_verified=False,
    )

    with pytest.raises(HTTPException) as ei:
        await dep(req, db=stub_db)
    assert ei.value.status_code == 403
    assert ei.value.detail == "MFA_REQUIRED"

    assert len(captured_deny_calls) == 1
    call = captured_deny_calls[0]
    assert call["action"] == "discount.apply.over_threshold"
    assert call["user_id"] == MANAGER_LIJIE_ID
    assert call["user_role"] == "store_manager"
    assert call["reason"] == "MFA_REQUIRED"
    # 关键：MFA 路径默认 severity=error（比 role-only 的 warn 高一档）
    assert call["severity"] == "error"


# ──────────────────────────────────────────────────────────────────────────
# 场景 3：401 AUTH_MISSING — 即使没 user_id 也能写一条
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unauthenticated_request_still_writes_deny_audit(stub_db, captured_deny_calls):
    """无 JWT 的攻击/扫描请求 → 401 AUTH_MISSING。安全审计场景必须留痕。"""
    dep = require_role_audited(
        "refund.apply", "store_manager", "admin", db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=None,  # 未认证
        tenant_id=XUJI_CHANGSHA_TENANT,  # tenant 来自 header（可能是攻击者伪造）
        role="",
    )

    with pytest.raises(HTTPException) as ei:
        await dep(req, db=stub_db)
    assert ei.value.status_code == 401
    assert ei.value.detail == "AUTH_MISSING"

    assert len(captured_deny_calls) == 1
    call = captured_deny_calls[0]
    # extract_user_context 在 user_id 为 None 时返回空串，audit_deny 内部把空串
    # 转成 "(unauthenticated)" — 我们这里用 stub 拦截，所以传入仍是空串
    assert call["user_id"] == ""
    assert call["reason"] == "AUTH_MISSING"


# ──────────────────────────────────────────────────────────────────────────
# 场景 4：dev_bypass — 单测/本地环境短路，不写 deny 审计
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dev_bypass_skips_audit_when_TX_AUTH_ENABLED_false(
    monkeypatch, stub_db, captured_deny_calls,
):
    """TX_AUTH_ENABLED=false 时 require_role 直接返回 mock admin（dev_bypass）。
    audit-aware 装饰器不应在这种情况下也写 deny（会污染本地开发数据）。"""
    monkeypatch.setenv("TX_AUTH_ENABLED", "false")
    dep = require_role_audited(
        "refund.apply", "store_manager", "admin", db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=None,
        tenant_id=XUJI_CHANGSHA_TENANT,
        role="",
    )

    ctx = await dep(req, db=stub_db)
    assert ctx.role == "admin"
    assert ctx.user_id == "dev-user-mock"
    # 关键：dev_bypass 路径不写 deny（也不写 allow，allow 由路由层 write_audit）
    assert captured_deny_calls == []


# ──────────────────────────────────────────────────────────────────────────
# 场景 5：allow 路径不调用 audit_deny（idx_trade_audit_deny 不被污染）
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_manager_refund_allow_path_does_not_write_deny_audit(
    stub_db, captured_deny_calls,
):
    """店长李姐有权 refund → require_role_audited 通过 → 不写 deny。
    allow 审计仍由路由层 write_audit(action='refund.apply', result='allow') 写。"""
    dep = require_role_audited(
        "refund.apply", "store_manager", "admin", db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=MANAGER_LIJIE_ID,
        tenant_id=XUJI_CHANGSHA_TENANT,
        role="store_manager",
    )

    ctx = await dep(req, db=stub_db)
    assert ctx.role == "store_manager"
    assert ctx.user_id == MANAGER_LIJIE_ID
    assert captured_deny_calls == []


# ──────────────────────────────────────────────────────────────────────────
# 场景 6：audit_deny 抛错时仍正常 raise HTTPException（审计绝不阻塞业务）
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_deny_error_does_not_block_403_response(monkeypatch, stub_db):
    """write_audit 故障时（DB 挂了）必须仍然抛出 403，不阻塞 RBAC 决策。"""

    async def _failing_audit(**kwargs):
        raise RuntimeError("audit DB unreachable")

    def _shim(**kwargs):
        return _failing_audit(**kwargs)

    monkeypatch.setattr(rbac, "_audit_deny_safe", _shim)

    dep = require_role_audited(
        "refund.apply", "store_manager", "admin", db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=CASHIER_XIAOWANG_ID,
        tenant_id=XUJI_CHANGSHA_TENANT,
        role="cashier",
    )

    # 必须仍抛出 HTTPException 403（不被审计故障吞掉）
    with pytest.raises(HTTPException) as ei:
        await dep(req, db=stub_db)
    assert ei.value.status_code == 403
    assert ei.value.detail == "ROLE_FORBIDDEN"


# ──────────────────────────────────────────────────────────────────────────
# 场景 7：跨租户探测 — 长沙 cashier 用自己的 token 访问韶山的资源
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_xujihaixian_cross_tenant_probe_audit_uses_caller_tenant(
    stub_db, captured_deny_calls,
):
    """长沙店 cashier 持自店 token 试图访问韶山店退款。RBAC 拒绝（角色不够）→
    audit 写入的 tenant_id 必须是来自 request.state（=长沙），绝不能是请求 body 里
    伪造的 tenant_id。同时 idx_trade_audit_deny 部分索引能命中。
    """
    dep = require_role_audited(
        "refund.apply", "store_manager", "admin",
        severity_on_deny="error",  # 跨租户探测属高敏感
        db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=CASHIER_XIAOWANG_ID,
        tenant_id=XUJI_CHANGSHA_TENANT,  # 来自 JWT 注入
        role="cashier",
        path=f"/api/v1/trade/orders/{XUJI_SHAOSHAN_TENANT}/refund",  # URL 写韶山 ID
    )

    with pytest.raises(HTTPException):
        await dep(req, db=stub_db)

    assert len(captured_deny_calls) == 1
    call = captured_deny_calls[0]
    # 关键：audit 用 request.state.tenant_id（长沙），不是 URL/body 里的韶山 ID
    assert call["tenant_id"] == XUJI_CHANGSHA_TENANT
    assert call["severity"] == "error"


# ──────────────────────────────────────────────────────────────────────────
# 性能护栏：deny 审计同步 await 但单次不超过 100ms（mocked DB）
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_deny_synchronous_overhead_under_100ms(stub_db, captured_deny_calls):
    """audit_deny 同步 await（保证可靠落盘）但开销不能拖累 403 响应。

    Mock DB 下 P99 应 < 10ms；真实 DB 下目标 < 100ms。
    """
    dep = require_role_audited(
        "refund.apply", "store_manager", "admin", db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=CASHIER_XIAOWANG_ID,
        tenant_id=XUJI_CHANGSHA_TENANT,
        role="cashier",
    )

    import time
    t0 = time.perf_counter()
    with pytest.raises(HTTPException):
        await dep(req, db=stub_db)
    dt_ms = (time.perf_counter() - t0) * 1000
    assert dt_ms < 100.0, f"deny audit overhead {dt_ms:.2f}ms >= 100ms"
    assert len(captured_deny_calls) == 1
