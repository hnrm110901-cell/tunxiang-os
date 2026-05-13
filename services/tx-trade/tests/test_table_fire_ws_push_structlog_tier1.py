"""Tier 1 回归测试：push_table_ready_ws structlog kwarg 冲突 (Issue #568)

PR #566 (Closes #562) 同模式 follow-up — table_production_plan.push_table_ready_ws
有两层 structlog 冲突：

修前：
  L88: log = logger.bind(store_id=..., tenant_id=..., event=event)
       → 不抛但 event 字段会被 L89 positional 静默覆盖（dead state）
  L89: log.info("table_fire.ws_push", ..., event=event)
       → TypeError: meth() got multiple values for argument 'event'

修后：
  L88: log = logger.bind(store_id=..., tenant_id=..., notify_event=event)
  L89: log.info("table_fire.ws_push", ..., notify_event=event)

业务场景（真实餐厅）：
  - 200 桌晚高峰：每桌点单 → 拆单到热菜/凉菜/汤档 → 各档完成后调
    TableFireCoordinator.notify_dept_ready
  - 全档就绪（all_ready=True）→ 调 push_table_ready_ws 推送 "table_ready" WebSocket 信号
  - 修前：L89 抛 TypeError → 异常被 caller L297 except 兜底 → log.error 误判为
    "ws_push_failed"（Redis push 失败）→ 实际 Redis 永不执行 →
    mac-station / ExpoStation 收不到 table_ready → 后厨传菜员未被通知 → 出餐延迟

业务影响：P1（影响门店运营 KDS / ExpoStation 出餐信号丢失，不影响订单/资金）

关联：
  - Issue #568 (PR #566 同模式 follow-up; Closes #562)
  - 参照范本：test_delivery_adapter_notify_platform_tier1.py (PR #566)
  - 注意：Redis pub/sub wire payload (L94 \"event\": event) 是消息格式，保留不动
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── 路径 ──────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── pytest collection guard ──────────────────────────────────────────────────
# table_production_plan 顶层 import shared.events.UniversalPublisher,
# 间接拖 shared.events 用 `dataclass(slots=True)`, 仅 Python 3.10+ 支持.
# CI Python 3.11 原生通过. 用 sys.version_info gate (PR-A round-1 教训:
# 不用 sys.modules stub 污染同目录其他 tier1 测试).
if sys.version_info < (3, 10):
    pytest.skip(
        "需 Python 3.10+ (shared.events 用 dataclass slots=True); CI Python 3.11 跑通",
        allow_module_level=True,
    )


STORE_ID = "00000000-0000-0000-0000-000000000002"
TENANT_ID = "00000000-0000-0000-0000-000000000001"


class TestPushTableReadyWsStructlogCollisionTier1:
    """Issue #568 — push_table_ready_ws 两层 structlog event= 冲突回归."""

    def test_push_table_ready_ws_no_typeerror_with_event_kwarg(self):
        """场景：200 桌晚高峰 all_ready=True 触发推送 → log.info 不应抛
        TypeError(multiple values for 'event')."""
        from services.tx_trade.src.services.table_production_plan import (  # noqa: E402
            push_table_ready_ws,
        )

        # Mock Redis publisher (不真打 Redis)
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(return_value=1)

        with patch(
            "services.tx_trade.src.services.table_production_plan.UniversalPublisher"
        ) as mock_publisher:
            mock_publisher.get_redis = AsyncMock(return_value=mock_redis)

            # 直接跑 coroutine — 修前 L89 立即抛 TypeError
            asyncio.get_event_loop().run_until_complete(
                push_table_ready_ws(
                    store_id=STORE_ID,
                    tenant_id=TENANT_ID,
                    event="table_ready",
                    data={
                        "plan_id": "plan-001",
                        "order_id": "order-001",
                        "table_no": "B01",
                    },
                )
            )

        # Redis publish 必须被调用 (修前 L89 TypeError 阻断 L91 之后所有代码,
        # 修后 Redis 流程正常执行)
        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args
        # publish(channel, payload) - channel 格式 table_fire:{tenant}:{store}
        channel = call_args[0][0]
        assert channel == f"table_fire:{TENANT_ID}:{STORE_ID}"

    def test_push_table_ready_ws_log_uses_notify_event_kwarg(self):
        """log 包含 notify_event=<event_str>（修后正确字段名），
        且 event 字段值为 structlog 保留的 event_name='table_fire.ws_push'."""
        import structlog
        from structlog.testing import capture_logs

        from services.tx_trade.src.services.table_production_plan import (  # noqa: E402
            push_table_ready_ws,
        )

        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(return_value=1)

        with patch(
            "services.tx_trade.src.services.table_production_plan.UniversalPublisher"
        ) as mock_publisher:
            mock_publisher.get_redis = AsyncMock(return_value=mock_redis)

            with capture_logs() as logs:
                asyncio.get_event_loop().run_until_complete(
                    push_table_ready_ws(
                        store_id=STORE_ID,
                        tenant_id=TENANT_ID,
                        event="table_ready",
                        data={"plan_id": "plan-002", "table_no": "C01"},
                    )
                )

        # 必须捕获到 table_fire.ws_push log 记录
        ws_push_logs = [
            log for log in logs if log.get("event") == "table_fire.ws_push"
        ]
        assert len(ws_push_logs) == 1, (
            f"应捕获 1 条 table_fire.ws_push log；实际 {len(ws_push_logs)} 条: {logs!r}"
        )
        entry = ws_push_logs[0]

        # 修后 payload 字段 rename: event= → notify_event=
        assert entry.get("notify_event") == "table_ready", (
            f"log 必须含 notify_event='table_ready' 字段；实际 entry={entry!r}"
        )
        # 修后 event 字段是 structlog event_name (positional), 不是 table_ready
        assert entry["event"] == "table_fire.ws_push", (
            f"event 应是 structlog event_name='table_fire.ws_push'; 实际={entry['event']!r}"
        )
        # bind context 保留: store_id / tenant_id / notify_event
        assert entry.get("store_id") == STORE_ID
        assert entry.get("tenant_id") == TENANT_ID
        # table_no 来自 info() kwargs
        assert entry.get("table_no") == "C01"

    def test_push_table_ready_ws_redis_payload_event_field_preserved(self):
        """Redis pub/sub wire payload 必须保留 'event' 字段 — mac-station 消费协议依赖.
        本 fix 仅 rename structlog kwarg, 不动 wire format."""
        import json

        from services.tx_trade.src.services.table_production_plan import (  # noqa: E402
            push_table_ready_ws,
        )

        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(return_value=1)

        with patch(
            "services.tx_trade.src.services.table_production_plan.UniversalPublisher"
        ) as mock_publisher:
            mock_publisher.get_redis = AsyncMock(return_value=mock_redis)

            asyncio.get_event_loop().run_until_complete(
                push_table_ready_ws(
                    store_id=STORE_ID,
                    tenant_id=TENANT_ID,
                    event="table_ready",
                    data={
                        "plan_id": "plan-003",
                        "table_no": "D01",
                        "ready_at": "2026-05-13T20:00:00Z",
                    },
                )
            )

        # parse Redis payload JSON
        call_args = mock_redis.publish.call_args
        payload_str = call_args[0][1]
        payload = json.loads(payload_str)

        # wire protocol: 'event' 字段必须保留 (mac-station 消费协议依赖)
        assert payload.get("event") == "table_ready", (
            f"Redis payload 'event' 字段必须保留 wire protocol; 实际={payload!r}"
        )
        assert payload.get("store_id") == STORE_ID
        # data 字段铺平进 payload
        assert payload.get("plan_id") == "plan-003"
        assert payload.get("table_no") == "D01"

    def test_push_table_ready_ws_signature_unchanged(self):
        """函数签名 (store_id, tenant_id, event, data) 不变 — caller L291
        notify_dept_ready 用 event= kwarg 调用, 保持兼容."""
        from services.tx_trade.src.services.table_production_plan import (  # noqa: E402
            push_table_ready_ws,
        )

        sig = inspect.signature(push_table_ready_ws)
        params = list(sig.parameters.keys())
        assert params == ["store_id", "tenant_id", "event", "data"], (
            f"签名应保持不变；实际 params={params}"
        )
