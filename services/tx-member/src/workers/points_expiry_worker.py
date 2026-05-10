"""积分过期 FIFO 清理 Cron Worker

每日凌晨 3 点（Asia/Shanghai）触发，扫描所有租户的积分批次：
  - 已过期且 remaining_points > 0 → 按 FIFO 清零
  - 旁路写入 MemberEventType.POINTS_CHANGED（direction=expire）
  - 失败的租户隔离记录，不影响其他租户

设计要点：
  - 单独 Worker 类，便于 main.py 注册到 AsyncIOScheduler
  - 业务逻辑全部走纯函数 services.points_expiry_fifo.clear_expired_batches_fifo
  - 数据获取留给 Repository 模式（本版预留接口）

集成方式（main.py lifespan 中注册）：
    from services.tx_member.src.workers.points_expiry_worker import PointsExpiryWorker
    _scheduler.add_job(
        lambda: asyncio.create_task(PointsExpiryWorker().run_for_all_tenants()),
        "cron", hour=3, minute=0,
        id="points_expiry_daily",
        replace_existing=True,
    )
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PointsExpiryWorker:
    """积分过期 FIFO 清理后台任务。"""

    def __init__(self, batch_loader: Optional[Any] = None) -> None:
        """
        Args:
            batch_loader: 可注入的批次加载器，签名为
                async (tenant_id) -> list[batch dict]
                若为 None，会按需从 shared.ontology.src.database 取 session
                查询（生产路径，集成测试时通过传入 fake loader 绕开）。
        """
        self._batch_loader = batch_loader

    async def run_for_tenant(self, tenant_id: str) -> dict[str, Any]:
        """单租户清理。

        Returns:
            {"tenant_id", "cleared_count", "cleared_points", "details"}
        """
        from services.tx_member.src.services.points_expiry_fifo import clear_expired_batches_fifo  # noqa: PLC0415

        try:
            from datetime import datetime, timezone  # noqa: PLC0415

            now = datetime.now(timezone.utc)
            batches = await self._load_batches(tenant_id)
            result = clear_expired_batches_fifo(batches, now=now)

            # 旁路写事件（每条清零都发一次，便于审计）
            await self._emit_expiry_events(tenant_id, result["details"])

            logger.info(
                "points_expiry_worker.tenant_done",
                extra={
                    "tenant_id": tenant_id,
                    "cleared_count": result["cleared_count"],
                    "cleared_points": result["cleared_points"],
                },
            )
            return {"tenant_id": tenant_id, **result}
        except (RuntimeError, ValueError) as exc:
            logger.error(
                "points_expiry_worker.tenant_failed",
                extra={"tenant_id": tenant_id, "error": str(exc)},
                exc_info=True,
            )
            return {"tenant_id": tenant_id, "error": str(exc)}

    async def run_for_all_tenants(self) -> dict[str, Any]:
        """全租户扫描入口（Scheduler 调用此函数）。

        失败的租户被隔离，不阻断其他租户的清理。
        """
        tenants = await self._load_active_tenants()
        results = []
        for tenant_id in tenants:
            res = await self.run_for_tenant(tenant_id)
            results.append(res)

        total_cleared = sum(r.get("cleared_count", 0) for r in results)
        total_points = sum(r.get("cleared_points", 0) for r in results)
        logger.info(
            "points_expiry_worker.batch_done",
            extra={
                "tenant_count": len(tenants),
                "total_cleared": total_cleared,
                "total_points": total_points,
            },
        )
        return {
            "tenant_count": len(tenants),
            "total_cleared": total_cleared,
            "total_points": total_points,
            "per_tenant": results,
        }

    # ──────────────────────────────────────────────────────────
    # 私有：数据访问（生产环境需接 DB；本版留 stub）
    # ──────────────────────────────────────────────────────────

    async def _load_batches(self, tenant_id: str) -> list[dict[str, Any]]:
        if self._batch_loader is not None:
            return await self._batch_loader(tenant_id)
        # 生产路径：接入 services.points_expiry._points_batches（内存版，待迁 DB）
        try:
            from services.tx_member.src.services.points_expiry import _points_batches  # noqa: PLC0415

            collected: list[dict[str, Any]] = []
            for batches in _points_batches.values():
                collected.extend(b for b in batches if b.get("tenant_id") == tenant_id)
            return collected
        except ImportError:
            return []

    async def _load_active_tenants(self) -> list[str]:
        # 生产路径：从 tenants 表读取；本版 stub
        # TODO: 接入 RLS-aware 租户列表查询
        try:
            from services.tx_member.src.services.points_expiry import _points_batches  # noqa: PLC0415

            tids: set[str] = set()
            for batches in _points_batches.values():
                for b in batches:
                    tid = b.get("tenant_id")
                    if tid:
                        tids.add(tid)
            return sorted(tids)
        except ImportError:
            return []

    async def _emit_expiry_events(self, tenant_id: str, details: list[dict[str, Any]]) -> None:
        if not details:
            return
        try:
            from shared.events.src.emitter import emit_event  # noqa: PLC0415
            from shared.events.src.event_types import MemberEventType  # noqa: PLC0415
        except ImportError:
            return

        for detail in details:
            asyncio.create_task(
                emit_event(
                    event_type=MemberEventType.POINTS_CHANGED,
                    tenant_id=tenant_id,
                    stream_id=str(detail.get("batch_id", "unknown")),
                    payload={
                        "direction": "expire",
                        "points": int(detail.get("cleared_points", 0)),
                        "expiry_date": detail.get("expiry_date"),
                    },
                    source_service="tx-member",
                )
            )
