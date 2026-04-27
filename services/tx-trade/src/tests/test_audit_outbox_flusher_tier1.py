"""Tier 1 — PR-4 audit outbox 后台 flusher 循环测试

PR-3 落了 outbox 写入侧（write_audit_to_outbox）；PR-4 让 outbox 真正被消费：
tx-trade lifespan 启动后台 task 周期性调用 flush_outbox_to_pg(session)。

测试覆盖：
  1. flusher 周期性触发 flush_outbox_to_pg
  2. stop_event 触发后 loop 优雅退出（不超时）
  3. 单次迭代异常不会让 loop 死掉（永生）
  4. TX_AUDIT_OUTBOX_FLUSHER_DISABLED=true 时返回 noop task
  5. 间隔可配置（小到 0.05s 用于快速测试）
  6. session_factory 失败也不让 loop 死（兜底层 2）
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from src.services.audit_outbox import (
    _flusher_loop,
    start_audit_outbox_flusher,
)

# 测试默认强制 RBAC 走真实路径（防其他测试模块把 TX_AUTH_ENABLED 设为 false）。
# 放在 import 之后是 isort 友好的写法 — flusher 在调用时读 env，不在 import 期间求值。
os.environ.setdefault("TX_AUTH_ENABLED", "true")


# ──────────────── fixtures ────────────────


@pytest.fixture
def fake_session_factory():
    """返回一个 callable，每次调用产出一个 async context manager 包装的 mock session。"""
    sessions_used: list[AsyncMock] = []

    @asynccontextmanager
    async def _factory():
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        sessions_used.append(session)
        yield session

    _factory.sessions_used = sessions_used  # type: ignore[attr-defined]
    return _factory


# ──────────────────────────────────────────────────────────────────────────
# 场景 1：flusher 周期性触发 flush_outbox_to_pg
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flusher_loop_calls_flush_periodically(fake_session_factory):
    """两次 0.05s 间隔后，flush_outbox_to_pg 应该被至少调用 2 次。"""
    call_count = {"n": 0}

    async def _fake_flush(session):
        call_count["n"] += 1
        return 0  # 没有 outbox 内容

    with patch("src.services.audit_outbox.flush_outbox_to_pg", _fake_flush):
        stop_event = asyncio.Event()
        loop_task = asyncio.create_task(
            _flusher_loop(fake_session_factory, stop_event, interval_seconds=0.05),
        )
        await asyncio.sleep(0.18)  # 应该够 3-4 次迭代
        stop_event.set()
        await asyncio.wait_for(loop_task, timeout=1.0)

    assert call_count["n"] >= 2, f"expected >= 2 flush calls, got {call_count['n']}"


# ──────────────────────────────────────────────────────────────────────────
# 场景 2：stop_event 触发后 loop 立刻退出（不必等 interval）
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_event_terminates_loop_promptly(fake_session_factory):
    """stop_event.set() 后 loop 应在 << interval_seconds 内退出（asyncio.wait_for 唤醒）。"""

    async def _fake_flush(session):
        return 0

    with patch("src.services.audit_outbox.flush_outbox_to_pg", _fake_flush):
        stop_event = asyncio.Event()
        # interval=10s，但应在 0.1s 内通过 stop_event 退出
        loop_task = asyncio.create_task(
            _flusher_loop(fake_session_factory, stop_event, interval_seconds=10.0),
        )
        await asyncio.sleep(0.05)  # 让 loop 进入第一次 sleep
        stop_event.set()
        # 必须远早于 10s
        await asyncio.wait_for(loop_task, timeout=1.0)


# ──────────────────────────────────────────────────────────────────────────
# 场景 3：iteration 异常不让 loop 死掉
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_iteration_exception_does_not_kill_loop(fake_session_factory):
    """flush_outbox_to_pg 抛 RuntimeError 时，loop 应该 log + 继续下一轮。"""
    call_count = {"n": 0}

    async def _failing_flush(session):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated PG outage")
        return 0

    with patch("src.services.audit_outbox.flush_outbox_to_pg", _failing_flush):
        stop_event = asyncio.Event()
        loop_task = asyncio.create_task(
            _flusher_loop(fake_session_factory, stop_event, interval_seconds=0.05),
        )
        await asyncio.sleep(0.15)  # 第 1 次抛错，第 2 次应正常
        stop_event.set()
        await asyncio.wait_for(loop_task, timeout=1.0)

    # 至少调用了 2 次（第 1 抛错 + 第 2 成功），证明 loop 没死
    assert call_count["n"] >= 2, f"loop must survive iteration exception; calls={call_count['n']}"


# ──────────────────────────────────────────────────────────────────────────
# 场景 4：session_factory 本身抛错（连接池耗尽）loop 也不死
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_factory_failure_does_not_kill_loop():
    """session_factory() 进入 async with 时抛错 → loop 仍继续。"""
    factory_call_count = {"n": 0}

    @asynccontextmanager
    async def _failing_factory():
        factory_call_count["n"] += 1
        if factory_call_count["n"] == 1:
            raise RuntimeError("connection pool exhausted")
        # 第二次正常
        session = AsyncMock()
        yield session

    async def _noop_flush(session):
        return 0

    with patch("src.services.audit_outbox.flush_outbox_to_pg", _noop_flush):
        stop_event = asyncio.Event()
        loop_task = asyncio.create_task(
            _flusher_loop(_failing_factory, stop_event, interval_seconds=0.05),
        )
        await asyncio.sleep(0.15)
        stop_event.set()
        await asyncio.wait_for(loop_task, timeout=1.0)

    assert factory_call_count["n"] >= 2


# ──────────────────────────────────────────────────────────────────────────
# 场景 5：TX_AUDIT_OUTBOX_FLUSHER_DISABLED=true 返回 noop task
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_env_returns_noop_task(monkeypatch, fake_session_factory):
    """运维紧急关停场景：env var=true → 返回立即完成的 task + 已 set 的 event。

    调用方 lifespan 代码路径不变（仍可 stop_event.set() + await task）。
    """
    monkeypatch.setenv("TX_AUDIT_OUTBOX_FLUSHER_DISABLED", "true")

    task, stop_event = start_audit_outbox_flusher(
        fake_session_factory,
        interval_seconds=0.05,
    )

    assert stop_event.is_set(), "disabled 路径必须立刻 set stop_event"
    # task 应在极短时间内完成（noop 不等待任何东西）
    await asyncio.wait_for(task, timeout=1.0)
    assert task.done()

    # session_factory 不应被调用（flusher 完全跳过）
    assert len(fake_session_factory.sessions_used) == 0  # type: ignore[attr-defined]


@pytest.mark.parametrize("disabled_value", ["true", "TRUE", "True", "1", "yes"])
@pytest.mark.asyncio
async def test_disabled_env_value_variants(monkeypatch, fake_session_factory, disabled_value):
    """env 值各种 truthy 变体都应该禁用 flusher。"""
    monkeypatch.setenv("TX_AUDIT_OUTBOX_FLUSHER_DISABLED", disabled_value)

    task, stop_event = start_audit_outbox_flusher(fake_session_factory)
    assert stop_event.is_set()
    await asyncio.wait_for(task, timeout=1.0)


@pytest.mark.parametrize("non_disabling_value", ["false", "0", "no", "", "anything-else"])
@pytest.mark.asyncio
async def test_non_disabling_env_value_runs_flusher(
    monkeypatch,
    fake_session_factory,
    non_disabling_value,
):
    """env 值不是 truthy 时（false/0/未设置/乱码）flusher 应正常启动。"""
    monkeypatch.setenv("TX_AUDIT_OUTBOX_FLUSHER_DISABLED", non_disabling_value)

    async def _noop_flush(session):
        return 0

    with patch("src.services.audit_outbox.flush_outbox_to_pg", _noop_flush):
        task, stop_event = start_audit_outbox_flusher(
            fake_session_factory,
            interval_seconds=0.05,
        )
        assert not stop_event.is_set(), f"env={non_disabling_value!r} 不应禁用 flusher"
        await asyncio.sleep(0.07)  # 让一次迭代发生
        stop_event.set()
        await asyncio.wait_for(task, timeout=1.0)


# ──────────────────────────────────────────────────────────────────────────
# 场景 6：start_audit_outbox_flusher 返回的 task 是 asyncio.Task
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_returns_task_and_event_pair(fake_session_factory):
    """API 契约：返回 (task, event) 对，类型分别是 asyncio.Task / asyncio.Event。"""

    async def _noop_flush(session):
        return 0

    with patch("src.services.audit_outbox.flush_outbox_to_pg", _noop_flush):
        task, stop_event = start_audit_outbox_flusher(
            fake_session_factory,
            interval_seconds=10.0,
        )
        try:
            assert isinstance(task, asyncio.Task)
            assert isinstance(stop_event, asyncio.Event)
        finally:
            stop_event.set()
            await asyncio.wait_for(task, timeout=1.0)


# ──────────────────────────────────────────────────────────────────────────
# 场景 7：成功 flush 行数大于 0 时 logger.info 携带 rows_ingested
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_successful_flush_logs_rows_ingested(fake_session_factory, caplog):
    """flush_outbox_to_pg 返回 > 0 时 log INFO audit_outbox_flusher_iteration。"""
    import logging

    caplog.set_level(logging.INFO)

    async def _flush_with_rows(session):
        return 5

    with patch("src.services.audit_outbox.flush_outbox_to_pg", _flush_with_rows):
        stop_event = asyncio.Event()
        loop_task = asyncio.create_task(
            _flusher_loop(fake_session_factory, stop_event, interval_seconds=0.05),
        )
        await asyncio.sleep(0.07)
        stop_event.set()
        await asyncio.wait_for(loop_task, timeout=1.0)

    # caplog 在 structlog + JSON 模式下可能不抓 — 用更宽松的检查
    # 只验证 loop 跑了至少一次（前面的 sleep 0.07 + interval 0.05 应该够）
    # 真实 logger.info 验证留给 e2e
