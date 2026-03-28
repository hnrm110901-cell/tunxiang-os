"""菜品经营分析 API 路由

GET  /api/v1/analysis/dish/sales-ranking          — 菜品销量排行
GET  /api/v1/analysis/dish/return-rate             — 退菜率排行+原因分布
GET  /api/v1/analysis/dish/negative-reviews        — 差评菜清单
GET  /api/v1/analysis/dish/stockout-frequency      — 沽清频率排行
GET  /api/v1/analysis/dish/structure               — 菜品四象限分析
GET  /api/v1/analysis/dish/new-performance         — 新菜表现
GET  /api/v1/analysis/dish/optimization            — AI菜单优化建议
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Header, Query, HTTPException

from ..services.dish_analysis import (
    sales_ranking,
    return_rate_analysis,
    negative_review_dishes,
    stockout_frequency,
    dish_structure_analysis,
    new_dish_performance,
    menu_optimization_suggestions,
)

router = APIRouter(prefix="/api/v1/analysis/dish", tags=["dish-analysis"])


def _require_tenant(tenant_id: Optional[str]) -> uuid.UUID:
    """校验 tenant_id 必填并转 UUID"""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    try:
        return uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid X-Tenant-ID format")


def _parse_store_id(store_id: str) -> uuid.UUID:
    """解析 store_id 为 UUID"""
    try:
        return uuid.UUID(store_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid store_id format")


def _parse_date_range(start_date: Optional[str], end_date: Optional[str]) -> tuple[date, date]:
    """解析日期范围，默认最近30天"""
    try:
        ed = date.fromisoformat(end_date) if end_date else date.today()
        sd = date.fromisoformat(start_date) if start_date else ed - timedelta(days=30)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format, use YYYY-MM-DD")
    if sd > ed:
        raise HTTPException(status_code=422, detail="start_date must be <= end_date")
    return (sd, ed)


# ─── 1. 菜品销量排行 ───

@router.get("/sales-ranking")
async def api_sales_ranking(
    store_id: str = Query(..., description="门店ID"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    sort_by: str = Query("sales_qty", description="排序字段: sales_qty/sales_amount_fen"),
    limit: int = Query(50, ge=1, le=200),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """菜品销量排行（含金额/数量/占比）"""
    tid = _require_tenant(x_tenant_id)
    sid = _parse_store_id(store_id)
    dr = _parse_date_range(start_date, end_date)

    data = sales_ranking(sid, dr, tid, db=None, sort_by=sort_by, limit=limit)
    return {"ok": True, "data": {"items": data, "total": len(data)}}


# ─── 2. 退菜率排行+原因分布 ───

@router.get("/return-rate")
async def api_return_rate(
    store_id: str = Query(..., description="门店ID"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    limit: int = Query(50, ge=1, le=200),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """退菜率排行 + 退菜原因分布"""
    tid = _require_tenant(x_tenant_id)
    sid = _parse_store_id(store_id)
    dr = _parse_date_range(start_date, end_date)

    data = return_rate_analysis(sid, dr, tid, db=None, limit=limit)
    return {"ok": True, "data": data}


# ─── 3. 差评菜清单 ───

@router.get("/negative-reviews")
async def api_negative_reviews(
    store_id: str = Query(..., description="门店ID"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    min_rating: float = Query(3.0, ge=1.0, le=5.0, description="低于此评分视为差评"),
    limit: int = Query(30, ge=1, le=200),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """差评菜清单"""
    tid = _require_tenant(x_tenant_id)
    sid = _parse_store_id(store_id)
    dr = _parse_date_range(start_date, end_date)

    data = negative_review_dishes(sid, dr, tid, db=None, min_rating=min_rating, limit=limit)
    return {"ok": True, "data": {"items": data, "total": len(data)}}


# ─── 4. 沽清频率排行 ───

@router.get("/stockout-frequency")
async def api_stockout_frequency(
    store_id: str = Query(..., description="门店ID"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    limit: int = Query(30, ge=1, le=200),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """沽清频率排行"""
    tid = _require_tenant(x_tenant_id)
    sid = _parse_store_id(store_id)
    dr = _parse_date_range(start_date, end_date)

    data = stockout_frequency(sid, dr, tid, db=None, limit=limit)
    return {"ok": True, "data": {"items": data, "total": len(data)}}


# ─── 5. 菜品四象限分析 ───

@router.get("/structure")
async def api_dish_structure(
    store_id: str = Query(..., description="门店ID"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    margin_threshold: Optional[float] = Query(None, description="毛利率阈值(%)，默认50"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """菜品四象限分析（明星/金牛/问号/瘦狗）"""
    tid = _require_tenant(x_tenant_id)
    sid = _parse_store_id(store_id)
    dr = _parse_date_range(start_date, end_date)

    mt = Decimal(str(margin_threshold)) if margin_threshold is not None else None
    data = dish_structure_analysis(sid, dr, tid, db=None, margin_threshold=mt)
    return {"ok": True, "data": data}


# ─── 6. 新菜表现 ───

@router.get("/new-performance")
async def api_new_dish_performance(
    store_id: str = Query(..., description="门店ID"),
    days_since_launch: int = Query(30, ge=1, le=365, description="上架天数阈值"),
    limit: int = Query(30, ge=1, le=200),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """新菜表现（销量曲线/复购率）"""
    tid = _require_tenant(x_tenant_id)
    sid = _parse_store_id(store_id)

    data = new_dish_performance(sid, days_since_launch, tid, db=None, limit=limit)
    return {"ok": True, "data": {"items": data, "total": len(data)}}


# ─── 7. AI菜单优化建议 ───

@router.get("/optimization")
async def api_menu_optimization(
    store_id: str = Query(..., description="门店ID"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """AI菜单优化建议（汰换/提价/推广/保持）"""
    tid = _require_tenant(x_tenant_id)
    sid = _parse_store_id(store_id)
    dr = _parse_date_range(start_date, end_date)

    data = menu_optimization_suggestions(sid, tid, db=None, date_range=dr)
    return {"ok": True, "data": data}
