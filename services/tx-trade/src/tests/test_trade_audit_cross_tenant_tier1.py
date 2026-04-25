"""Tier 1 测试 — A4-R2 / write_audit 跨租户 target_id 防探测信道

§19 独立审查发现：原 write_audit 不校验 target_id 所属租户，长沙经理可在请求体中
传入韶山店订单 UUID 作为 target_id，把跨租户标识写入长沙审计行。攻击者通过查
audit 表回查 target_id 命中情况，可枚举其他租户的订单 ID。

修复（trade_audit_log.py L207~_target_in_caller_tenant + L243 调用点）：
  1. write_audit 在 set_config 后、INSERT 前对 target_type 注册过的实体表
     SELECT 1 LIMIT 1，依赖已绑定 app.tenant_id 的 RLS 自动 scope 到 caller 租户
  2. 查不到 → sanitize：target_id/amount_fen/before_state/after_state → NULL；
     result 升级为 'deny'，severity 升级为 'critical'，reason 拼上
     cross_tenant_target_blocked:<target_type>
  3. structlog.error 记 critical 级别 → 触发 SIEM 告警
  4. fail-open：未注册 target_type / 候选表全部查询失败 → 跳过校验

测试场景（基于徐记海鲜真实业务路径）：
  T1: 跨租户订单 UUID 写入 → 必须 sanitize + downgrade 到 deny + severity=critical
  T2: 同租户订单 UUID 写入 → 正常审计，target_id 保留
  T3: 未注册 target_type='voucher' → 跳过校验，正常写入（fail-open）
  T4: 候选表全部 raise SQLAlchemyError → 跳过校验，正常写入（fail-open）
  T5: target_id=None → 不发起 lookup
  T6: 已是 deny audit + 跨租户 target → 保留 result='deny'，sanitize target_id
  T7: target_type='order' 但 target_id 非 UUID 格式（如 EMO20240101...） → 跳过 UUID 表
  T8: critical structlog 必须发出（SIEM 告警链路）
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.services.trade_audit_log import (
    _is_valid_uuid,
    _target_in_caller_tenant,
    _TARGET_TENANT_LOOKUPS,
    write_audit,
)

# ─── 固定测试数据 ──────────────────────────────────────────────────────────

_TENANT_CHANGSHA = "11111111-aaaa-aaaa-aaaa-111111111111"  # 长沙店租户
_TENANT_SHAOSHAN = "22222222-bbbb-bbbb-bbbb-222222222222"  # 韶山店租户（受害方）
_USER_CASHIER = "33333333-cccc-cccc-cccc-333333333333"
_STORE_CHANGSHA = "44444444-dddd-dddd-dddd-444444444444"
_ORDER_UUID = "55555555-eeee-eeee-eeee-555555555555"


def _mk_db_with_lookup(*, lookup_returns_row: bool, raise_on_lookup: bool = False) -> AsyncMock:
    """构造一个 db mock：set_config / INSERT 永远成功，lookup 按参数行为。

    lookup_returns_row=True  → result.first() 返回 MagicMock（视为命中行）
    lookup_returns_row=False → result.first() 返回 None（视为未命中）
    raise_on_lookup=True     → lookup query 抛 SQLAlchemyError（fail-open）
    """
    db = AsyncMock()

    set_config_call_count = {"n": 0}

    async def execute_side_effect(query, params=None):
        sql_text = str(query)
        # set_config 总是成功
        if "set_config" in sql_text:
            set_config_call_count["n"] += 1
            return MagicMock()
        # lookup query：SELECT 1 FROM ... WHERE ... = CAST(...)
        if "SELECT 1 FROM" in sql_text:
            if raise_on_lookup:
                raise SQLAlchemyError("simulated lookup failure")
            mock_result = MagicMock()
            mock_result.first.return_value = MagicMock() if lookup_returns_row else None
            return mock_result
        # INSERT INTO trade_audit_logs
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _captured_insert_params(db: AsyncMock) -> dict | None:
    """从 db.execute 的调用历史中找出 INSERT 调用的 params dict。"""
    for call in db.execute.await_args_list:
        args, kwargs = call.args, call.kwargs
        if args and "INSERT INTO trade_audit_logs" in str(args[0]):
            # text(...) + params dict
            return args[1] if len(args) > 1 else kwargs.get("parameters")
    return None


# ─── T1: 跨租户检测（核心场景） ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_t1_cross_tenant_order_id_sanitized_and_escalated():
    """长沙收银员在请求体里传韶山订单 UUID → 必须 sanitize + 升级 deny。

    徐记真实场景：APT 攻击者拿到长沙店 manager 凭据，尝试用韶山店订单 UUID 调
    /api/v1/payment-direct/alipay。create_alipay_payment 走 RLS 看不到该单 →
    业务层抛错（OK），但 write_audit 仍被 caller 调用。原代码会把 target_id=
    韶山UUID 写入长沙的 audit 行，构成回查信道。

    修复后：lookup SELECT 因 RLS 看不到韶山订单 → returns None → False →
    sanitize：
        - target_id = NULL
        - amount_fen = NULL
        - result = 'deny'
        - severity = 'critical'
        - reason 包含 'cross_tenant_target_blocked:order'
    """
    db = _mk_db_with_lookup(lookup_returns_row=False)

    await write_audit(
        db,
        tenant_id=_TENANT_CHANGSHA,
        store_id=_STORE_CHANGSHA,
        user_id=_USER_CASHIER,
        user_role="store_manager",
        action="payment.alipay.create",
        target_type="order",
        target_id=_ORDER_UUID,  # 假装是韶山店订单
        amount_fen=88800,
        client_ip="192.168.1.10",
    )

    params = _captured_insert_params(db)
    assert params is not None, "INSERT 必须发生（审计不可丢）"
    assert params["target_id"] is None, "跨租户 target_id 必须被清空"
    assert params["amount_fen"] is None, "跨租户金额也清空（避免侧信道）"
    assert params["result"] == "deny"
    assert params["severity"] == "critical"
    assert params["reason"] is not None and "cross_tenant_target_blocked:order" in params["reason"]
    assert params["before_state"] is None
    assert params["after_state"] is None
    db.commit.assert_awaited_once()


# ─── T2: 同租户正常路径（必须保留 target_id） ──────────────────────────────


@pytest.mark.asyncio
async def test_t2_same_tenant_order_id_passes_through():
    """长沙收银员对长沙店订单收款 → lookup 命中 → 正常审计，target_id 保留。"""
    db = _mk_db_with_lookup(lookup_returns_row=True)

    await write_audit(
        db,
        tenant_id=_TENANT_CHANGSHA,
        store_id=_STORE_CHANGSHA,
        user_id=_USER_CASHIER,
        user_role="store_manager",
        action="payment.alipay.create",
        target_type="order",
        target_id=_ORDER_UUID,
        amount_fen=88800,
        client_ip="192.168.1.10",
    )

    params = _captured_insert_params(db)
    assert params is not None
    assert params["target_id"] == _ORDER_UUID
    assert params["amount_fen"] == 88800
    assert params["result"] is None  # 调用方未传，正常 NULL
    assert params["severity"] is None


# ─── T3: 未注册 target_type → fail-open ────────────────────────────────────


@pytest.mark.asyncio
async def test_t3_unknown_target_type_skips_check():
    """target_type='voucher' 未在 _TARGET_TENANT_LOOKUPS 注册 → 跳过校验。

    实际背景：抖音核销 audit 用 target_type='voucher' 但 target_id=None；
    保险起见即便 target_id 给了也 fail-open（fail-open 不阻塞合法审计）。
    """
    assert "voucher" not in _TARGET_TENANT_LOOKUPS  # 前置条件：确实未注册
    db = _mk_db_with_lookup(lookup_returns_row=False)

    await write_audit(
        db,
        tenant_id=_TENANT_CHANGSHA,
        store_id=_STORE_CHANGSHA,
        user_id=_USER_CASHIER,
        user_role="cashier",
        action="douyin_voucher.verify",
        target_type="voucher",
        target_id="DY12345",  # 假抖音券码，绕开 UUID 检查
        amount_fen=4900,
        client_ip=None,
    )

    params = _captured_insert_params(db)
    assert params is not None
    assert params["target_id"] == "DY12345", "未注册 target_type 应 fail-open"
    assert params["amount_fen"] == 4900
    # 没有 lookup SELECT 发生
    lookup_calls = [
        c for c in db.execute.await_args_list
        if "SELECT 1 FROM" in str(c.args[0])
    ]
    assert len(lookup_calls) == 0, "未注册 target_type 不应触发 lookup"


# ─── T4: 候选表全部 raise → fail-open ──────────────────────────────────────


@pytest.mark.asyncio
async def test_t4_all_lookup_tables_error_fails_open():
    """连接池抖动 / 表未迁移 → lookup 全部 SQLAlchemyError → fail-open。

    设计原则：审计基础设施（lookup）抖动不应让审计 record 丢失。降级为
    "未校验"，但记 structlog 让运维可见。
    """
    db = _mk_db_with_lookup(lookup_returns_row=False, raise_on_lookup=True)

    await write_audit(
        db,
        tenant_id=_TENANT_CHANGSHA,
        store_id=_STORE_CHANGSHA,
        user_id=_USER_CASHIER,
        user_role="cashier",
        action="payment.alipay.create",
        target_type="order",
        target_id=_ORDER_UUID,
        amount_fen=88800,
        client_ip=None,
    )

    params = _captured_insert_params(db)
    assert params is not None, "lookup 失败也必须正常落 INSERT"
    assert params["target_id"] == _ORDER_UUID, "fail-open: 保留原 target_id"
    assert params["amount_fen"] == 88800
    assert params["result"] is None
    db.commit.assert_awaited_once()


# ─── T5: target_id=None → 跳过 lookup ─────────────────────────────────────


@pytest.mark.asyncio
async def test_t5_no_target_id_skips_lookup():
    """target_id=None（如查询、取消类操作）→ 完全跳过 lookup。"""
    db = _mk_db_with_lookup(lookup_returns_row=False)

    await write_audit(
        db,
        tenant_id=_TENANT_CHANGSHA,
        store_id=_STORE_CHANGSHA,
        user_id=_USER_CASHIER,
        user_role="cashier",
        action="payment.scan_pay.cancel",
        target_type="payment",
        target_id=None,
        amount_fen=None,
        client_ip=None,
    )

    params = _captured_insert_params(db)
    assert params is not None
    assert params["target_id"] is None
    lookup_calls = [
        c for c in db.execute.await_args_list
        if "SELECT 1 FROM" in str(c.args[0])
    ]
    assert len(lookup_calls) == 0


# ─── T6: 已是 deny audit + 跨租户 target → 保留 deny，augment reason ──────


@pytest.mark.asyncio
async def test_t6_existing_deny_with_cross_tenant_target_keeps_deny():
    """audit_deny 路径已经 result='deny'，再加跨租户 target → 保留 deny，
    target_id 仍 sanitize，reason 拼接，severity 升 critical。
    """
    db = _mk_db_with_lookup(lookup_returns_row=False)

    await write_audit(
        db,
        tenant_id=_TENANT_CHANGSHA,
        store_id=_STORE_CHANGSHA,
        user_id=_USER_CASHIER,
        user_role="cashier",
        action="refund.apply",
        target_type="order",
        target_id=_ORDER_UUID,  # 假装是韶山订单
        amount_fen=8800,
        client_ip=None,
        result="deny",
        reason="ROLE_FORBIDDEN",
        severity="warn",
    )

    params = _captured_insert_params(db)
    assert params is not None
    assert params["result"] == "deny"
    assert params["target_id"] is None
    assert params["amount_fen"] is None
    assert params["severity"] == "critical"  # 升级
    assert params["reason"] is not None
    assert "ROLE_FORBIDDEN" in params["reason"]
    assert "cross_tenant_target_blocked:order" in params["reason"]


# ─── T7: target_type=order + 非 UUID target_id（EMO 回退路径） ─────────────


@pytest.mark.asyncio
async def test_t7_order_with_non_uuid_target_id_skips_uuid_tables():
    """enterprise_meal_routes 的 SQLError 回退路径会用 'EMO20240101...' 作为
    order_id 写审计。这种字符串 CAST AS UUID 必败。

    修复：UUID 类型表前置 _is_valid_uuid 检查，非 UUID 直接跳过该表。本场景
    所有候选表都是 UUID，全部跳过 → any_table_queried=False → returns None →
    fail-open。
    """
    db = _mk_db_with_lookup(lookup_returns_row=False)
    fallback_id = "EMO20260425120000"

    await write_audit(
        db,
        tenant_id=_TENANT_CHANGSHA,
        store_id=_STORE_CHANGSHA,
        user_id=_USER_CASHIER,
        user_role="store_manager",
        action="enterprise_meal.order.create",
        target_type="order",
        target_id=fallback_id,
        amount_fen=2400,
        client_ip=None,
    )

    params = _captured_insert_params(db)
    assert params is not None
    assert params["target_id"] == fallback_id, "非 UUID 应 fail-open"
    # 验证没有 lookup 真的发起（UUID 检查在 SQL 之前已挡）
    lookup_calls = [
        c for c in db.execute.await_args_list
        if "SELECT 1 FROM" in str(c.args[0])
    ]
    assert len(lookup_calls) == 0


# ─── T8: SIEM 告警必须触发（structlog critical） ──────────────────────────


@pytest.mark.asyncio
async def test_t8_cross_tenant_emits_critical_structlog():
    """跨租户检出必须 logger.error('trade_audit_cross_tenant_target_blocked',
    severity='critical')。SIEM 告警靠这条 log 触发，是 P0 链路。
    """
    db = _mk_db_with_lookup(lookup_returns_row=False)

    with patch("src.services.trade_audit_log.logger") as mock_logger:
        await write_audit(
            db,
            tenant_id=_TENANT_CHANGSHA,
            store_id=_STORE_CHANGSHA,
            user_id=_USER_CASHIER,
            user_role="store_manager",
            action="payment.alipay.create",
            target_type="order",
            target_id=_ORDER_UUID,
            amount_fen=88800,
            client_ip="192.168.1.10",
        )

        # 必须发出 trade_audit_cross_tenant_target_blocked 这条 error 级别 log
        critical_logs = [
            c for c in mock_logger.error.call_args_list
            if c.args and c.args[0] == "trade_audit_cross_tenant_target_blocked"
        ]
        assert len(critical_logs) == 1, "必须发出 1 条 critical SIEM log"
        kwargs = critical_logs[0].kwargs
        assert kwargs.get("severity") == "critical"
        assert kwargs.get("tenant_id") == _TENANT_CHANGSHA
        assert kwargs.get("user_id") == _USER_CASHIER
        assert kwargs.get("action") == "payment.alipay.create"
        assert kwargs.get("target_type") == "order"
        assert kwargs.get("target_id_blocked") == _ORDER_UUID  # 仅 log，不落 DB


# ─── 辅助测试：_is_valid_uuid 与 _target_in_caller_tenant 单元 ────────────


def test_is_valid_uuid_tolerant_to_none_and_garbage():
    assert _is_valid_uuid(_ORDER_UUID) is True
    assert _is_valid_uuid("EMO20240101120000") is False
    assert _is_valid_uuid("") is False
    assert _is_valid_uuid(None) is False
    assert _is_valid_uuid("not-a-uuid") is False


@pytest.mark.asyncio
async def test_target_in_caller_tenant_returns_none_for_unknown_type():
    db = _mk_db_with_lookup(lookup_returns_row=False)
    out = await _target_in_caller_tenant(db, target_type="reconcile", target_id="abc")
    assert out is None, "未注册类型必须 fail-open（None）"


@pytest.mark.asyncio
async def test_target_in_caller_tenant_returns_none_for_empty_target_id():
    db = _mk_db_with_lookup(lookup_returns_row=False)
    out = await _target_in_caller_tenant(db, target_type="order", target_id="")
    assert out is None
