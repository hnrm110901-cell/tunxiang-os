"""Tier 1 邻接 unit tests for relay_worker shadow mode (W3 P0 issue #757).

强红线 (per plan §7.1):
  - shadow_mode=True: relay log + continue, 0 events.append 调用
  - shadow_mode 默认 true (env unset)
  - asyncpg PostgresConnectionError → backoff + counter inc + 不崩
  - outermost except → log warning with exc_info=True + sleep + continue

文件名带 `_tier1.py` 后缀 (per memory `feedback_tier1_test_filename_workflow_trigger.md`).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.tx_event_relay.src import relay_worker
from services.tx_event_relay.src.relay_worker import (
    RelayConfig,
    _backoff_seconds,
    _lag_seconds,
    relay_loop,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Each test starts with clean RELAY_* env."""
    for key in ("RELAY_SHADOW_MODE", "RELAY_POLL_INTERVAL_MS", "RELAY_BATCH_SIZE"):
        monkeypatch.delenv(key, raising=False)
    yield


def _sample_outbox_row(event_type: str = "ORDER.PAID") -> dict:
    """Build a minimal outbox row dict matching outbox_repo.fetch_pending_batch shape."""
    return {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "event_type": event_type,
        "stream_id": "order-12345",
        "payload": {"total_fen": 8800},
        "metadata": {},
        "source_service": "tx-trade",
        "store_id": uuid4(),
        "causation_id": None,
        "correlation_id": None,
        "created_at": datetime.now(timezone.utc),
        "delivery_attempts": 0,
        "last_error": None,
    }


@pytest.mark.asyncio
async def test_shadow_does_not_write_events():
    """强红线: shadow_mode=True 跑 5 rows, 0 真投递分支触发 (per plan §1 Phase 3 验收 #3).

    模拟 fetch_pending_batch 返 5 rows, 验证:
      1. 5 次都走 shadow log + continue
      2. 0 次 raise NotImplementedError (真投递路径未触)
      3. shutdown_event 让 loop 退出, 整个循环不崩
    """
    config = RelayConfig(shadow_mode=True, poll_interval_ms=10, batch_size=5)
    shutdown_event = asyncio.Event()
    sample_rows = [_sample_outbox_row() for _ in range(5)]

    call_count = {"fetch": 0}

    async def fake_fetch(pool, batch_size):
        call_count["fetch"] += 1
        if call_count["fetch"] == 1:
            return sample_rows
        # 第二次 polling 返回空 + 触发 shutdown
        shutdown_event.set()
        return []

    with patch.object(relay_worker, "fetch_pending_batch", side_effect=fake_fetch):
        # NotImplementedError 不应抛 (shadow_mode=True 不进真投递分支)
        await relay_loop(pool=MagicMock(), config=config, shutdown_event=shutdown_event)

    assert call_count["fetch"] >= 1, "fetch 必须被调用至少一次"
    # 5 rows 全走 shadow 分支 → loop 完整执行 1 轮 + shutdown 触发退出


@pytest.mark.asyncio
async def test_shadow_mode_default_true():
    """env unset 时 RelayConfig.shadow_mode 默认 true (防误开真投递)."""
    config = RelayConfig.from_env()
    assert config.shadow_mode is True, "默认必须 shadow_mode=True (Q1 决议)"


@pytest.mark.asyncio
async def test_shadow_mode_env_override_false(monkeypatch):
    """env RELAY_SHADOW_MODE=false 时 shadow_mode 翻为 False."""
    monkeypatch.setenv("RELAY_SHADOW_MODE", "false")
    config = RelayConfig.from_env()
    assert config.shadow_mode is False


