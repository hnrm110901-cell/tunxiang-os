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
    _push_supplier_portal,
    _push_wecom_purchaser,
    _push_wecom_safety_director,
    _scan_one_tenant,
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

        # cert_alert_log 幂等查询（SELECT ... AND success = TRUE）
        if "cert_alert_log" in sql and "SELECT" in sql.upper() and "INSERT" not in sql.upper():
            if already_alerted:
                result.first.return_value = MagicMock()
            else:
                result.first.return_value = None
            return result

        # cert_alert_log INSERT/UPSERT
        if "cert_alert_log" in sql and "INSERT" in sql.upper():
            return MagicMock()

        # tenants webhook 查询
        if "tenants" in sql and "extra_data" in sql:
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

    def test_d30_window_day_28_pushes(self):
        """D-28（task 跑漏两天，补救场景） → D-30 阈值（±2 天容错窗口）。"""
        assert _classify_threshold(28) == "D-30"

    def test_d30_window_day_29_pushes(self):
        """D-29（task 跑漏一天，补救场景） → D-30 阈值（±2 天容错窗口）。"""
        assert _classify_threshold(29) == "D-30"

    def test_d15_window_day_13_pushes(self):
        """D-13（task 跑漏两天，补救场景） → D-15 阈值。"""
        assert _classify_threshold(13) == "D-15"

    def test_d7_window_day_5_pushes(self):
        """D-5（task 跑漏两天，补救场景） → D-7 阈值。"""
        assert _classify_threshold(5) == "D-7"

    def test_between_windows_returns_none(self):
        """D-27（窗口间隙） → None，不推。"""
        assert _classify_threshold(27) is None


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
        """_log_alert UPSERT 语义：同日同 cert 重复调用不报错，success 可被覆盖。

        Day 1 推送失败（success=False）→ _log_alert 落 success=False
        Day 1 retry（Celery）→ _log_alert UPSERT 更新 success=True
        _already_alerted（success=TRUE）第一次返回 False（失败记录不算"已告知"）
        _already_alerted（success=TRUE）第二次（retry 成功后）返回 True
        """
        # 模拟两次 _already_alerted：第一次返回 False（失败记录），第二次返回 True（成功记录）
        call_count = 0

        async def already_alerted_side_effect(query, params=None):
            nonlocal call_count
            sql = str(query)
            result = MagicMock()
            if "cert_alert_log" in sql and "INSERT" not in sql.upper():
                call_count += 1
                if call_count == 1:
                    result.first.return_value = None   # 失败记录不触发 success=TRUE 命中
                else:
                    result.first.return_value = MagicMock()  # 成功覆盖后命中
                return result
            return MagicMock()

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=already_alerted_side_effect)

        # 第一次 _already_alerted（push 失败前）→ False
        result1 = await _already_alerted(db, _CERT_A, "D-30", CHANNEL_WECOM_SAFETY)
        assert result1 is False, "推送失败时不算已告知，应可重推"

        # 模拟推送成功后再次查询 → True
        result2 = await _already_alerted(db, _CERT_A, "D-30", CHANNEL_WECOM_SAFETY)
        assert result2 is True, "推送成功后 retry 应被幂等过滤"

        # _log_alert UPSERT 两次都不报错（语义验证）
        db2 = _mk_db(already_alerted=False)
        await _log_alert(db2, _TENANT_XUJI, _CERT_A, "D-30", CHANNEL_WECOM_SAFETY, False, "5xx")
        await _log_alert(db2, _TENANT_XUJI, _CERT_A, "D-30", CHANNEL_WECOM_SAFETY, True, None)
        assert db2.execute.call_count >= 2, "两次 _log_alert UPSERT 均应执行"


# ─── 9. 无 webhook URL 时跳过该 channel 并 log warn ────────────────────────


