"""厨房综合异常监控 API 路由

端点：
  GET /dashboard/{store_id}  - 综合监控面板（超时+沽清+退菜）
  GET /overtime/{store_id}   - 只返回超时工单
  GET /shortage/{store_id}   - 只返回沽清告警
  GET /remake/{store_id}     - 只返回退菜工单
  GET /trend/{store_id}      - 今日各类异常数量趋势（按小时）

统一响应格式: {"ok": bool, "data": {}, "error": {}}

# ROUTER REGISTRATION:
# from .api.kitchen_monitor_routes import router as kitchen_monitor_router
# app.include_router(kitchen_monitor_router, prefix="/api/v1/kitchen-monitor")
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List

import structlog
from fastapi import APIRouter

from shared.ontology.src.database import Depends, HTTPException, Request
from shared.ontology.src.database import get_db as _get_db

router = APIRouter(tags=["kitchen-monitor"])

log = structlog.get_logger(__name__)


# ─── 数据库依赖占位 ───



def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部查询函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _get_overtime_tasks(store_id: str, tenant_id: str, db: Any) -> List[dict]:
    """查询当前超时工单（warning + critical）。"""
    try:
        from ..services.cooking_timeout import check_timeouts
    except ImportError:
        from services.cooking_timeout import check_timeouts  # type: ignore[no-redef]  # noqa: PLC0415

    items = await check_timeouts(store_id, tenant_id, db)
    result = []
    for item in items:
        # 获取标准出餐时间（threshold 字段）
        standard_min = item.get("threshold", 0)
        elapsed_min = item.get("wait_minutes", 0)
        overtime_min = round(elapsed_min - standard_min, 1) if elapsed_min > standard_min else 0.0
        result.append(
            {
                "task_id": item.get("order_item_id", ""),
                "table_no": item.get("table_number", ""),
                "dish_name": item.get("dish", ""),
                "elapsed_min": elapsed_min,
                "standard_min": standard_min,
                "overtime_min": overtime_min,
                "status": item.get("status", "warning"),
                "dept": item.get("dept", ""),
            }
        )
    return result


async def _get_shortage_alerts(store_id: str, tenant_id: str, db: Any) -> List[dict]:
    """查询今日沽清告警（按菜品聚合，统计次数）。"""
    from sqlalchemy import text

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, TRUE)"),
        {"tid": tenant_id},
    )
    result = await db.execute(
        text("""
            SELECT
                kt.dish_id::text AS dish_id,
                COALESCE(oi.item_name, kt.dish_name, '') AS dish_name,
                COUNT(*) AS shortage_count,
                MAX(kt.created_at) AS latest_at
            FROM kds_tasks kt
            LEFT JOIN order_items oi ON oi.dish_id = kt.dish_id
            WHERE kt.tenant_id = :tenant_id
              AND kt.store_id = :store_id
              AND kt.shortage_reported = TRUE
              AND kt.created_at >= :today_start
              AND kt.is_deleted = FALSE
            GROUP BY kt.dish_id, oi.item_name, kt.dish_name
            ORDER BY shortage_count DESC, latest_at DESC
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "today_start": today_start.isoformat(),
        },
    )
    rows = result.fetchall()
    return [
        {
            "dish_id": row.dish_id or "",
            "dish_name": row.dish_name or "",
            "shortage_count": int(row.shortage_count),
            "latest_at": row.latest_at.isoformat() if hasattr(row.latest_at, "isoformat") else str(row.latest_at),
        }
        for row in rows
    ]


