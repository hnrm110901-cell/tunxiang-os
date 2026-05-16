"""hr_event_consumer XGROUP CREATE except 收窄 regression tests

issue #704 — 验证 HREventConsumer.start() 的 xgroup_create 路径异常处理:
  - BUSYGROUP ResponseError  → 静默 + debug log (幂等已存在场景)
  - 其他 ResponseError       → warn log + raise
  - ConnectionError          → 直接 raise (fail-loud, 不被 swallow)

关联: PR #695 (Wave 4 PR-3) §19 reviewer follow-up #6
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# CI 最小依赖集不装 redis (per sediment feedback_tier1_ci_minimal_deps_trap.md);
# 本地 / 生产容器有 redis 时才跑, 否则整文件 skip, 不让"扩 CI workflow install redis"
# 这种反 sediment 动作发生.
redis_exceptions = pytest.importorskip("redis.exceptions")

from services.tx_org.src.services.hr_event_consumer import HREventConsumer  # noqa: E402


def _make_redis_mock(xgroup_side_effect=None) -> MagicMock:
    """构造一个 Redis 实例 mock, xgroup_create 的副作用可注入

    返回值用于替换 ``Redis.from_url`` 的返回, 同时阻止 start() 进入 while
    循环 (xreadgroup 抛 asyncio.CancelledError 立即退出 consumer 循环)。
    """
    import asyncio

    redis_mock = MagicMock()
    if xgroup_side_effect is None:
        redis_mock.xgroup_create = AsyncMock(return_value=None)
    else:
        redis_mock.xgroup_create = AsyncMock(side_effect=xgroup_side_effect)
    # while self.running 循环立即被 CancelledError 中断, 避免无限等待 redis
    redis_mock.xreadgroup = AsyncMock(side_effect=asyncio.CancelledError())
    redis_mock.close = AsyncMock()
    return redis_mock


@pytest.mark.asyncio
async def test_xgroup_busygroup_swallowed_as_debug() -> None:
    """BUSYGROUP ResponseError → 静默 + debug, 不抛, consumer 进入正常循环"""
    redis_mock = _make_redis_mock(
        xgroup_side_effect=redis_exceptions.ResponseError(
            "BUSYGROUP Consumer Group name already exists"
        )
    )
    consumer = HREventConsumer(redis_url="redis://localhost:6379")

    with patch(
        "services.tx_org.src.services.hr_event_consumer.Redis.from_url",
        return_value=redis_mock,
    ):
        # 不应抛任何异常; while 循环被 CancelledError 退出
        await consumer.start()

    # 验证 xgroup_create 被调用过
    redis_mock.xgroup_create.assert_awaited_once()
    # 进入 while 循环说明 BUSYGROUP 已被吞 (running 被设为 True)
    assert consumer.running is True


@pytest.mark.asyncio
async def test_xgroup_other_response_error_warns_and_raises() -> None:
    """非 BUSYGROUP ResponseError (如 WRONGTYPE) → warn + raise, fail-loud"""
    redis_mock = _make_redis_mock(
        xgroup_side_effect=redis_exceptions.ResponseError(
            "WRONGTYPE Operation against a key holding the wrong kind of value"
        )
    )
    consumer = HREventConsumer(redis_url="redis://localhost:6379")

    with patch(
        "services.tx_org.src.services.hr_event_consumer.Redis.from_url",
        return_value=redis_mock,
    ):
        with pytest.raises(redis_exceptions.ResponseError, match="WRONGTYPE"):
            await consumer.start()

    redis_mock.xgroup_create.assert_awaited_once()
    # 未进入 while 循环: running 仍为 False
    assert consumer.running is False


@pytest.mark.asyncio
async def test_xgroup_connection_error_propagates() -> None:
    """ConnectionError 不被 catch → 直接 raise, 防 4h 断网恢复被静默吞为'假启动成功'"""
    redis_mock = _make_redis_mock(
        xgroup_side_effect=redis_exceptions.ConnectionError("Connection refused")
    )
    consumer = HREventConsumer(redis_url="redis://localhost:6379")

    with patch(
        "services.tx_org.src.services.hr_event_consumer.Redis.from_url",
        return_value=redis_mock,
    ):
        with pytest.raises(redis_exceptions.ConnectionError, match="Connection refused"):
            await consumer.start()

    redis_mock.xgroup_create.assert_awaited_once()
    assert consumer.running is False
