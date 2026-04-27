"""projector_registry — 投影器注册中心

统一管理所有投影器的生命周期：启动、停止、重建。

职责：
- 持有 9 个投影器实例的单例
- 并发启动所有投影器监听循环（asyncio.gather）
- 优雅关闭：批量 stop()
- 支持单个或全部投影器的重建（rebuild）

使用方式：
    # 启动（服务启动时调用一次，阻塞直到 stop_all 被调用）
    registry = ProjectorRegistry(tenant_id=tenant_id)
    await registry.start_all()

    # 停止（服务关闭时）
    await registry.stop_all()

    # 全量重建单个投影器（视图损坏时）
    total = await registry.rebuild("discount_health")

    # 全量重建所有投影器（灾难恢复）
    totals = await registry.rebuild_all()
"""

from __future__ import annotations

import asyncio
from typing import Optional
from uuid import UUID

import structlog

from .projector import ProjectorBase
from .projectors import (
    ChannelMarginProjector,
    DailySettlementProjector,
    DiscountHealthProjector,
    EnergyEfficiencyProjector,
    InventoryBomProjector,
    MemberClvProjector,
    PublicOpinionProjector,
    SafetyComplianceProjector,
    StorePnlProjector,
)

logger = structlog.get_logger(__name__)


class ProjectorRegistry:
    """投影器注册中心 — 管理所有投影器实例的生命周期。

    Args:
        tenant_id: 租户 UUID（每个注册中心实例对应单个租户）
    """

    def __init__(self, tenant_id: UUID | str) -> None:
        self.tenant_id = UUID(str(tenant_id))
        self._projectors: list[ProjectorBase] = [
            DiscountHealthProjector(tenant_id=self.tenant_id),
            ChannelMarginProjector(tenant_id=self.tenant_id),
            InventoryBomProjector(tenant_id=self.tenant_id),
            MemberClvProjector(tenant_id=self.tenant_id),
            StorePnlProjector(tenant_id=self.tenant_id),
            DailySettlementProjector(tenant_id=self.tenant_id),
            SafetyComplianceProjector(tenant_id=self.tenant_id),
            EnergyEfficiencyProjector(tenant_id=self.tenant_id),
            PublicOpinionProjector(tenant_id=self.tenant_id),
        ]
        self._tasks: list[asyncio.Task] = []

    # ──────────────────────────────────────────────────────────────────────
    # 按名称查找
    # ──────────────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[ProjectorBase]:
        """按 projector.name 查找投影器实例，未找到返回 None。"""
        for p in self._projectors:
            if p.name == name:
                return p
        return None

    # ──────────────────────────────────────────────────────────────────────
    # 启动 / 停止
    # ──────────────────────────────────────────────────────────────────────

    async def start_all(self) -> None:
        """并发启动所有投影器（阻塞直到全部结束或 stop_all 被调用）。

        推荐在独立 asyncio.Task 中调用：
            asyncio.create_task(registry.start_all())
        """
        logger.info(
            "projector_registry_starting",
            tenant_id=str(self.tenant_id),
            projector_count=len(self._projectors),
            names=[p.name for p in self._projectors],
        )
        await asyncio.gather(
            *[p.run() for p in self._projectors],
            return_exceptions=True,
        )
        logger.info(
            "projector_registry_all_stopped",
            tenant_id=str(self.tenant_id),
        )

    async def stop_all(self) -> None:
        """优雅停止所有投影器（设置 _running=False，等待本轮处理完成）。"""
        logger.info(
            "projector_registry_stopping",
            tenant_id=str(self.tenant_id),
        )
        await asyncio.gather(
            *[p.stop() for p in self._projectors],
            return_exceptions=True,
        )

    # ──────────────────────────────────────────────────────────────────────
    # 重建
    # ──────────────────────────────────────────────────────────────────────

    async def rebuild(self, projector_name: str) -> int:
        """从事件流重建单个投影器的物化视图。

        Args:
            projector_name: 投影器 name 字段（如 "discount_health"）

        Returns:
            重建时处理的事件数，投影器不存在时返回 -1。
        """
        projector = self.get(projector_name)
        if projector is None:
            logger.warning(
                "projector_registry_rebuild_not_found",
                name=projector_name,
                tenant_id=str(self.tenant_id),
                available=[p.name for p in self._projectors],
            )
            return -1

        logger.info(
            "projector_registry_rebuild_start",
            name=projector_name,
            tenant_id=str(self.tenant_id),
        )
        total = await projector.rebuild()
        logger.info(
            "projector_registry_rebuild_done",
            name=projector_name,
            tenant_id=str(self.tenant_id),
            total_events=total,
        )
        return total

    async def rebuild_all(self) -> dict[str, int]:
        """并发重建所有投影器的物化视图（灾难恢复用）。

        Returns:
            {projector_name: events_processed} 映射表。
        """
        logger.info(
            "projector_registry_rebuild_all_start",
            tenant_id=str(self.tenant_id),
            projector_count=len(self._projectors),
        )

        results = await asyncio.gather(
            *[p.rebuild() for p in self._projectors],
            return_exceptions=True,
        )

        summary: dict[str, int] = {}
        for projector, result in zip(self._projectors, results):
            if isinstance(result, BaseException):
                logger.error(
                    "projector_registry_rebuild_failed",
                    name=projector.name,
                    tenant_id=str(self.tenant_id),
                    error=str(result),
                    exc_info=result,
                )
                summary[projector.name] = -1
            else:
                summary[projector.name] = result  # type: ignore[assignment]

        total_events = sum(v for v in summary.values() if v >= 0)
        logger.info(
            "projector_registry_rebuild_all_done",
            tenant_id=str(self.tenant_id),
            summary=summary,
            total_events=total_events,
        )
        return summary

    # ──────────────────────────────────────────────────────────────────────
    # 状态检查
    # ──────────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """返回所有投影器的运行状态摘要。"""
        return {
            "tenant_id": str(self.tenant_id),
            "projectors": [
                {
                    "name": p.name,
                    "event_types": sorted(p.event_types) if p.event_types else "all",
                    "running": p._running,
                }
                for p in self._projectors
            ],
        }


# ──────────────────────────────────────────────────────────────────────────
# 便捷工厂函数
# ──────────────────────────────────────────────────────────────────────────


async def start_all_projectors(tenant_id: UUID | str) -> ProjectorRegistry:
    """工厂函数：创建注册中心并在后台启动所有投影器。

    返回 registry 实例，调用方可持有用于 stop_all / rebuild。

    Example::
        registry = await start_all_projectors(tenant_id)
        # ... 服务运行中 ...
        await registry.stop_all()
    """
    registry = ProjectorRegistry(tenant_id=tenant_id)
    asyncio.create_task(registry.start_all())
    logger.info(
        "start_all_projectors_launched",
        tenant_id=str(tenant_id),
        projectors=[p.name for p in registry._projectors],
    )
    return registry
