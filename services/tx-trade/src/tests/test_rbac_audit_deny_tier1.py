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


# ──────────────────────────────────────────────────────────────────────────
#  R-补1-1 §19 复审追加场景（致命缺陷修复）：
#    第 3 项 — 401 路径 tenant_id="" 在真 PG 上 UUID NOT NULL cast 失败丢审计
#    第 6 项 — 测试盲点：原场景 3 用 _mk_request 传 tenant_id 不模拟真 401
# ──────────────────────────────────────────────────────────────────────────


NIL_TENANT_UUID = "00000000-0000-0000-0000-000000000000"


def _mk_request_unauthenticated(
    *,
    forged_tenant_header: str | None = None,
    forged_tenant_header_invalid: bool = False,
    client_ip: str = "10.0.0.5",
    path: str = "/api/v1/trade/orders/O-1/refund",
    request_id: str = "req-xj-attack-001",
):
    """模拟 gateway middleware 拒绝 JWT 后的 request：state 不带任何字段。

    生产环境真实 401 路径：gateway AuthMiddleware JWT 验证失败时
    *不向 request.state 注入* user_id / tenant_id / role。原 test_unauthenticated_*
    用 _mk_request(tenant_id=...) 仍向 state 写 tenant_id，**不模拟真实 401**。
    """
    state = SimpleNamespace()
    client = SimpleNamespace(host=client_ip)
    headers = {"X-Request-Id": request_id}
    if forged_tenant_header_invalid:
        headers["X-Tenant-ID"] = "not-a-uuid-payload"
    elif forged_tenant_header is not None:
        headers["X-Tenant-ID"] = forged_tenant_header
    return SimpleNamespace(
        state=state,
        client=client,
        headers=headers,
        url=SimpleNamespace(path=path),
    )


@pytest.mark.asyncio
async def test_truly_unauthenticated_uses_nil_tenant_uuid(stub_db, captured_deny_calls):
    """无 JWT + 无 X-Tenant-ID → audit_deny 收到 NIL UUID（不能是 ""）。

    §19 审查发现的致命缺陷：原实现把 tenant_id="" 传到 write_audit，
    PG 上 trade_audit_logs.tenant_id 是 UUID NOT NULL → cast "" → SQLAlchemyError
    → 被 broad except 吞 → 审计永久丢失。NIL UUID 兜底确保 INSERT 成功。
    """
    dep = require_role_audited(
        "refund.apply", "store_manager", "admin", db_provider=lambda: stub_db,
    )
    req = _mk_request_unauthenticated()

    with pytest.raises(HTTPException) as ei:
        await dep(req, db=stub_db)
    assert ei.value.status_code == 401
    assert ei.value.detail == "AUTH_MISSING"

    assert len(captured_deny_calls) == 1
    call = captured_deny_calls[0]
    # 关键：tenant_id 必须是 NIL UUID（PG 上能 cast 成功的有效 UUID）
    assert call["tenant_id"] == NIL_TENANT_UUID, (
        f"401 path must fall back to NIL UUID; got {call['tenant_id']!r}"
    )
    assert call["reason"] == "AUTH_MISSING"


@pytest.mark.asyncio
async def test_forged_x_tenant_id_does_not_pollute_victim_audit_table(
    stub_db, captured_deny_calls,
):
    """攻击者无 JWT 但伪造 X-Tenant-ID=victim → audit 落 NIL UUID，不落 victim。

    安全约束：永远不能让攻击者通过 X-Tenant-ID header 把行注入到任意租户的
    audit 表（污染 + 误导取证）。但 forged value 必须保留为取证证据 → 进 reason。
    """
    dep = require_role_audited(
        "refund.apply", "store_manager", "admin", db_provider=lambda: stub_db,
    )
    req = _mk_request_unauthenticated(forged_tenant_header=XUJI_CHANGSHA_TENANT)

    with pytest.raises(HTTPException) as ei:
        await dep(req, db=stub_db)
    assert ei.value.status_code == 401

    call = captured_deny_calls[0]
    # tenant_id 走 NIL — 不写到 victim 租户表
    assert call["tenant_id"] == NIL_TENANT_UUID
    # forged 值保留在 reason 中作为证据
    assert "probed_tenant" in call["reason"], (
        f"forged X-Tenant-ID must be preserved in reason for forensics; "
        f"got reason={call['reason']!r}"
    )
    assert XUJI_CHANGSHA_TENANT in call["reason"]


