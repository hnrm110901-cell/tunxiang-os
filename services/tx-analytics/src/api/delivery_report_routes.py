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
):
    """外卖单量统计 — 含各平台分拆、退款金额、净收入"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    by_platform: list[dict] = []
    data = {
        "total_orders": 0,
        "total_gmv": 0.0,
        "refund_orders": 0,
        "refund_amount": 0.0,
        "net_revenue": 0.0,
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
):
    """外卖品项明细 — 各菜品销量/金额/差评率"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回格式: [{dish_id, dish_name, quantity, amount, proportion, bad_review_count, bad_review_rate}]
    items: list[dict] = []

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
):
    """骑手配送统计 — 平均配送时长/准时率/超时次数/时段分布"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    by_time_slot: list[dict] = []
    data = {
        "avg_delivery_minutes": 0.0,
        "on_time_rate": 0.0,
        "late_count": 0,
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
):
    """外卖订单明细 — 含平台/金额/状态/配送时长/下单时间"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回格式: {total, items: [{order_id, platform, amount, status, delivery_minutes, created_at}]}
    items: list[dict] = []
    data = {
        "total": 0,
        "page": page,
        "page_size": page_size,
        "items": items,
    }

    if format == "csv":
        return _csv_response(items, f"delivery_orders_{d_from}_{d_to}.csv")
    return _ok(data)
