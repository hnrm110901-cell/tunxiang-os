"""出餐排序算法 — 智能调度出品顺序

考虑因素：VIP优先、等待时间、工序复杂度。
为每个档口的任务列表生成最优出餐顺序。

新增：
- 同桌同出（Course Firing）— 多道菜协同延迟开始，保证同桌齐出
- 基于历史数据的出餐时间预测（P50/P90 + 档口负载修正）
- 档口负载均衡建议
- TableFireCoordinator 集成：分单后自动创建协调计划
"""

import statistics
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Dish, Order, OrderItem

logger = structlog.get_logger()

# ─── 默认出餐时间预估（秒） ───

DEFAULT_COOKING_TIME_SEC = 300  # 5分钟
SIMPLE_DISH_SEC = 120  # 简单菜品 2分钟
COMPLEX_DISH_SEC = 600  # 复杂菜品 10分钟

# ─── 历史数据阈值 ───

MIN_HISTORY_SAMPLES = 10  # 最少历史样本数（不足时 fallback 到 BOM 预设值）
HISTORY_QUERY_LIMIT = 50  # 查询最近 N 条完成记录

# ─── 档口负载均衡阈值 ───

DEFAULT_OVERLOAD_THRESHOLD = 8  # 排队超过此数量触发分流建议

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


# ─────────────────────────────────────────────
# A. 同桌同出（Course Firing）
# ─────────────────────────────────────────────


async def coordinate_same_table(
    order_id: str,
    tasks: list[dict],
    db: AsyncSession,
) -> list[dict]:
    """协同计算同桌菜品的延迟开始时间，保证所有菜同时出齐。

    原理：找出最慢的菜（bottleneck），给快菜设置延迟开始时间。
    例：鱼头25分钟、小炒肉8分钟 → 小炒肉延迟17分钟开始。

    Args:
        order_id: 订单ID
        tasks: 该订单的所有 KDS 任务列表，每个任务需包含 task_id 和 dish_id
        db: 数据库会话

    Returns:
        [{"task_id": str, "dish_name": str, "estimated_seconds": int,
          "start_delay_seconds": int, "target_completion": str}, ...]
    """
    log = logger.bind(order_id=order_id, task_count=len(tasks))

    if not tasks:
        log.info("cooking_scheduler.coordinate_same_table.empty")
        return []

    # 1) 为每道菜预测出餐时间
    task_estimates: list[dict] = []
    for task in tasks:
        dish_id = task.get("dish_id")
        if dish_id:
            prediction = await estimate_cooking_time(dish_id, db)
            est_seconds = prediction["estimated_seconds"]
        else:
            est_seconds = DEFAULT_COOKING_TIME_SEC

        task_estimates.append(
            {
                "task_id": task["task_id"],
                "dish_id": dish_id,
                "dish_name": task.get("dish_name", ""),
                "estimated_seconds": est_seconds,
            }
        )

    # 2) 找到 bottleneck（最慢的菜）
    bottleneck_seconds = max(t["estimated_seconds"] for t in task_estimates)

    # 3) 计算每道菜的延迟开始时间和目标完成时间
    now = datetime.now(timezone.utc)
    target_completion = now + timedelta(seconds=bottleneck_seconds)

    coordination_result: list[dict] = []
    for t in task_estimates:
        delay = bottleneck_seconds - t["estimated_seconds"]
        coordination_result.append(
            {
                "task_id": t["task_id"],
                "dish_name": t["dish_name"],
                "estimated_seconds": t["estimated_seconds"],
                "start_delay_seconds": delay,
                "target_completion": target_completion.isoformat(),
            }
        )

    log.info(
        "cooking_scheduler.coordinate_same_table.done",
        order_id=order_id,
        bottleneck_seconds=bottleneck_seconds,
        tasks_delayed=sum(1 for r in coordination_result if r["start_delay_seconds"] > 0),
    )
    return coordination_result


# ─────────────────────────────────────────────
# D. TableFire 协调引擎集成
# ─────────────────────────────────────────────


