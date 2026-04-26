"""Tier 1 — assert_mfa_for_high_value 阈值动态 MFA 门禁测试

§19 复审 PR-5 (9232e7ad) 反馈第 4 项：banquet.deposit.create 几万元定金没 MFA。
PR-5 已经把 4 个纯高敏感路由（refund / payment.refund / discount.rule.*）
切到 require_mfa_audited 装饰器。但 banquet.deposit.create 是混合路由
（< ¥5000 高频低额 / ≥ ¥5000 低频高额），全量 MFA UX 不可接受。

修复：handler 内动态金额阈值检查（rbac.assert_mfa_for_high_value，已在
cfd117a0 合入）。本测试补回测试覆盖（cfd117a0 合并时漏掉了测试文件）。

阈值优先级：
  TX_MFA_THRESHOLD_FEN__<ACTION>  > TX_MFA_THRESHOLD_FEN_DEFAULT > 入参 default
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.security.rbac import (
    UserContext,
    _high_value_threshold_fen,
    assert_mfa_for_high_value,
)

os.environ.setdefault("TX_AUTH_ENABLED", "true")


XUJI_TENANT = "00000000-0000-0000-0000-0000000000a1"
MANAGER_ID = "00000000-0000-0000-0000-000000000012"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个测试都清掉阈值环境变量，防止跨测试污染。"""
    for var in (
        "TX_MFA_THRESHOLD_FEN_DEFAULT",
        "TX_MFA_THRESHOLD_FEN__BANQUET_DEPOSIT_CREATE",
        "TX_MFA_THRESHOLD_FEN__SOME_ACTION",
        "TX_MFA_THRESHOLD_FEN__CUSTOM_ACTION",
    ):
        monkeypatch.delenv(var, raising=False)


def _user(*, mfa_verified: bool = False, role: str = "store_manager") -> UserContext:
    return UserContext(
        user_id=MANAGER_ID, tenant_id=XUJI_TENANT, role=role,
        mfa_verified=mfa_verified, store_id="00000000-0000-0000-0000-0000000000a2",
        client_ip="10.0.0.5",
    )


@pytest.fixture
def stub_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.fixture
def captured_audit_deny(monkeypatch):
    """拦截 trade_audit_log.audit_deny 调用记录参数。"""
    from src.services import trade_audit_log
    captured: list[dict] = []

    async def _fake_audit_deny(db, **kwargs):
        captured.append(dict(kwargs))

    monkeypatch.setattr(trade_audit_log, "audit_deny", _fake_audit_deny)
    return captured


# ──────────────────────────────────────────────────────────────────────────
# 场景 1：低额无 MFA → 放行（cashier UX 友好）
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_low_amount_without_mfa_passes(stub_db, captured_audit_deny):
    """¥4999 (499_900 fen) 低于默认阈值 ¥5000 → 不要求 MFA。"""
    user = _user(mfa_verified=False)
    await assert_mfa_for_high_value(
        user, stub_db,
        action="banquet.deposit.create",
        amount_fen=499_900,
    )
    # 低额路径不应写 audit（保持 idx_trade_audit_deny 不被污染）
    assert captured_audit_deny == []


# ──────────────────────────────────────────────────────────────────────────
# 场景 2：高额无 MFA → 403 + audit deny severity=error
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_high_amount_without_mfa_returns_403(stub_db, captured_audit_deny):
    """¥10000 (1_000_000 fen) ≥ 默认阈值 ¥5000 + 未 MFA → 403 MFA_REQUIRED。"""
    user = _user(mfa_verified=False)

    with pytest.raises(HTTPException) as ei:
        await assert_mfa_for_high_value(
            user, stub_db,
            action="banquet.deposit.create",
            amount_fen=1_000_000,
            request_id="req-banquet-001",
        )
    assert ei.value.status_code == 403
    assert ei.value.detail == "MFA_REQUIRED"

    assert len(captured_audit_deny) == 1
    call = captured_audit_deny[0]
    assert call["action"] == "banquet.deposit.create"
    assert call["amount_fen"] == 1_000_000
    assert call["severity"] == "error"
    assert "MFA_REQUIRED_FOR_HIGH_VALUE" in call["reason"]
    assert "amount_fen=1000000" in call["reason"]
    assert "threshold_fen=500000" in call["reason"]
    assert call["request_id"] == "req-banquet-001"


# ──────────────────────────────────────────────────────────────────────────
# 场景 3：高额 + MFA 已验证 → 放行
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_high_amount_with_mfa_passes(stub_db, captured_audit_deny):
    """高额且 MFA 验证通过 → 放行；不写 audit（不污染索引）。"""
    user = _user(mfa_verified=True)
    await assert_mfa_for_high_value(
        user, stub_db,
        action="banquet.deposit.create",
        amount_fen=1_000_000,
    )
    assert captured_audit_deny == []


