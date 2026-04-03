"""拼团超时过期 — 后台定时任务

每 60 秒扫描一次 forming 状态且已过期的团队，
调用 group_buy_service.expire_teams 批量置过期。

由 tx-trade lifespan 启动。
"""
from __future__ import annotations

import asyncio
from typing import Callable

import structlog

from .group_buy_service import expire_teams

logger = structlog.get_logger(__name__)

INTERVAL_SECONDS = 60


async def start_group_buy_expiry_scheduler(
    session_factory: Callable,
    tenant_ids: list[str] | None = None,
) -> None:
    """持续循环，每 INTERVAL_SECONDS 秒检查过期拼团

    Args:
        session_factory: async_session_factory（返回 AsyncSession）
        tenant_ids: 需要扫描的租户列表。
                    生产环境从配置/数据库获取活跃租户列表。
                    为 None 时跳过（安全降级）。
    """
    logger.info("group_buy_scheduler.started", interval=INTERVAL_SECONDS)

    while True:
        try:
            await asyncio.sleep(INTERVAL_SECONDS)

            if not tenant_ids:
                continue

            for tid in tenant_ids:
                async with session_factory() as db, db.begin():
                    result = await expire_teams(tid, db)
                    if result["expired_count"] > 0:
                        logger.info(
                            "group_buy_scheduler.expired",
                            tenant_id=tid,
                            count=result["expired_count"],
                        )
        except asyncio.CancelledError:
            logger.info("group_buy_scheduler.stopped")
            break
        except Exception:  # noqa: BLE001 — scheduler top-level loop must not crash
            logger.exception("group_buy_scheduler.error", exc_info=True)
            await asyncio.sleep(5)
