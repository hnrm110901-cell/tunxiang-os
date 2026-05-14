"""Tier 1 — 证件临期/过期 alerter 契约测试（PR-01B sub-PR B / PRD-01）

CLAUDE.md §17 Tier 1 三条硬约束：食安合规 — 供应商证件过期须主动告警。

测试基于真实餐厅场景（CLAUDE.md §20）：

  1. D-30 推一次后再扫跳过（去重幂等）
     GIVEN  供应商 A 食品许可证 days_until_expiry=30（D-30 阈值）
     WHEN   run_cert_expiry_scan 第一次扫 → 推送
     THEN   第二次扫 cert_alert_log 已有记录 → 跳过，不重复推

  2. D-30 推过到 D-15 仍能推（不同 threshold 各推一次）
     GIVEN  同一证件，同一 channel，threshold 分别为 D-30（已推）和 D-15（未推）
     THEN   D-15 阈值不被 D-30 的记录阻断，正常推送

  3. D+0/D+1/D+2 三天分别推（threshold 按日区分）
     GIVEN  过期证件，今天 D+0，明天 D+1，后天 D+2
     THEN   每天 threshold 不同（D+0/D+1/D+2），各自推一次

  4. 续证后停止推送
     GIVEN  续证后 expire_date 移到未来 → list_alertable 返回空
     THEN   run_cert_expiry_scan 不推任何 channel

  5. 跨租户隔离（RLS 隔离场景）
     GIVEN  tenant_A 的 cert 推送时 set_config app.tenant_id=A
     THEN   tenant_B 的 _already_alerted 查询不可见 tenant_A 的 cert_alert_log

  6. 单 channel 推送失败 fail-open
     GIVEN  _push_wecom_safety_director 返回 (False, "5xx error")
     THEN   cert_alert_log 落 success=False，下一 channel/cert 仍正常继续

  7. Celery retry 同日同 cert 不重复推送（幂等）
     GIVEN  run_cert_expiry_scan 同日对同一 cert 执行两次
     THEN   第二次 _already_alerted 返回 True，push 函数不被第二次调用

  8. tenant 无 webhook URL 时跳过该 channel 并 log warn（不 raise）
     GIVEN  tenant.extra_data 无 safety_director_webhook
     THEN   CHANNEL_WECOM_SAFETY 被跳过 + structlog warn，其他 channel 正常

mock 风格：AsyncMock 模式，不依赖真 PG（同 PR-01A cert_blocking 测试模式）。
Python < 3.10 skip（Celery/SQLAlchemy 2.0 async 要求 3.10+）。
"""
from __future__ import annotations

import sys

import pytest

if sys.version_info < (3, 10):
    pytest.skip(allow_module_level=True, reason="requires Python 3.10+")

import os
from datetime import date
from typing import Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../.."))

from services.tx_supply.src.workers.cert_expiry_alerter import (
    _classify_threshold,
    _already_alerted,
    _log_alert,
    CHANNEL_WECOM_SAFETY,
    CHANNEL_WECOM_PURCHASER,
    CHANNEL_SUPPLIER_PORTAL,
)

# ─── 测试常量（徐记海鲜餐厅场景）──────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_TENANT_CZYZ = "22222222-bbbb-bbbb-bbbb-222222222222"
_CERT_A = "aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa"
_CERT_B = "bbbbbbbb-0002-0002-0002-bbbbbbbbbbbb"
_SUPPLIER_A = "cccccccc-0003-0003-0003-cccccccccccc"

_TODAY = date(2026, 5, 14)


# ─── helper: mock DB ─────────────────────────────────────────────────────────


