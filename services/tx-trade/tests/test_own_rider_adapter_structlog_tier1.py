"""Tier 1 回归测试：own_rider_adapter._publish_to_rider_app structlog kwarg 冲突 (Issue #573)

PR #566 (Closes #562) + PR #570 (Closes #568) 同模式 follow-up — 跨服务 multi-line
ripgrep 扫描发现 OwnRiderAdapter 内核推送方法存在同 structlog 保留字段 `event` 与
payload kwarg 冲突 bug.

修前 (origin/main `cc518e39` 之前):
  logger.info("own_rider.publish_to_app", event=event, store_id=..., payload_keys=...)
  → structlog 把第一个 positional 当 event_name 字段（保留字段 'event'）,
    payload 又传 `event=` kwarg → TypeError: multiple values for argument 'event'.

修后:
  payload kwarg rename → `dispatch_event=event` 避免冲突.

业务场景（真实餐厅自有骑手池）:
  - dispatch()           → "rider.new_dispatch"     (订单已派单 → 推送骑手 App 接单)
  - cancel()             → "rider.dispatch_cancelled" (取消派单 → 通知骑手停止接单)
  - notify_pickup_ready() → "rider.pickup_ready"     (KDS 出餐完成 → 通知骑手到店取餐)

修前: 3 路径全在 200 桌晚高峰 + 自有骑手池启用门店触发 TypeError →
  - dispatch 抛异常 → 调用方拿不到 provider_order_id → 回滚或重试 (派单失败)
  - cancel 抛异常 → 骑手 App 不知取消 → 可能上门取餐
  - notify_pickup_ready 抛异常 → 骑手不知何时取餐 → 出餐延迟/餐凉

归 P1: 影响门店运营 (自有骑手 dispatch 全链路), 不影响订单/资金正确性.

关联:
  - Issue #573 (PR #566/#570 同模式 cross-service follow-up)
  - 跨行调用 grep 漏抓教训: 单行 `grep ', *event='` 漏掉 multi-line kwargs,
    future structlog 扫描必须用 `rg --multiline`
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
# own_rider_adapter 仅依赖 base 同目录纯 dataclass + structlog + asyncio,
# 不拖 shared.ontology / shared.events. 理论可在 Python 3.9 跑.
# 但 base.py 用 `@dataclass(frozen=True)` 未用 slots, 兼容 3.9. 不需要 skip.
# 仍保留 sys.version gate 以与 PR #566/#570 同范本对齐 (避免 collection 漂移).
if sys.version_info < (3, 10):
    pytest.skip(
        "本机 Python 3.9 跳过; CI Python 3.11 跑通 (与 PR #566/#570 同范本)",
        allow_module_level=True,
    )


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
STORE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _make_adapter():
    """构造 OwnRiderAdapter; _publish_to_rider_app 不触碰 DB 不需 session."""
    from services.tx_trade.src.services.delivery_dispatch_adapters.base import (  # noqa: E402
        ProviderConfigSnapshot,
    )
    from services.tx_trade.src.services.delivery_dispatch_adapters.own_rider_adapter import (  # noqa: E402
        OwnRiderAdapter,
    )

    config = ProviderConfigSnapshot(
        provider="self_rider",
        tenant_id=str(TENANT_ID),
        store_id=str(STORE_ID),
    )
    return OwnRiderAdapter(config)


class TestOwnRiderPublishStructlogCollisionTier1:
    """Issue #573 — structlog 保留字段 `event` 与 payload kwarg 冲突回归测试."""

    def test_publish_no_typeerror_with_event_kwarg(self):
        """场景: dispatch/cancel/notify_pickup_ready 3 caller 全经过 _publish_to_rider_app,
        每次传不同 event 字符串. 旧版任一次都会抛 TypeError(multiple values for 'event')."""
        adapter = _make_adapter()

        for event_name in ("rider.new_dispatch", "rider.dispatch_cancelled", "rider.pickup_ready"):
            result = asyncio.get_event_loop().run_until_complete(
                adapter._publish_to_rider_app(event_name, {"foo": "bar"})
            )
            assert result is True, f"_publish_to_rider_app 应返回 True, event={event_name}"

    def test_publish_log_uses_dispatch_event_kwarg(self):
        """log 包含 dispatch_event=<event_str>（修后正确字段名）,
        且 event 字段值为 structlog 保留的 event_name='own_rider.publish_to_app'."""
        import structlog
        from structlog.testing import capture_logs

        adapter = _make_adapter()

        with capture_logs() as logs:
            asyncio.get_event_loop().run_until_complete(
                adapter._publish_to_rider_app(
                    "rider.pickup_ready",
                    {"dispatch_id": "DSP-001", "provider_order_id": "OWN-XXXX"},
                )
            )

        publish_logs = [
            log for log in logs if log.get("event") == "own_rider.publish_to_app"
        ]
        assert len(publish_logs) == 1, (
            f"应捕获 1 条 own_rider.publish_to_app log; 实际 {len(publish_logs)} 条: {logs!r}"
        )
        entry = publish_logs[0]
        # 修后 dispatch_event 字段含 caller 的 event 名
        assert entry.get("dispatch_event") == "rider.pickup_ready", (
            f"dispatch_event 应是 caller event 字符串; 实际 entry={entry!r}"
        )
        # 修后 event 字段是 structlog event_name, 不是 'rider.pickup_ready'
        assert entry["event"] == "own_rider.publish_to_app", (
            f"event 应是 structlog event_name='own_rider.publish_to_app'; 实际={entry['event']!r}"
        )
        # store_id 字段保持原样, payload_keys 含 caller 传入的 payload key 名
        assert entry.get("store_id") == str(STORE_ID)
        assert set(entry.get("payload_keys", [])) == {"dispatch_id", "provider_order_id"}

    def test_publish_e2e_via_dispatch_cancel_pickup_ready(self):
        """3 caller 端到端 (dispatch / cancel / notify_pickup_ready) 都触发
        _publish_to_rider_app, 修前任一会抛 TypeError, 修后全部正常返回."""
        from services.tx_trade.src.services.delivery_dispatch_adapters.base import (  # noqa: E402
            DispatchOrderInput,
        )

        adapter = _make_adapter()
        loop = asyncio.get_event_loop()

        # 1) dispatch — 写新订单到骑手 App
        order = DispatchOrderInput(
            dispatch_id="DSP-TEST-1",
            order_id="ORD-TEST-1",
            store_id=str(STORE_ID),
            delivery_address="湖南省长沙市天心区屯象大厦 1 楼",
            delivery_lat=28.1234,
            delivery_lng=112.5678,
            distance_meters=1200,
            delivery_fee_fen=600,
            tip_fen=200,
            estimated_minutes=30,
        )
        dispatch_result = loop.run_until_complete(adapter.dispatch(order))
        assert dispatch_result.success is True
        assert dispatch_result.provider_order_id is not None

        # 2) cancel — 取消派单
        cancel_result = loop.run_until_complete(
            adapter.cancel(dispatch_result.provider_order_id, reason="顾客退单")
        )
        assert cancel_result is True

        # 3) notify_pickup_ready — KDS 出餐完成
        pickup_result = loop.run_until_complete(
            adapter.notify_pickup_ready(
                provider_order_id=dispatch_result.provider_order_id,
                dispatch_id="DSP-TEST-1",
            )
        )
        assert pickup_result is True

    def test_publish_signature_unchanged(self):
        """函数签名 (self, event, payload) 不变 — dispatch/cancel/notify_pickup_ready 3 caller
        全 positional 调用, 保持兼容."""
        import inspect

        from services.tx_trade.src.services.delivery_dispatch_adapters.own_rider_adapter import (  # noqa: E402
            OwnRiderAdapter,
        )

        sig = inspect.signature(OwnRiderAdapter._publish_to_rider_app)
        params = list(sig.parameters.keys())
        assert params == ["self", "event", "payload"], (
            f"签名应保持不变; 实际 params={params}"
        )
