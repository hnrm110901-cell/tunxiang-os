"""离线查询 API — 接本地 PostgreSQL（mac-station 专用）

端点：
1. GET /api/v1/offline/revenue    当日/指定日期营业额汇总
2. GET /api/v1/offline/inventory  食材库存快照
3. GET /api/v1/offline/orders     待处理/指定状态订单列表

注意：
  - 不走 RLS，直接用 WHERE store_id 过滤（门店机只服务自己的 store_id）
  - 日期参数格式 YYYY-MM-DD；传 "today" 或省略则取当天
  - 本地 PG 由 sync-engine 定期从云端增量同步
"""

from datetime import date, datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Query
from offline_db import local_db_dependency
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/offline", tags=["offline"])


def _parse_date(date_str: str) -> date:
    """将 'today' 或 'YYYY-MM-DD' 解析为 date 对象"""
    if date_str == "today" or not date_str:
        return datetime.now(timezone.utc).date()
    return date.fromisoformat(date_str)


# ─── 1. 营业额查询 ─────────────────────────────────────────────────────────────


@router.get("/revenue", summary="离线查询当日营业额")
async def query_revenue_offline(
    store_id: str = Query(..., description="门店 ID"),
    date: str = Query("today", description="日期 YYYY-MM-DD 或 today"),
    db: AsyncSession = Depends(local_db_dependency),
) -> dict:
    """从本地 PG 聚合指定门店当日订单营业额。

    - 仅统计 status='paid' 的订单
    - 返回 total_revenue_fen、order_count、avg_order_fen
    """
    try:
        target_date = _parse_date(date)
    except ValueError:
        return {"ok": False, "error": {"code": "INVALID_DATE", "message": f"日期格式错误: {date}"}}

    result = await db.execute(
        text("""
            SELECT
                COUNT(*)                    AS order_count,
                COALESCE(SUM(total_amount_fen), 0) AS total_revenue_fen,
                COALESCE(AVG(total_amount_fen), 0) AS avg_order_fen
            FROM orders
            WHERE store_id = :sid
              AND status = 'paid'
              AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = :target_date
        """),
        {"sid": store_id, "target_date": target_date},
    )
    row = result.fetchone()

    log.info(
        "offline_revenue_queried", store_id=store_id, date=str(target_date), order_count=row.order_count if row else 0
    )
    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "date": str(target_date),
            "order_count": int(row.order_count) if row else 0,
            "total_revenue_fen": int(row.total_revenue_fen) if row else 0,
            "avg_order_fen": int(row.avg_order_fen) if row else 0,
            "source": "local_pg",
        },
    }


# ─── 2. 库存查询 ───────────────────────────────────────────────────────────────


@router.get("/inventory", summary="离线查询食材库存")
async def query_inventory_offline(
    store_id: str = Query(..., description="门店 ID"),
    low_stock_only: bool = Query(False, description="仅返回低库存（quantity_unit <= min_stock_unit）"),
    db: AsyncSession = Depends(local_db_dependency),
) -> dict:
    """从本地 PG 读取门店食材库存快照。

    - 返回食材名称、当前库存、单位、最低库存阈值
    - low_stock_only=true 时只返回需要补货的食材
    """
    sql = """
        SELECT
            i.id,
            i.name,
            i.unit,
            il.quantity_unit,
            i.min_stock_unit,
            i.category,
            il.last_updated_at
        FROM ingredients i
        JOIN ingredient_levels il
          ON il.ingredient_id = i.id AND il.store_id = :sid
        WHERE i.is_deleted = FALSE
    """
    if low_stock_only:
        sql += " AND il.quantity_unit <= i.min_stock_unit"
    sql += " ORDER BY i.category, i.name"

    result = await db.execute(text(sql), {"sid": store_id})
    rows = result.fetchall()

    items = [
        {
            "ingredient_id": str(r.id),
            "name": r.name,
            "unit": r.unit,
            "quantity": float(r.quantity_unit),
            "min_stock": float(r.min_stock_unit),
            "is_low": float(r.quantity_unit) <= float(r.min_stock_unit),
            "category": r.category,
            "last_updated_at": r.last_updated_at.isoformat() if r.last_updated_at else None,
        }
        for r in rows
    ]

    log.info("offline_inventory_queried", store_id=store_id, item_count=len(items), low_stock_only=low_stock_only)
    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "items": items,
            "total": len(items),
            "low_stock_count": sum(1 for it in items if it["is_low"]),
            "source": "local_pg",
        },
    }


# ─── 3. 订单查询 ───────────────────────────────────────────────────────────────


@router.get("/orders", summary="离线查询订单列表")
async def query_orders_offline(
    store_id: str = Query(..., description="门店 ID"),
    status: str = Query("pending", description="订单状态: pending/preparing/ready/paid/cancelled"),
    limit: int = Query(50, ge=1, le=200, description="最多返回条数"),
    db: AsyncSession = Depends(local_db_dependency),
) -> dict:
    """从本地 PG 读取指定状态的订单列表。

    - 按 created_at DESC 排序（最新在前）
    - 断网时收银/KDS 可通过此接口继续显示待处理订单
    """
    result = await db.execute(
        text("""
            SELECT
                o.id,
                o.order_no,
                o.table_id,
                o.status,
                o.total_amount_fen,
                o.item_count,
                o.created_at,
                o.updated_at
            FROM orders o
            WHERE o.store_id = :sid
              AND o.status = :status
            ORDER BY o.created_at DESC
            LIMIT :lim
        """),
        {"sid": store_id, "status": status, "lim": limit},
    )
    rows = result.fetchall()

    orders = [
        {
            "order_id": str(r.id),
            "order_no": r.order_no,
            "table_id": str(r.table_id) if r.table_id else None,
            "status": r.status,
            "total_amount_fen": r.total_amount_fen,
            "item_count": r.item_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]

    log.info("offline_orders_queried", store_id=store_id, status=status, count=len(orders))
    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "status": status,
            "orders": orders,
            "total": len(orders),
            "source": "local_pg",
        },
    }
