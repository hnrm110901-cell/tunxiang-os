"""Tier 1 — R-A4-4 资金出口路由 MFA 强制 + enterprise_meal cashier 移除

§19 复审报告第 4 项发现：
  - 32 个 require_role_audited 调用点中，**0 个用 require_mfa_audited**
    资金动作（refund/payment.refund/discount.rule.*）只有角色检查没有 MFA
  - enterprise_meal.order.create 包含 cashier 角色，但企业团餐常 ¥80k+
    单笔，cashier 不应能创建（应由店长操作）

修复：
  1. refund_routes.py: refund.apply              → require_mfa_audited
  2. payment_direct_routes.py: payment.refund    → require_mfa_audited
  3. discount_engine_routes.py: discount.rule.create → require_mfa_audited
  4. discount_engine_routes.py: discount.rule.update → require_mfa_audited
  5. enterprise_meal_routes.py: enterprise_meal.order.create 移除 cashier

不切的（保持 require_role_audited 的理由）：
  - payment.wechat/alipay/unionpay.create — cashier 收款是核心岗位职责，
    每单都 MFA 不现实
  - discount.apply — 单笔应用频率太高，已有 over_threshold 机制在调用方
  - banquet.deposit.create — 需观测生产实际频次后决定（保守暂留）
  - platform_coupon.verify/redeem — cashier 标准核销动作
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.security import rbac
from src.security.rbac import (
    require_mfa_audited,
    require_role_audited,
)

# 强制走真实 RBAC 路径
os.environ.setdefault("TX_AUTH_ENABLED", "true")


# ──────────────── 常量 + fixtures ────────────────

XUJI_TENANT = "00000000-0000-0000-0000-0000000000a1"
MANAGER_ID = "00000000-0000-0000-0000-000000000012"
CASHIER_ID = "00000000-0000-0000-0000-000000000011"
ADMIN_ID = "00000000-0000-0000-0000-000000000013"


@pytest.fixture(autouse=True)
def _force_auth_enabled(monkeypatch):
    monkeypatch.setenv("TX_AUTH_ENABLED", "true")


def _mk_request(*, user_id, tenant_id, role, mfa_verified=False):
    state = SimpleNamespace(
        user_id=user_id, tenant_id=tenant_id, role=role,
        mfa_verified=mfa_verified, store_id="00000000-0000-0000-0000-0000000000a2",
    )
    return SimpleNamespace(
        state=state,
        client=SimpleNamespace(host="10.0.0.5"),
        headers={"X-Request-Id": "req-001"},
        url=SimpleNamespace(path="/api/v1/test"),
    )


@pytest.fixture
def stub_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.fixture
def captured_deny_calls(monkeypatch):
    captured: list[dict] = []

    async def _fake_audit_deny_safe(**kwargs):
        captured.append(dict(kwargs))

    def _shim(**kwargs):
        return _fake_audit_deny_safe(**kwargs)

    monkeypatch.setattr(rbac, "_audit_deny_safe", _shim)
    return captured


# ──────────────────────────────────────────────────────────────────────────
# 场景 1：refund.apply MFA 缺失 → 403 MFA_REQUIRED + audit severity=error
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refund_apply_without_mfa_returns_403(stub_db, captured_deny_calls):
    """refund.apply 切换到 require_mfa_audited 后，store_manager 无 MFA → 403。

    退款是资金出口最高敏感动作，必须 MFA。审计 severity 默认 error（高一档）。
    """
    dep = require_mfa_audited(
        "refund.apply", "store_manager", "admin", db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=MANAGER_ID, tenant_id=XUJI_TENANT, role="store_manager",
        mfa_verified=False,
    )

    with pytest.raises(HTTPException) as ei:
        await dep(req, db=stub_db)
    assert ei.value.status_code == 403
    assert ei.value.detail == "MFA_REQUIRED"

    assert len(captured_deny_calls) == 1
    call = captured_deny_calls[0]
    assert call["action"] == "refund.apply"
    assert call["reason"] == "MFA_REQUIRED"
    # require_mfa_audited 默认 severity=error（比 require_role_audited 的 warn 高一档）
    assert call["severity"] == "error"


@pytest.mark.asyncio
async def test_refund_apply_with_mfa_passes(stub_db, captured_deny_calls):
    """已 MFA 的店长 refund.apply 应正常通过，不写 deny。"""
    dep = require_mfa_audited(
        "refund.apply", "store_manager", "admin", db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=MANAGER_ID, tenant_id=XUJI_TENANT, role="store_manager",
        mfa_verified=True,
    )

    ctx = await dep(req, db=stub_db)
    assert ctx.user_id == MANAGER_ID
    assert ctx.role == "store_manager"
    assert captured_deny_calls == []


# ──────────────────────────────────────────────────────────────────────────
# 场景 2：payment.refund 同样要求 MFA
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_payment_refund_without_mfa_returns_403(stub_db, captured_deny_calls):
    """payment.refund（支付通道退款）也必须 MFA — 与 refund.apply 同等敏感。"""
    dep = require_mfa_audited(
        "payment.refund", "store_manager", "admin", db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=MANAGER_ID, tenant_id=XUJI_TENANT, role="store_manager",
        mfa_verified=False,
    )

    with pytest.raises(HTTPException) as ei:
        await dep(req, db=stub_db)
    assert ei.value.status_code == 403
    assert ei.value.detail == "MFA_REQUIRED"

    assert captured_deny_calls[0]["action"] == "payment.refund"
    assert captured_deny_calls[0]["severity"] == "error"


# ──────────────────────────────────────────────────────────────────────────
# 场景 3：discount.rule.create / update — admin 无 MFA 也被拒
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discount_rule_create_admin_without_mfa_returns_403(
    stub_db, captured_deny_calls,
):
    """折扣规则创建影响所有未来订单（系统性风险），admin 无 MFA 也必须拒。"""
    dep = require_mfa_audited(
        "discount.rule.create", "admin", db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=ADMIN_ID, tenant_id=XUJI_TENANT, role="admin",
        mfa_verified=False,
    )

    with pytest.raises(HTTPException) as ei:
        await dep(req, db=stub_db)
    assert ei.value.status_code == 403
    assert ei.value.detail == "MFA_REQUIRED"
    assert captured_deny_calls[0]["action"] == "discount.rule.create"


@pytest.mark.asyncio
async def test_discount_rule_update_admin_without_mfa_returns_403(
    stub_db, captured_deny_calls,
):
    """折扣规则更新同等敏感（旧规则改阈值同样影响所有订单）。"""
    dep = require_mfa_audited(
        "discount.rule.update", "admin", db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=ADMIN_ID, tenant_id=XUJI_TENANT, role="admin",
        mfa_verified=False,
    )

    with pytest.raises(HTTPException) as ei:
        await dep(req, db=stub_db)
    assert ei.value.status_code == 403
    assert ei.value.detail == "MFA_REQUIRED"
    assert captured_deny_calls[0]["action"] == "discount.rule.update"


# ──────────────────────────────────────────────────────────────────────────
# 场景 4：enterprise_meal.order.create 不再放行 cashier
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enterprise_meal_create_rejects_cashier(stub_db, captured_deny_calls):
    """R-A4-4：cashier 角色已从 enterprise_meal.order.create 移除。

    新允许角色：仅 store_manager + admin。cashier 调用必须 403 ROLE_FORBIDDEN。
    """
    # 模拟新的 require_role_audited 配置（与生产代码一致）
    dep = require_role_audited(
        "enterprise_meal.order.create", "store_manager", "admin",
        db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=CASHIER_ID, tenant_id=XUJI_TENANT, role="cashier",
    )

    with pytest.raises(HTTPException) as ei:
        await dep(req, db=stub_db)
    assert ei.value.status_code == 403
    assert ei.value.detail == "ROLE_FORBIDDEN"

    assert captured_deny_calls[0]["action"] == "enterprise_meal.order.create"
    assert captured_deny_calls[0]["user_role"] == "cashier"


@pytest.mark.asyncio
async def test_enterprise_meal_create_allows_store_manager(stub_db, captured_deny_calls):
    """店长正常通过 enterprise_meal.order.create（无 MFA 要求）。"""
    dep = require_role_audited(
        "enterprise_meal.order.create", "store_manager", "admin",
        db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=MANAGER_ID, tenant_id=XUJI_TENANT, role="store_manager",
    )

    ctx = await dep(req, db=stub_db)
    assert ctx.role == "store_manager"
    assert captured_deny_calls == []


# ──────────────────────────────────────────────────────────────────────────
# 场景 5：未提升的路由（payment.wechat.create）保持 require_role_audited，
#         不被本 PR 的 MFA 推广误伤 — 回归保护
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_payment_wechat_create_still_role_only_no_mfa_required(
    stub_db, captured_deny_calls,
):
    """收银员日常微信收款不应触发 MFA — 回归保护。

    payment.wechat.create 等核心收款路径保持 require_role_audited（角色够即可），
    本 PR 只升级 4 个 fund-out 路由到 MFA。如果某天误把所有 require_role_audited
    都改成 require_mfa_audited，本测试会失败提醒。
    """
    dep = require_role_audited(
        "payment.wechat.create",
        "cashier", "store_manager", "admin",
        db_provider=lambda: stub_db,
    )
    req = _mk_request(
        user_id=CASHIER_ID, tenant_id=XUJI_TENANT, role="cashier",
        mfa_verified=False,  # 关键：cashier 永远不会 MFA 验证
    )

    # 不抛 = 通过
    ctx = await dep(req, db=stub_db)
    assert ctx.role == "cashier"
    assert captured_deny_calls == []


# ──────────────────────────────────────────────────────────────────────────
# 场景 6：源代码静态校验 — 确保 4 个目标路由真的切到 require_mfa_audited
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("route_file", "action_name"),
    [
        ("services/tx-trade/src/api/refund_routes.py", "refund.apply"),
        ("services/tx-trade/src/api/payment_direct_routes.py", "payment.refund"),
        ("services/tx-trade/src/api/discount_engine_routes.py", "discount.rule.create"),
        ("services/tx-trade/src/api/discount_engine_routes.py", "discount.rule.update"),
    ],
)
def test_fund_out_routes_use_require_mfa_audited(route_file, action_name):
    """静态防回退：4 个 fund-out 路由的源码必须包含 require_mfa_audited("<action>"...)。

    这条测试在 grep 层面盯住，防止后续重构误把 require_mfa_audited 改回
    require_role_audited（CI 立即报红）。
    """
    from pathlib import Path
    src_path = Path(__file__).resolve().parents[4] / route_file
    src = src_path.read_text(encoding="utf-8")
    target = f'require_mfa_audited("{action_name}"'
    assert target in src, (
        f"{route_file} 必须用 require_mfa_audited('{action_name}'...) "
        f"调用，不能退回 require_role_audited（R-A4-4 安全防线）"
    )


def test_enterprise_meal_create_no_cashier_role_in_source():
    """静态防回退：enterprise_meal.order.create 源码不能再含 'cashier' 字面量
    出现在 require_role_audited("enterprise_meal.order.create", ...) 调用里。
    """
    from pathlib import Path
    src_path = Path(__file__).resolve().parents[4] / "services/tx-trade/src/api/enterprise_meal_routes.py"
    src = src_path.read_text(encoding="utf-8")
    # 寻找 enterprise_meal.order.create 那一行
    for line in src.splitlines():
        if "enterprise_meal.order.create" in line and "require_role_audited" in line:
            assert '"cashier"' not in line, (
                f"enterprise_meal.order.create 不应再允许 cashier 角色（R-A4-4）：{line!r}"
            )
            return
    raise AssertionError(
        "未找到 enterprise_meal.order.create 的 require_role_audited 调用"
    )