@pytest.mark.asyncio
async def test_invalid_x_tenant_id_header_dropped_no_log_poisoning(
    stub_db, captured_deny_calls,
):
    """X-Tenant-ID 非 UUID → 直接丢弃，不进 reason（防 log poisoning / SQL 拼接）。"""
    dep = require_role_audited(
        "refund.apply", "store_manager", "admin", db_provider=lambda: stub_db,
    )
    req = _mk_request_unauthenticated(forged_tenant_header_invalid=True)

    with pytest.raises(HTTPException):
        await dep(req, db=stub_db)

    call = captured_deny_calls[0]
    assert call["tenant_id"] == NIL_TENANT_UUID
    # 非 UUID 格式 header 不应进 reason
    assert "probed_tenant" not in (call["reason"] or "")
    assert "not-a-uuid" not in (call["reason"] or "")
    assert call["reason"] == "AUTH_MISSING"


@pytest.mark.asyncio
async def test_audit_deny_internal_defense_for_empty_tenant_id(stub_db):
    """audit_deny 内部防御层：调用方传 tenant_id="" 时仍兜底为 NIL UUID。

    防御层 2 — 即使 wrapper 路径有 bug 漏了 resolve（如未来新增直接调用），
    audit_deny 仍保证 PG INSERT 用合法 UUID，不静默丢审计。
    """
    from src.services.trade_audit_log import audit_deny

    captured_tids: list[str] = []

    async def _capture_execute(stmt, params=None):
        if params and "tid" in params:
            captured_tids.append(params["tid"])
        # 返回一个 mock — 但 audit_deny 内部 db.execute 还会被 INSERT 调一次
        m = AsyncMock()
        m.first = lambda: None
        return m

    stub_db.execute.side_effect = _capture_execute

    await audit_deny(
        stub_db,
        tenant_id="",  # 故意传空模拟漏 resolve
        store_id=None,
        user_id="",
        user_role="",
        action="refund.apply",
        reason="AUTH_MISSING",
    )

    # set_config 必须收到 NIL UUID，不是空串
    assert NIL_TENANT_UUID in captured_tids, (
        f"audit_deny must defensively coerce empty tenant_id to NIL UUID; "
        f"got captured tids={captured_tids}"
    )
    assert "" not in captured_tids


@pytest.mark.asyncio
async def test_authenticated_caller_tenant_id_unchanged(stub_db, captured_deny_calls):
    """已认证 caller（ctx.tenant_id 非空）必须照样使用其真实 tenant_id，不退化为 NIL。

    回归保护：NIL UUID 兜底只在 401 / 缺失场景生效，不能影响正常 deny 路径。
    """
    dep = require_role_audited(
        "refund.apply", "store_manager", "admin", db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=CASHIER_XIAOWANG_ID,
        tenant_id=XUJI_CHANGSHA_TENANT,
        role="cashier",
    )

    with pytest.raises(HTTPException):
        await dep(req, db=stub_db)

    call = captured_deny_calls[0]
    assert call["tenant_id"] == XUJI_CHANGSHA_TENANT
    assert "probed_tenant" not in (call["reason"] or "")


