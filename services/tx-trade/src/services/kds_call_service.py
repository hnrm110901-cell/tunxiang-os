"""KDS 等叫（CALLING）状态服务

状态机扩展：pending → cooking → calling → done
                                    ↑
                        厨师做好后标记"等叫"，
                        服务员叫菜后确认"上桌"。

# SCHEMA SQL
-- ALTER TABLE kds_tasks ADD COLUMN IF NOT EXISTS called_at TIMESTAMPTZ;
-- ALTER TABLE kds_tasks ADD COLUMN IF NOT EXISTS served_at TIMESTAMPTZ;
-- ALTER TABLE kds_tasks ADD COLUMN IF NOT EXISTS call_count INT NOT NULL DEFAULT 0;
-- 状态机扩展: status CHECK 新增 'calling' 值
--   ALTER TABLE kds_tasks DROP CONSTRAINT IF EXISTS kds_tasks_status_check;
--   ALTER TABLE kds_tasks ADD CONSTRAINT kds_tasks_status_check
--     CHECK (status IN ('pending','cooking','calling','done','cancelled'));
"""
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import httpx
import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from ..models.kds_task import KDSTask
except ImportError:
    from models.kds_task import KDSTask  # type: ignore[no-redef]  # noqa: PLC0415

logger = structlog.get_logger()

MAC_STATION_URL = os.getenv("MAC_STATION_URL", "http://localhost:8000")

STATUS_COOKING = "cooking"
STATUS_CALLING = "calling"
STATUS_DONE = "done"


# ─── 响应数据结构 ───

@dataclass
class CallingStats:
    calling_count: int
    avg_waiting_minutes: float


# ─── 内部 WebSocket 推送 ───

async def _broadcast(event_type: str, payload: dict) -> None:
    """广播 WebSocket 事件到 Mac mini KDS 推送服务。

    失败时仅记录日志，不抛出异常，避免影响主业务流程。
    """
    log = logger.bind(event_type=event_type)
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.post(
                f"{MAC_STATION_URL}/api/v1/kds/broadcast",
                json={"type": event_type, **payload},
            )
            if resp.status_code == 200:
                log.info("kds_call_service.broadcast.ok")
            else:
                log.warning("kds_call_service.broadcast.failed", status=resp.status_code)
    except httpx.ConnectError:
        log.warning("kds_call_service.broadcast.mac_station_unavailable")
    except httpx.TimeoutException:
        log.warning("kds_call_service.broadcast.timeout")


# ─── 查询辅助 ───

