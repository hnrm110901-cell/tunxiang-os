"""ProjectorRunner — 投影器运行服务

职责：
- 在 tx-agent 服务启动时，为所有已注册租户启动投影器
- 每个投影器是一个独立的 asyncio 任务
- 提供 rebuild 接口（视图损坏时从事件流完整重建）
- 服务关闭时优雅停止所有投影器

集成方式（在 tx-agent/main.py 的 lifespan 中）：
    runner = ProjectorRunner()
    await runner.start(tenant_ids=["uuid-1", "uuid-2"])
    # 服务关闭时
    await runner.stop()

管理 API（在 api/ 中注册）：
    POST /api/v1/projectors/rebuild/{projector_name}?tenant_id=xxx
    GET  /api/v1/projectors/status
"""

from __future__ import annotations

import asyncio
from typing import Optional
from uuid import UUID

import structlog

from shared.events.src.projectors import ALL_PROJECTORS, ProjectorBase

logger = structlog.get_logger(__name__)


class ProjectorRunner:
    """投影器运行器 — 管理所有投影器的生命周期"""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}  # key: "{projector_name}:{tenant_id}"
        self._projectors: dict[str, ProjectorBase] = {}
        self._running = False

    async def start(self, tenant_ids: list[str | UUID]) -> None:
        """为所有租户启动全部投影器。"""
        self._running = True
        for tenant_id in tenant_ids:
            await self._start_for_tenant(str(tenant_id))

        logger.info(
            "projector_runner_started",
            tenant_count=len(tenant_ids),
            projector_count=len(ALL_PROJECTORS),
            total_tasks=len(self._tasks),
        )

    async def _start_for_tenant(self, tenant_id: str) -> None:
        """为指定租户启动所有投影器。"""
        for projector_cls in ALL_PROJECTORS:
            key = f"{projector_cls.name}:{tenant_id}"
            if key in self._tasks and not self._tasks[key].done():
                continue  # 已运行，跳过

            projector = projector_cls(tenant_id=tenant_id)
            self._projectors[key] = projector

            task = asyncio.create_task(
                self._run_with_restart(projector, tenant_id),
                name=f"projector:{key}",
            )
            self._tasks[key] = task
            logger.debug("projector_task_started", name=projector_cls.name, tenant_id=tenant_id)

    async def _run_with_restart(self, projector: ProjectorBase, tenant_id: str) -> None:
        """带自动重启的投影器运行循环（崩溃后3秒重试）。"""
        while self._running:
            try:
                await projector.run()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "projector_crashed",
                    name=projector.name,
                    tenant_id=tenant_id,
                    error=str(exc),
                    exc_info=True,
                )
                if self._running:
                    await asyncio.sleep(3)  # 短暂等待后重启

    async def stop(self) -> None:
        """优雅停止所有投影器。"""
        self._running = False
        for key, projector in self._projectors.items():
            await projector.stop()

        for key, task in self._tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

        self._tasks.clear()
        self._projectors.clear()
        logger.info("projector_runner_stopped")

    async def rebuild(self, projector_name: str, tenant_id: str) -> dict:
        """从事件流完整重建指定投影器的物化视图。

        Returns:
            {"events_processed": N, "duration_ms": N}
        """
        import time

        projector_cls = next((p for p in ALL_PROJECTORS if p.name == projector_name), None)
        if not projector_cls:
            raise ValueError(f"未知投影器: {projector_name}")

        logger.info("projector_rebuild_started", name=projector_name, tenant_id=tenant_id)
        start = time.monotonic()

        projector = projector_cls(tenant_id=tenant_id)
        count = await projector.rebuild()

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "projector_rebuild_done",
            name=projector_name,
            tenant_id=tenant_id,
            events_processed=count,
            duration_ms=duration_ms,
        )
        return {"events_processed": count, "duration_ms": duration_ms}

    def get_status(self) -> list[dict]:
        """返回所有投影器运行状态。"""
        statuses = []
        for key, task in self._tasks.items():
            name, tenant_id = key.split(":", 1)
            statuses.append(
                {
                    "projector_name": name,
                    "tenant_id": tenant_id,
                    "running": not task.done(),
                    "failed": task.done() and not task.cancelled() and task.exception() is not None,
                }
            )
        return statuses


# ── 模块级单例 ──
_runner: Optional[ProjectorRunner] = None


def get_runner() -> ProjectorRunner:
    global _runner
    if _runner is None:
        _runner = ProjectorRunner()
    return _runner