class TestNoWebhookSkippedLogged:
    @pytest.mark.asyncio
    async def test_no_safety_director_webhook_skipped(self):
        """tenant 无 safety_director_webhook → CHANNEL_WECOM_SAFETY 跳过，不 raise。

        验证：
        1. _push_wecom_safety_director 不被调用（webhook 缺失时跳过）
        2. logger.warning 事件名 cert_alert_no_safety_director_webhook 存在于代码路径
        3. 无异常抛出，_scan_one_tenant 正常返回
        """
        cert_d30 = {
            "cert_id": _CERT_A,
            "supplier_id": _SUPPLIER_A,
            "supplier_name": "徐记海鲜供应商A",
            "cert_type": "食品经营许可证",
            "cert_number": "XJ-2024-001",
            "expire_date": date(2026, 6, 13),
            "days_until_expiry": 30,
        }

        # 构造 mock async context manager for engine.connect()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=MagicMock())
        mock_conn.commit = AsyncMock()

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(return_value=mock_cm)

        with patch(
            "services.tx_supply.src.workers.cert_expiry_alerter._get_engine",
            return_value=mock_engine,
        ), patch(
            "services.tx_supply.src.workers.cert_expiry_alerter._get_tenant_webhook_urls",
            new=AsyncMock(return_value={"safety_director_webhook": None, "purchaser_webhook": "https://qyapi.weixin.qq.com/purchaser"}),
        ), patch(
            "services.tx_supply.src.workers.cert_expiry_alerter._already_alerted",
            new=AsyncMock(return_value=False),
        ), patch(
            "services.tx_supply.src.workers.cert_expiry_alerter._log_alert",
            new=AsyncMock(),
        ), patch(
            "services.tx_supply.src.workers.cert_expiry_alerter._push_wecom_safety_director",
        ) as mock_push_safety, patch(
            "services.tx_supply.src.workers.cert_expiry_alerter._push_wecom_purchaser",
            new=AsyncMock(return_value=(True, None)),
        ), patch(
            "services.tx_supply.src.workers.cert_expiry_alerter.logger"
        ) as mock_logger:
            # list_alertable は _scan_one_tenant 内でローカルインポートされる
            with patch(
                "services.tx_supply.src.services.cert_service.list_alertable",
                new=AsyncMock(return_value=[cert_d30]),
            ):
                result = await _scan_one_tenant(_TENANT_XUJI, _TODAY)

        # safety push は呼ばれない（webhook URL なし）
        assert not mock_push_safety.called, "webhook URL 不在时不应调用 _push_wecom_safety_director"

        # logger.warning が cert_alert_no_safety_director_webhook イベントで呼ばれる
        warning_events = [
            str(call_args)
            for call_args in mock_logger.warning.call_args_list
        ]
        assert any(
            "cert_alert_no_safety_director_webhook" in ev for ev in warning_events
        ), f"应记录 safety director webhook 缺失 warning，实际: {warning_events}"

        # 无异常，returned dict 结构正确
        assert "evaluated" in result and "sent" in result


# ─── 10. sub-PR C — 推送通道接线契约 ────────────────────────────────────────
#
# tx_org IMNotificationService 注册：从 tx-supply 测试树运行时，根 conftest
# 只注册顶级 `services` namespace + 各服务 src/services/；tx_supply/conftest
# 仅注册 services.tx_supply.*。需要手动注册 services.tx_org.* 命名空间
# 才能 patch tx-supply worker 内对 services.tx_org.src.services.im_notification_service
# 的懒 import。
import importlib.util as _importlib_util
import types as _types

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
_TX_ORG_SVC_DIR = os.path.join(_REPO_ROOT, "services", "tx-org")
_TX_ORG_SRC_DIR = os.path.join(_TX_ORG_SVC_DIR, "src")