async def create_table_fire_plan(
    order_id: str,
    table_no: str,
    store_id: str,
    tenant_id: str,
    dept_tasks: list[dict],
    db: AsyncSession,
) -> dict | None:
    """分单后为该桌创建同出协调计划（TableFire）。

    调用时机：kds_dispatch 完成分单后自动调用。
    会为每个档口计算基于历史均值的预计完成时间，
    然后由 TableFireCoordinator 分配延迟开始时间。

    Args:
        order_id: 订单ID
        table_no: 桌号
        store_id: 门店ID
        tenant_id: 租户ID（显式隔离）
        dept_tasks: kds_dispatch 返回的 dept_tasks 列表
        db: 数据库会话

    Returns:
        {"plan_id": str, "dept_delays": {dept_id: seconds}, "target_completion": str}
        或 None（创建失败时）
    """
    from .table_production_plan import TableFireCoordinator

    log = logger.bind(order_id=order_id, table_no=table_no, tenant_id=tenant_id)

    if not dept_tasks:
        log.info("cooking_scheduler.table_fire.no_dept_tasks")
        return None

    # ── 1. 为每个档口预估完成时间 ──
    items_by_dept: dict[str, dict] = {}
    for dept in dept_tasks:
        dept_id = dept.get("dept_id", "")
        items = dept.get("items", [])
        if not dept_id or not items:
            continue

        # 取该档口所有菜品的估时均值
        est_list: list[int] = []
        for item in items:
            dish_id = item.get("dish_id")
            if dish_id:
                try:
                    prediction = await estimate_cooking_time(dish_id, db)
                    est_list.append(prediction["estimated_seconds"])
                except (ValueError, AttributeError) as exc:
                    log.warning(
                        "cooking_scheduler.table_fire.estimate_failed",
                        dish_id=dish_id,
                        error=str(exc),
                    )
                    est_list.append(DEFAULT_COOKING_TIME_SEC)
            else:
                est_list.append(DEFAULT_COOKING_TIME_SEC)

        # 档口完成时间 = 所有菜品估时的最大值（串行假设）
        dept_est_seconds = max(est_list) if est_list else DEFAULT_COOKING_TIME_SEC

        items_by_dept[dept_id] = {
            "dept_name": dept.get("dept_name", ""),
            "estimated_seconds": dept_est_seconds,
            "items": [
                {
                    "task_id": item.get("task_id", ""),
                    "dish_name": item.get("dish_name", ""),
                    "urgent": item.get("urgent", False),
                }
                for item in items
            ],
        }

    if not items_by_dept:
        log.info("cooking_scheduler.table_fire.no_valid_depts")
        return None

    # ── 2. 调用 TableFireCoordinator 创建协调计划 ──
    coordinator = TableFireCoordinator()
    try:
        plan = await coordinator.create_plan(
            order_id=order_id,
            table_no=table_no,
            store_id=store_id,
            tenant_id=tenant_id,
            items_by_dept=items_by_dept,
            db=db,
        )
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 协调计划创建失败降级为None，最外层兜底
        log.error(
            "cooking_scheduler.table_fire.create_plan_failed",
            error=str(exc),
            exc_info=True,
        )
        return None

    if plan is None:
        return None

    log.info(
        "cooking_scheduler.table_fire.plan_created",
        plan_id=str(plan.id),
        dept_count=len(items_by_dept),
    )

    return {
        "plan_id": str(plan.id),
        "dept_delays": plan.dept_delays,
        "target_completion": plan.target_completion.isoformat(),
    }


# ─────────────────────────────────────────────
# B. 出餐时间预测（历史数据驱动）
# ─────────────────────────────────────────────


