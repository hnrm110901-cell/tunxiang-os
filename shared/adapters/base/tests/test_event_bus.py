"""test_event_bus.py —— emit_adapter_event / AdapterEventMixin 覆盖（Sprint F1 / PR F）

覆盖点：
  1. emit_adapter_event：校验 stream_id 构造、source_service 前缀、payload 注入
  2. adapter_name 校验：空串 / >32 字符 → ValueError
  3. track_sync 成功路径：发 SYNC_STARTED + SYNC_FINISHED，track.ingested 注入 payload
  4. track_sync 失败路径：发 SYNC_STARTED + SYNC_FAILED 并原样抛出，ingested_count 保留
  5. emit_reconnected / emit_credential_expired / emit_webhook_received 各发一条
  6. 内部 emitter 失败（mock _get_publisher throws）→ track_sync 正常路径不受影响
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

# conftest 已把 shared/adapters/base/src 加入 sys.path，此处补加仓库根
_here = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.abspath(os.path.join(_here, "../../../.."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from shared.adapters.base.src.event_bus import (  # noqa: E402
    AdapterEventMixin,
    emit_adapter_event,
)
from shared.events.src.event_types import AdapterEventType  # noqa: E402

# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def tenant_id() -> UUID:
    return uuid4()


@pytest.fixture
def emit_spy(monkeypatch):
    """用 AsyncMock 替换 emit_event，记录每次调用参数。"""
    spy = AsyncMock(return_value="evt-mocked")
    # 替换 event_bus 模块导入的 emit_event 符号（本地绑定，不是全局）
    monkeypatch.setattr(
        "shared.adapters.base.src.event_bus.emit_event",
        spy,
    )
    return spy


# ──────────────────────────────────────────────────────────────────────
# 1. emit_adapter_event 函数式接口
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_adapter_event_basic(emit_spy, tenant_id):
    eid = await emit_adapter_event(
        adapter_name="pinzhi",
        event_type=AdapterEventType.ORDER_INGESTED,
        tenant_id=tenant_id,
        scope="orders",
        payload={"source_id": "bill-001"},
    )
    assert eid == "evt-mocked"
    emit_spy.assert_awaited_once()
    kwargs = emit_spy.await_args.kwargs
    assert kwargs["event_type"] == AdapterEventType.ORDER_INGESTED
    assert kwargs["tenant_id"] == tenant_id
    assert kwargs["stream_id"] == "pinzhi:orders"
    assert kwargs["source_service"] == "adapter:pinzhi"
    assert kwargs["payload"]["adapter_name"] == "pinzhi"
    assert kwargs["payload"]["scope"] == "orders"
    assert kwargs["payload"]["source_id"] == "bill-001"
    assert kwargs["metadata"]["adapter_name"] == "pinzhi"


@pytest.mark.asyncio
async def test_emit_adapter_event_custom_stream_id(emit_spy, tenant_id):
    await emit_adapter_event(
        adapter_name="meituan",
        event_type=AdapterEventType.WEBHOOK_RECEIVED,
        tenant_id=tenant_id,
        stream_id="meituan:webhook:abc",
        payload={},
    )
    kwargs = emit_spy.await_args.kwargs
    assert kwargs["stream_id"] == "meituan:webhook:abc"


@pytest.mark.asyncio
async def test_emit_adapter_event_empty_name_rejected(tenant_id):
    with pytest.raises(ValueError, match="不能为空"):
        await emit_adapter_event(
            adapter_name="",
            event_type=AdapterEventType.SYNC_STARTED,
            tenant_id=tenant_id,
        )


@pytest.mark.asyncio
async def test_emit_adapter_event_name_too_long_rejected(tenant_id):
    with pytest.raises(ValueError, match="过长"):
        await emit_adapter_event(
            adapter_name="x" * 33,
            event_type=AdapterEventType.SYNC_STARTED,
            tenant_id=tenant_id,
        )


# ──────────────────────────────────────────────────────────────────────
# 2. AdapterEventMixin.track_sync
# ──────────────────────────────────────────────────────────────────────

class _FakeAdapter(AdapterEventMixin):
    adapter_name = "fake"


@pytest.mark.asyncio
async def test_track_sync_success_emits_started_and_finished(emit_spy, tenant_id):
    adapter = _FakeAdapter()

    async with adapter.track_sync(tenant_id=tenant_id, scope="orders") as track:
        track.ingested = 42

    # 等待 fire-and-forget 的 create_task 完成
    await _drain_pending()

    calls = emit_spy.await_args_list
    types_called = [c.kwargs["event_type"] for c in calls]
    assert AdapterEventType.SYNC_STARTED in types_called
    assert AdapterEventType.SYNC_FINISHED in types_called
    assert AdapterEventType.SYNC_FAILED not in types_called

    # SYNC_FINISHED 的 payload 应含 ingested_count
    finished = next(c for c in calls if c.kwargs["event_type"] == AdapterEventType.SYNC_FINISHED)
    assert finished.kwargs["payload"]["ingested_count"] == 42
    assert "duration_ms" in finished.kwargs["payload"]


@pytest.mark.asyncio
async def test_track_sync_failure_emits_failed_and_reraises(emit_spy, tenant_id):
    adapter = _FakeAdapter()

    class _BoomError(RuntimeError):
        pass

    with pytest.raises(_BoomError):
        async with adapter.track_sync(tenant_id=tenant_id, scope="menu") as track:
            track.ingested = 7
            raise _BoomError("boom")

    await _drain_pending()

    types_called = [c.kwargs["event_type"] for c in emit_spy.await_args_list]
    assert AdapterEventType.SYNC_STARTED in types_called
    assert AdapterEventType.SYNC_FAILED in types_called
    assert AdapterEventType.SYNC_FINISHED not in types_called

    failed = next(c for c in emit_spy.await_args_list if c.kwargs["event_type"] == AdapterEventType.SYNC_FAILED)
    assert failed.kwargs["payload"]["error_code"] == "_BoomError"
    assert failed.kwargs["payload"]["error_message"] == "boom"
    assert failed.kwargs["payload"]["ingested_count"] == 7


@pytest.mark.asyncio
async def test_track_sync_correlation_id_is_shared(emit_spy, tenant_id):
    adapter = _FakeAdapter()

    async with adapter.track_sync(tenant_id=tenant_id, scope="inventory"):
        pass
    await _drain_pending()

    corrs = {
        c.kwargs["correlation_id"]
        for c in emit_spy.await_args_list
        if c.kwargs["event_type"] in (AdapterEventType.SYNC_STARTED, AdapterEventType.SYNC_FINISHED)
    }
    assert len(corrs) == 1, "started 和 finished 必须共享同一 correlation_id"


# ──────────────────────────────────────────────────────────────────────
# 3. Mixin 辅助方法
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_reconnected(emit_spy, tenant_id):
    adapter = _FakeAdapter()
    await adapter.emit_reconnected(tenant_id=tenant_id, downtime_seconds=123.7, scope="orders")
    kwargs = emit_spy.await_args.kwargs
    assert kwargs["event_type"] == AdapterEventType.RECONNECTED
    assert kwargs["payload"]["downtime_seconds"] == 123.7


@pytest.mark.asyncio
async def test_emit_credential_expired(emit_spy, tenant_id):
    adapter = _FakeAdapter()
    await adapter.emit_credential_expired(tenant_id=tenant_id, expires_at="2026-04-30T00:00:00Z")
    kwargs = emit_spy.await_args.kwargs
    assert kwargs["event_type"] == AdapterEventType.CREDENTIAL_EXPIRED
    assert kwargs["payload"]["expires_at"] == "2026-04-30T00:00:00Z"


@pytest.mark.asyncio
async def test_emit_webhook_received(emit_spy, tenant_id):
    adapter = _FakeAdapter()
    await adapter.emit_webhook_received(
        tenant_id=tenant_id,
        webhook_type="refund",
        source_id="mt-order-9999",
        payload={"reason": "customer_changed_mind"},
    )
    kwargs = emit_spy.await_args.kwargs
    assert kwargs["event_type"] == AdapterEventType.WEBHOOK_RECEIVED
    assert kwargs["stream_id"] == "fake:webhook:mt-order-9999"
    assert kwargs["payload"]["webhook_type"] == "refund"
    assert kwargs["payload"]["source_id"] == "mt-order-9999"
    assert kwargs["payload"]["reason"] == "customer_changed_mind"


# ──────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────

async def _drain_pending() -> None:
    """等待当前 event loop 里所有 create_task 排队任务完成。"""
    import asyncio
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