@pytest.mark.asyncio
async def test_relay_handles_pg_unavailable_with_backoff():
    """asyncpg PostgresConnectionError → backoff + counter inc + 不崩.

    模拟 fetch_pending_batch raise PostgresConnectionError, 验证:
      1. relay_pg_failure_total inc 被调用 (counter 累计)
      2. asyncio.sleep 被调用 (backoff)
      3. 第二次 polling 仍跑 (recovery)
    """
    # 注入一个真实可 raise 的 exception class (替换 _PgConnectionError sentinel)
    class FakePgConnectionError(Exception):
        pass

    config = RelayConfig(shadow_mode=True, poll_interval_ms=10, batch_size=5)
    shutdown_event = asyncio.Event()

    call_count = {"fetch": 0, "sleep": 0}

    async def fake_fetch(pool, batch_size):
        call_count["fetch"] += 1
        if call_count["fetch"] == 1:
            raise FakePgConnectionError("connection refused")
        # 第二次 polling shutdown
        shutdown_event.set()
        return []

    original_sleep = asyncio.sleep

    async def counting_sleep(seconds):
        call_count["sleep"] += 1
        # 真实 sleep 但缩短到 0 加速测试
        await original_sleep(0)

    pg_failure_mock = MagicMock()

    with patch.object(relay_worker, "fetch_pending_batch", side_effect=fake_fetch), patch.object(
        relay_worker, "_PgConnectionError", FakePgConnectionError
    ), patch.object(relay_worker, "relay_pg_failure_total", pg_failure_mock), patch.object(
        relay_worker.asyncio, "sleep", side_effect=counting_sleep
    ):
        await relay_loop(pool=MagicMock(), config=config, shutdown_event=shutdown_event)

    assert call_count["fetch"] >= 2, "PG 失败后必须再次 polling (recovery)"
    assert call_count["sleep"] >= 1, "backoff sleep 必须被调用"
    pg_failure_mock.inc.assert_called(), "relay_pg_failure_total.inc 必须被调用"


@pytest.mark.asyncio
async def test_relay_outermost_except_logs_exc_info():
    """generic Exception → log error with exc_info=True + sleep + continue (per CLAUDE.md §14).

    模拟 fetch_pending_batch raise generic RuntimeError, 验证:
      1. logger.error called with exc_info=True
      2. relay_loop_unexpected_total inc
      3. backoff sleep + 不崩出 loop
    """
    config = RelayConfig(shadow_mode=True, poll_interval_ms=10, batch_size=5)
    shutdown_event = asyncio.Event()

    call_count = {"fetch": 0}

    async def fake_fetch(pool, batch_size):
        call_count["fetch"] += 1
        if call_count["fetch"] == 1:
            raise RuntimeError("unexpected boom")
        shutdown_event.set()
        return []

    unexpected_mock = MagicMock()
    logger_mock = MagicMock()

    original_sleep = asyncio.sleep

    async def fast_sleep(seconds):
        await original_sleep(0)

    with patch.object(relay_worker, "fetch_pending_batch", side_effect=fake_fetch), patch.object(
        relay_worker, "relay_loop_unexpected_total", unexpected_mock
    ), patch.object(relay_worker, "logger", logger_mock), patch.object(
        relay_worker.asyncio, "sleep", side_effect=fast_sleep
    ):
        await relay_loop(pool=MagicMock(), config=config, shutdown_event=shutdown_event)

    # logger.error 至少被调用一次 with exc_info=True
    error_calls = [c for c in logger_mock.error.call_args_list if c.kwargs.get("exc_info") is True]
    assert error_calls, "logger.error 必须 with exc_info=True (per CLAUDE.md §14)"
    # 第一次 error call 必须是 relay_loop_unexpected
    assert error_calls[0].args[0] == "relay_loop_unexpected"
    unexpected_mock.inc.assert_called()


@pytest.mark.asyncio
async def test_shadow_mode_false_raises_not_implemented():
    """强红线: shadow_mode=False 走真投递分支 → 抛 NotImplementedError (W11 #767 未实现).

    防止任何 env override 静默走 fall-through 路径 (silent shadow break).
    """
    config = RelayConfig(shadow_mode=False, poll_interval_ms=10, batch_size=5)
    shutdown_event = asyncio.Event()

    async def fake_fetch(pool, batch_size):
        return [_sample_outbox_row()]

    with patch.object(relay_worker, "fetch_pending_batch", side_effect=fake_fetch):
        with pytest.raises(NotImplementedError, match="W11"):
            await relay_loop(pool=MagicMock(), config=config, shutdown_event=shutdown_event)


def test_backoff_seconds_exponential_cap():
    """Backoff schedule: 1 → 2 → 4 → 8 → 16 → 30 cap."""
    assert _backoff_seconds(0) == 1.0
    assert _backoff_seconds(1) == 2.0
    assert _backoff_seconds(2) == 4.0
    assert _backoff_seconds(5) == 30.0
    assert _backoff_seconds(99) == 30.0  # cap


def test_lag_seconds_handles_none_and_naive():
    """_lag_seconds 兜底处理 None + naive datetime."""
    assert _lag_seconds(None) == 0.0
    # naive datetime → 当 UTC 处理
    past = datetime.now(timezone.utc).replace(tzinfo=None)
    lag = _lag_seconds(past)
    assert lag >= 0.0
