"""Tier 1 回归测试：delivery_adapter._notify_platform structlog kwarg 冲突 (Issue #562)

PR-F §19 reviewer P2#1 follow-up。

修前 (origin/main `d98a23e0` 之前)：
  logger.info("platform_notified", platform=..., event=event_str, data=...)
  → structlog 把第一个 positional 当作 event_name 字段（保留字段 'event'），
    payload 又传 `event=` kwarg → TypeError: multiple values for argument 'event'.

修后：
  payload kwarg rename → `notify_event=event` 避免冲突。

业务场景（真实餐厅）：
  - 美团/饿了么/抖音外卖 webhook 触发 confirm/ready/cancel/complete 4 state machine 路径
  - 路径在 session.commit() 成功后调用 _notify_platform 通知平台
  - 修前：状态已落库 ✅ 但 _notify_platform 抛 TypeError → API caller 见异常 + log 噪音
  - 修后：4 路径 + 直接调用均不抛 TypeError，log 含 `notify_event` 而非 `event` 冲突

关联：
  - Issue #562 (P2 follow-up from PR-F #563)
  - docs/security/tier1-row-lock-audit-2026-05.md §4.1.5 (delivery_adapter row-lock audit)
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

import pytest


# ── 路径 ──────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── pytest collection guard ──────────────────────────────────────────────────
# delivery_adapter 顶层 import shared.ontology.src.database，间接拖 shared.events
# 用 `dataclass(slots=True)`，仅 Python 3.10+ 支持。本机 3.9 跑会 TypeError；
# CI Python 3.11 原生通过。用 sys.version_info gate 而非 sys.modules stub
# （PR-A round-1 教训：stub 注入 'shared' 包污染同目录其他 tier1 测试）.
if sys.version_info < (3, 10):
    pytest.skip(
        "需 Python 3.10+ (shared.events 用 dataclass slots=True)；CI Python 3.11 跑通",
        allow_module_level=True,
    )


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
STORE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
BRAND_ID = uuid.UUID("00000000-0000-0000-0000-000000000004")


def _make_adapter():
    """构造 DeliveryPlatformAdapter；_notify_platform 不触碰 DB 不需 session."""
    from services.tx_trade.src.services.delivery_adapter import (  # noqa: E402
        DeliveryPlatformAdapter,
    )

    return DeliveryPlatformAdapter(
        store_id=str(STORE_ID),
        brand_id=str(BRAND_ID),
        tenant_id=str(TENANT_ID),
    )


class TestNotifyPlatformStructlogCollisionTier1:
    """Issue #562 — structlog 保留字段 `event` 与 payload kwarg 冲突回归测试."""

    def test_notify_platform_no_typeerror_with_event_kwarg(self):
        """场景：confirm_order/mark_ready/cancel_order/complete_order 4 路径
        commit 后调用 _notify_platform(platform, event='order_xxx', data=...)
        不应抛 TypeError(multiple values for 'event')."""
        adapter = _make_adapter()

        # 直接 await 跑 coroutine — 旧版若 event= 与 structlog 保留字段冲突会立即抛
        asyncio.get_event_loop().run_until_complete(
            adapter._notify_platform(
                platform="meituan",
                event="order_confirmed",
                data={"platform_order_id": "MT_TEST_001", "estimated_ready_min": 25},
            )
        )

    def test_notify_platform_log_uses_notify_event_kwarg(self):
        """log 包含 notify_event=<event_str>（修后正确字段名），
        且 event 字段值为 structlog 保留的 event_name='platform_notified'."""
        import structlog
        from structlog.testing import capture_logs

        adapter = _make_adapter()

        with capture_logs() as logs:
            asyncio.get_event_loop().run_until_complete(
                adapter._notify_platform(
                    platform="eleme",
                    event="order_ready",
                    data={"platform_order_id": "EL_TEST_002"},
                )
            )

        # 必须捕获到 platform_notified log 记录
        platform_notified = [
            log for log in logs if log.get("event") == "platform_notified"
        ]
        assert len(platform_notified) == 1, (
            f"应捕获 1 条 platform_notified log；实际 {len(platform_notified)} 条："
            f"{logs!r}"
        )
        entry = platform_notified[0]

        # 修后 payload 字段 rename: event= → notify_event=
        assert entry.get("notify_event") == "order_ready", (
            f"log 必须含 notify_event='order_ready' 字段；实际 entry={entry!r}"
        )
        # 修后 event 字段是 structlog event_name，不是 order_ready
        assert entry["event"] == "platform_notified", (
            f"event 应是 structlog event_name='platform_notified'；实际={entry['event']!r}"
        )
        # platform / data 字段保持原样
        assert entry.get("platform") == "eleme"
        assert entry.get("data") == {"platform_order_id": "EL_TEST_002"}

    def test_notify_platform_signature_unchanged(self):
        """函数签名 (platform, event, data) 不变 — 4 callers 全 positional，保持兼容."""
        import inspect

        from services.tx_trade.src.services.delivery_adapter import (  # noqa: E402
            DeliveryPlatformAdapter,
        )

        sig = inspect.signature(DeliveryPlatformAdapter._notify_platform)
        params = list(sig.parameters.keys())
        # self + platform + event + data (signature 不动避免 caller side 联动)
        assert params == ["self", "platform", "event", "data"], (
            f"签名应保持不变；实际 params={params}"
        )
