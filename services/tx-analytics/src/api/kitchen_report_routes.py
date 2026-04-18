"""厨房管理报表 API 路由

GET /api/v1/reports/kitchen/overtime           制作超时报表
GET /api/v1/reports/kitchen/chef-performance   厨师业绩报表
GET /api/v1/reports/kitchen/station-efficiency 档口效率报表
GET /api/v1/reports/kitchen/dish-duration      菜品制作时长分析
GET /api/v1/reports/kitchen/steaming-stats     蒸制统计
GET /api/v1/reports/kitchen/peak-analysis      厨房高峰时段
GET /api/v1/reports/kitchen/waste-stats        厨房损耗（废单/退菜）
GET /api/v1/reports/kitchen/daily-summary      厨房综合日报

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
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/reports/kitchen", tags=["kitchen-reports"])


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
# 1. 制作超时报表
# ──────────────────────────────────────────────

@router.get("/overtime")
async def api_kitchen_overtime(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    threshold_minutes: int = Query(15, description="超时阈值（分钟），默认15"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页条数"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """制作超时报表 — 超过阈值的出餐明细"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    items: list[dict] = []
    data = {
        "total_overtime_count": 0,
        "overtime_rate": 0.0,
        "threshold_minutes": threshold_minutes,
        "page": page,
        "page_size": page_size,
        "items": items,
    }

    if format == "csv":
        return _csv_response(items, f"kitchen_overtime_{d_from}_{d_to}.csv")
    return _ok(data)


# ──────────────────────────────────────────────
# 2. 厨师业绩报表
# ──────────────────────────────────────────────

@router.get("/chef-performance")
async def api_chef_performance(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    chef_id: Optional[str] = Query(None, description="厨师ID，不传则返回全部"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """厨师业绩报表 — 人均出品量/超时率/综合评分"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回格式: [{chef_id, chef_name, total_dishes, avg_duration, overtime_count, overtime_rate, score}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"chef_performance_{d_from}_{d_to}.csv")
    return _ok(items)


# ──────────────────────────────────────────────
# 3. 档口效率报表
# ──────────────────────────────────────────────

@router.get("/station-efficiency")
async def api_station_efficiency(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """档口效率报表 — 各档口出品量/平均等待/高峰时段/利用率"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回格式: [{station_id, station_name, total_output, avg_wait_minutes, peak_hour, utilization_rate}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"station_efficiency_{d_from}_{d_to}.csv")
    return _ok(items)


# ──────────────────────────────────────────────
# 4. 菜品制作时长分析
# ──────────────────────────────────────────────

@router.get("/dish-duration")
async def api_dish_duration(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    dish_id: Optional[str] = Query(None, description="菜品ID，不传则返回全部"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """菜品制作时长分析 — 平均/最短/最长/超时率"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回格式: [{dish_id, dish_name, avg_duration, min_duration, max_duration, overtime_rate, sample_count}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"dish_duration_{d_from}_{d_to}.csv")
    return _ok(items)


# ──────────────────────────────────────────────
# 5. 蒸制统计
# ──────────────────────────────────────────────

@router.get("/steaming-stats")
async def api_steaming_stats(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """蒸制统计 — 蒸制品类次数/时长/收入"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回格式: [{dish_name, steaming_count, avg_duration, total_revenue}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"steaming_stats_{d_from}_{d_to}.csv")
    return _ok(items)


# ──────────────────────────────────────────────
# 6. 厨房高峰时段
# ──────────────────────────────────────────────

@router.get("/peak-analysis")
async def api_kitchen_peak_analysis(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """厨房高峰时段分析 — 每小时订单量/平均等待/压力等级"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回格式: [{hour, order_count, avg_wait, pressure_level: low/medium/high/critical}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"kitchen_peak_{d_from}_{d_to}.csv")
    return _ok(items)


# ──────────────────────────────────────────────
# 7. 厨房损耗（废单/退菜）
# ──────────────────────────────────────────────

@router.get("/waste-stats")
async def api_kitchen_waste_stats(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """厨房损耗报表 — 废单/退菜统计，按原因/菜品分类"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    by_reason: list[dict] = []
    by_dish: list[dict] = []
    data = {
        "total_waste_count": 0,
        "total_waste_amount": 0.0,
        "by_reason": by_reason,
        "by_dish": by_dish,
    }

    if format == "csv":
        return _csv_response(by_dish, f"kitchen_waste_{d_from}_{d_to}.csv")
    return _ok(data)


# ──────────────────────────────────────────────
# 8. 厨房综合日报
# ──────────────────────────────────────────────

@router.get("/daily-summary")
async def api_kitchen_daily_summary(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date: Optional[str] = Query(None, description="业务日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """厨房综合日报 — 全天核心指标汇总"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    target_date = _parse_date(date)

    # TODO: 接入真实数据库查询
    data = {
        "date": str(target_date),
        "total_dishes": 0,
        "overtime_rate": 0.0,
        "avg_wait": 0.0,
        "top_chef": None,
        "busiest_hour": None,
        "waste_count": 0,
    }

    if format == "csv":
        return _csv_response([data], f"kitchen_daily_summary_{target_date}.csv")
    return _ok(data)
