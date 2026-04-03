"""经营驾驶舱 API 路由

GET /dashboard/today/{store_id}   — 今日总览
GET /dashboard/stores             — 多店概览
GET /dashboard/ranking            — 门店排行
GET /dashboard/alerts/{store_id}  — 异常摘要
GET /dashboard/alerts/stats       — 异常统计
"""
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from ..services.alert_summary import get_alert_stats, get_today_alerts
from ..services.store_ranking import get_store_comparison, get_store_ranking
from ..services.today_overview import get_multi_store_overview, get_today_overview

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def _require_tenant(tenant_id: Optional[str]) -> str:
    """校验 tenant_id 必填"""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return tenant_id


# ─── 今日总览（单店） ───

@router.get("/today/{store_id}")
async def api_today_overview(
    store_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """今日营业总览（营收/单量/客单/翻台率/环比/峰值时段/上座率）"""
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_today_overview(store_id, tenant_id, db=None)
    return {"ok": True, "data": data}


# ─── 多店概览（总部视角） ───

@router.get("/stores")
async def api_multi_store_overview(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """多店概览（营收/单量/健康分）"""
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_multi_store_overview(tenant_id, db=None)
    return {"ok": True, "data": data}


# ─── 门店排行 ───

@router.get("/ranking")
async def api_store_ranking(
    metric: str = Query("revenue", description="排行指标: revenue/margin/turnover/satisfaction"),
    date_range: str = Query("today", description="日期范围: today/week/month/quarter"),
    ascending: bool = Query(False, description="正序(True)/倒序(False)"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """门店排行榜"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        data = await get_store_ranking(metric, date_range, tenant_id, db=None, ascending=ascending)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "data": data}


# ─── 门店对比 ───

@router.get("/comparison")
async def api_store_comparison(
    store_ids: str = Query(..., description="门店ID列表，逗号分隔"),
    metrics: str = Query("revenue", description="指标列表，逗号分隔"),
    date_range: str = Query("today"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """多店多指标对比"""
    tenant_id = _require_tenant(x_tenant_id)
    sid_list = [s.strip() for s in store_ids.split(",") if s.strip()]
    metric_list = [m.strip() for m in metrics.split(",") if m.strip()]
    try:
        data = await get_store_comparison(sid_list, metric_list, date_range, tenant_id, db=None)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "data": data}


# ─── 异常摘要（单店） ───
# 注意：stats 路由必须在 {store_id} 之前注册，避免路径冲突

@router.get("/alerts/stats")
async def api_alert_stats(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """全租户异常统计"""
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_alert_stats(tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/alerts/{store_id}")
async def api_today_alerts(
    store_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """今日异常摘要（单店）"""
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_today_alerts(store_id, tenant_id, db=None)
    return {"ok": True, "data": data}
