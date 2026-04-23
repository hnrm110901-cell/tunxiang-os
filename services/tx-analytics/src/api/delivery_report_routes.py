"""外卖报表 API 路由

GET /api/v1/reports/delivery/summary          外卖单量统计
GET /api/v1/reports/delivery/items            外卖品项明细
GET /api/v1/reports/delivery/rider-performance 骑手配送统计
GET /api/v1/reports/delivery/order-detail     外卖订单明细

公共参数：
  ?store_id=<UUID>              门店ID（必填）
  ?date_from=YYYY-MM-DD         起始日期
  ?date_to=YYYY-MM-DD           截止日期
  ?platform=meituan|eleme|douyin|all  平台筛选（默认 all）
  ?format=csv                   返回 CSV 文件

响应格式：{"code": 0, "data": {...}, "message": "ok"}

数据来源：
  delivery_orders (id, tenant_id, store_id, platform, order_no,
                   total_amount_fen, refund_amount_fen, status,
                   delivery_minutes, created_at)
  delivery_order_items (id, order_id, dish_id, dish_name, quantity,
                        unit_price_fen, bad_review)
  delivery_riders (id, order_id, rider_name, pickup_at, delivered_at,
                   is_on_time)

查询说明：
  - summary:        GROUP BY platform，SUM(amount)/COUNT/refund统计
  - items:          JOIN delivery_order_items，GROUP BY dish_id 统计各菜品销量
  - rider-performance: GROUP BY EXTRACT(HOUR FROM created_at)，统计 delivery_minutes
  - order-detail:   分页查 delivery_orders，支持 platform/status 过滤
  所有查询均包含 tenant_id + store_id 过滤。
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/reports/delivery", tags=["delivery-reports"])

PlatformType = Literal["meituan", "eleme", "douyin", "all"]


# ──────────────────────────────────────────────
# 公共辅助
# ──────────────────────────────────────────────


def _require_store(store_id: Optional[str]) -> str:
    if not store_id:
        raise HTTPException(status_code=400, detail="store_id query parameter is required")
    return store_id


def _require_tenant(tenant_id: Optional[str]) -> str:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return tenant_id


def _parse_date(date_str: Optional[str], default: Optional[date] = None) -> date:
    if not date_str:
        return default or date.today()
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date format '{date_str}', expected YYYY-MM-DD",
        )


def _ok(data: object) -> dict:
    return {"code": 0, "data": data, "message": "ok"}


def _csv_response(rows: list[dict], filename: str) -> StreamingResponse:
    if not rows:
        content = ""
    else:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        content = buf.getvalue()
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ──────────────────────────────────────────────
# 1. 外卖单量统计
# ──────────────────────────────────────────────


@router.get("/summary")
async def api_delivery_summary(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    platform: str = Query("all", description="平台：meituan/eleme/douyin/all"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """外卖单量统计 — 含各平台分拆、退款金额、净收入"""
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            SELECT
                platform,
                COUNT(*)                                                        AS total_orders,
                COUNT(*) FILTER (WHERE status = 'completed')                    AS completed_orders,
                COALESCE(SUM(total_amount_fen) FILTER (WHERE status = 'completed'), 0)
                                                                                AS gross_gmv_fen,
                COUNT(*) FILTER (WHERE status = 'refunded')                     AS refund_orders,
                COALESCE(SUM(refund_amount_fen) FILTER (WHERE status = 'refunded'), 0)
                                                                                AS refund_amount_fen,
                COALESCE(
                    SUM(total_amount_fen - COALESCE(refund_amount_fen, 0))
                    FILTER (WHERE status = 'completed'),
                    0
                )                                                               AS net_revenue_fen
            FROM delivery_orders
            WHERE tenant_id = :tenant_id
              AND store_id  = :store_id
              AND created_at BETWEEN :d_from AND :d_to + INTERVAL '1 day'
              AND (:platform = 'all' OR platform = :platform)
            GROUP BY platform
            ORDER BY gross_gmv_fen DESC NULLS LAST
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
            "platform": platform,
        },
    )
    by_platform = [dict(r) for r in rows.mappings()]

    total_orders = sum(r.get("total_orders") or 0 for r in by_platform)
    total_gmv_fen = sum(r.get("gross_gmv_fen") or 0 for r in by_platform)
    refund_orders = sum(r.get("refund_orders") or 0 for r in by_platform)
    refund_amount_fen = sum(r.get("refund_amount_fen") or 0 for r in by_platform)
    net_revenue_fen = sum(r.get("net_revenue_fen") or 0 for r in by_platform)

    data = {
        "total_orders": total_orders,
        "total_gmv_fen": total_gmv_fen,
        "refund_orders": refund_orders,
        "refund_amount_fen": refund_amount_fen,
        "net_revenue_fen": net_revenue_fen,
        "platform": platform,
        "by_platform": by_platform,
    }

    if format == "csv":
        return _csv_response(by_platform, f"delivery_summary_{d_from}_{d_to}.csv")
    return _ok(data)


# ──────────────────────────────────────────────
# 2. 外卖品项明细
# ──────────────────────────────────────────────


@router.get("/items")
async def api_delivery_items(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    platform: str = Query("all", description="平台：meituan/eleme/douyin/all"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """外卖品项明细 — 各菜品销量/金额/差评率"""
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            SELECT
                doi.dish_id,
                doi.dish_name,
                SUM(doi.quantity)                                               AS total_quantity,
                SUM(doi.quantity * doi.unit_price_fen)                          AS total_amount_fen,
                ROUND(
                    100.0 * SUM(doi.quantity * doi.unit_price_fen)
                    / NULLIF(SUM(SUM(doi.quantity * doi.unit_price_fen)) OVER (), 0),
                    2
                )::float                                                        AS proportion_pct,
                COUNT(*) FILTER (WHERE doi.bad_review = TRUE)                   AS bad_review_count,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE doi.bad_review = TRUE)
                    / NULLIF(COUNT(*), 0),
                    2
                )::float                                                        AS bad_review_rate
            FROM delivery_order_items doi
            JOIN delivery_orders dor ON doi.order_id = dor.id
            WHERE dor.tenant_id = :tenant_id
              AND dor.store_id  = :store_id
              AND dor.created_at BETWEEN :d_from AND :d_to + INTERVAL '1 day'
              AND dor.status    = 'completed'
              AND (:platform = 'all' OR dor.platform = :platform)
            GROUP BY doi.dish_id, doi.dish_name
            ORDER BY total_amount_fen DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
            "platform": platform,
        },
    )
    items = [dict(r) for r in rows.mappings()]

    if format == "csv":
        return _csv_response(items, f"delivery_items_{d_from}_{d_to}.csv")
    return _ok(items)


# ──────────────────────────────────────────────
# 3. 骑手配送统计
# ──────────────────────────────────────────────


@router.get("/rider-performance")
async def api_rider_performance(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """骑手配送统计 — 平均配送时长/准时率/超时次数/时段分布"""
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # 汇总指标
    stats_row = await db.execute(
        text(
            """
            SELECT
                ROUND(
                    AVG(
                        EXTRACT(EPOCH FROM (r.delivered_at - r.pickup_at)) / 60.0
                    )::numeric, 1
                )::float                                                        AS avg_delivery_minutes,
                ROUND(
                    100.0 * SUM(CASE WHEN r.is_on_time THEN 1 ELSE 0 END)
                    / NULLIF(COUNT(*), 0),
                    1
                )::float                                                        AS on_time_rate,
                COUNT(*) FILTER (WHERE NOT r.is_on_time)                        AS late_count
            FROM delivery_riders r
            JOIN delivery_orders dor ON r.order_id = dor.id
            WHERE dor.tenant_id = :tenant_id
              AND dor.store_id  = :store_id
              AND dor.created_at BETWEEN :d_from AND :d_to + INTERVAL '1 day'
              AND r.delivered_at IS NOT NULL
              AND r.pickup_at    IS NOT NULL
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    stats = stats_row.mappings().first()

    # 时段分布
    slot_rows = await db.execute(
        text(
            """
            SELECT
                EXTRACT(HOUR FROM dor.created_at)::int  AS hour,
                COUNT(*)                                AS order_count
            FROM delivery_orders dor
            WHERE dor.tenant_id = :tenant_id
              AND dor.store_id  = :store_id
              AND dor.created_at BETWEEN :d_from AND :d_to + INTERVAL '1 day'
            GROUP BY EXTRACT(HOUR FROM dor.created_at)::int
            ORDER BY hour
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    by_time_slot = [dict(r) for r in slot_rows.mappings()]

    data = {
        "avg_delivery_minutes": float(stats["avg_delivery_minutes"] or 0.0) if stats else 0.0,
        "on_time_rate": float(stats["on_time_rate"] or 0.0) if stats else 0.0,
        "late_count": int(stats["late_count"] or 0) if stats else 0,
        "by_time_slot": by_time_slot,
    }

    if format == "csv":
        return _csv_response(by_time_slot, f"rider_performance_{d_from}_{d_to}.csv")
    return _ok(data)


# ──────────────────────────────────────────────
# 4. 外卖订单明细
# ──────────────────────────────────────────────


@router.get("/order-detail")
async def api_delivery_order_detail(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    platform: str = Query("all", description="平台：meituan/eleme/douyin/all"),
    status: str = Query("all", description="订单状态：all/completed/refunded/cancelled"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页条数"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """外卖订单明细 — 含平台/金额/状态/配送时长/下单时间"""
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)
    offset = (page - 1) * page_size

    params: dict = {
        "tenant_id": tenant_id,
        "store_id": store_id,
        "d_from": str(d_from),
        "d_to": str(d_to),
        "platform": platform,
        "status": status,
        "limit": page_size,
        "offset": offset,
    }

    # 总数查询
    count_row = await db.execute(
        text(
            """
            SELECT COUNT(*) AS total
            FROM delivery_orders
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND created_at BETWEEN :d_from AND :d_to + INTERVAL '1 day'
              AND (:platform = 'all' OR platform = :platform)
              AND (:status   = 'all' OR status   = :status)
            """
        ),
        params,
    )
    total = int((count_row.mappings().first() or {}).get("total") or 0)

    # 明细分页
    rows = await db.execute(
        text(
            """
            SELECT
                dor.id                              AS order_id,
                dor.order_no,
                dor.platform,
                dor.total_amount_fen,
                dor.refund_amount_fen,
                dor.status,
                dor.delivery_minutes,
                dor.created_at
            FROM delivery_orders dor
            WHERE dor.tenant_id  = :tenant_id
              AND dor.store_id   = :store_id
              AND dor.created_at BETWEEN :d_from AND :d_to + INTERVAL '1 day'
              AND (:platform = 'all' OR dor.platform = :platform)
              AND (:status   = 'all' OR dor.status   = :status)
            ORDER BY dor.created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )
    items = [dict(r) for r in rows.mappings()]

    data = {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }

    if format == "csv":
        return _csv_response(items, f"delivery_orders_{d_from}_{d_to}.csv")
    return _ok(data)
