"""预定报表 API 路由

GET /api/v1/reports/booking/summary     预定汇总
GET /api/v1/reports/booking/proportion  预定占比分析
GET /api/v1/reports/booking/trend       预定走势
GET /api/v1/reports/booking/items       预定品项统计

公共参数：
  ?store_id=<UUID>              门店ID（必填）
  ?date_from=YYYY-MM-DD         起始日期
  ?date_to=YYYY-MM-DD           截止日期
  ?format=csv                   返回 CSV 文件

响应格式：{"code": 0, "data": {...}, "message": "ok"}

数据来源：
  bookings (id, tenant_id, store_id, booking_no, contact_name, contact_phone,
            table_size, booking_time, arrived_at, cancelled_at,
            deposit_amount_fen, status, created_at)
  booking_order_items (id, booking_id, dish_id, dish_name, quantity,
                       unit_price_fen)

查询说明：
  - summary:    COUNT(*)/COUNT(arrived)/COUNT(cancelled)/SUM(deposit_amount_fen)
                按 booking_time BETWEEN d_from AND d_to 过滤
  - proportion: GROUP BY 时段（早/午/晚/夜）和 table_size
  - trend:      DATE_TRUNC(:granularity, booking_time) GROUP BY 聚合
  - items:      JOIN booking_order_items，GROUP BY dish_id 统计各菜品
  所有查询均包含 tenant_id + store_id 过滤。
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/reports/booking", tags=["booking-reports"])


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
# 1. 预定汇总
# ──────────────────────────────────────────────


@router.get("/summary")
async def api_booking_summary(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """预定汇总 — 预定量/到店率/取消率/爽约率/定金总额"""
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    row = await db.execute(
        text(
            """
            SELECT
                COUNT(*)                                                            AS total_bookings,
                COUNT(*) FILTER (WHERE status = 'arrived')                         AS arrived_count,
                COUNT(*) FILTER (WHERE status = 'cancelled')                       AS cancelled_count,
                COUNT(*) FILTER (WHERE status = 'no_show')                         AS no_show_count,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE status = 'arrived')
                    / NULLIF(COUNT(*), 0),
                    1
                )::float                                                            AS arrival_rate_pct,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE status = 'cancelled')
                    / NULLIF(COUNT(*), 0),
                    1
                )::float                                                            AS cancel_rate_pct,
                COALESCE(SUM(deposit_amount_fen), 0)                               AS total_deposit_fen
            FROM bookings
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND booking_time BETWEEN :d_from AND :d_to + INTERVAL '1 day'
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    r = row.mappings().first()

    data = {
        "total_bookings": int(r["total_bookings"] or 0) if r else 0,
        "arrived_count": int(r["arrived_count"] or 0) if r else 0,
        "cancelled_count": int(r["cancelled_count"] or 0) if r else 0,
        "no_show_count": int(r["no_show_count"] or 0) if r else 0,
        "arrival_rate_pct": float(r["arrival_rate_pct"] or 0.0) if r else 0.0,
        "cancel_rate_pct": float(r["cancel_rate_pct"] or 0.0) if r else 0.0,
        "total_deposit_fen": int(r["total_deposit_fen"] or 0) if r else 0,
    }

    if format == "csv":
        return _csv_response([data], f"booking_summary_{d_from}_{d_to}.csv")
    return _ok(data)


# ──────────────────────────────────────────────
# 2. 预定占比分析
# ──────────────────────────────────────────────


