"""KDS 停菜 & 抢单服务

停菜（Pause）：
  半成品已制作完成，但当前不需要出品（如菜上太快、顾客示意稍等）。
  标记后卡片变灰色+暂停图标，厨师确认恢复后重新进入 calling 队列。

抢单（Grab）：
  厨师主动抢取 pending 任务，实现多劳多得激励机制。
  抢单记录到 grabbed_by 字段，作为绩效计件的归属依据。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.kds_task import KDSTask

logger = structlog.get_logger()

# ─── 停菜操作 ───

async def pause_task(
    task_id: str,
    operator_id: Optional[str],
    db: AsyncSession,
) -> dict:
    """停菜：标记任务暂停出品。

    适用状态：cooking（已开始制作）
    目标状态：cooking + is_paused=True（状态不变，加停菜标记）
    """
    result = await db.execute(
        select(KDSTask).where(KDSTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise ValueError(f"task_id={task_id} 不存在")
    if task.status not in ("cooking", "pending"):
        raise ValueError(f"当前状态 {task.status} 不允许停菜（仅 pending/cooking 可停菜）")
    if task.is_paused:
        raise ValueError("任务已处于停菜状态")

    now = datetime.now(timezone.utc)
    await db.execute(
        update(KDSTask)
        .where(KDSTask.id == uuid.UUID(task_id))
        .values(
            is_paused=True,
            paused_at=now,
            operator_id=uuid.UUID(operator_id) if operator_id else task.operator_id,
            updated_at=now,
        )
    )
    await db.commit()

    logger.info("kds.task.paused", task_id=task_id, operator_id=operator_id)
    return {
        "task_id": task_id,
        "is_paused": True,
        "paused_at": now.isoformat(),
    }


async def resume_task(
    task_id: str,
    operator_id: Optional[str],
    db: AsyncSession,
) -> dict:
    """恢复停菜：解除暂停标记，任务重新进入出品队列。"""
    result = await db.execute(
        select(KDSTask).where(KDSTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise ValueError(f"task_id={task_id} 不存在")
    if not task.is_paused:
        raise ValueError("任务当前未处于停菜状态")

    now = datetime.now(timezone.utc)
    await db.execute(
        update(KDSTask)
        .where(KDSTask.id == uuid.UUID(task_id))
        .values(
            is_paused=False,
            paused_at=None,
            operator_id=uuid.UUID(operator_id) if operator_id else task.operator_id,
            updated_at=now,
        )
    )
    await db.commit()

    logger.info("kds.task.resumed", task_id=task_id, operator_id=operator_id)
    return {
        "task_id": task_id,
        "is_paused": False,
        "resumed_at": now.isoformat(),
    }


# ─── 抢单操作 ───

async def grab_task(
    task_id: str,
    operator_id: str,
    db: AsyncSession,
) -> dict:
    """抢单：厨师主动认领 pending 任务，开始制作。

    先到先得：若已被抢走则返回错误提示抢单者。
    同时将 grabbed_by 写入 operator_id，作为绩效归属依据。
    """
    result = await db.execute(
        select(KDSTask).where(KDSTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise ValueError(f"task_id={task_id} 不存在")
    if task.status != "pending":
        raise ValueError(f"该任务已被抢走或不可抢单（当前状态：{task.status}）")
    if task.grabbed_by is not None:
        raise ValueError("该任务已被其他厨师抢走")

    now = datetime.now(timezone.utc)
    # 乐观并发：用 WHERE grabbed_by IS NULL 防止两人同时抢单
    rows = await db.execute(
        update(KDSTask)
        .where(
            KDSTask.id == uuid.UUID(task_id),
            KDSTask.grabbed_by.is_(None),
            KDSTask.status == "pending",
        )
        .values(
            grabbed_by=uuid.UUID(operator_id),
            operator_id=uuid.UUID(operator_id),
            status="cooking",
            started_at=now,
            updated_at=now,
        )
        .returning(KDSTask.id)
    )
    grabbed = rows.scalar_one_or_none()
    if grabbed is None:
        raise ValueError("抢单失败：任务已被其他厨师抢走，请刷新列表")

    await db.commit()

    logger.info("kds.task.grabbed", task_id=task_id, operator_id=operator_id)
    return {
        "task_id": task_id,
        "grabbed_by": operator_id,
        "status": "cooking",
        "started_at": now.isoformat(),
    }
