"""mark_offline_scheduler — Sprint C3 §19 KDS 离线扫描周期调度

由 tx-trade lifespan 启动一个 asyncio.create_task，每 interval_sec 秒
跨租户调用 DeviceRegistryService.mark_offline_if_stale_global，
将超 600s 心跳的 edge_device_registry 标记为 health_status=offline。

背景：CLAUDE.md §19 §20 Tier1 §22 — DEMO 演示拔 KDS 网线 11 分钟后
health_status 必须翻 offline，否则运维面板永远停留 healthy（致命假象）。

flag 控制：edge.kds.mark_offline_scheduler（默认 off，DEMO/灰度逐步开启）。
"""

from __future__ import annotations

import asyncio
from typing import Callable

import structlog
from sqlalchemy.exc import SQLAlchemyError

from .device_registry_service import DeviceRegistryService

logger = structlog.get_logger(__name__)

DEFAULT_INTERVAL_SEC = 60


async def mark_offline_scheduler_loop(
    session_factory: Callable,
    *,
    interval_sec: int = DEFAULT_INTERVAL_SEC,
) -> None:
    """C3 周期任务：每 interval_sec 秒跨租户标记离线 KDS 设备。

    异常处理：
      - asyncio.CancelledError：lifespan exit 时取消，正常向上传播退出
      - SQLAlchemyError：DB 闪断（PG 主从切换）单轮失败仅记 warning，
        下一轮重试，不杀死 task
      - 其它 Exception：审计修复期允许的兜底（CLAUDE.md §14 §10 例外），
        必须带 exc_info=True，防 task 死亡使整个服务失忆

    Args:
        session_factory: async_session_factory（返回 AsyncSession）
        interval_sec: 调度间隔（默认 60s）
    """
    logger.info("mark_offline_scheduler_started", interval_sec=interval_sec)

    while True:
        try:
            await asyncio.sleep(interval_sec)
            summary = await DeviceRegistryService.mark_offline_if_stale_global(
                session_factory,
            )
            logger.info(
                "mark_offline_scheduler_tick",
                tenants_scanned=summary["tenants_scanned"],
                devices_marked_offline=summary["devices_marked_offline"],
            )
        except asyncio.CancelledError:
            logger.info("mark_offline_scheduler_stopped")
            raise
        except SQLAlchemyError as exc:
            logger.warning(
                "mark_offline_scheduler_db_error",
                error=str(exc),
            )
        except Exception:  # noqa: BLE001 — scheduler 顶层兜底，防 task 死亡（CLAUDE.md §14 审计修复期例外）
            logger.exception("mark_offline_scheduler_unexpected_error", exc_info=True)
            await asyncio.sleep(5)
