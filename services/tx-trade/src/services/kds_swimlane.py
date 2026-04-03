"""KDS 泳道模式（生产动线/工序流水线）

泳道模式适用场景：
  - 多工序厨房：切配 → 烹饪 → 装盘 → 传菜
  - 烧烤业态：腌制 → 上串 → 烤制 → 出品
  - 大厨房：备料间 → 热菜间 → 主厨台 → 装盘区

数据模型：
  production_steps  — 档口的工序定义（管理员配置）
  kds_task_steps    — 每个任务在每道工序的执行实例

泳道看板显示：
  每列 = 一道工序
  每行 = 一个任务
  单元格颜色 = 当前工序状态（pending/in_progress/done）
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.kds_task import KDSTask
from ..models.kds_task_step import KDSTaskStep
from ..models.production_step import ProductionStep

logger = structlog.get_logger()


# ─── 工序定义管理 ───

async def get_steps_for_dept(
    tenant_id: str,
    dept_id: str,
    db: AsyncSession,
) -> list[dict]:
    """查询档口的工序列表（按 step_order 排序）。"""
    result = await db.execute(
        select(ProductionStep)
        .where(
            ProductionStep.tenant_id == uuid.UUID(tenant_id),
            ProductionStep.dept_id == uuid.UUID(dept_id),
            ProductionStep.is_active.is_(True),
            ProductionStep.is_deleted.is_(False),
        )
        .order_by(ProductionStep.step_order)
    )
    steps = result.scalars().all()
    return [
        {
            "step_id": str(s.id),
            "step_name": s.step_name,
            "step_order": s.step_order,
            "color": s.color,
        }
        for s in steps
    ]


async def upsert_step(
    tenant_id: str,
    store_id: str,
    dept_id: str,
    step_name: str,
    step_order: int,
    color: str,
    step_id: Optional[str],
    db: AsyncSession,
) -> dict:
    """新增或更新工序定义。"""
    now = datetime.now(timezone.utc)
    if step_id:
        await db.execute(
            update(ProductionStep)
            .where(
                ProductionStep.id == uuid.UUID(step_id),
                ProductionStep.tenant_id == uuid.UUID(tenant_id),
            )
            .values(
                step_name=step_name,
                step_order=step_order,
                color=color,
                updated_at=now,
            )
        )
        await db.commit()
        return {"step_id": step_id, "updated": True}

    step = ProductionStep(
        tenant_id=uuid.UUID(tenant_id),
        store_id=uuid.UUID(store_id),
        dept_id=uuid.UUID(dept_id),
        step_name=step_name,
        step_order=step_order,
        color=color,
    )
    db.add(step)
    await db.commit()
    await db.refresh(step)
    return {"step_id": str(step.id), "created": True}


# ─── 任务工序实例管理 ───

async def init_task_steps(
    tenant_id: str,
    task_id: str,
    dept_id: str,
    db: AsyncSession,
) -> list[dict]:
    """为新任务根据档口工序定义创建工序实例（分单时调用）。"""
    steps = await get_steps_for_dept(tenant_id, dept_id, db)
    if not steps:
        return []

    instances = []
    for s in steps:
        instance = KDSTaskStep(
            tenant_id=uuid.UUID(tenant_id),
            task_id=uuid.UUID(task_id),
            step_id=uuid.UUID(s["step_id"]),
            step_order=s["step_order"],
            status="pending",
        )
        db.add(instance)
        instances.append(instance)

    await db.commit()
    return [
        {"step_id": s["step_id"], "step_order": s["step_order"], "status": "pending"}
        for s in steps
    ]


async def advance_step(
    tenant_id: str,
    task_id: str,
    step_id: str,
    operator_id: Optional[str],
    db: AsyncSession,
) -> dict:
    """推进工序：将指定工序标记为 done，自动激活下一道工序。"""
    now = datetime.now(timezone.utc)

    # 完成当前工序
    await db.execute(
        update(KDSTaskStep)
        .where(
            KDSTaskStep.task_id == uuid.UUID(task_id),
            KDSTaskStep.step_id == uuid.UUID(step_id),
            KDSTaskStep.tenant_id == uuid.UUID(tenant_id),
        )
        .values(
            status="done",
            completed_at=now,
            operator_id=uuid.UUID(operator_id) if operator_id else None,
            updated_at=now,
        )
    )

    # 查找下一道工序（按 step_order 排序）
    result = await db.execute(
        select(KDSTaskStep)
        .where(
            KDSTaskStep.task_id == uuid.UUID(task_id),
            KDSTaskStep.tenant_id == uuid.UUID(tenant_id),
            KDSTaskStep.status == "pending",
        )
        .order_by(KDSTaskStep.step_order)
        .limit(1)
    )
    next_step = result.scalar_one_or_none()

    if next_step:
        await db.execute(
            update(KDSTaskStep)
            .where(KDSTaskStep.id == next_step.id)
            .values(status="in_progress", started_at=now, updated_at=now)
        )
        await db.commit()
        return {
            "task_id": task_id,
            "completed_step": step_id,
            "next_step": str(next_step.step_id),
            "all_done": False,
        }

    # 所有工序完成
    await db.commit()
    logger.info("kds.swimlane.all_steps_done", task_id=task_id)
    return {
        "task_id": task_id,
        "completed_step": step_id,
        "next_step": None,
        "all_done": True,
    }


async def get_swimlane_board(
    tenant_id: str,
    dept_id: str,
    db: AsyncSession,
) -> dict:
    """获取泳道看板数据：工序列表 + 每列的任务卡片。"""
    steps = await get_steps_for_dept(tenant_id, dept_id, db)
    if not steps:
        return {"steps": [], "lanes": {}}

    step_ids = [s["step_id"] for s in steps]

    # 查询该档口所有活跃任务的工序实例
    result = await db.execute(
        select(KDSTaskStep)
        .join(KDSTask, KDSTaskStep.task_id == KDSTask.id)
        .where(
            KDSTaskStep.tenant_id == uuid.UUID(tenant_id),
            KDSTaskStep.step_id.in_([uuid.UUID(sid) for sid in step_ids]),
            KDSTask.status.in_(["pending", "cooking"]),
            KDSTask.is_deleted.is_(False),
        )
    )
    task_steps = result.scalars().all()

    # 按工序分组
    lanes: dict[str, list[dict]] = {sid: [] for sid in step_ids}
    for ts in task_steps:
        sid = str(ts.step_id)
        if sid in lanes:
            lanes[sid].append({
                "task_step_id": str(ts.id),
                "task_id": str(ts.task_id),
                "status": ts.status,
                "operator_id": str(ts.operator_id) if ts.operator_id else None,
                "started_at": ts.started_at.isoformat() if ts.started_at else None,
            })

    return {"steps": steps, "lanes": lanes}
