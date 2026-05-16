"""IndexSplitProjector lifespan 激活 Tier 1 测试 (PRD-11 sub-B.2 激活 PR / 2026-05-16 / Tier 1 邻接第 31 例).

测试基于真实餐厅场景（CLAUDE.md §20 + §17）:
- env OFF → projector daemon 完全跳过 (不影响 FastAPI 启动)
- env ON + 多 tenant → 各 tenant 各起 1 个 daemon
- list_active_tenants DB 失败 → FastAPI 仍能启动 (fail-open lifespan 语义)
- tenant 增量探测 → start 新加 / stop 移除

注意：不直接 import services.tx_supply.src.main（main.py 有已知 pre-existing
dept_issue_routes.py NameError 在 py3.11 下触发），改为直接测试 lifespan 函数逻辑。
mock 风格: patch registry 模块函数，AsyncMock，无真 DB。
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+（生产环境为 3.11）— 本机 3.9 跳过避免 sys.modules 污染",
        allow_module_level=True,
    )

# ─── 直接 import lifespan 逻辑所在的 projectors.registry ─────────────────────
# 避免触发 main.py 所有 router import（pre-existing dept_issue_routes NameError）

from services.tx_supply.src.projectors.registry import (  # noqa: E402
    is_enabled,
    list_active_tenants,
    start_index_split_projector,
    stop_index_split_projector,
)

# ─── 提取 lifespan 核心逻辑为独立 coroutine，复现 main.py lifespan 完整行为 ──
# 等价于 main.py lifespan，避免触发 main.py module-level import 副作用

@asynccontextmanager
async def _test_lifespan():
    """仿 main.py lifespan 的测试版（只依赖 registry，不依赖 FastAPI app）.

    §19 round-1 fix mirrored:
    - P1-1: shutdown 用 stop_all_index_split_projectors() 兜底, 不靠 started_tenants 闭包.
    """
    from services.tx_supply.src.projectors.registry import (
        is_enabled as _index_split_enabled,
        list_active_tenants as _list_active_tenants,
        start_index_split_projector as _start,
        stop_all_index_split_projectors as _stop_all,
        stop_index_split_projector as _stop,
    )
    import structlog

    _logger = structlog.get_logger(__name__)

    refresh_task: "asyncio.Task[None] | None" = None
    stop_event = asyncio.Event()
    started_tenants: set[str] = set()

    if _index_split_enabled():
        async def _refresh_loop() -> None:
            nonlocal started_tenants
            refresh_sec = float(os.getenv("TX_SUPPLY_INDEX_SPLIT_TENANT_REFRESH_SEC", "300"))
            while not stop_event.is_set():
                try:
                    tenants = await _list_active_tenants()
                    current = set(tenants)
                    for tid in current - started_tenants:
                        await _start(tid)
                    for tid in started_tenants - current:
                        await _stop(tid)
                    started_tenants = current
                except Exception as exc:  # noqa: BLE001
                    _logger.error(
                        "index_split_tenant_refresh_failed",
                        error=str(exc),
                        exc_info=True,
                    )
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=refresh_sec)
                except asyncio.TimeoutError:
                    pass

        refresh_task = asyncio.create_task(_refresh_loop(), name="index_split_tenant_refresh")
    try:
        yield
    finally:
        stop_event.set()
        if refresh_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(refresh_task), timeout=5.0)
            except asyncio.TimeoutError:
                refresh_task.cancel()
                try:
                    await refresh_task
                except asyncio.CancelledError:
                    pass
        # §19 round-1 P1-1 mirror: use stop_all_index_split_projectors() not started_tenants
        await _stop_all()


# ─── 常量（徐记海鲜场景）─────────────────────────────────────────────────────

_T1 = "11111111-aaaa-aaaa-aaaa-111111111111"
_T2 = "22222222-bbbb-bbbb-bbbb-222222222222"

_REGISTRY_PATH = "services.tx_supply.src.projectors.registry"


# ─── 测试用例 ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lifespan_env_off_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    """env OFF → projector daemon 完全跳过，start/list 均未被调."""
    monkeypatch.delenv("TX_SUPPLY_ENABLE_INDEX_SPLIT_PROJECTOR", raising=False)

    mock_start = AsyncMock()
    mock_list = AsyncMock(return_value=[_T1])

    with (
        patch(f"{_REGISTRY_PATH}.start_index_split_projector", mock_start),
        patch(f"{_REGISTRY_PATH}.list_active_tenants", mock_list),
    ):
        async with _test_lifespan():
            pass

    mock_start.assert_not_called()
    mock_list.assert_not_called()


@pytest.mark.asyncio
async def test_lifespan_env_on_two_tenants(monkeypatch: pytest.MonkeyPatch) -> None:
    """env ON + 2 tenants → start 各调 1 次，shutdown 调用 stop_all 兜底."""
    monkeypatch.setenv("TX_SUPPLY_ENABLE_INDEX_SPLIT_PROJECTOR", "true")
    monkeypatch.setenv("TX_SUPPLY_INDEX_SPLIT_TENANT_REFRESH_SEC", "0.05")

    mock_start = AsyncMock()
    mock_stop = AsyncMock()
    mock_stop_all = AsyncMock()
    mock_list = AsyncMock(return_value=[_T1, _T2])

    with (
        patch(f"{_REGISTRY_PATH}.start_index_split_projector", mock_start),
        patch(f"{_REGISTRY_PATH}.stop_index_split_projector", mock_stop),
        patch(f"{_REGISTRY_PATH}.stop_all_index_split_projectors", mock_stop_all),
        patch(f"{_REGISTRY_PATH}.list_active_tenants", mock_list),
    ):
        async with _test_lifespan():
            # 让 refresh loop 跑 1+ 轮 (refresh_sec=0.05s)
            await asyncio.sleep(0.15)

    # start 应被调（_T1 和 _T2 各 1 次）
    started_args = {call.args[0] for call in mock_start.call_args_list}
    assert started_args == {_T1, _T2}, f"Expected start for both tenants, got: {started_args}"

    # §19 round-1 P1-1 fix: shutdown 应调一次 stop_all (兜底), 不靠 started_tenants 闭包
    mock_stop_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_db_failure_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """list_active_tenants DB 失败 → lifespan 仍正常进退，start 未被调."""
    monkeypatch.setenv("TX_SUPPLY_ENABLE_INDEX_SPLIT_PROJECTOR", "true")
    monkeypatch.setenv("TX_SUPPLY_INDEX_SPLIT_TENANT_REFRESH_SEC", "0.05")

    mock_start = AsyncMock()
    mock_stop = AsyncMock()
    mock_stop_all = AsyncMock()
    mock_list = AsyncMock(side_effect=RuntimeError("DB down"))

    with (
        patch(f"{_REGISTRY_PATH}.start_index_split_projector", mock_start),
        patch(f"{_REGISTRY_PATH}.stop_index_split_projector", mock_stop),
        patch(f"{_REGISTRY_PATH}.stop_all_index_split_projectors", mock_stop_all),
        patch(f"{_REGISTRY_PATH}.list_active_tenants", mock_list),
    ):
        # lifespan 进退不应抛出异常
        async with _test_lifespan():
            await asyncio.sleep(0.15)

    # DB 一直失败 → start 从未被调
    mock_start.assert_not_called()
    # shutdown 仍走 stop_all 兜底 (即使从未 start, stop_all 是 noop 不抛错)
    mock_stop_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_tenant_delta(monkeypatch: pytest.MonkeyPatch) -> None:
    """refresh 探测到 tenant 增量: 轮 1=[T1] → 轮 2=[T1,T2] → 轮 3=[T2]

    期望: start T1 (轮1), start T2 (轮2), stop T1 (轮3移除).
    """
    monkeypatch.setenv("TX_SUPPLY_ENABLE_INDEX_SPLIT_PROJECTOR", "true")
    monkeypatch.setenv("TX_SUPPLY_INDEX_SPLIT_TENANT_REFRESH_SEC", "0.05")

    _rounds = [[_T1], [_T1, _T2], [_T2]]
    _call_count = 0

    async def _side_effect() -> list[str]:
        nonlocal _call_count
        if _call_count < len(_rounds):
            result = _rounds[_call_count]
        else:
            result = _rounds[-1]
        _call_count += 1
        return result

    mock_start = AsyncMock()
    mock_stop = AsyncMock()
    mock_stop_all = AsyncMock()
    mock_list = AsyncMock(side_effect=_side_effect)

    with (
        patch(f"{_REGISTRY_PATH}.start_index_split_projector", mock_start),
        patch(f"{_REGISTRY_PATH}.stop_index_split_projector", mock_stop),
        patch(f"{_REGISTRY_PATH}.stop_all_index_split_projectors", mock_stop_all),
        patch(f"{_REGISTRY_PATH}.list_active_tenants", mock_list),
    ):
        async with _test_lifespan():
            # 让 refresh loop 跑 3+ 轮（每轮 0.05s）
            await asyncio.sleep(0.25)

    # start 应包含 T1 和 T2
    started_args = {call.args[0] for call in mock_start.call_args_list}
    assert _T1 in started_args, "T1 应在轮 1 被 start"
    assert _T2 in started_args, "T2 应在轮 2 被 start"

    # mid-refresh diff: T1 在轮 3 被移除时 stop 调过
    stopped_args = {call.args[0] for call in mock_stop.call_args_list}
    assert _T1 in stopped_args, "T1 应在轮 3 移除时被 stop_index_split_projector"
    # §19 round-1 P1-1 fix: shutdown 兜底 stop_all
    mock_stop_all.assert_awaited_once()


# ─── §19 round-1 P1-2 fix regression ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_active_tenants_uses_status_filter() -> None:
    """§19 round-1 P1-2 regression: SQL 必须用 `status = 'active'` 而非 `is_deleted = FALSE`.

    v006 建 tenants 表只含 id/code/name/brand_name/pos_system/pos_config/status/
    created_at/updated_at — 无 is_deleted 列. 用 is_deleted 过滤会运行时 ProgrammingError,
    被 _refresh_loop fail-open 吞掉 → projector 永不启动 (静默 noop).
    """
    from services.tx_supply.src.projectors import registry as _registry
    import re

    src = _registry.list_active_tenants.__doc__ or ""
    # 通过查询的 SQL 文本断言 (sqlalchemy.text 包装的字符串可被 .text 属性读)
    # 这里直接 grep 源码: 用 inspect 拿函数源
    import inspect
    body = inspect.getsource(_registry.list_active_tenants)

    assert "status = 'active'" in body or 'status = "active"' in body, (
        "list_active_tenants SQL 必须 filter status='active' (v006 schema). "
        "WHERE is_deleted = FALSE 是 cert_expiry_alerter 的 pre-existing bug (out-of-scope)."
    )
    assert not re.search(r"is_deleted\s*=\s*FALSE", body), (
        "list_active_tenants 不可用 is_deleted = FALSE — tenants 表 v006 无此列, "
        "会运行时 ProgrammingError 致 projector 静默 noop. 用 status='active' 替代."
    )
