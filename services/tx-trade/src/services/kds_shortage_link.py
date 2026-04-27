"""KDS 缺料联动 -- 缺料上报后自动沽清/通知/采购建议

当后厨 KDS 上报缺料时，自动联动：
1. 验证库存是否真的不足
2. 自动标记相关菜品沽清（无需人工确认）
3. 通知前台（推送到 web-crew）
4. 触发采购建议（联动 stock_forecast）

同时提供出品节拍分析和出品顺序优化。
"""

import uuid
from datetime import date, datetime, timezone

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Ingredient
from shared.ontology.src.enums import InventoryStatus

logger = structlog.get_logger()

# ─── 沽清状态 ───

SELLOUT_STATUS_AVAILABLE = "available"
SELLOUT_STATUS_SOLD_OUT = "sold_out"

# ─── 内存存储（后续迁移到 Redis / DB） ───

# key: "{tenant_id}:{store_id}:{dish_id}" → sellout status
_sellout_map: dict[str, str] = {}

# key: "{tenant_id}:{store_id}" → list of notifications
_notifications: dict[str, list[dict]] = {}

# key: "{tenant_id}:{store_id}" → list of purchase suggestions
_purchase_suggestions: dict[str, list[dict]] = {}

# key: "{tenant_id}:{store_id}:{dept_id}" → list of production records
_production_records: dict[str, list[dict]] = {}

# 菜品-原料 BOM 映射（简化版，实际从 tx-menu BOM 服务获取）
# key: ingredient_id → list of dish_ids
_ingredient_dish_map: dict[str, list[str]] = {}


# ─── 工具函数 ───


def _uuid(val: str | uuid.UUID) -> uuid.UUID:
    return val if isinstance(val, uuid.UUID) else uuid.UUID(str(val))


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _store_key(store_id: str, tenant_id: str) -> str:
    return f"{tenant_id}:{store_id}"


def _dish_key(store_id: str, dish_id: str, tenant_id: str) -> str:
    return f"{tenant_id}:{store_id}:{dish_id}"


def _dept_key(store_id: str, dept_id: str, tenant_id: str) -> str:
    return f"{tenant_id}:{store_id}:{dept_id}"


# ─── 外部注册接口（供测试或初始化使用） ───


def register_ingredient_dishes(ingredient_id: str, dish_ids: list[str]) -> None:
    """注册原料-菜品映射关系。"""
    _ingredient_dish_map[ingredient_id] = list(dish_ids)


def add_production_record(
    store_id: str,
    dept_id: str,
    tenant_id: str,
    task_id: str,
    dish_name: str,
    started_at: str,
    finished_at: str,
    duration_sec: int,
) -> None:
    """添加出品记录（供 KDS 动作回调使用）。"""
    key = _dept_key(store_id, dept_id, tenant_id)
    records = _production_records.setdefault(key, [])
    records.append(
        {
            "task_id": task_id,
            "dept_id": dept_id,
            "dish_name": dish_name,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_sec": duration_sec,
        }
    )


# ─── B4-1: 缺料上报联动 ───