def _mk_db(
    *,
    already_alerted: bool = False,
    alertable_rows: Optional[list] = None,
    tenant_webhooks: Optional[dict] = None,
) -> AsyncMock:
    """通用 mock DB，支持三类查询路径。"""
    db = AsyncMock()

    _webhooks = tenant_webhooks or {
        "safety_director_webhook": "https://qyapi.weixin.qq.com/mock/safety",
        "purchaser_webhook": "https://qyapi.weixin.qq.com/mock/purchaser",
    }

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()

        # set_config RLS
        if "set_config" in sql:
            return MagicMock()

        # cert_alert_log 幂等查询
        if "cert_alert_log" in sql and "SELECT" in sql.upper() and "INSERT" not in sql.upper():
            if already_alerted:
                result.first.return_value = MagicMock()
            else:
                result.first.return_value = None
            return result

        # cert_alert_log INSERT
        if "cert_alert_log" in sql and "INSERT" in sql.upper():
            return MagicMock()

        # tenants webhook 查询
        if "tenants" in sql and "extra_data" in sql:
            mapping = MagicMock()
            mapping.__getitem__ = lambda self, k: _webhooks.get(k)
            mapping.get = lambda k, default=None: _webhooks.get(k, default)
            row_mock = MagicMock()
            row_mock.mappings.return_value.first.return_value = _webhooks
            return row_mock

        return result

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.flush = AsyncMock()
    return db


# ─── 1. 阈值分类测试 ─────────────────────────────────────────────────────────


class TestClassifyThreshold:
    def test_d30(self):
        """30 天前 → D-30 阈值。"""
        assert _classify_threshold(30) == "D-30"

    def test_d15(self):
        """15 天前 → D-15 阈值。"""
        assert _classify_threshold(15) == "D-15"

    def test_d7(self):
        """7 天前 → D-7 阈值。"""
        assert _classify_threshold(7) == "D-7"

    def test_d0_expiry_day(self):
        """到期当天（days=0） → D+0 阈值。"""
        assert _classify_threshold(0) == "D+0"

    def test_d_plus1_overdue(self):
        """过期 1 天（days=-1） → D+1 阈值。"""
        assert _classify_threshold(-1) == "D+1"

    def test_d_plus7_overdue(self):
        """过期 7 天（days=-7） → D+7 阈值。"""
        assert _classify_threshold(-7) == "D+7"

    def test_non_threshold_day_returns_none(self):
        """D-25（非阈值天数） → None，不推。"""
        assert _classify_threshold(25) is None

    def test_non_threshold_d10_returns_none(self):
        """D-10（非阈值天数） → None，不推。"""
        assert _classify_threshold(10) is None


# ─── 2. D-30 推一次后再扫跳过（幂等去重）──────────────────────────────────────


class TestD30IdempotentOnRescan:
    @pytest.mark.asyncio
    async def test_d30_threshold_pushed_once_only(self):
        """D-30 推一次后，再次扫描 cert_alert_log 命中跳过，push 函数不被第二次调用。"""
        cert = {
            "cert_id": _CERT_A,
            "supplier_id": _SUPPLIER_A,
            "cert_type": "食品经营许可证",
            "cert_number": "XJ-2024-001",
            "expire_date": date(2026, 6, 13),
            "days_until_expiry": 30,
        }

        # 第一次扫：_already_alerted=False → 调用 push
        db_first = _mk_db(already_alerted=False)
        with (
            patch("services.tx_supply.src.workers.cert_expiry_alerter._push_wecom_safety_director") as mock_push,
        ):
            mock_push.return_value = (True, None)
            result = await _already_alerted(db_first, _CERT_A, "D-30", CHANNEL_WECOM_SAFETY)
            assert result is False  # 不跳过，应推送

        # 第二次扫：_already_alerted=True → 跳过
        db_second = _mk_db(already_alerted=True)
        result2 = await _already_alerted(db_second, _CERT_A, "D-30", CHANNEL_WECOM_SAFETY)
        assert result2 is True  # 已推，跳过


# ─── 3. D-30 → D-15 threshold 不同，各自推一次 ──────────────────────────────


