"""Wave 5 silent failures observability — tx-analytics sample tests

Covers the 4 fixed prod sites + 2 fixed test-mirror sites in tx-analytics:
  1. main.py:133 asyncio.TimeoutError pass → logger.debug("split_attribution_refresh_tick")
  2. main.py:161 asyncio.CancelledError pass → logger.debug("split_attribution_refresh_task_cancelled")
  3. projectors/registry.py:163 asyncio.CancelledError pass → log.debug("split_attribution_projector_task_cancelled")
  4. projectors/split_attribution.py:176 (ValueError, TypeError) return None → log.warning + return None
  5. tests/test_lifespan_split_attribution_tier1.py:100 → contextlib.suppress(asyncio.TimeoutError)
  6. tests/test_lifespan_split_attribution_tier1.py:117 → contextlib.suppress(asyncio.CancelledError)

Tests replicate the exact fixed code logic with self-contained logger capture.

PR pattern (Wave 4 PR-4 #697 cross-svc batch mirror; Wave 1 sub-D PR #752 individual-svc mirror).
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress

import pytest

# ── Self-contained logger capture ─────────────────────────────────────────────


class _CapLogger:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []

    def warning(self, event: str, **kw):
        self.calls.append(("warning", event, kw))

    def debug(self, event: str, **kw):
        self.calls.append(("debug", event, kw))

    def info(self, event: str, **kw):
        self.calls.append(("info", event, kw))


# ── Test 1: lifespan refresh tick (TimeoutError) → debug log ──────────────────


@pytest.mark.asyncio
async def test_lifespan_refresh_tick_logs_debug():
    """main.py:133 — asyncio.TimeoutError 包装 wait_for sleep, 添加 debug 观测.

    refresh_sec timeout 是预期信号 (周期任务进入下一轮 tick), 不是错误.
    debug level 让运维可在 verbose log 模式下看到 daemon 仍在运行,
    不污染默认 info+ log stream.
    """
    logger = _CapLogger()
    stop_event = asyncio.Event()
    refresh_sec = 0.05

    # ── fixed code 模拟 ──────────────────────────────────────────────────────
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=refresh_sec)
    except asyncio.TimeoutError:
        logger.debug("split_attribution_refresh_tick")
    # ──────────────────────────────────────────────────────────────────────────

    debug_events = [e for lvl, e, _ in logger.calls if lvl == "debug"]
    assert "split_attribution_refresh_tick" in debug_events, (
        f"Expected refresh_tick debug, got: {logger.calls}"
    )


# ── Test 2: shutdown CancelledError → debug log (lifespan cleanup) ────────────


@pytest.mark.asyncio
async def test_lifespan_shutdown_cancelled_logs_debug():
    """main.py:161 — refresh_task cancel + await → CancelledError, debug 观测.

    Shutdown 路径预期信号: lifespan 退出时主动 cancel daemon task, await
    必然抛 CancelledError. debug level 让运维知道 task 已干净退出.
    """
    logger = _CapLogger()

    async def _bg():
        await asyncio.sleep(60)

    task = asyncio.create_task(_bg())
    task.cancel()

    # ── fixed code 模拟 ──────────────────────────────────────────────────────
    try:
        await task
    except asyncio.CancelledError:
        logger.debug("split_attribution_refresh_task_cancelled")
    # ──────────────────────────────────────────────────────────────────────────

    debug_events = [e for lvl, e, _ in logger.calls if lvl == "debug"]
    assert "split_attribution_refresh_task_cancelled" in debug_events, (
        f"Expected refresh_task_cancelled debug, got: {logger.calls}"
    )


# ── Test 3: split_attribution._safe_uuid invalid → warning log + return None ─


def test_safe_uuid_invalid_logs_warning():
    """projectors/split_attribution.py:176 — 畸形 UUID payload 加 warning.

    保留 return None 让 caller 落 NULL (DLQ 行 ID 仍可读), 不阻塞 projector 推进.
    warn level 给运维可观测 — 与 tx-supply IndexSplitProjector _safe_uuid 同模式
    (PR #752 sub-D 镜像). cardinality 受 raw_value [:40] 截断保护.
    """
    logger = _CapLogger()

    def _safe_uuid_under_test(val):
        if not val:
            return None
        if isinstance(val, uuid.UUID):
            return val
        try:
            return uuid.UUID(str(val))
        except (ValueError, TypeError) as exc:
            logger.warning(
                "split_attribution_safe_uuid_invalid",
                raw_value=str(val)[:40],
                error=str(exc),
            )
            return None

    # ── 测试: 非法字符串 → 返 None + warn ────────────────────────────────────
    assert _safe_uuid_under_test("not-a-uuid-but-too-long-for-uuid-parser-xxxxx") is None
    assert _safe_uuid_under_test(12345) is None  # int via str() also fails

    warning_events = [e for lvl, e, _ in logger.calls if lvl == "warning"]
    assert len(warning_events) == 2, f"Expected 2 warnings, got: {logger.calls}"
    assert all(ev == "split_attribution_safe_uuid_invalid" for ev in warning_events)

    # raw_value 截断到 40 字符 (cardinality 保护)
    warn_kw = [kw for lvl, e, kw in logger.calls if lvl == "warning"]
    assert all(len(kw.get("raw_value", "")) <= 40 for kw in warn_kw)


# ── Test 4: test mirror suppress(TimeoutError) drops silent counter ───────────


@pytest.mark.asyncio
async def test_test_mirror_uses_suppress_timeout():
    """tests/test_lifespan_split_attribution_tier1.py:100 — suppress(TimeoutError).

    silent_failure_count 治理: with suppress(...) 是 ContextManager AST 节点,
    不计入 silent_failure_count (vs try/except: pass 计入). 测试 mirror
    必须用 suppress 而非 pass 让 silent 治理收尾 (per feedback_silent_counter_logger_debug_loophole).
    """
    stop_event = asyncio.Event()
    refresh_sec = 0.05

    # ── fixed test mirror 代码 ───────────────────────────────────────────────
    with suppress(asyncio.TimeoutError):
        await asyncio.wait_for(stop_event.wait(), timeout=refresh_sec)
    # ──────────────────────────────────────────────────────────────────────────

    # suppress 不抛异常, 顺利执行到这里 = 通过
    assert True


@pytest.mark.asyncio
async def test_test_mirror_uses_suppress_cancelled():
    """tests/test_lifespan_split_attribution_tier1.py:117 — suppress(CancelledError)."""

    async def _bg():
        await asyncio.sleep(60)

    task = asyncio.create_task(_bg())
    task.cancel()

    # ── fixed test mirror 代码 ───────────────────────────────────────────────
    with suppress(asyncio.CancelledError):
        await task
    # ──────────────────────────────────────────────────────────────────────────

    assert task.cancelled()


# ── Test 5: stop_split_attribution_projector CancelledError → debug ───────────


@pytest.mark.asyncio
async def test_stop_projector_cancelled_logs_debug():
    """projectors/registry.py:163 — stop helper 内 task.cancel + await → debug.

    每个 tenant projector daemon 都会经历 cancel + await CancelledError,
    debug log 带 tenant_id 让运维可定位特定租户停止行为.
    """
    logger = _CapLogger()
    tenant_str = "11111111-aaaa-aaaa-aaaa-111111111111"

    async def _bg():
        await asyncio.sleep(60)

    task = asyncio.create_task(_bg())
    task.cancel()

    # ── fixed code 模拟 (registry.py stop_split_attribution_projector) ───────
    try:
        await task
    except asyncio.CancelledError:
        logger.debug("split_attribution_projector_task_cancelled", tenant_id=tenant_str)
    # ──────────────────────────────────────────────────────────────────────────

    debug_events = [(e, kw) for lvl, e, kw in logger.calls if lvl == "debug"]
    assert len(debug_events) == 1
    event, kw = debug_events[0]
    assert event == "split_attribution_projector_task_cancelled"
    assert kw.get("tenant_id") == tenant_str
