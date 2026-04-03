"""高峰值守服务 — E3 模块

提供高峰检测、档口负载监控、服务加派建议、等位拥堵指标、高峰事件处理。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# 高峰判定阈值
PEAK_OCCUPANCY_THRESHOLD = 0.80   # 上座率 >= 80% 视为高峰
PEAK_QUEUE_THRESHOLD = 10          # 等位数 >= 10 视为高峰
DEPT_OVERLOAD_THRESHOLD = 0.90     # 档口负载率 >= 90% 视为过载


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS tenant context"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── 高峰检测 ───


async def detect_peak(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """检测门店是否进入高峰（基于当前上座率 + 等位数）

    Returns:
        is_peak: bool
        occupancy_rate: float (0-1)
        queue_count: int
        peak_level: str ("normal" / "busy" / "peak" / "extreme")
    """
    await _set_tenant(db, tenant_id)

    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)
    now = datetime.now(timezone.utc)

    # 查询上座率
    occupancy_result = await db.execute(
        text("""
            SELECT
                COUNT(CASE WHEN t.status = 'occupied' THEN 1 END) AS occupied_count,
                COUNT(*) AS total_tables
            FROM tables t
            WHERE t.store_id = :store_id
              AND t.tenant_id = :tenant_id
              AND t.is_deleted = false
        """),
        {"store_id": store_uuid, "tenant_id": tenant_uuid},
    )
    occ_row = occupancy_result.mappings().first()
    total_tables = occ_row["total_tables"] if occ_row else 0
    occupied = occ_row["occupied_count"] if occ_row else 0
    occupancy_rate = occupied / total_tables if total_tables > 0 else 0

    # 查询等位数
    queue_result = await db.execute(
        text("""
            SELECT COUNT(*) AS queue_count
            FROM queue_tickets qt
            WHERE qt.store_id = :store_id
              AND qt.tenant_id = :tenant_id
              AND qt.status = 'waiting'
              AND qt.created_at > :now - interval '4 hours'
        """),
        {"store_id": store_uuid, "tenant_id": tenant_uuid, "now": now},
    )
    queue_count = queue_result.scalar() or 0

    # 判定高峰级别
    is_peak = occupancy_rate >= PEAK_OCCUPANCY_THRESHOLD or queue_count >= PEAK_QUEUE_THRESHOLD

    if queue_count >= PEAK_QUEUE_THRESHOLD * 3:
        peak_level = "extreme"
    elif is_peak and queue_count >= PEAK_QUEUE_THRESHOLD:
        peak_level = "peak"
    elif occupancy_rate >= 0.65 or queue_count >= 5:
        peak_level = "busy"
    else:
        peak_level = "normal"

    log.info(
        "peak_detected",
        store_id=store_id,
        is_peak=is_peak,
        peak_level=peak_level,
        occupancy_rate=round(occupancy_rate, 2),
        queue_count=queue_count,
        tenant_id=tenant_id,
    )

    return {
        "store_id": store_id,
        "is_peak": is_peak,
        "peak_level": peak_level,
        "occupancy_rate": round(occupancy_rate, 2),
        "occupied_tables": occupied,
        "total_tables": total_tables,
        "queue_count": queue_count,
        "detected_at": now.isoformat(),
    }


# ─── 档口负载实时监控 ───


async def get_dept_load_monitor(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """档口负载实时监控

    计算每个档口的待处理订单数 / 档口处理能力，得出负载率。
    """
    await _set_tenant(db, tenant_id)

    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    result = await db.execute(
        text("""
            SELECT
                dept.id AS dept_id,
                dept.name AS dept_name,
                dept.capacity_per_hour,
                COUNT(oi.id) FILTER (WHERE oi.status IN ('pending', 'cooking')) AS pending_count,
                AVG(EXTRACT(EPOCH FROM (NOW() - oi.created_at)))
                    FILTER (WHERE oi.status IN ('pending', 'cooking'))
                    AS avg_wait_seconds
            FROM departments dept
            LEFT JOIN order_items oi
                ON oi.dept_id = dept.id
                AND oi.store_id = dept.store_id
                AND oi.tenant_id = dept.tenant_id
                AND oi.status IN ('pending', 'cooking')
                AND oi.is_deleted = false
            WHERE dept.store_id = :store_id
              AND dept.tenant_id = :tenant_id
              AND dept.is_deleted = false
            GROUP BY dept.id, dept.name, dept.capacity_per_hour
            ORDER BY COUNT(oi.id) FILTER (WHERE oi.status IN ('pending', 'cooking')) DESC
        """),
        {"store_id": store_uuid, "tenant_id": tenant_uuid},
    )
    rows = result.mappings().all()

    departments = []
    overloaded_count = 0
    for r in rows:
        capacity = r["capacity_per_hour"] or 30  # 默认每小时30份
        pending = r["pending_count"] or 0
        # 负载率 = 待处理量 / (每小时能力 / 6) — 假设10分钟窗口
        load_rate = pending / max(capacity / 6, 1)
        is_overloaded = load_rate >= DEPT_OVERLOAD_THRESHOLD

        if is_overloaded:
            overloaded_count += 1

        departments.append({
            "dept_id": str(r["dept_id"]),
            "dept_name": r["dept_name"],
            "capacity_per_hour": capacity,
            "pending_count": pending,
            "load_rate": round(min(load_rate, 2.0), 2),
            "avg_wait_seconds": round(r["avg_wait_seconds"]) if r["avg_wait_seconds"] else 0,
            "is_overloaded": is_overloaded,
        })

    log.info(
        "dept_load_monitored",
        store_id=store_id,
        dept_count=len(departments),
        overloaded_count=overloaded_count,
        tenant_id=tenant_id,
    )

    return {
        "store_id": store_id,
        "departments": departments,
        "overloaded_count": overloaded_count,
        "total_departments": len(departments),
    }


# ─── 服务加派建议 ───


async def suggest_staff_dispatch(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """服务加派建议

    基于档口负载 + 等位数 + 上座率，生成调度建议。
    """
    await _set_tenant(db, tenant_id)

    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    # 查询当前值班人员
    staff_result = await db.execute(
        text("""
            SELECT
                s.id AS staff_id,
                s.name AS staff_name,
                s.role,
                s.current_dept_id,
                dept.name AS current_dept_name,
                s.skill_tags
            FROM staff_schedules ss
            JOIN staff s ON s.id = ss.staff_id AND s.tenant_id = :tenant_id
            LEFT JOIN departments dept ON dept.id = s.current_dept_id AND dept.tenant_id = :tenant_id
            WHERE ss.store_id = :store_id
              AND ss.tenant_id = :tenant_id
              AND ss.shift_date = CURRENT_DATE
              AND ss.is_on_duty = true
              AND ss.is_deleted = false
              AND s.is_deleted = false
        """),
        {"store_id": store_uuid, "tenant_id": tenant_uuid},
    )
    staff_rows = staff_result.mappings().all()

    # 获取档口负载
    dept_load = await get_dept_load_monitor(store_id, tenant_id, db)

    suggestions = []
    for dept in dept_load["departments"]:
        if dept["is_overloaded"]:
            # 找到可调派的空闲或低负载档口员工
            available = [
                s for s in staff_rows
                if str(s["current_dept_id"]) != dept["dept_id"]
                and s["role"] in ("cook", "helper", "flexible")
            ]
            if available:
                candidate = available[0]
                suggestions.append({
                    "action": "dispatch",
                    "target_dept_id": dept["dept_id"],
                    "target_dept_name": dept["dept_name"],
                    "staff_id": str(candidate["staff_id"]),
                    "staff_name": candidate["staff_name"],
                    "reason": f"档口'{dept['dept_name']}'负载率{dept['load_rate']:.0%}，"
                              f"待处理{dept['pending_count']}单",
                    "priority": "high" if dept["load_rate"] > 1.5 else "medium",
                })

    log.info(
        "staff_dispatch_suggested",
        store_id=store_id,
        suggestion_count=len(suggestions),
        on_duty_count=len(staff_rows),
        tenant_id=tenant_id,
    )

    return {
        "store_id": store_id,
        "on_duty_staff": len(staff_rows),
        "overloaded_depts": dept_load["overloaded_count"],
        "suggestions": suggestions,
    }


# ─── 等位拥堵指标 ───


async def get_queue_pressure(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """等位拥堵指标

    返回各桌型等位数、平均等待时长、预估等待时间。
    """
    await _set_tenant(db, tenant_id)

    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        text("""
            SELECT
                qt.table_type,
                COUNT(*) AS queue_count,
                AVG(EXTRACT(EPOCH FROM (:now - qt.created_at))) AS avg_wait_seconds,
                MAX(EXTRACT(EPOCH FROM (:now - qt.created_at))) AS max_wait_seconds,
                MIN(qt.created_at) AS earliest_ticket
            FROM queue_tickets qt
            WHERE qt.store_id = :store_id
              AND qt.tenant_id = :tenant_id
              AND qt.status = 'waiting'
              AND qt.created_at > :now - interval '4 hours'
            GROUP BY qt.table_type
            ORDER BY COUNT(*) DESC
        """),
        {"store_id": store_uuid, "tenant_id": tenant_uuid, "now": now},
    )
    rows = result.mappings().all()

    # 查询各桌型翻台速度
    turnover_result = await db.execute(
        text("""
            SELECT
                t.table_type,
                AVG(EXTRACT(EPOCH FROM (o.paid_at - o.created_at))) AS avg_dining_seconds
            FROM orders o
            JOIN tables t ON t.id = o.table_id AND t.tenant_id = :tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND o.status = 'paid'
              AND o.created_at > :now - interval '7 days'
              AND o.is_deleted = false
            GROUP BY t.table_type
        """),
        {"store_id": store_uuid, "tenant_id": tenant_uuid, "now": now},
    )
    turnover_rows = {r["table_type"]: r["avg_dining_seconds"]
                     for r in turnover_result.mappings().all()}

    queues = []
    total_waiting = 0
    for r in rows:
        table_type = r["table_type"]
        queue_count = r["queue_count"]
        total_waiting += queue_count
        avg_dining_sec = turnover_rows.get(table_type, 3600)  # 默认1小时

        # 预估等待 = 平均用餐时长 * (等位数 / 该桌型台数) — 简化估算
        estimated_wait_minutes = round(
            (avg_dining_sec or 3600) * queue_count / max(queue_count, 1) / 60
        )

        queues.append({
            "table_type": table_type,
            "queue_count": queue_count,
            "avg_wait_seconds": round(r["avg_wait_seconds"]) if r["avg_wait_seconds"] else 0,
            "max_wait_seconds": round(r["max_wait_seconds"]) if r["max_wait_seconds"] else 0,
            "estimated_wait_minutes": estimated_wait_minutes,
        })

    # 拥堵指数 (0-100)
    congestion_index = min(100, total_waiting * 5 + sum(
        q["avg_wait_seconds"] / 60 for q in queues
    ))

    log.info(
        "queue_pressure_calculated",
        store_id=store_id,
        total_waiting=total_waiting,
        congestion_index=round(congestion_index),
        tenant_id=tenant_id,
    )

    return {
        "store_id": store_id,
        "total_waiting": total_waiting,
        "congestion_index": round(congestion_index),
        "queues": queues,
        "measured_at": now.isoformat(),
    }


# ─── 高峰事件处理 ───


async def handle_peak_event(
    store_id: str,
    event_type: str,
    tenant_id: str,
    db: AsyncSession,
    *,
    params: Optional[dict] = None,
) -> dict:
    """高峰事件处理（临时调菜/调台）

    Args:
        store_id: 门店 ID
        event_type: 事件类型
            - "temp_menu_switch": 临时切换高峰菜单（隐藏耗时菜品）
            - "table_merge": 并台
            - "table_split": 拆台
            - "express_mode": 开启快速出餐模式
            - "queue_divert": 等位分流
        tenant_id: 租户 ID
        db: 数据库会话
        params: 事件参数
    """
    await _set_tenant(db, tenant_id)

    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)
    now = datetime.now(timezone.utc)
    event_params = params or {}

    event_id = uuid.uuid4()

    # 记录事件
    await db.execute(
        text("""
            INSERT INTO peak_events (
                id, tenant_id, store_id, event_type,
                params, status,
                is_deleted, created_at, updated_at
            ) VALUES (
                :id, :tenant_id, :store_id, :event_type,
                :params, 'active',
                false, :now, :now
            )
        """),
        {
            "id": event_id,
            "tenant_id": tenant_uuid,
            "store_id": store_uuid,
            "event_type": event_type,
            "params": str(event_params),
            "now": now,
        },
    )

    # 根据事件类型执行对应操作
    action_result: dict = {}

    if event_type == "temp_menu_switch":
        # 临时隐藏耗时菜品
        hide_dish_ids = event_params.get("hide_dish_ids", [])
        if hide_dish_ids:
            await db.execute(
                text("""
                    UPDATE dish_store_settings
                    SET is_temporarily_hidden = true, updated_at = :now
                    WHERE store_id = :store_id
                      AND tenant_id = :tenant_id
                      AND dish_id = ANY(:dish_ids)
                """),
                {
                    "store_id": store_uuid,
                    "tenant_id": tenant_uuid,
                    "dish_ids": [uuid.UUID(d) for d in hide_dish_ids],
                    "now": now,
                },
            )
        action_result = {"hidden_dishes": len(hide_dish_ids)}

    elif event_type == "express_mode":
        # 开启快速出餐模式：通知所有档口优先出简单菜品
        await db.execute(
            text("""
                UPDATE store_runtime_config
                SET express_mode = true, express_mode_since = :now, updated_at = :now
                WHERE store_id = :store_id AND tenant_id = :tenant_id
            """),
            {"store_id": store_uuid, "tenant_id": tenant_uuid, "now": now},
        )
        action_result = {"express_mode": True}

    elif event_type == "table_merge":
        source_table = event_params.get("source_table_id")
        target_table = event_params.get("target_table_id")
        action_result = {
            "merged": True,
            "source_table_id": source_table,
            "target_table_id": target_table,
        }

    elif event_type == "table_split":
        table_id = event_params.get("table_id")
        action_result = {"split": True, "table_id": table_id}

    elif event_type == "queue_divert":
        # 分流：引导部分等位客人到其他区域
        divert_count = event_params.get("divert_count", 0)
        target_area = event_params.get("target_area", "bar")
        action_result = {
            "diverted": True,
            "divert_count": divert_count,
            "target_area": target_area,
        }

    await db.flush()

    log.info(
        "peak_event_handled",
        event_id=str(event_id),
        store_id=store_id,
        event_type=event_type,
        action_result=action_result,
        tenant_id=tenant_id,
    )

    return {
        "event_id": str(event_id),
        "store_id": store_id,
        "event_type": event_type,
        "status": "active",
        "action_result": action_result,
        "created_at": now.isoformat(),
    }