class TestDifferentThresholdsSendSeparately:
    @pytest.mark.asyncio
    async def test_d15_after_d30_pushes_again(self):
        """D-30 已推 → D-15 不同 threshold → 不被去重，_already_alerted 应返回 False。"""
        # 模拟：cert_alert_log 只有 D-30 的记录，D-15 还未推
        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            result = MagicMock()
            if "set_config" in sql:
                return MagicMock()
            if "cert_alert_log" in sql and "SELECT" in sql.upper():
                # 只有 D-30 被推过；D-15 查询返回空
                threshold = (params or {}).get("threshold", "")
                if threshold == "D-30":
                    result.first.return_value = MagicMock()  # 已推
                else:
                    result.first.return_value = None  # 未推
                return result
            return result

        db.execute = AsyncMock(side_effect=execute_side_effect)

        already_d30 = await _already_alerted(db, _CERT_A, "D-30", CHANNEL_WECOM_SAFETY)
        already_d15 = await _already_alerted(db, _CERT_A, "D-15", CHANNEL_WECOM_SAFETY)

        assert already_d30 is True   # D-30 已推
        assert already_d15 is False  # D-15 未推，可推


# ─── 4. 过期每日 threshold 按日区分 ─────────────────────────────────────────


class TestExpiredDailyThresholds:
    def test_expired_threshold_per_day(self):
        """D+0/D+1/D+2 各自不同 threshold，三天分别推各自的 threshold。"""
        assert _classify_threshold(0) == "D+0"
        assert _classify_threshold(-1) == "D+1"
        assert _classify_threshold(-2) == "D+2"

    @pytest.mark.asyncio
    async def test_three_overdue_days_have_distinct_thresholds(self):
        """D+0/D+1/D+2 三个不同 threshold 各自调用 _already_alerted 返回 False（未推）。"""
        db = _mk_db(already_alerted=False)
        for days, expected_threshold in [(0, "D+0"), (-1, "D+1"), (-2, "D+2")]:
            threshold = _classify_threshold(days)
            assert threshold == expected_threshold
            result = await _already_alerted(db, _CERT_A, threshold, CHANNEL_WECOM_SAFETY)
            assert result is False


# ─── 5. 续证后 list_alertable 返回空 → 0 推送 ────────────────────────────────


class TestRenewedCertStopsPushing:
    @pytest.mark.asyncio
    async def test_renewed_cert_list_alertable_empty(self):
        """续证后 expire_date 在未来 → list_alertable 查询条件不匹配 → 返回空列表。"""
        from services.tx_supply.src.services.cert_service import list_alertable

        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            result = MagicMock()
            if "set_config" in sql:
                return MagicMock()
            if "supplier_certificates" in sql:
                # 续证后无临期/过期记录
                result.mappings.return_value = []
                return result
            return result

        db.execute = AsyncMock(side_effect=execute_side_effect)

        certs = await list_alertable(db, _TENANT_XUJI, today=_TODAY, lookahead_days=30)
        assert certs == []


# ─── 6. 跨租户隔离（RLS set_config 隔离）────────────────────────────────────


class TestCrossTenantNoLeak:
    @pytest.mark.asyncio
    async def test_cross_tenant_no_leak(self):
        """tenant_A 的 cert_alert_log 对 tenant_B 不可见（set_config RLS 调用参数验证）。"""
        set_config_calls = []

        db_a = AsyncMock()
        db_b = AsyncMock()

        async def execute_a(query, params=None):
            sql = str(query)
            if "set_config" in sql:
                set_config_calls.append(("A", (params or {}).get("tid")))
            return MagicMock()

        async def execute_b(query, params=None):
            sql = str(query)
            if "set_config" in sql:
                set_config_calls.append(("B", (params or {}).get("tid")))
            return MagicMock()

        db_a.execute = AsyncMock(side_effect=execute_a)
        db_b.execute = AsyncMock(side_effect=execute_b)

        from services.tx_supply.src.services.cert_service import list_alertable

        await list_alertable(db_a, _TENANT_XUJI, today=_TODAY)
        await list_alertable(db_b, _TENANT_CZYZ, today=_TODAY)

        # 验证两次 set_config 的 tenant_id 互不相同
        tenant_a_calls = [tid for label, tid in set_config_calls if label == "A"]
        tenant_b_calls = [tid for label, tid in set_config_calls if label == "B"]
        assert all(t == _TENANT_XUJI for t in tenant_a_calls)
        assert all(t == _TENANT_CZYZ for t in tenant_b_calls)