async def estimate_cooking_time(dish_id: str, db: AsyncSession) -> dict:
    """基于历史出餐记录预测某道菜的制作时间。

    优先级：
    1. 历史数据（最近50条完成记录）→ 计算 P50 / P90 + 当前档口负载修正
    2. Fallback: 菜品 BOM 的 preparation_time 字段
    3. 兜底: DEFAULT_COOKING_TIME_SEC

    Returns:
        {
            "estimated_seconds": int,   # 推荐预估（P50 + 负载修正）
            "confidence": str,          # "high" / "medium" / "low"
            "p50": int | None,          # 中位数（秒）
            "p90": int | None,          # 90分位（秒）
            "source": str,             # "history" / "bom" / "default"
        }
    """
    log = logger.bind(dish_id=dish_id)

    # ── 1. 查询历史完成记录 ──
    # 通过 OrderItem 关联 Order，取 served_at - order_time 作为实际出餐耗时
    history_stmt = (
        select(
            func.extract(
                "epoch",
                Order.served_at - Order.order_time,
            ).label("duration_seconds")
        )
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(
            and_(
                OrderItem.dish_id == uuid.UUID(dish_id),
                Order.served_at.isnot(None),
                Order.is_deleted == False,  # noqa: E712
                OrderItem.is_deleted == False,  # noqa: E712
                OrderItem.return_flag == False,  # noqa: E712
            )
        )
        .order_by(Order.served_at.desc())
        .limit(HISTORY_QUERY_LIMIT)
    )

    try:
        result = await db.execute(history_stmt)
        durations: list[float] = [float(row[0]) for row in result.all() if row[0] is not None and row[0] > 0]
    except (ValueError, AttributeError) as exc:
        log.warning("cooking_scheduler.estimate.history_query_failed", error=str(exc))
        durations = []

    # ── 2. 历史数据充足 → 统计 P50 / P90 ──
    if len(durations) >= MIN_HISTORY_SAMPLES:
        p50 = int(statistics.median(durations))
        sorted_durations = sorted(durations)
        p90_idx = int(len(sorted_durations) * 0.9)
        p90 = int(sorted_durations[min(p90_idx, len(sorted_durations) - 1)])

        # 查询档口当前负载，做修正
        load_factor = await _calc_load_factor(dish_id, db)
        estimated = int(p50 * load_factor)

        confidence = "high" if len(durations) >= 30 else "medium"
        log.info(
            "cooking_scheduler.estimate.from_history",
            dish_id=dish_id,
            samples=len(durations),
            p50=p50,
            p90=p90,
            load_factor=round(load_factor, 2),
            estimated=estimated,
        )
        return {
            "estimated_seconds": estimated,
            "confidence": confidence,
            "p50": p50,
            "p90": p90,
            "source": "history",
        }

    # ── 3. Fallback: 菜品 BOM preparation_time ──
    try:
        dish_stmt = select(Dish.preparation_time).where(
            and_(
                Dish.id == uuid.UUID(dish_id),
                Dish.is_deleted == False,  # noqa: E712
            )
        )
        dish_result = await db.execute(dish_stmt)
        prep_minutes = dish_result.scalar_one_or_none()
    except (ValueError, AttributeError) as exc:
        log.warning("cooking_scheduler.estimate.dish_query_failed", error=str(exc))
        prep_minutes = None

    if prep_minutes and prep_minutes > 0:
        estimated = prep_minutes * 60  # 转秒
        log.info(
            "cooking_scheduler.estimate.from_bom",
            dish_id=dish_id,
            prep_minutes=prep_minutes,
            estimated=estimated,
            history_samples=len(durations),
        )
        return {
            "estimated_seconds": estimated,
            "confidence": "low",
            "p50": None,
            "p90": None,
            "source": "bom",
        }

    # ── 4. 兜底默认值 ──
    log.info("cooking_scheduler.estimate.default", dish_id=dish_id)
    return {
        "estimated_seconds": DEFAULT_COOKING_TIME_SEC,
        "confidence": "low",
        "p50": None,
        "p90": None,
        "source": "default",
    }


async def _calc_load_factor(dish_id: str, db: AsyncSession) -> float:
    """根据菜品所在档口的当前排队深度计算负载修正系数。

    排队为空 → 1.0（无修正）
    排队越多 → 系数越高（线性，每多1道菜 +5%，上限 2.0）
    """
    # 查档口
    try:
        station_stmt = (
            select(OrderItem.kds_station)
            .where(
                and_(
                    OrderItem.dish_id == uuid.UUID(dish_id),
                    OrderItem.kds_station.isnot(None),
                    OrderItem.is_deleted == False,  # noqa: E712
                )
            )
            .order_by(OrderItem.created_at.desc())
            .limit(1)
        )
        station_result = await db.execute(station_stmt)
        station = station_result.scalar_one_or_none()
    except (ValueError, AttributeError):
        return 1.0

    if not station:
        return 1.0

    load = await get_dept_load(station, db)
    pending = load.get("pending", 0)

    # 线性修正：每多1道菜 +5%，上限 2.0
    factor = 1.0 + (pending * 0.05)
    return min(factor, 2.0)


# ─────────────────────────────────────────────
# C. 档口负载均衡
# ─────────────────────────────────────────────


