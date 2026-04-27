"""test_mark_offline_scheduler_tier1 — Sprint C3 §19 mark_offline 周期调度 Tier1

Tier1 铁律（CLAUDE.md §17/§20 零容忍）：
  - 测试用例基于徐记海鲜真实场景（拔 KDS 网线 11 分钟必须翻 offline）
  - task 启动 / 取消 / 异常恢复全覆盖
  - mock asyncio.sleep 让单测秒级跑完，不真睡 60s

3 条徐记海鲜场景：
  1. test_xujihaixian_scheduler_invokes_mark_offline_global_each_tick
       — 每 60s tick 调用一次 mark_offline_if_stale_global，命中数写日志
  2. test_xujihaixian_scheduler_graceful_cancel_on_lifespan_exit
       — lifespan exit cancel task 后正常退出（不卡 await）
  3. test_xujihaixian_scheduler_survives_db_error_does_not_die
       — SQLAlchemyError 单轮失败 task 不死，下一轮继续

数据约定：徐记海鲜 17 号店 / 韶山路店 两租户，KDS 设备拔网超 600s。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

os.environ.setdefault("TX_AUTH_ENABLED", "true")

from src.services.mark_offline_scheduler import mark_offline_scheduler_loop  # noqa: E402

# ──────────────── 徐记海鲜测试常量 ────────────────

XUJI_17_TENANT = "00000000-0000-0000-0000-0000000000a1"
XUJI_SHAOSHAN_TENANT = "00000000-0000-0000-0000-0000000000b1"


# ──────────────── 场景 1：每 60s tick 调用 global 扫描 ────────────────


@pytest.mark.asyncio
async def test_xujihaixian_scheduler_invokes_mark_offline_global_each_tick():
    """徐记海鲜 17 号店 + 韶山路店两租户。
    scheduler 每 60s 调一次 mark_offline_if_stale_global，
    命中 2 台 KDS 翻 offline 后日志带 devices_marked_offline=2。

    用 patch.object 替 mark_offline_if_stale_global 为 mock；
    用 patch asyncio.sleep 让 sleep 立即返回（避免真睡 60s）。
    """
    sleep_calls: list[float] = []

    async def _fast_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        # 跑完 3 轮就让 task 自取消（避免无限循环）
        if len(sleep_calls) >= 3:
            raise asyncio.CancelledError()

    fake_global = AsyncMock(
        return_value={"tenants_scanned": 2, "devices_marked_offline": 2}
    )

    fake_session_factory = AsyncMock()  # 内部不会真用，仅传给 global 的 mock

    with (
        patch("asyncio.sleep", side_effect=_fast_sleep),
        patch(
            "src.services.device_registry_service.DeviceRegistryService.mark_offline_if_stale_global",
            fake_global,
        ),
    ):
        with pytest.raises(asyncio.CancelledError):
            await mark_offline_scheduler_loop(fake_session_factory, interval_sec=60)

    # 三次 sleep 各 60s
    assert sleep_calls == [60, 60, 60], f"期望 3 次 60s sleep，实际 {sleep_calls}"
    # 三次 mark_offline_if_stale_global 调用（前两次成功，第三次 sleep 抛 cancel 不调用 global）
    assert fake_global.await_count == 2, f"期望 2 次 global 调用，实际 {fake_global.await_count}"
    fake_global.assert_awaited_with(fake_session_factory)


# ──────────────── 场景 2：lifespan exit cancel task ────────────────


@pytest.mark.asyncio
async def test_xujihaixian_scheduler_graceful_cancel_on_lifespan_exit():
    """tx-trade lifespan 退出时 cancel mark_offline_scheduler_loop task，
    task 应当干净退出（CancelledError 向上传播，不卡 await，不吞异常）。"""
    fake_session_factory: Any = AsyncMock()
    fake_global = AsyncMock(
        return_value={"tenants_scanned": 0, "devices_marked_offline": 0}
    )

    with patch(
        "src.services.device_registry_service.DeviceRegistryService.mark_offline_if_stale_global",
        fake_global,
    ):
        task = asyncio.create_task(
            mark_offline_scheduler_loop(fake_session_factory, interval_sec=60),
        )
        # 让 task 进入 sleep（一个事件循环 tick 即可）
        await asyncio.sleep(0)

        # 模拟 lifespan exit
        task.cancel()

        # graceful：await 应当抛 CancelledError（而不是吞）
        with pytest.raises(asyncio.CancelledError):
            await task

    assert task.done(), "cancel + await 后 task 必须完成"
    assert task.cancelled(), "task 必须标记为 cancelled"


# ──────────────── 场景 3：DB 异常 task 不死 ────────────────


@pytest.mark.asyncio
async def test_xujihaixian_scheduler_survives_db_error_does_not_die():
    """演示场景：DB 短暂闪断（PG 主从切换 5 秒），mark_offline_if_stale_global
    第一轮抛 SQLAlchemyError，scheduler 应记 warning 后继续，
    第二轮恢复正常调用，不能让整个 task 死亡（否则 KDS 永远停留 healthy）。"""
    sleep_calls: list[float] = []

    async def _fast_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 3:
            raise asyncio.CancelledError()

    # 第一次 raise SQLAlchemyError，第二次正常返回
    fake_global = AsyncMock(
        side_effect=[
            SQLAlchemyError("connection lost"),
            {"tenants_scanned": 2, "devices_marked_offline": 1},
        ]
    )

    fake_session_factory: Any = AsyncMock()

    with (
        patch("asyncio.sleep", side_effect=_fast_sleep),
        patch(
            "src.services.device_registry_service.DeviceRegistryService.mark_offline_if_stale_global",
            fake_global,
        ),
    ):
        with pytest.raises(asyncio.CancelledError):
            await mark_offline_scheduler_loop(fake_session_factory, interval_sec=60)

    # 验证：第一轮异常未杀死 task，第二轮成功调用
    assert fake_global.await_count == 2, (
        f"DB 闪断后 task 必须继续，期望 2 次 global 调用，实际 {fake_global.await_count}"
    )