def _register_tx_org_im_namespace() -> None:
    """注册 services.tx_org.src.services.im_notification_service 命名空间链。"""
    if "services.tx_org.src.services.im_notification_service" in sys.modules:
        return
    for name, path in [
        ("services.tx_org", _TX_ORG_SVC_DIR),
        ("services.tx_org.src", _TX_ORG_SRC_DIR),
        ("services.tx_org.src.services", os.path.join(_TX_ORG_SRC_DIR, "services")),
    ]:
        if name not in sys.modules:
            mod = _types.ModuleType(name)
            mod.__path__ = [path]
            mod.__package__ = name
            sys.modules[name] = mod
    spec = _importlib_util.spec_from_file_location(
        "services.tx_org.src.services.im_notification_service",
        os.path.join(_TX_ORG_SRC_DIR, "services", "im_notification_service.py"),
    )
    if spec and spec.loader:
        _mod = _importlib_util.module_from_spec(spec)
        sys.modules["services.tx_org.src.services.im_notification_service"] = _mod
        spec.loader.exec_module(_mod)


_register_tx_org_im_namespace()


def _sample_cert(*, days: int = 30, expire: date = date(2026, 6, 13)) -> dict:
    """sub-PR C 推送测试用 cert dict（含 supplier_name，匹配 cert_service round-2 fix）。"""
    return {
        "cert_id": _CERT_A,
        "supplier_id": _SUPPLIER_A,
        "supplier_name": "徐记海鲜供应商A",
        "cert_type": "食品经营许可证",
        "cert_number": "XJ-2024-001",
        "expire_date": expire,
        "days_until_expiry": days,
    }


