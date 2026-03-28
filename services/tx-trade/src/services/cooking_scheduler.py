"""出餐排序算法 — 智能调度出品顺序

考虑因素：VIP优先、等待时间、工序复杂度。
为每个档口的任务列表生成最优出餐顺序。
"""
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem

logger = structlog.get_logger()

# ─── 默认出餐时间预估（秒） ───

DEFAULT_COOKING_TIME_SEC = 300  # 5分钟
SIMPLE_DISH_SEC = 120           # 简单菜品 2分钟
COMPLEX_DISH_SEC = 600          # 复杂菜品 10分钟

# ─── 优先级权重 ───

WEIGHT_VIP = 3.0
WEIGHT_WAIT_TIME = 2.0
WEIGHT_COMPLEXITY = 1.0
WEIGHT_URGENT = 5.0


def _calculate_priority_score(task: dict, now: datetime) -> float:
    """计算单个任务的综合优先级分数（越高越优先）。

    公式：score = urgent_bonus + vip_bonus + wait_time_score - complexity_penalty
    """
    score = 0.0

    # 催菜标记 — 最高优先
    if task.get("urgent"):
        score += WEIGHT_URGENT * 100

    # VIP 加权
    if task.get("is_vip"):
        score += WEIGHT_VIP * 50

    # 等待时间加权（等越久越优先）
    created_str = task.get("created_at")
    if created_str:
        if isinstance(created_str, str):
            try:
                created = datetime.fromisoformat(created_str)
            except ValueError:
                created = now
        else:
            created = created_str
        wait_seconds = (now - created).total_seconds()
        score += WEIGHT_WAIT_TIME * min(wait_seconds / 60, 30)  # 最多30分钟的加权

    # 复杂度惩罚（复杂菜出餐慢，排后面）
    complexity = task.get("complexity", 1)
    score -= WEIGHT_COMPLEXITY * complexity

    return score


async def calculate_cooking_order(
    dept_tasks: list[dict],
    db: AsyncSession,
) -> list[dict]:
    """对档口任务列表按优先级排序。

    Args:
        dept_tasks: [{"dept_id": ..., "dept_name": ..., "items": [...], "priority": ...}]
        db: 数据库会话

    Returns:
        排序后的同结构任务列表，items 内部已按优先级重新排序。
    """
    log = logger.bind(dept_count=len(dept_tasks))
    now = datetime.now(timezone.utc)

    sorted_tasks = []
    for dept in dept_tasks:
        items = dept.get("items", [])
        # 为每个 item 计算分数
        scored_items = []
        for item in items:
            score = _calculate_priority_score(item, now)
            scored_items.append((score, item))

        # 按分数降序排列
        scored_items.sort(key=lambda x: x[0], reverse=True)

        sorted_dept = {
            **dept,
            "items": [item for _, item in scored_items],
        }
        sorted_tasks.append(sorted_dept)

    log.info("cooking_scheduler.sorted", total_items=sum(len(d["items"]) for d in sorted_tasks))
    return sorted_tasks


async def estimate_cooking_time(dish_id: str, db: AsyncSession) -> int:
    """预估某道菜的出餐时间（秒）。

    当前采用基于菜品类型的静态预估，后续可接入 Core ML 边缘推理
    （POST /predict/dish-time）获取更精准的预测。

    Returns:
        预估秒数
    """
    log = logger.bind(dish_id=dish_id)

    # TODO: 接入 Core ML 预测模型（edge/coreml-bridge POST /predict/dish-time）
    # 当前使用默认值
    estimated = DEFAULT_COOKING_TIME_SEC

    log.info("cooking_scheduler.estimate_time", dish_id=dish_id, seconds=estimated)
    return estimated


async def get_dept_load(dept_id: str, db: AsyncSession) -> dict:
    """获取档口当前负载情况。

    Returns:
        {"pending": N, "in_progress": N, "avg_wait_seconds": float}
    """
    log = logger.bind(dept_id=dept_id)

    # 查询该档口的 pending 和 cooking 任务
    pending_stmt = select(func.count()).select_from(OrderItem).where(
        and_(
            OrderItem.kds_station == dept_id,
            OrderItem.sent_to_kds_flag == True,  # noqa: E712
            OrderItem.is_deleted == False,  # noqa: E712
        )
    )
    pending_result = await db.execute(pending_stmt)
    pending_count = pending_result.scalar() or 0

    # 计算平均等待时间
    now = datetime.now(timezone.utc)
    avg_stmt = select(func.avg(func.extract("epoch", now - OrderItem.created_at))).where(
        and_(
            OrderItem.kds_station == dept_id,
            OrderItem.sent_to_kds_flag == True,  # noqa: E712
            OrderItem.is_deleted == False,  # noqa: E712
        )
    )
    avg_result = await db.execute(avg_stmt)
    avg_wait = avg_result.scalar() or 0.0

    load = {
        "pending": pending_count,
        "in_progress": 0,  # TODO: 需 KDS 任务表区分 cooking 状态
        "avg_wait_seconds": round(float(avg_wait), 1),
    }

    log.info("cooking_scheduler.dept_load", **load)
    return load