# ──────────────────────────────────────────────────────────────────────────
#  Integration test — 真 PG，验证 401 路径 NIL UUID 实际能落盘
#
#  跳过条件：环境变量 TX_INTEGRATION_DB_URL 未设置（本地默认）。
#  CI 启用方式：export TX_INTEGRATION_DB_URL=postgresql+asyncpg://user:pwd@host/tx_test
#               + alembic upgrade head 后跑 pytest -m integration
#
#  此测试是 R-补1-1 §19 复审第 6 项的修复 —— mock 测试无法覆盖 PG UUID 列对
#  空字符串的 cast 行为，必须真 PG 才能验证 NIL UUID 兜底是否真的工作。
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("TX_INTEGRATION_DB_URL"),
    reason="需要 TX_INTEGRATION_DB_URL 才能跑真 PG 集成测试",
)
@pytest.mark.asyncio
async def test_pg_integration_unauthenticated_audit_actually_persists():
    """真 PG 验证：401 路径 NIL UUID 落盘 trade_audit_logs，UUID cast 不失败。

    §19 复审第 3 项：原实现 tenant_id="" → PG UUID NOT NULL 列 cast 失败 →
    SQLAlchemyError → broad except 吞 → 审计永久丢失。修复后用 NIL UUID 兜底，
    本测试通过查询表验证 deny 行确实写入。

    前置：alembic upgrade 至少到 v261（创建 trade_audit_logs + RLS）+ v290
    （扩 result/reason 列）。
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.services.trade_audit_log import audit_deny

    db_url = os.environ["TX_INTEGRATION_DB_URL"]
    engine = create_async_engine(db_url, echo=False)
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with SessionLocal() as session:
            # 必须先 set_config 到 NIL UUID（audit_deny 内部会做，这里测前置已干净）
            await audit_deny(
                session,
                tenant_id="",  # ← R-补1-1 关键：故意传空，验证内部兜底为 NIL UUID
                store_id=None,
                user_id="",
                user_role="",
                action="refund.apply",
                reason="AUTH_MISSING | probed_tenant=00000000-0000-0000-0000-0000000000a1",
                severity="warn",
                client_ip="10.0.0.5",
                request_id="integ-test-001",
            )

            # 校验：用 NIL UUID 作为 RLS 上下文查这条记录
            from sqlalchemy import text
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": "00000000-0000-0000-0000-000000000000"},
            )
            row = (await session.execute(
                text(
                    "SELECT user_id, user_role, action, result, reason "
                    "FROM trade_audit_logs "
                    "WHERE tenant_id = '00000000-0000-0000-0000-000000000000'::uuid "
                    "AND request_id = :rid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"rid": "integ-test-001"},
            )).first()

            assert row is not None, (
                "401 路径 NIL UUID 兜底未落盘 — UUID cast 仍失败或 RLS 拒绝"
            )
            assert row.action == "refund.apply"
            assert row.result == "deny"
            assert "probed_tenant" in row.reason
            # 第二轮 §19 复审追加：user_id 列必须是 NIL UUID（不能是 "(unauthenticated)" 字符串）
            assert str(row.user_id) == "00000000-0000-0000-0000-000000000000", (
                f"user_id 应是 NIL UUID 兜底；得到 {row.user_id!r}"
            )
            assert row.user_role == "(unauthenticated)"
    finally:
        await engine.dispose()


# ──────────────────────────────────────────────────────────────────────────
#  R-补1-2 第二轮 §19 复审：补 da70fd0c 漏盖的 audit-loss 分支
#    - safe_user_id "(unauthenticated)" 给 PG UUID NOT NULL 列 cast 失败
#    - reason String(128) / request_id String(64) / session_id String(64) 溢出
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_deny_empty_user_id_uses_nil_uuid_not_string_sentinel(stub_db):
    """audit_deny user_id="" → user_id 列收到 NIL UUID（不是 "(unauthenticated)"）。

    da70fd0c 修了 tenant_id 同根因，但 audit_deny 仍把 "(unauthenticated)" 当
    user_id 给 PG UUID NOT NULL 列 → cast 失败 → broad except → 静默丢审计。
    本测试断言 INSERT 参数里 user_id 是合法 UUID 字符串。
    """
    from src.services.trade_audit_log import audit_deny

    captured_params: list[dict] = []

    async def _capture_execute(stmt, params=None):
        if params is not None:
            captured_params.append(dict(params))
        m = AsyncMock()
        m.first = lambda: None
        return m

    stub_db.execute.side_effect = _capture_execute

    await audit_deny(
        stub_db,
        tenant_id="",
        store_id=None,
        user_id="",  # 401 路径
        user_role="",
        action="refund.apply",
        reason="AUTH_MISSING",
    )

    insert_params = [p for p in captured_params if "user_id" in p]
    assert len(insert_params) == 1
    p = insert_params[0]
    # user_id 必须是合法 UUID 格式（NIL UUID）
    assert p["user_id"] == NIL_TENANT_UUID, (
        f"user_id 必须用 NIL UUID 兜底；得到 {p['user_id']!r}（这会让 PG cast 失败）"
    )
    # user_role 列保留 "(unauthenticated)" 语义（TEXT 列无 cast 限制）
    assert p["user_role"] == "(unauthenticated)"


@pytest.mark.asyncio
async def test_write_audit_oversize_reason_truncated_not_dropped(stub_db):
    """reason 超 128 字符 → 截断到 128（末尾 '~' 标记），不让 PG 抛 truncation error。

    攻击者可通过组合长 exc.detail + cross_tenant_target_blocked tag + probed_tenant
    后缀让 reason 溢出 → StringDataRightTruncation → broad except → 静默丢审计。
    """
    from src.services.trade_audit_log import audit_deny

    captured_params: list[dict] = []

    async def _capture_execute(stmt, params=None):
        if params is not None:
            captured_params.append(dict(params))
        m = AsyncMock()
        m.first = lambda: None
        return m

    stub_db.execute.side_effect = _capture_execute

    long_reason = "X" * 200  # 远超 128
    await audit_deny(
        stub_db,
        tenant_id=XUJI_CHANGSHA_TENANT,
        store_id=None,
        user_id=CASHIER_XIAOWANG_ID,
        user_role="cashier",
        action="refund.apply",
        reason=long_reason,
    )

    insert_params = [p for p in captured_params if "reason" in p]
    assert len(insert_params) == 1
    truncated = insert_params[0]["reason"]
    assert len(truncated) <= 128, f"reason 必须截断到 ≤128；得到 len={len(truncated)}"
    assert truncated.endswith("~"), "truncation 必须在末尾留 '~' 标记"


@pytest.mark.asyncio
async def test_write_audit_oversize_request_id_truncated(stub_db):
    """X-Request-Id 超 64 字符（攻击者可控 header）→ 截断不丢审计。"""
    from src.services.trade_audit_log import audit_deny

    captured_params: list[dict] = []

    async def _capture_execute(stmt, params=None):
        if params is not None:
            captured_params.append(dict(params))
        m = AsyncMock()
        m.first = lambda: None
        return m

    stub_db.execute.side_effect = _capture_execute

    long_request_id = "Z" * 200
    await audit_deny(
        stub_db,
        tenant_id=XUJI_CHANGSHA_TENANT,
        store_id=None,
        user_id=CASHIER_XIAOWANG_ID,
        user_role="cashier",
        action="refund.apply",
        reason="ROLE_FORBIDDEN",
        request_id=long_request_id,
    )

    insert_params = [p for p in captured_params if "request_id" in p]
    assert len(insert_params) == 1
    truncated = insert_params[0]["request_id"]
    assert len(truncated) <= 64
    assert truncated.endswith("~")


@pytest.mark.asyncio
async def test_write_audit_oversize_session_id_truncated(stub_db):
    """session_id 超 64 字符 → 截断不丢审计。"""
    from src.services.trade_audit_log import audit_deny

    captured_params: list[dict] = []

    async def _capture_execute(stmt, params=None):
        if params is not None:
            captured_params.append(dict(params))
        m = AsyncMock()
        m.first = lambda: None
        return m

    stub_db.execute.side_effect = _capture_execute

    long_session_id = "S" * 200
    await audit_deny(
        stub_db,
        tenant_id=XUJI_CHANGSHA_TENANT,
        store_id=None,
        user_id=CASHIER_XIAOWANG_ID,
        user_role="cashier",
        action="refund.apply",
        reason="ROLE_FORBIDDEN",
        session_id=long_session_id,
    )

    insert_params = [p for p in captured_params if "session_id" in p]
    assert len(insert_params) == 1
    truncated = insert_params[0]["session_id"]
    assert len(truncated) <= 64
    assert truncated.endswith("~")


@pytest.mark.asyncio
async def test_write_audit_normal_length_passthrough_no_truncation_marker(stub_db):
    """正常长度 reason / request_id / session_id 原样写入，不加 '~' 后缀。"""
    from src.services.trade_audit_log import audit_deny

    captured_params: list[dict] = []

    async def _capture_execute(stmt, params=None):
        if params is not None:
            captured_params.append(dict(params))
        m = AsyncMock()
        m.first = lambda: None
        return m

    stub_db.execute.side_effect = _capture_execute

    await audit_deny(
        stub_db,
        tenant_id=XUJI_CHANGSHA_TENANT,
        store_id=None,
        user_id=CASHIER_XIAOWANG_ID,
        user_role="cashier",
        action="refund.apply",
        reason="ROLE_FORBIDDEN",
        request_id="req-xj-001",
        session_id="session-001",
    )

    insert_params = [p for p in captured_params if "reason" in p]
    p = insert_params[0]
    assert p["reason"] == "ROLE_FORBIDDEN"
    assert not p["reason"].endswith("~")
    assert p["request_id"] == "req-xj-001"
    assert not p["request_id"].endswith("~")
    assert p["session_id"] == "session-001"
