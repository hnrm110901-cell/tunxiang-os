"""门店经营分析 API 路由

前缀: /api/v1/analysis/store

端点:
  GET  /{store_id}/revenue       — 营收分析
  GET  /{store_id}/turnover      — 翻台深度分析
  GET  /{store_id}/ticket        — 桌均客单分析
  GET  /{store_id}/peak-hours    — 高峰时段分析
  GET  /{store_id}/shifts        — 班次分析
  POST /comparison               — 多店对比
"""
import uuid
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.store_analysis import (
    peak_hour_analysis,
    revenue_analysis,
    shift_analysis,
    store_comparison,
    ticket_analysis,
    turnover_deep_analysis,
)

router = APIRouter(prefix="/api/v1/analysis/store", tags=["store-analysis"])


# ─── 请求模型 ───


class ComparisonRequest(BaseModel):
    """多店对比请求体"""
    store_ids: list[str] = Field(..., min_length=2, max_length=10, description="门店ID列表")
    metrics: list[str] = Field(
        default=["revenue", "orders", "avg_ticket"],
        description="对比指标: revenue/orders/avg_ticket/turnover/per_capita",
    )
    start_date: str = Field(..., description="开始日期 YYYY-MM-DD")
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD")


# ─── 辅助函数 ───


def _require_tenant(tenant_id: Optional[str]) -> uuid.UUID:
    """校验并解析 tenant_id"""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    try:
        return uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID must be a valid UUID")


def _parse_date_range(
    start_date: Optional[str],
    end_date: Optional[str],
) -> tuple[date, date]:
    """解析日期范围，默认近7天"""
    today = date.today()
    if start_date:
        try:
            sd = date.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid start_date: {start_date}")
    else:
        sd = today - timedelta(days=6)

    if end_date:
        try:
            ed = date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid end_date: {end_date}")
    else:
        ed = today

    if sd > ed:
        raise HTTPException(status_code=422, detail="start_date must be <= end_date")
    if (ed - sd).days > 365:
        raise HTTPException(status_code=422, detail="Date range must not exceed 365 days")

    return sd, ed


def _parse_store_id(store_id: str) -> uuid.UUID:
    """解析门店 UUID"""
    try:
        return uuid.UUID(store_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid store_id: {store_id}")


# ─── 端点 ───


@router.get("/{store_id}/revenue")
async def api_revenue_analysis(
    store_id: str,
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """营收分析（日营收趋势/渠道/餐段/趋势方向）"""
    tenant_id = _require_tenant(x_tenant_id)
    sid = _parse_store_id(store_id)
    dr = _parse_date_range(start_date, end_date)
    data = await revenue_analysis(sid, dr, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/{store_id}/turnover")
async def api_turnover_deep(
    store_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """翻台深度分析（区域/工作日周末/高峰时段翻台）"""
    tenant_id = _require_tenant(x_tenant_id)
    sid = _parse_store_id(store_id)
    dr = _parse_date_range(start_date, end_date)
    data = await turnover_deep_analysis(sid, dr, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/{store_id}/ticket")
async def api_ticket_analysis(
    store_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """桌均客单分析（客单均值/人均/分布/按桌台规格）"""
    tenant_id = _require_tenant(x_tenant_id)
    sid = _parse_store_id(store_id)
    dr = _parse_date_range(start_date, end_date)
    data = await ticket_analysis(sid, dr, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/{store_id}/peak-hours")
async def api_peak_hours(
    store_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """高峰时段分析（时段营收/单量/午餐晚餐峰值/空闲时段）"""
    tenant_id = _require_tenant(x_tenant_id)
    sid = _parse_store_id(store_id)
    dr = _parse_date_range(start_date, end_date)
    data = await peak_hour_analysis(sid, dr, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/{store_id}/shifts")
async def api_shift_analysis(
    store_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """班次分析（各班次营收/单量/客单/人效）"""
    tenant_id = _require_tenant(x_tenant_id)
    sid = _parse_store_id(store_id)
    dr = _parse_date_range(start_date, end_date)
    data = await shift_analysis(sid, dr, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.post("/comparison")
async def api_store_comparison(
    body: ComparisonRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """多店多维对比矩阵"""
    tenant_id = _require_tenant(x_tenant_id)
    dr = _parse_date_range(body.start_date, body.end_date)
    store_uuids = []
    for sid in body.store_ids:
        try:
            store_uuids.append(uuid.UUID(sid))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid store_id: {sid}")
    try:
        data = await store_comparison(store_uuids, body.metrics, dr, tenant_id, db=None)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "data": data}
