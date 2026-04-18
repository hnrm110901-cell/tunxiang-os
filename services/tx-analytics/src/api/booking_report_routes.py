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
"""
from __future__ import annotations

import csv
import io
from datetime import date
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

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
):
    """预定汇总 — 预定量/到店率/取消率/人均消费/定金总额"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    data = {
        "total_bookings": 0,
        "arrived_count": 0,
        "cancelled_count": 0,
        "arrival_rate": 0.0,
        "avg_spend_per_head": 0.0,
        "total_deposit": 0.0,
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
):
    """预定占比分析 — 预定 vs 散客比例/时段分布/桌型分布"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    by_time_slot: list[dict] = []
    by_table_size: list[dict] = []
    data = {
        "booking_vs_walkin_ratio": 0.0,
        "arrival_rate": 0.0,
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
):
    """预定走势 — 按粒度展示预定量/到店/取消/定金趋势"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回格式: [{date, booking_count, arrived_count, cancelled_count, deposit_amount}]
    items: list[dict] = []

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
):
    """预定品项统计 — 预订菜品数量/金额/占比"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回格式: [{dish_id, dish_name, pre_order_count, amount, proportion}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"booking_items_{d_from}_{d_to}.csv")
    return _ok(items)