async def should_redistribute(
    dept_id: str,
    db: AsyncSession,
    *,
    overload_threshold: int = DEFAULT_OVERLOAD_THRESHOLD,
) -> dict | None:
    """判断某档口是否过载，并建议分流到备用档口。

    逻辑：
    1. 当前档口排队数 > overload_threshold
    2. 存在同类备用档口（dept_code 前缀相同，如 hot_1 / hot_2）
    3. 备用档口排队数 < 当前档口排队数

    Args:
        dept_id: 档口ID
        db: 数据库会话
        overload_threshold: 过载阈值（默认8道菜）

    Returns:
        {
            "overloaded": True,
            "current_dept_id": str,
            "current_pending": int,
            "suggested_dept_id": str,
            "suggested_dept_name": str,
            "suggested_pending": int,
        }
        or None（不需要分流）
    """
    from ..models.production_dept import ProductionDept

    log = logger.bind(dept_id=dept_id)

    # 1) 获取当前档口负载
    current_load = await get_dept_load(dept_id, db)
    current_pending = current_load["pending"]

    if current_pending <= overload_threshold:
        log.debug(
            "cooking_scheduler.redistribute.not_overloaded",
            pending=current_pending,
            threshold=overload_threshold,
        )
        return None

    # 2) 查当前档口的 dept_code，找同类备用档口
    try:
        dept_stmt = select(ProductionDept).where(
            and_(
                ProductionDept.id == uuid.UUID(dept_id),
                ProductionDept.is_deleted == False,  # noqa: E712
            )
        )
        dept_result = await db.execute(dept_stmt)
        current_dept = dept_result.scalar_one_or_none()
    except (ValueError, AttributeError) as exc:
        log.warning("cooking_scheduler.redistribute.dept_query_failed", error=str(exc))
        return None

    if not current_dept:
        return None

    # 提取 dept_code 前缀（如 "hot_1" → "hot"，"cold_kitchen" → "cold"）
    code_parts = current_dept.dept_code.split("_")
    code_prefix = code_parts[0] if code_parts else current_dept.dept_code

    # 查找同前缀的其他档口
    sibling_stmt = select(ProductionDept).where(
        and_(
            ProductionDept.tenant_id == current_dept.tenant_id,
            ProductionDept.id != current_dept.id,
            ProductionDept.dept_code.startswith(code_prefix),
            ProductionDept.is_deleted == False,  # noqa: E712
        )
    )
    sibling_result = await db.execute(sibling_stmt)
    siblings = sibling_result.scalars().all()

    if not siblings:
        log.info(
            "cooking_scheduler.redistribute.no_siblings",
            dept_code=current_dept.dept_code,
            code_prefix=code_prefix,
        )
        return None

    # 3) 找负载最低的备用档口
    best_candidate: dict | None = None
    for sibling in siblings:
        sib_load = await get_dept_load(str(sibling.id), db)
        sib_pending = sib_load["pending"]

        if sib_pending < current_pending:
            if best_candidate is None or sib_pending < best_candidate["pending"]:
                best_candidate = {
                    "dept_id": str(sibling.id),
                    "dept_name": sibling.dept_name,
                    "pending": sib_pending,
                }

    if not best_candidate:
        log.info(
            "cooking_scheduler.redistribute.siblings_also_loaded",
            dept_code=current_dept.dept_code,
        )
        return None

    result = {
        "overloaded": True,
        "current_dept_id": dept_id,
        "current_pending": current_pending,
        "suggested_dept_id": best_candidate["dept_id"],
        "suggested_dept_name": best_candidate["dept_name"],
        "suggested_pending": best_candidate["pending"],
    }

    log.info("cooking_scheduler.redistribute.suggestion", **result)
    return result


async def get_dept_load(dept_id: str, db: AsyncSession) -> dict:
    """获取档口当前负载情况。

    Returns:
        {"pending": N, "in_progress": N, "avg_wait_seconds": float}
    """
    log = logger.bind(dept_id=dept_id)

    # 查询该档口的 pending 和 cooking 任务
    pending_stmt = (
        select(func.count())
        .select_from(OrderItem)
        .where(
            and_(
                OrderItem.kds_station == dept_id,
                OrderItem.sent_to_kds_flag == True,  # noqa: E712
                OrderItem.is_deleted == False,  # noqa: E712
            )
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

    cooking_result = await db.execute(
        text("""
            SELECT COUNT(*) FROM kds_tasks
            WHERE dept_id = :dept_id AND status = 'cooking' AND is_deleted = FALSE
        """),
        {"dept_id": dept_id},
    )
    in_progress_count = int(cooking_result.scalar() or 0)

    load = {
        "pending": pending_count,
        "in_progress": in_progress_count,
        "avg_wait_seconds": round(float(avg_wait), 1),
    }

    log.info("cooking_scheduler.dept_load", **load)
    return load