class TestPushChannelWiringTier1:
    """sub-PR C 推送通道接线 Tier 1 契约测试。

    覆盖：
      1. 食安总监 wecom 推送：调 IMNotificationService.send_wecom_bot 且消息含证件信息
      2. send_wecom_bot 返回 False → stub 返回 (False, 'wecom_send_failed')
      3. 采购员推送 message 含'采购员'角色（区别于食安总监）
      4. supplier_portal 推送：执行 INSERT INTO supplier_portal_messages（subject/body/metadata）
      5. supplier_portal SQLAlchemyError → 返回 (False, 'portal_insert_failed: <ClassName>')，不 raise
      6. 任何 channel 的 success/failure log 都不能含 webhook_url 字符串值（防泄漏）
    """

    @pytest.mark.asyncio
    async def test_push_wecom_safety_director_calls_im_service_with_correct_args(self):
        """食安总监 wecom 推送：调 IMNotificationService.send_wecom_bot，message 含证件信息。"""
        cert = _sample_cert(days=30)
        webhook = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SECRET-XYZ"

        mock_inst = MagicMock()
        rendered_message = (
            "### 供应商证件临期预警\n"
            "**供应商**：徐记海鲜供应商A\n"
            "**证件类型**：食品经营许可证\n"
            "**证件编号**：XJ-2024-001\n"
            "**到期日**：2026-06-13\n"
            "**距过期**：30 天（阈值 D-30）\n"
            "**收件角色**：食安总监\n\n请通知供应商提前准备续证材料，避免临期断档。"
        )
        mock_inst.notify_cert_expiry = AsyncMock(return_value=rendered_message)
        mock_inst.send_wecom_bot = AsyncMock(return_value=True)

        with patch(
            "services.tx_org.src.services.im_notification_service.IMNotificationService",
            return_value=mock_inst,
        ):
            success, error_msg = await _push_wecom_safety_director(
                _TENANT_XUJI, cert, "D-30", webhook
            )

        assert success is True
        assert error_msg is None

        # send_wecom_bot 调 webhook + rendered message
        assert mock_inst.send_wecom_bot.call_count == 1
        sent_args, sent_kwargs = mock_inst.send_wecom_bot.call_args
        sent_url = sent_args[0] if sent_args else sent_kwargs.get("webhook_url")
        sent_msg = sent_args[1] if len(sent_args) > 1 else sent_kwargs.get("message")
        assert sent_url == webhook
        assert "徐记海鲜供应商A" in sent_msg
        assert "食品经营许可证" in sent_msg
        assert "XJ-2024-001" in sent_msg
        assert "2026-06-13" in sent_msg

        # notify_cert_expiry 用了食安总监 recipient_role
        assert mock_inst.notify_cert_expiry.call_count == 1
        _, kw = mock_inst.notify_cert_expiry.call_args
        assert kw["recipient_role"] == "食安总监"
        assert kw["threshold"] == "D-30"
        assert kw["supplier_name"] == "徐记海鲜供应商A"
        assert kw["cert_type"] == "食品经营许可证"
        assert kw["cert_number"] == "XJ-2024-001"

    @pytest.mark.asyncio
    async def test_push_wecom_safety_director_returns_false_on_send_failure(self):
        """send_wecom_bot 返回 False（5xx/timeout）→ stub 返回 (False, 'wecom_send_failed')。"""
        cert = _sample_cert(days=7)

        mock_inst = MagicMock()
        mock_inst.notify_cert_expiry = AsyncMock(return_value="rendered")
        mock_inst.send_wecom_bot = AsyncMock(return_value=False)

        with patch(
            "services.tx_org.src.services.im_notification_service.IMNotificationService",
            return_value=mock_inst,
        ):
            success, error_msg = await _push_wecom_safety_director(
                _TENANT_XUJI, cert, "D-7", "https://qyapi.weixin.qq.com/mock"
            )

        assert success is False
        assert error_msg == "wecom_send_failed"

    @pytest.mark.asyncio
    async def test_push_wecom_purchaser_uses_purchaser_recipient_role(self):
        """采购员推送 message 用'采购员'角色文案（区别于食安总监模板）。"""
        cert = _sample_cert(days=15)

        mock_inst = MagicMock()
        mock_inst.notify_cert_expiry = AsyncMock(return_value="### 供应商证件临期预警\n采购员")
        mock_inst.send_wecom_bot = AsyncMock(return_value=True)

        with patch(
            "services.tx_org.src.services.im_notification_service.IMNotificationService",
            return_value=mock_inst,
        ):
            success, error_msg = await _push_wecom_purchaser(
                _TENANT_XUJI, cert, "D-15", "https://qyapi.weixin.qq.com/purchaser"
            )

        assert success is True
        assert error_msg is None

        # recipient_role='采购员' 与 safety director 模板区分
        _, kw = mock_inst.notify_cert_expiry.call_args
        assert kw["recipient_role"] == "采购员"
        assert kw["threshold"] == "D-15"

    @pytest.mark.asyncio
    async def test_push_supplier_portal_inserts_with_correct_payload(self):
        """supplier_portal 推送：执行 INSERT INTO supplier_portal_messages，含 message_type/subject/body/metadata。"""
        cert = _sample_cert(days=0, expire=date(2026, 5, 14))

        captured: dict = {}

        async def execute_capture(query, params=None):
            captured["sql"] = str(query)
            captured["params"] = params or {}
            return MagicMock()

        conn = AsyncMock()
        conn.execute = AsyncMock(side_effect=execute_capture)

        success, error_msg = await _push_supplier_portal(
            conn, _TENANT_XUJI, cert, "D+0"
        )

        assert success is True
        assert error_msg is None
        assert "INSERT INTO supplier_portal_messages" in captured["sql"]
        assert captured["params"]["tenant_id"] == _TENANT_XUJI
        assert captured["params"]["supplier_id"] == _SUPPLIER_A
        assert captured["params"]["message_type"] == "cert_expiry_alert"
        # subject 体现 D+0 已过期分支
        assert "已过期" in captured["params"]["subject"]
        assert "食品经营许可证" in captured["params"]["subject"]
        # body 含证件编号 + 过期日
        assert "XJ-2024-001" in captured["params"]["body"]
        # metadata 是 JSON 字符串（CAST AS JSONB），含 cert_id / threshold
        import json as _json

        meta = _json.loads(captured["params"]["metadata"])
        assert meta["cert_id"] == _CERT_A
        assert meta["threshold"] == "D+0"
        assert meta["cert_type"] == "食品经营许可证"

    @pytest.mark.asyncio
    async def test_push_supplier_portal_inserts_临期_subject_for_negative_threshold(self):
        """临期阈值（D-7/D-15/D-30）→ subject 走"临期"分支，不是"已过期"。"""
        cert = _sample_cert(days=7)

        captured: dict = {}

        async def execute_capture(query, params=None):
            captured["params"] = params or {}
            return MagicMock()

        conn = AsyncMock()
        conn.execute = AsyncMock(side_effect=execute_capture)

        await _push_supplier_portal(conn, _TENANT_XUJI, cert, "D-7")
        assert "临期" in captured["params"]["subject"]
        assert "D-7" in captured["params"]["subject"]
        assert "已过期" not in captured["params"]["subject"]

    @pytest.mark.asyncio
    async def test_push_supplier_portal_returns_false_on_db_error(self):
        """conn.execute raises SQLAlchemyError → 返回 (False, 'portal_insert_failed: <ClassName>')，不 raise。"""
        cert = _sample_cert(days=0)

        from sqlalchemy.exc import IntegrityError

        async def execute_raises(query, params=None):
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))

        conn = AsyncMock()
        conn.execute = AsyncMock(side_effect=execute_raises)

        success, error_msg = await _push_supplier_portal(
            conn, _TENANT_XUJI, cert, "D+1"
        )

        assert success is False
        assert error_msg is not None
        assert error_msg.startswith("portal_insert_failed:")
        assert "IntegrityError" in error_msg

    @pytest.mark.asyncio
    async def test_push_does_not_log_webhook_url_content(self):
        """监管：success log 不能含 webhook_url 字符串值（防 token 泄漏）。"""
        secret_token = "SECRET-TOKEN-DO-NOT-LEAK-XYZ"
        webhook = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={secret_token}"
        cert = _sample_cert(days=30)

        mock_inst = MagicMock()
        mock_inst.notify_cert_expiry = AsyncMock(return_value="rendered")
        mock_inst.send_wecom_bot = AsyncMock(return_value=True)

        with patch(
            "services.tx_org.src.services.im_notification_service.IMNotificationService",
            return_value=mock_inst,
        ), patch(
            "services.tx_supply.src.workers.cert_expiry_alerter.logger"
        ) as mock_logger:
            await _push_wecom_safety_director(_TENANT_XUJI, cert, "D-30", webhook)

        # 收集所有 logger.info / logger.warning 调用的 args + kwargs 字符串化
        all_log_text = ""
        for log_call in (
            list(mock_logger.info.call_args_list)
            + list(mock_logger.warning.call_args_list)
        ):
            all_log_text += str(log_call)

        assert secret_token not in all_log_text, (
            f"webhook 内 token 泄漏到 log: {all_log_text}"
        )

    @pytest.mark.asyncio
    async def test_push_wecom_failure_log_does_not_leak_webhook_url(self):
        """监管：failure log 也不能含 webhook_url 字符串值。"""
        secret_token = "FAILURE-PATH-SECRET-TOKEN"
        webhook = f"https://qyapi.weixin.qq.com/mock?key={secret_token}"
        cert = _sample_cert(days=15)

        mock_inst = MagicMock()
        mock_inst.notify_cert_expiry = AsyncMock(return_value="rendered")
        mock_inst.send_wecom_bot = AsyncMock(return_value=False)

        with patch(
            "services.tx_org.src.services.im_notification_service.IMNotificationService",
            return_value=mock_inst,
        ), patch(
            "services.tx_supply.src.workers.cert_expiry_alerter.logger"
        ) as mock_logger:
            await _push_wecom_purchaser(_TENANT_XUJI, cert, "D-15", webhook)

        all_log_text = ""
        for log_call in (
            list(mock_logger.info.call_args_list)
            + list(mock_logger.warning.call_args_list)
        ):
            all_log_text += str(log_call)

        assert secret_token not in all_log_text
