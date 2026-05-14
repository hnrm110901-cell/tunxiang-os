"""回归测试: tx-org im_webhook_handler.handle_wecom_callback structlog kwarg 冲突 (Issue #582)

PR #574 (Closes #573) + PR #581 (Closes #576) 同模式 cross-service follow-up.

修前 (origin/main `c7a51ea1` 之前):
  L57: logger.info("wecom_callback_received", event=event, change_type=change_type)
  L66: logger.info("wecom_callback_unhandled", event=event, change_type=change_type)
  → structlog 把第一个 positional 当 event_name 字段（保留字段 'event'）,
    payload 又传 `event=` kwarg → TypeError(multiple values for 'event').

修后:
  payload kwarg rename → `wecom_event=event` 避免冲突.

业务场景（企微员工通讯录回调）:
  POST /api/v1/im/wecom/callback 解析 XML 后直接调用 handle_wecom_callback,
  修前: **每条**企微回调都触发 L57 wecom_callback_received → TypeError →
    callback 路由 500 → 企微平台失败重试风暴 → 员工入职/离职/部门变更全链路阻塞

归 P1: webhook 每次触发, 非边界场景 (比 PR #581 P2 边界场景影响面大).

return dict 中 `"event": event` wire 字段保留不动 (caller 路由层消费).
"""

from __future__ import annotations

import asyncio
import os
import sys


# ── 路径 ──────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


class TestWecomCallbackReceivedStructlogCollision:
    """Issue #582 — wecom_callback_received structlog event= 冲突."""

    def test_handle_wecom_callback_no_typeerror(self):
        """场景: 企微通讯录回调 POST → handle_wecom_callback 调用,
        修前 L57 logger.info 直接抛 TypeError 阻塞所有企微回调."""
        from services.tx_org.src.services.im_webhook_handler import (  # noqa: E402
            handle_wecom_callback,
        )

        # 任意 Event 类型都会触发 L57 wecom_callback_received log
        result = asyncio.get_event_loop().run_until_complete(
            handle_wecom_callback({"Event": "change_contact", "ChangeType": "create_user", "UserID": "u1", "Name": "测试", "Mobile": "13800138000", "Department": "1", "Position": "服务员"})
        )
        assert result["handled"] is True

    def test_handle_wecom_callback_log_uses_wecom_event_kwarg(self):
        """log 含 wecom_event=<event_str>（修后字段名）,
        且 event 字段值为 structlog 保留 event_name 'wecom_callback_received'."""
        from structlog.testing import capture_logs

        from services.tx_org.src.services.im_webhook_handler import (  # noqa: E402
            handle_wecom_callback,
        )

        with capture_logs() as logs:
            asyncio.get_event_loop().run_until_complete(
                handle_wecom_callback({"Event": "change_contact", "ChangeType": "create_user", "UserID": "u1", "Name": "测试"})
            )

        received_logs = [log for log in logs if log.get("event") == "wecom_callback_received"]
        assert len(received_logs) == 1, f"应捕获 1 条 wecom_callback_received log; 实际 {len(received_logs)} 条: {logs!r}"
        entry = received_logs[0]
        assert entry.get("wecom_event") == "change_contact", (
            f"wecom_event 应是 'change_contact'; 实际 entry={entry!r}"
        )
        assert entry["event"] == "wecom_callback_received", (
            f"event 应是 structlog event_name; 实际={entry['event']!r}"
        )
        assert entry.get("change_type") == "create_user"


class TestWecomCallbackUnhandledStructlogCollision:
    """Issue #582 — wecom_callback_unhandled structlog event= 冲突."""

    def test_handle_wecom_callback_unhandled_no_typeerror(self):
        """场景: 未识别 Event 类型（非 change_contact）→ L66 unhandled log + return,
        修前抛 TypeError."""
        from services.tx_org.src.services.im_webhook_handler import (  # noqa: E402
            handle_wecom_callback,
        )

        # 非 change_contact Event → 走 L66 unhandled 分支
        result = asyncio.get_event_loop().run_until_complete(
            handle_wecom_callback({"Event": "approval", "ChangeType": "approval_status_change"})
        )
        assert result == {"handled": False, "event": "approval", "change_type": "approval_status_change"}

    def test_handle_wecom_callback_unhandled_log_uses_wecom_event_kwarg(self):
        """L66 log 含 wecom_event=<event_str>（修后字段名）+ wire return dict
        `event` 字段保留 (caller 路由层消费协议不变)."""
        from structlog.testing import capture_logs

        from services.tx_org.src.services.im_webhook_handler import (  # noqa: E402
            handle_wecom_callback,
        )

        with capture_logs() as logs:
            result = asyncio.get_event_loop().run_until_complete(
                handle_wecom_callback({"Event": "approval", "ChangeType": "approval_status_change"})
            )

        unhandled_logs = [log for log in logs if log.get("event") == "wecom_callback_unhandled"]
        assert len(unhandled_logs) == 1, f"应捕获 1 条 wecom_callback_unhandled log; 实际 {len(unhandled_logs)} 条: {logs!r}"
        entry = unhandled_logs[0]
        assert entry.get("wecom_event") == "approval"
        assert entry["event"] == "wecom_callback_received" or entry["event"] == "wecom_callback_unhandled", (
            f"event 应是 structlog event_name; 实际={entry['event']!r}"
        )
        # wire return dict 中 'event' 字段必须保留 (caller 路由层消费)
        assert result["event"] == "approval", (
            f"return dict 'event' 字段是 wire 协议必须保留; 实际={result!r}"
        )