# ──────────────────────────────────────────────────────────────────────────
# 场景 4：边界值 — amount == threshold 视为高额（≥ 而不是 >）
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_amount_equal_to_threshold_treated_as_high(stub_db, captured_audit_deny):
    """amount == threshold 视为高额（保守，避免攻击者把金额设为 threshold-1 绕过）。"""
    user = _user(mfa_verified=False)
    with pytest.raises(HTTPException) as ei:
        await assert_mfa_for_high_value(
            user, stub_db,
            action="banquet.deposit.create",
            amount_fen=500_000,
        )
    assert ei.value.status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# 场景 5：环境变量阈值覆盖
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_action_specific_env_threshold_overrides_default(
    monkeypatch, stub_db, captured_audit_deny,
):
    """TX_MFA_THRESHOLD_FEN__BANQUET_DEPOSIT_CREATE 覆盖默认 ¥5000。"""
    monkeypatch.setenv("TX_MFA_THRESHOLD_FEN__BANQUET_DEPOSIT_CREATE", "200000")  # ¥2000
    user = _user(mfa_verified=False)
    with pytest.raises(HTTPException):
        await assert_mfa_for_high_value(
            user, stub_db,
            action="banquet.deposit.create",
            amount_fen=300_000,  # ¥3000 ≥ ¥2000 自定义阈值
        )


@pytest.mark.asyncio
async def test_global_default_env_threshold_applies_when_no_action_specific(
    monkeypatch, stub_db, captured_audit_deny,
):
    """TX_MFA_THRESHOLD_FEN_DEFAULT 在没有 action 专属变量时生效。"""
    monkeypatch.setenv("TX_MFA_THRESHOLD_FEN_DEFAULT", "100000")  # ¥1000
    user = _user(mfa_verified=False)
    with pytest.raises(HTTPException):
        await assert_mfa_for_high_value(
            user, stub_db,
            action="some.other.action",
            amount_fen=150_000,
        )


@pytest.mark.asyncio
async def test_action_specific_takes_precedence_over_global(
    monkeypatch, stub_db, captured_audit_deny,
):
    """action 专属阈值优先于全局；金额低于 action 专属阈值 → 放行。"""
    monkeypatch.setenv("TX_MFA_THRESHOLD_FEN_DEFAULT", "100000")
    monkeypatch.setenv(
        "TX_MFA_THRESHOLD_FEN__BANQUET_DEPOSIT_CREATE", "10000000",
    )
    user = _user(mfa_verified=False)
    # ¥50000 高于全局 ¥1000 但低于 action 专属 ¥100000 → 应放行
    await assert_mfa_for_high_value(
        user, stub_db,
        action="banquet.deposit.create",
        amount_fen=5_000_000,
    )


# ──────────────────────────────────────────────────────────────────────────
# 场景 6：阈值变量值非法 → fallback 到 default
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad_value", ["abc", "", "-100", "0", "1.5", "  "])
def test_invalid_env_threshold_fallbacks_to_default(monkeypatch, bad_value):
    """非法值（非数字 / 负数 / 零 / 浮点 / 空白）→ 回退到入参默认。"""
    monkeypatch.setenv("TX_MFA_THRESHOLD_FEN_DEFAULT", bad_value)
    monkeypatch.setenv("TX_MFA_THRESHOLD_FEN__SOME_ACTION", bad_value)
    result = _high_value_threshold_fen("some.action", default_fen=500_000)
    assert result == 500_000


# ──────────────────────────────────────────────────────────────────────────
# 场景 7：audit_deny 内部抛错时仍正常抛 403
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_deny_failure_does_not_block_403(monkeypatch, stub_db):
    """audit_deny 抛 RuntimeError 时，403 仍正常抛出（与 require_mfa_audited 同语义）。"""
    from src.services import trade_audit_log

    async def _failing_audit_deny(db, **kwargs):
        raise RuntimeError("simulated audit DB outage")

    monkeypatch.setattr(trade_audit_log, "audit_deny", _failing_audit_deny)
    user = _user(mfa_verified=False)
    with pytest.raises(HTTPException) as ei:
        await assert_mfa_for_high_value(
            user, stub_db,
            action="banquet.deposit.create",
            amount_fen=1_000_000,
        )
    assert ei.value.status_code == 403
    assert ei.value.detail == "MFA_REQUIRED"


# ──────────────────────────────────────────────────────────────────────────
# 场景 8：调用方 threshold_fen 入参覆盖
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_custom_threshold_argument_overrides_default(stub_db, captured_audit_deny):
    """调用方传 threshold_fen 作为 env var 缺失时的回退。"""
    user = _user(mfa_verified=False)
    with pytest.raises(HTTPException):
        await assert_mfa_for_high_value(
            user, stub_db,
            action="custom.action",
            amount_fen=300_000,
            threshold_fen=200_000,
        )

    captured_audit_deny.clear()
    await assert_mfa_for_high_value(
        user, stub_db,
        action="custom.action",
        amount_fen=150_000,
        threshold_fen=200_000,
    )
    assert captured_audit_deny == []