async def _get_task(
    task_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[KDSTask]:
    """按 task_id + tenant_id 查询任务，不存在返回 None。"""
    try:
        tid = uuid.UUID(tenant_id)
        task_uuid = uuid.UUID(task_id)
    except ValueError as exc:
        raise ValueError(f"无效的 task_id 或 tenant_id: {exc}") from exc

    stmt = select(KDSTask).where(
        and_(
            KDSTask.id == task_uuid,
            KDSTask.tenant_id == tid,
            KDSTask.is_deleted == False,  # noqa: E712
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# ─── 服务类 ───

class KdsCallService:
    """等叫（calling）状态管理服务。

    所有方法均为 async classmethod，无需实例化。
    依赖注入：AsyncSession 由 FastAPI Depends 提供。
    """

    @classmethod
    async def mark_calling(
        cls,
        task_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> KDSTask:
        """将任务状态从 cooking 推进到 calling（厨师做好、等服务员叫菜）。

        Args:
            task_id:   KDS 任务 UUID（str）
            tenant_id: 租户 UUID（str）
            db:        异步数据库会话

        Returns:
            更新后的 KDSTask 实例

        Raises:
            ValueError:   task_id / tenant_id 格式错误
            LookupError:  任务不存在
            RuntimeError: 状态流转不合法（非 cooking 状态）
        """
        log = logger.bind(task_id=task_id, tenant_id=tenant_id)

        task = await _get_task(task_id, tenant_id, db)
        if task is None:
            raise LookupError(f"任务 {task_id} 不存在")

        if task.status != STATUS_COOKING:
            raise RuntimeError(
                f"状态流转不合法：当前状态 '{task.status}'，"
                f"只有 cooking 状态可以转为 calling"
            )

        now = datetime.now(timezone.utc)
        task.status = STATUS_CALLING
        task.called_at = now  # type: ignore[attr-defined]
        task.call_count = (getattr(task, "call_count", 0) or 0) + 1  # type: ignore[attr-defined]

        await db.flush()
        log.info("kds_call_service.mark_calling.ok", call_count=task.call_count)  # type: ignore[attr-defined]

        await _broadcast("task_called", {
            "task_id": task_id,
            "tenant_id": tenant_id,
            "dept_id": str(task.dept_id) if task.dept_id else None,
            "called_at": now.isoformat(),
        })

        return task

    @classmethod
    async def confirm_served(
        cls,
        task_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> KDSTask:
        """将任务状态从 calling 推进到 done（服务员确认已上桌）。

        Args:
            task_id:   KDS 任务 UUID（str）
            tenant_id: 租户 UUID（str）
            db:        异步数据库会话

        Returns:
            更新后的 KDSTask 实例

        Raises:
            ValueError:   task_id / tenant_id 格式错误
            LookupError:  任务不存在
            RuntimeError: 状态流转不合法（非 calling 状态）
        """
        log = logger.bind(task_id=task_id, tenant_id=tenant_id)

        task = await _get_task(task_id, tenant_id, db)
        if task is None:
            raise LookupError(f"任务 {task_id} 不存在")

        if task.status != STATUS_CALLING:
            raise RuntimeError(
                f"状态流转不合法：当前状态 '{task.status}'，"
                f"只有 calling 状态可以转为 done（确认上桌）"
            )

        now = datetime.now(timezone.utc)
        task.status = STATUS_DONE
        task.served_at = now  # type: ignore[attr-defined]
        task.completed_at = now

        await db.flush()
        log.info("kds_call_service.confirm_served.ok")

        await _broadcast("task_served", {
            "task_id": task_id,
            "tenant_id": tenant_id,
            "dept_id": str(task.dept_id) if task.dept_id else None,
            "served_at": now.isoformat(),
        })

        return task

    @classmethod
    async def get_calling_tasks(
        cls,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> List[KDSTask]:
        """查询当前门店所有 calling 状态的工单（等叫队列）。

        按 called_at 升序排列（等待最久的在最前）。

        Args:
            store_id:  门店 UUID（str，用于过滤档口范围，暂作 tenant 级全局过滤）
            tenant_id: 租户 UUID（str）
            db:        异步数据库会话

        Returns:
            KDSTask 列表

        Raises:
            ValueError: tenant_id 格式错误
        """
        try:
            tid = uuid.UUID(tenant_id)
        except ValueError as exc:
            raise ValueError(f"无效的 tenant_id: {exc}") from exc

        # store_id 预留用于后续通过 dept → store 关联过滤；
        # 当前按 tenant 级查询所有 calling 任务
        stmt = (
            select(KDSTask)
            .where(
                and_(
                    KDSTask.tenant_id == tid,
                    KDSTask.status == STATUS_CALLING,
                    KDSTask.is_deleted == False,  # noqa: E712
                )
            )
            .order_by(KDSTask.called_at)  # type: ignore[attr-defined]
        )

        result = await db.execute(stmt)
        tasks = list(result.scalars().all())
        logger.bind(
            store_id=store_id, tenant_id=tenant_id, count=len(tasks)
        ).debug("kds_call_service.get_calling_tasks")
        return tasks

    @classmethod
    async def get_calling_stats(
        cls,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> CallingStats:
        """计算等叫队列统计信息。

        Args:
            store_id:  门店 UUID（str）
            tenant_id: 租户 UUID（str）
            db:        异步数据库会话

        Returns:
            CallingStats(calling_count, avg_waiting_minutes)

        Raises:
            ValueError: tenant_id 格式错误
        """
        tasks = await cls.get_calling_tasks(store_id, tenant_id, db)

        if not tasks:
            return CallingStats(calling_count=0, avg_waiting_minutes=0.0)

        now = datetime.now(timezone.utc)
        waiting_minutes: List[float] = []

        for t in tasks:
            called_at = getattr(t, "called_at", None)
            if called_at is not None:
                # 确保时区一致性
                if called_at.tzinfo is None:
                    called_at = called_at.replace(tzinfo=timezone.utc)
                delta_min = (now - called_at).total_seconds() / 60.0
                waiting_minutes.append(max(delta_min, 0.0))

        avg = sum(waiting_minutes) / len(waiting_minutes) if waiting_minutes else 0.0

        return CallingStats(
            calling_count=len(tasks),
            avg_waiting_minutes=round(avg, 2),
        )