@router.get("/proportion")
async def api_booking_proportion(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """预定占比分析 — 时段分布（早/午/下午/晚）/桌型分布"""
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    base_params = {
        "tenant_id": tenant_id,
        "store_id": store_id,
        "d_from": str(d_from),
        "d_to": str(d_to),
    }

    # 时段分布：早(<11:00) / 午(11:00-14:00) / 下午(14:00-17:00) / 晚(>=17:00)
    slot_rows = await db.execute(
        text(
            """
            SELECT
                CASE
                    WHEN EXTRACT(HOUR FROM booking_time) < 11  THEN '早餐'
                    WHEN EXTRACT(HOUR FROM booking_time) < 14  THEN '午餐'
                    WHEN EXTRACT(HOUR FROM booking_time) < 17  THEN '下午'
                    ELSE '晚餐'
                END                                                             AS time_slot,
                COUNT(*)                                                        AS booking_count,
                COUNT(*) FILTER (WHERE status = 'arrived')                     AS arrived_count,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE status = 'arrived')
                    / NULLIF(COUNT(*), 0),
                    1
                )::float                                                        AS arrival_rate_pct
            FROM bookings
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND booking_time BETWEEN :d_from AND :d_to + INTERVAL '1 day'
            GROUP BY
                CASE
                    WHEN EXTRACT(HOUR FROM booking_time) < 11  THEN '早餐'
                    WHEN EXTRACT(HOUR FROM booking_time) < 14  THEN '午餐'
                    WHEN EXTRACT(HOUR FROM booking_time) < 17  THEN '下午'
                    ELSE '晚餐'
                END
            ORDER BY MIN(EXTRACT(HOUR FROM booking_time))
            """
        ),
        base_params,
    )
    by_time_slot = [dict(r) for r in slot_rows.mappings()]

    # 桌位规格分布
    table_rows = await db.execute(
        text(
            """
            SELECT
                CASE
                    WHEN table_size <= 2  THEN '2人桌'
                    WHEN table_size <= 4  THEN '4人桌'
                    WHEN table_size <= 6  THEN '6人桌'
                    WHEN table_size <= 8  THEN '8人桌'
                    ELSE '10人以上'
                END                                                             AS table_category,
                COUNT(*)                                                        AS booking_count,
                ROUND(
                    100.0 * COUNT(*)
                    / NULLIF(SUM(COUNT(*)) OVER (), 0),
                    1
                )::float                                                        AS proportion_pct
            FROM bookings
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND booking_time BETWEEN :d_from AND :d_to + INTERVAL '1 day'
            GROUP BY
                CASE
                    WHEN table_size <= 2  THEN '2人桌'
                    WHEN table_size <= 4  THEN '4人桌'
                    WHEN table_size <= 6  THEN '6人桌'
                    WHEN table_size <= 8  THEN '8人桌'
                    ELSE '10人以上'
                END
            ORDER BY MIN(table_size)
            """
        ),
        base_params,
    )
    by_table_size = [dict(r) for r in table_rows.mappings()]

    total_bookings = sum(r.get("booking_count") or 0 for r in by_time_slot)
    arrived_total = sum(r.get("arrived_count") or 0 for r in by_time_slot)
    arrival_rate = round(100.0 * arrived_total / total_bookings, 1) if total_bookings else 0.0

    data = {
        "arrival_rate_pct": arrival_rate,
        "by_time_slot": by_time_slot,
        "by_table_size": by_table_size,
    }

    if format == "csv":
        rows = by_time_slot or [data]
        return _csv_response(rows, f"booking_proportion_{d_from}_{d_to}.csv")
    return _ok(data)


# ──────────────────────────────────────────────
# 3. 预定走势
# ──────────────────────────────────────────────


@router.get("/trend")
async def api_booking_trend(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    granularity: str = Query("day", description="汇总粒度 day|week|month"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """预定走势 — 按粒度展示预定量/到店/取消/定金趋势"""
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # 校验粒度参数，防注入
    if granularity not in ("day", "week", "month"):
        raise HTTPException(status_code=422, detail="granularity must be day, week or month")

    rows = await db.execute(
        text(
            f"""
            SELECT
                DATE_TRUNC('{granularity}', booking_time)::date          AS period,
                COUNT(*)                                                  AS booking_count,
                COUNT(*) FILTER (WHERE status = 'arrived')               AS arrived_count,
                COUNT(*) FILTER (WHERE status = 'cancelled')             AS cancelled_count,
                COUNT(*) FILTER (WHERE status = 'no_show')               AS no_show_count,
                COALESCE(SUM(deposit_amount_fen), 0)                     AS deposit_amount_fen
            FROM bookings
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND booking_time BETWEEN :d_from AND :d_to + INTERVAL '1 day'
            GROUP BY DATE_TRUNC('{granularity}', booking_time)
            ORDER BY period
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    items = [dict(r) for r in rows.mappings()]
    # 将 period 转为字符串以保证 JSON 可序列化
    for item in items:
        if item.get("period") is not None:
            item["period"] = str(item["period"])

    if format == "csv":
        return _csv_response(items, f"booking_trend_{d_from}_{d_to}.csv")
    return _ok(items)


# ──────────────────────────────────────────────
# 4. 预定品项统计
# ──────────────────────────────────────────────


@router.get("/items")
async def api_booking_items(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """预定品项统计 — 预订菜品数量/金额/占比"""
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            SELECT
                boi.dish_id,
                boi.dish_name,
                SUM(boi.quantity)                                               AS pre_order_count,
                SUM(boi.quantity * boi.unit_price_fen)                          AS total_amount_fen,
                ROUND(
                    100.0 * SUM(boi.quantity * boi.unit_price_fen)
                    / NULLIF(SUM(SUM(boi.quantity * boi.unit_price_fen)) OVER (), 0),
                    2
                )::float                                                        AS proportion_pct
            FROM booking_order_items boi
            JOIN bookings b ON boi.booking_id = b.id
            WHERE b.tenant_id  = :tenant_id
              AND b.store_id   = :store_id
              AND b.booking_time BETWEEN :d_from AND :d_to + INTERVAL '1 day'
            GROUP BY boi.dish_id, boi.dish_name
            ORDER BY total_amount_fen DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    items = [dict(r) for r in rows.mappings()]

    if format == "csv":
        return _csv_response(items, f"booking_items_{d_from}_{d_to}.csv")
    return _ok(items)
