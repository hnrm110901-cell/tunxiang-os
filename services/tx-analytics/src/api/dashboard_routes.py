"""经营驾驶舱 API 路由

GET /dashboard/today/{store_id}         — 今日总览
GET /dashboard/stores                   — 多店概览
GET /dashboard/ranking                  — 门店排行
GET /dashboard/comparison               — 多店对比
GET /dashboard/trend/{store_id}         — 营收趋势图（逐日折线）
GET /dashboard/top-dishes/{store_id}    — Top 菜品排行
GET /dashboard/alerts/stats             — 异常统计
GET /dashboard/alerts/{store_id}        — 今日异常摘要
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.alert_summary import get_alert_stats, get_today_alerts
from ..services.store_ranking import get_store_comparison, get_store_ranking
from ..services.today_overview import get_multi_store_overview, get_today_overview
from ..services.sql_queries import query_revenue_trend, query_top_dishes

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
    db: AsyncSession = Depends(get_db),
):
    """今日营业总览（营收/单量/客单/翻台率/环比/峰值时段/上座率）"""
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_today_overview(store_id, tenant_id, db=db)
    return {"ok": True, "data": data}


# ─── 多店概览（总部视角） ───

@router.get("/stores")
async def api_multi_store_overview(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """多店概览（营收/单量/健康分）"""
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_multi_store_overview(tenant_id, db=db)
    return {"ok": True, "data": data}


# ─── 门店排行 ───

@router.get("/ranking")
async def api_store_ranking(
    metric: str = Query("revenue", description="排行指标: revenue/margin/turnover/satisfaction"),
    date_range: str = Query("today", description="日期范围: today/week/month/quarter"),
    ascending: bool = Query(False, description="正序(True)/倒序(False)"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """门店排行榜"""
    tenant_id = _require_tenant(x_tenant_id)
    try:
        data = await get_store_ranking(metric, date_range, tenant_id, db=db, ascending=ascending)
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
    db: AsyncSession = Depends(get_db),
):
    """多店多指标对比"""
    tenant_id = _require_tenant(x_tenant_id)
    sid_list = [s.strip() for s in store_ids.split(",") if s.strip()]
    metric_list = [m.strip() for m in metrics.split(",") if m.strip()]
    try:
        data = await get_store_comparison(sid_list, metric_list, date_range, tenant_id, db=db)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "data": data}


# ─── 营收趋势图 ───

@router.get("/trend/{store_id}")
async def api_revenue_trend(
    store_id: str,
    days: int = Query(30, ge=1, le=365, description="统计天数（默认30天）"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """逐日营收趋势折线图数据

    返回最近 N 天每日营收（分）和订单数，按日期升序，
    无数据的日期不补零（前端自行填充）。
    """
    tenant_id = _require_tenant(x_tenant_id)
    try:
        data = await query_revenue_trend(
            store_id=store_id,
            tenant_id=tenant_id,
            days=days,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "data": data, "meta": {"store_id": store_id, "days": days}}


# ─── Top 菜品排行 ───

@router.get("/top-dishes/{store_id}")
async def api_top_dishes(
    store_id: str,
    days: int = Query(30, ge=1, le=365, description="统计天数（默认30天）"),
    limit: int = Query(10, ge=1, le=50, description="返回条数（默认10）"),
    order_by: str = Query("revenue", description="排序依据: qty（销量）| revenue（营收）"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """Top 菜品排行

    按销量或营收倒序返回最受欢迎菜品，含名次、品类、均价。
    """
    tenant_id = _require_tenant(x_tenant_id)
    if order_by not in {"qty", "revenue"}:
        raise HTTPException(status_code=422, detail="order_by 只支持 qty 或 revenue")
    try:
        data = await query_top_dishes(
            store_id=store_id,
            tenant_id=tenant_id,
            days=days,
            limit=limit,
            order_by=order_by,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {
        "ok": True,
        "data": data,
        "meta": {"store_id": store_id, "days": days, "order_by": order_by},
    }


# ─── 异常摘要（注意：stats 必须在 {store_id} 路由前注册） ───

@router.get("/alerts/stats")
async def api_alert_stats(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """全租户异常统计"""
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_alert_stats(tenant_id, db=db)
    return {"ok": True, "data": data}


@router.get("/alerts/{store_id}")
async def api_today_alerts(
    store_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """今日异常摘要（单店）"""
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_today_alerts(store_id, tenant_id, db=db)
    return {"ok": True, "data": data}
