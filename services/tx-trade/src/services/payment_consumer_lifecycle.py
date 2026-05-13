"""tx-pay 支付事件消费者启动 helper — Tier 1 资金链路 fail-loud (W1-T1)

CLAUDE.md §17 Tier 1：支付事件消费者启动失败时必须 fail-loud，让 k8s
readiness probe 直接拒绝服务上线，而非以"无支付事件消费"的残废状态启动
（订单永远 stuck 在 paying — P0 资金风险）。

历史背景：`fd94028e feat(payment+rls): 支付事件消费者...` (PR #128) 把启动
包在 `except Exception: warning(...)` 里静吞，导致 redis 不可达 / topic 配置
错时 tx-trade 仍能起来。W1-T1 修复此 P0。

抽到独立模块的原因：main.py 的 module-level 依赖链（permission_client /
omni_channel_service / tenacity 等）让单测里直接 import main 不现实；
helper 只 import payment_event_consumer，单测可干净 mock。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_logger = structlog.get_logger(__name__)


async def start_payment_event_consumer_or_raise(
    session_factory: "async_sessionmaker[AsyncSession]",
    register_background_task: Callable[["asyncio.Task"], "asyncio.Task"],
) -> "asyncio.Task":
    """启动 tx-pay 支付事件消费者并注册到 lifespan 后台任务集合。

    启动失败时**重新抛出**（fail-loud），由调用方（lifespan）决定是否
    让 readiness probe 失败 — 绝不 silent swallow。

    Args:
        session_factory: 数据库 session 工厂，注入到 PaymentEventHandlers。
        register_background_task: lifespan 提供的注册函数，用于将
            consumer task 加入 app.state.background_tasks 集合，保证
            SIGTERM 时被 graceful cancel + await。

    Returns:
        asyncio.Task: 已启动并已注册的 consumer 后台 task。

    Raises:
        Exception: 工厂创建或 consumer.start 期间的任何异常都向上传播。
    """
    from .payment_event_consumer import (
        create_payment_event_consumer,
        start_payment_event_consumer,
    )

    consumer = create_payment_event_consumer(session_factory)
    task = await start_payment_event_consumer(consumer, session_factory)
    register_background_task(task)
    _logger.info("payment_event_consumer_started")
    return task