async def _get_remake_tasks(store_id: str, tenant_id: str, db: Any) -> List[dict]:
    """查询今日退菜（重做）工单。"""
    from sqlalchemy import text

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, TRUE)"),
        {"tid": tenant_id},
    )
    result = await db.execute(
        text("""
            SELECT
                kt.id::text AS task_id,
                o.table_number AS table_no,
                COALESCE(oi.item_name, kt.dish_name, '') AS dish_name,
                kt.remake_reason AS reason,
                kt.created_at
            FROM kds_tasks kt
            JOIN orders o ON o.id = kt.order_id
            LEFT JOIN order_items oi ON oi.id = kt.order_item_id
            WHERE kt.tenant_id = :tenant_id
              AND kt.store_id = :store_id
              AND kt.remake_count > 0
              AND kt.created_at >= :today_start
              AND kt.is_deleted = FALSE
            ORDER BY kt.created_at DESC
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "today_start": today_start.isoformat(),
        },
    )
    rows = result.fetchall()
    return [
        {
            "task_id": row.task_id,
            "table_no": row.table_no or "",
            "dish_name": row.dish_name or "",
            "reason": row.reason or "",
            "created_at": row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else str(row.created_at),
        }
        for row in rows
    ]


async def _get_hourly_trend(store_id: str, tenant_id: str, db: Any) -> List[dict]:
    """今日各类异常数量按小时趋势。

    返回 0~23 小时的每小时统计，包含：overtime_count, shortage_count, remake_count
    """
    from sqlalchemy import text

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    current_hour = datetime.now(timezone.utc).hour

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, TRUE)"),
        {"tid": tenant_id},
    )

    # 超时工单（按创建时间统计已超时的）
    result_overtime = await db.execute(
        text("""
            SELECT EXTRACT(HOUR FROM oi.created_at AT TIME ZONE 'UTC')::int AS hour,
                   COUNT(*) AS cnt
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.tenant_id = :tenant_id
              AND o.store_id = :store_id
              AND oi.sent_to_kds_flag = TRUE
              AND oi.created_at >= :today_start
              AND o.is_deleted = FALSE
            GROUP BY hour
            ORDER BY hour
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "today_start": today_start.isoformat(),
        },
    )
    overtime_rows = {row.hour: int(row.cnt) for row in result_overtime.fetchall()}

    # 沽清
    result_shortage = await db.execute(
        text("""
            SELECT EXTRACT(HOUR FROM created_at AT TIME ZONE 'UTC')::int AS hour,
                   COUNT(*) AS cnt
            FROM kds_tasks
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id
              AND shortage_reported = TRUE
              AND created_at >= :today_start
              AND is_deleted = FALSE
            GROUP BY hour
            ORDER BY hour
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "today_start": today_start.isoformat(),
        },
    )
    shortage_rows = {row.hour: int(row.cnt) for row in result_shortage.fetchall()}

    # 退菜
    result_remake = await db.execute(
        text("""
            SELECT EXTRACT(HOUR FROM created_at AT TIME ZONE 'UTC')::int AS hour,
                   COUNT(*) AS cnt
            FROM kds_tasks
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id
              AND remake_count > 0
              AND created_at >= :today_start
              AND is_deleted = FALSE
            GROUP BY hour
            ORDER BY hour
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "today_start": today_start.isoformat(),
        },
    )
    remake_rows = {row.hour: int(row.cnt) for row in result_remake.fetchall()}

    trend = []
    for h in range(current_hour + 1):
        trend.append(
            {
                "hour": h,
                "overtime_count": overtime_rows.get(h, 0),
                "shortage_count": shortage_rows.get(h, 0),
                "remake_count": remake_rows.get(h, 0),
            }
        )
    return trend


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /dashboard/{store_id}
#  综合监控面板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/dashboard/{store_id}")
async def get_dashboard(
    store_id: str,
    request: Request,
    db=Depends(_get_db),
):
    """厨房综合异常监控面板。

    汇总超时、沽清、退菜三类异常，返回统一面板数据。

    Returns:
        {
          "overtime_tasks": [{task_id, table_no, dish_name, elapsed_min, standard_min}],
          "shortage_alerts": [{dish_id, dish_name, shortage_count, latest_at}],
          "remake_tasks": [{task_id, table_no, dish_name, reason, created_at}],
          "summary": {overtime_count, shortage_count, remake_count, total_anomalies}
        }
    """
    tenant_id = _get_tenant_id(request)
    _log = log.bind(store_id=store_id, tenant_id=tenant_id)

    try:
        overtime = await _get_overtime_tasks(store_id, tenant_id, db)
        shortage = await _get_shortage_alerts(store_id, tenant_id, db)
        remake = await _get_remake_tasks(store_id, tenant_id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    total = len(overtime) + len(shortage) + len(remake)
    _log.info(
        "kitchen_monitor.dashboard",
        overtime=len(overtime),
        shortage=len(shortage),
        remake=len(remake),
    )

    return {
        "ok": True,
        "data": {
            "overtime_tasks": overtime,
            "shortage_alerts": shortage,
            "remake_tasks": remake,
            "summary": {
                "overtime_count": len(overtime),
                "shortage_count": len(shortage),
                "remake_count": len(remake),
                "total_anomalies": total,
            },
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /overtime/{store_id}
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/overtime/{store_id}")
async def get_overtime(
    store_id: str,
    request: Request,
    db=Depends(_get_db),
):
    """只返回当前超时工单（warning + critical）。"""
    tenant_id = _get_tenant_id(request)
    try:
        items = await _get_overtime_tasks(store_id, tenant_id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "total": len(items),
            "critical": sum(1 for i in items if i.get("status") == "critical"),
            "warning": sum(1 for i in items if i.get("status") == "warning"),
            "items": items,
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /shortage/{store_id}
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/shortage/{store_id}")
async def get_shortage(
    store_id: str,
    request: Request,
    db=Depends(_get_db),
):
    """只返回今日沽清告警（按菜品聚合）。"""
    tenant_id = _get_tenant_id(request)
    try:
        alerts = await _get_shortage_alerts(store_id, tenant_id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "total": len(alerts),
            "alerts": alerts,
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /remake/{store_id}
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/remake/{store_id}")
async def get_remake(
    store_id: str,
    request: Request,
    db=Depends(_get_db),
):
    """只返回今日退菜工单。"""
    tenant_id = _get_tenant_id(request)
    try:
        tasks = await _get_remake_tasks(store_id, tenant_id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "total": len(tasks),
            "tasks": tasks,
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /trend/{store_id}
#  今日各类异常数量趋势（按小时分桶）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/trend/{store_id}")
async def get_trend(
    store_id: str,
    request: Request,
    db=Depends(_get_db),
):
    """今日各类异常数量趋势（按小时分桶）。

    Returns:
        {
          "store_id": str,
          "trend": [
            {"hour": 0, "overtime_count": 0, "shortage_count": 0, "remake_count": 0},
            ...
          ]
        }
    """
    tenant_id = _get_tenant_id(request)
    try:
        trend = await _get_hourly_trend(store_id, tenant_id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "trend": trend,
        },
    }