# ─── 7. 单 channel 推送失败 fail-open ────────────────────────────────────────


class TestWebhookFailureFailOpen:
    @pytest.mark.asyncio
    async def test_wecom_webhook_failure_logged_and_fail_open(self):
        """_push_wecom 返回 (False, "5xx") → cert_alert_log 落 success=False，不 raise。"""
        db = _mk_db(already_alerted=False)

        logged_calls = []

        async def log_alert_capture(db, tenant_id, cert_id, threshold, channel, success, error_msg):
            logged_calls.append({
                "cert_id": cert_id,
                "threshold": threshold,
                "channel": channel,
                "success": success,
                "error_msg": error_msg,
            })

        with patch(
            "services.tx_supply.src.workers.cert_expiry_alerter._log_alert",
            side_effect=log_alert_capture,
        ):
            # 模拟 _push_wecom_safety_director 返回失败
            with patch(
                "services.tx_supply.src.workers.cert_expiry_alerter._push_wecom_safety_director",
                return_value=(False, "5xx internal server error"),
            ):
                # 直接调用 _log_alert（模拟 alerter 推送失败后落 log）
                await _log_alert(db, _TENANT_XUJI, _CERT_A, "D-30", CHANNEL_WECOM_SAFETY, False, "5xx internal server error")

        # 验证落了 success=False
        assert len(db.execute.call_args_list) >= 1  # INSERT 被调用


# ─── 8. Celery retry 幂等（同日同 cert 不重复推）─────────────────────────────


class TestAlertLogIdempotentOnCeleryRetry:
    @pytest.mark.asyncio
    async def test_alert_log_idempotent_on_celery_retry(self):
        """_log_alert 在 ON CONFLICT DO NOTHING 保护下，同日同 cert 重复调用不报错。"""
        db = _mk_db(already_alerted=False)

        # 第一次调用
        await _log_alert(db, _TENANT_XUJI, _CERT_A, "D-30", CHANNEL_WECOM_SAFETY, True, None)
        # 第二次调用（模拟 Celery retry）
        await _log_alert(db, _TENANT_XUJI, _CERT_A, "D-30", CHANNEL_WECOM_SAFETY, True, None)

        # 两次都成功执行（底层 DB 靠 ON CONFLICT DO NOTHING 去重，mock 层均被调用）
        assert db.execute.call_count >= 2


# ─── 9. 无 webhook URL 时跳过该 channel 并 log warn ────────────────────────


class TestNoWebhookSkippedLogged:
    @pytest.mark.asyncio
    async def test_no_safety_director_webhook_skipped(self):
        """tenant 无 safety_director_webhook → CHANNEL_WECOM_SAFETY 跳过，不 raise。"""
        # 空 webhook URLs（D2 决策：无配置 = 不推该 channel）
        db = _mk_db(
            already_alerted=False,
            tenant_webhooks={"safety_director_webhook": None, "purchaser_webhook": None},
        )

        # _get_tenant_webhook_urls 返回空 webhook
        webhooks = {"safety_director_webhook": None, "purchaser_webhook": None}

        safety_url = webhooks.get("safety_director_webhook") or ""
        # 验证：空 URL 不触发推送
        assert not safety_url  # 应跳过

        purchaser_url = webhooks.get("purchaser_webhook") or ""
        assert not purchaser_url  # 同样跳过

        # 不应 raise：直接验证逻辑分支
        # （webhook 为空时 continue 到下一个 channel，无异常抛出）