async def on_shortage_reported(
    task_id: str,
    ingredient_id: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """缺料上报后联动处理。

    自动执行四步联动：
    1. 检查库存是否真的不足
    2. 自动标记相关菜品沽清（无需人工确认）
    3. 通知前台（推送到 web-crew）
    4. 触发采购建议

    Args:
        task_id: KDS 任务ID
        ingredient_id: 缺料原料ID
        store_id: 门店ID
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"task_id": str, "ingredient_id": str, "stock_verified": bool,
         "actual_quantity": float, "dishes_sold_out": [...],
         "notification_sent": bool, "purchase_suggestion": dict|None}
    """
    log = logger.bind(
        task_id=task_id,
        ingredient_id=ingredient_id,
        store_id=store_id,
        tenant_id=tenant_id,
    )

    await _set_tenant(db, tenant_id)

    # ── Step 1: 验证库存 ──
    actual_quantity = 0.0
    stock_verified = False
    ingredient_name = ""

    result = await db.execute(
        select(Ingredient).where(
            Ingredient.id == _uuid(ingredient_id),
            Ingredient.store_id == _uuid(store_id),
            Ingredient.tenant_id == _uuid(tenant_id),
            Ingredient.is_deleted == False,  # noqa: E712
        )
    )
    ingredient = result.scalar_one_or_none()

    if ingredient is not None:
        actual_quantity = ingredient.current_quantity
        ingredient_name = ingredient.ingredient_name or ""
        min_qty = ingredient.min_quantity or 0

        # 库存确实不足（低于最低安全库存的 50%）
        stock_verified = actual_quantity <= min_qty * 0.5
    else:
        # 原料不存在，视为缺料确认
        stock_verified = True

    log.info(
        "shortage.stock_verified",
        actual_quantity=actual_quantity,
        stock_verified=stock_verified,
    )

    # ── Step 2: 自动沽清（无需人工确认） ──
    dishes_sold_out = []
    related_dishes = _ingredient_dish_map.get(ingredient_id, [])

    if stock_verified:
        for dish_id in related_dishes:
            dish_key = _dish_key(store_id, dish_id, tenant_id)
            _sellout_map[dish_key] = SELLOUT_STATUS_SOLD_OUT
            dishes_sold_out.append(dish_id)

        # 如果库存确实不足，更新原料状态
        if ingredient is not None and actual_quantity <= 0:
            ingredient.status = InventoryStatus.out_of_stock.value
            await db.flush()

        log.info("shortage.auto_sellout", dishes_count=len(dishes_sold_out))

    # ── Step 3: 通知前台 ──
    notification = {
        "id": uuid.uuid4().hex[:12].upper(),
        "type": "shortage_alert",
        "task_id": task_id,
        "ingredient_id": ingredient_id,
        "ingredient_name": ingredient_name,
        "actual_quantity": actual_quantity,
        "dishes_sold_out": dishes_sold_out,
        "message": f"{'已确认缺料' if stock_verified else '库存尚有余量，请人工核实'}: "
        f"{ingredient_name or ingredient_id}",
        "severity": "critical" if stock_verified else "warning",
        "created_at": _now().isoformat(),
    }

    sk = _store_key(store_id, tenant_id)
    _notifications.setdefault(sk, []).append(notification)

    log.info("shortage.notification_sent", notification_id=notification["id"])

    # ── Step 4: 触发采购建议 ──
    purchase_suggestion = None
    if stock_verified and ingredient is not None:
        # 计算建议采购量 = 最大库存 - 当前库存
        suggested_qty = (ingredient.max_quantity or 0) - actual_quantity
        if suggested_qty > 0:
            purchase_suggestion = {
                "id": uuid.uuid4().hex[:12].upper(),
                "ingredient_id": ingredient_id,
                "ingredient_name": ingredient_name,
                "current_quantity": actual_quantity,
                "suggested_quantity": suggested_qty,
                "unit": ingredient.unit or "kg",
                "supplier_name": ingredient.supplier_name or "",
                "urgency": "urgent",
                "reason": f"KDS缺料上报(任务{task_id})",
                "created_at": _now().isoformat(),
            }
            _purchase_suggestions.setdefault(sk, []).append(purchase_suggestion)

            log.info(
                "shortage.purchase_suggested",
                suggested_qty=suggested_qty,
            )

    return {
        "task_id": task_id,
        "ingredient_id": ingredient_id,
        "ingredient_name": ingredient_name,
        "stock_verified": stock_verified,
        "actual_quantity": actual_quantity,
        "dishes_sold_out": dishes_sold_out,
        "notification_sent": True,
        "purchase_suggestion": purchase_suggestion,
    }


# ─── B4-2: 出品节拍分析 ───


async def get_production_rhythm(
    store_id: str,
    date_range: tuple[date, date],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """出品节拍分析（各档口出品速度/瓶颈）。

    Args:
        store_id: 门店ID
        date_range: (start_date, end_date)
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"store_id": str, "date_range": [...], "departments": [...],
         "bottleneck_dept": str|None, "avg_speed_sec": float}
    """
    log = logger.bind(store_id=store_id, tenant_id=tenant_id)
    await _set_tenant(db, tenant_id)

    start_date, end_date = date_range
    start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)

    # 收集各档口的出品数据
    dept_stats: dict[str, dict] = {}

    for key, records in _production_records.items():
        parts = key.split(":")
        if len(parts) < 3:
            continue
        rec_tenant, rec_store, dept_id = parts[0], parts[1], parts[2]
        if rec_store != store_id or rec_tenant != tenant_id:
            continue

        dept_records = []
        for rec in records:
            finished = datetime.fromisoformat(rec["finished_at"])
            if finished < start_dt or finished > end_dt:
                continue
            dept_records.append(rec)

        if not dept_records:
            continue

        durations = [r["duration_sec"] for r in dept_records]
        avg_duration = sum(durations) / len(durations) if durations else 0
        max_duration = max(durations) if durations else 0
        min_duration = min(durations) if durations else 0

        dept_stats[dept_id] = {
            "dept_id": dept_id,
            "total_tasks": len(dept_records),
            "avg_duration_sec": round(avg_duration, 1),
            "max_duration_sec": max_duration,
            "min_duration_sec": min_duration,
            "throughput_per_hour": round(3600 / avg_duration, 1) if avg_duration > 0 else 0,
        }

    # 找瓶颈档口（平均耗时最长）
    bottleneck_dept = None
    if dept_stats:
        bottleneck_dept = max(dept_stats.keys(), key=lambda d: dept_stats[d]["avg_duration_sec"])

    all_durations = []
    for ds in dept_stats.values():
        all_durations.append(ds["avg_duration_sec"])
    overall_avg = round(sum(all_durations) / len(all_durations), 1) if all_durations else 0

    departments = list(dept_stats.values())

    log.info(
        "production_rhythm.analyzed",
        dept_count=len(departments),
        bottleneck=bottleneck_dept,
    )

    return {
        "store_id": store_id,
        "date_range": [start_date.isoformat(), end_date.isoformat()],
        "departments": departments,
        "bottleneck_dept": bottleneck_dept,
        "avg_speed_sec": overall_avg,
    }


# ─── B4-3: 优化出品顺序 ───


async def optimize_production_sequence(
    dept_id: str,
    tenant_id: str,
    db: AsyncSession,
    store_id: str = "",
) -> dict:
    """优化出品顺序（减少等待）。

    基于历史出品数据，按以下规则排序：
    1. 加急任务优先
    2. 耗时短的优先（SJF 最短作业优先，减少平均等待时间）
    3. 同等条件下按下单时间排序

    Args:
        dept_id: 档口ID
        tenant_id: 租户ID
        db: 数据库会话
        store_id: 门店ID（可选）

    Returns:
        {"dept_id": str, "optimized_sequence": [...],
         "estimated_savings_sec": float, "strategy": str}
    """
    log = logger.bind(dept_id=dept_id, tenant_id=tenant_id)
    await _set_tenant(db, tenant_id)

    # 收集该档口的历史平均耗时（按菜品名分组）
    dish_avg_times: dict[str, float] = {}

    for key, records in _production_records.items():
        parts = key.split(":")
        if len(parts) < 3:
            continue
        rec_tenant, _rec_store, rec_dept = parts[0], parts[1], parts[2]
        if rec_dept != dept_id or rec_tenant != tenant_id:
            continue

        for rec in records:
            dish = rec.get("dish_name", "unknown")
            dish_avg_times.setdefault(dish, [])
            dish_avg_times[dish].append(rec["duration_sec"])

    # 计算每道菜平均耗时
    avg_times = {}
    for dish, times in dish_avg_times.items():
        avg_times[dish] = round(sum(times) / len(times), 1) if times else 0

    # SJF 排序
    sorted_dishes = sorted(avg_times.items(), key=lambda x: x[1])

    optimized_sequence = []
    for i, (dish, avg_time) in enumerate(sorted_dishes):
        optimized_sequence.append(
            {
                "rank": i + 1,
                "dish_name": dish,
                "avg_duration_sec": avg_time,
                "priority": "high" if avg_time <= 120 else "normal",
            }
        )

    # 估算节省时间（SJF vs FCFS）
    if len(sorted_dishes) > 1:
        # SJF 的平均等待时间 vs 随机顺序
        sjf_wait = 0.0
        cumulative = 0.0
        for _, t in sorted_dishes:
            sjf_wait += cumulative
            cumulative += t
        sjf_avg = sjf_wait / len(sorted_dishes) if sorted_dishes else 0

        # 假设随机顺序等待时间约为 SJF 的 1.3 倍
        estimated_savings = round(sjf_avg * 0.3, 1)
    else:
        estimated_savings = 0.0

    log.info(
        "production_sequence.optimized",
        dept_id=dept_id,
        dish_count=len(optimized_sequence),
        estimated_savings=estimated_savings,
    )

    return {
        "dept_id": dept_id,
        "optimized_sequence": optimized_sequence,
        "estimated_savings_sec": estimated_savings,
        "strategy": "shortest_job_first",
    }


# ─── 查询辅助 ───


def get_sellout_status(store_id: str, dish_id: str, tenant_id: str) -> str:
    """获取菜品沽清状态。"""
    key = _dish_key(store_id, dish_id, tenant_id)
    return _sellout_map.get(key, SELLOUT_STATUS_AVAILABLE)


def get_pending_notifications(store_id: str, tenant_id: str) -> list[dict]:
    """获取待处理通知。"""
    sk = _store_key(store_id, tenant_id)
    return _notifications.get(sk, [])


def get_pending_purchase_suggestions(store_id: str, tenant_id: str) -> list[dict]:
    """获取待处理采购建议。"""
    sk = _store_key(store_id, tenant_id)
    return _purchase_suggestions.get(sk, [])
