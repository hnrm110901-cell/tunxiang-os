"""回归测试: gateway wecom_routes 早返回路径 structlog kwarg 冲突 (Issue #576)

PR #574 (Closes #573) 同模式 cross-service follow-up.

修前 (origin/main `55da116e` 之前):
  logger.warning("wecom_customer_add_missing_external_userid", event=event)
  logger.warning("wecom_customer_del_missing_external_userid", event=event)
  → structlog 把第一个 positional 当 event_name 字段（保留字段 'event'）,
    payload 又传 `event=` kwarg → TypeError(multiple values for 'event').

修后:
  payload kwarg rename → `wecom_payload=event` 避免冲突.

业务场景（企微回调 XML 边界，非常规 payload）:
  - POST /api/v1/wecom/callback 接收 customer_add / customer_del 事件
  - XML 解析后 dict 缺失 ExternalUserID 字段 → 早返回 + warning log
  - 修前: 该 warning log 直接抛 TypeError, 后台异步 task 异常被丢弃 + log 噪音
  - 修后: warning log 正常落, 含 wecom_payload 字段供下游排查

归 P2: 不影响数据正确性, 仅非常规企微 XML 时日志混乱.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest


# ── 路径 ──────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


class TestWecomCustomerAddStructlogCollision:
    """Issue #576 — wecom_customer_add_missing_external_userid structlog event= 冲突."""

    def test_handle_customer_add_no_typeerror_with_empty_external_userid(self):
        """场景: 企微 XML payload 缺 ExternalUserID 字段 → 早返回 warning log,
        旧版抛 TypeError(multiple values for 'event')."""
        from services.gateway.src.wecom_routes import _handle_customer_add  # noqa: E402

        # 缺 ExternalUserID 触发 L72 早返回 warning log
        asyncio.get_event_loop().run_until_complete(
            _handle_customer_add({"UserID": "u1", "State": "store_xxx"})
        )

    def test_handle_customer_add_log_uses_wecom_payload_kwarg(self):
        """log 含 wecom_payload=<dict>（修后正确字段名）,
        且 event 字段值为 structlog 保留的 event_name."""
        from structlog.testing import capture_logs

        from services.gateway.src.wecom_routes import _handle_customer_add  # noqa: E402

        wecom_event = {"UserID": "u1", "State": "store_001"}
        with capture_logs() as logs:
            asyncio.get_event_loop().run_until_complete(
                _handle_customer_add(wecom_event)
            )

        warn_logs = [
            log for log in logs if log.get("event") == "wecom_customer_add_missing_external_userid"
        ]
        assert len(warn_logs) == 1, f"应捕获 1 条 missing_external_userid log; 实际 {len(warn_logs)} 条: {logs!r}"
        entry = warn_logs[0]
        assert entry.get("wecom_payload") == wecom_event, (
            f"wecom_payload 应是原 dict; 实际 entry={entry!r}"
        )
        assert entry["event"] == "wecom_customer_add_missing_external_userid", (
            f"event 应是 structlog event_name; 实际={entry['event']!r}"
        )


class TestWecomCustomerDelStructlogCollision:
    """Issue #576 — wecom_customer_del_missing_external_userid structlog event= 冲突."""

    def test_handle_customer_del_no_typeerror_with_empty_external_userid(self):
        """场景: 企微 XML payload 缺 ExternalUserID 字段 → 早返回 warning log,
        旧版抛 TypeError(multiple values for 'event')."""
        from services.gateway.src.wecom_routes import _handle_customer_del  # noqa: E402

        asyncio.get_event_loop().run_until_complete(
            _handle_customer_del({"UserID": "u2"})
        )

    def test_handle_customer_del_log_uses_wecom_payload_kwarg(self):
        """log 含 wecom_payload=<dict>（修后正确字段名）,
        且 event 字段值为 structlog 保留的 event_name."""
        from structlog.testing import capture_logs

        from services.gateway.src.wecom_routes import _handle_customer_del  # noqa: E402

        wecom_event = {"UserID": "u2"}
        with capture_logs() as logs:
            asyncio.get_event_loop().run_until_complete(
                _handle_customer_del(wecom_event)
            )

        warn_logs = [
            log for log in logs if log.get("event") == "wecom_customer_del_missing_external_userid"
        ]
        assert len(warn_logs) == 1, f"应捕获 1 条 missing_external_userid log; 实际 {len(warn_logs)} 条: {logs!r}"
        entry = warn_logs[0]
        assert entry.get("wecom_payload") == wecom_event, (
            f"wecom_payload 应是原 dict; 实际 entry={entry!r}"
        )
        assert entry["event"] == "wecom_customer_del_missing_external_userid", (
            f"event 应是 structlog event_name; 实际={entry['event']!r}"
        )
