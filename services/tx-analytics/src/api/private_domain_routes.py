"""私域运营数据看板 API 路由

GET /api/v1/private-domain/dashboard          — 汇总驾驶舱（并发聚合）
GET /api/v1/private-domain/member-health      — 会员健康度评分
GET /api/v1/private-domain/wecom-reach        — 企微触达效率
GET /api/v1/private-domain/journey-funnel     — 旅程转化漏斗
GET /api/v1/private-domain/roi-trend          — ROI 趋势（近N天）
GET /api/v1/private-domain/cross-brand        — 跨品牌对比
"""

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from ..services.private_domain_dashboard import (
    get_cross_brand_comparison,
    get_journey_funnel,
    get_member_health,
    get_private_domain_dashboard,
    get_roi_trend,
    get_wecom_reach_efficiency,
)

router = APIRouter(prefix="/api/v1/private-domain", tags=["private-domain"])


def _require_tenant(tenant_id: Optional[str]) -> str:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return tenant_id


@router.get("/dashboard")
async def api_private_domain_dashboard(
    group_id: Optional[str] = Query(None, description="集团/品牌组ID，跨品牌对比时必填"),
    roi_days: int = Query(30, ge=7, le=90, description="ROI趋势天数"),
    reach_days: int = Query(7, ge=1, le=30, description="企微触达统计天数"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """
    私域运营总览驾驶舱

    并发聚合5大模块：会员健康度 / 企微触达效率 / 旅程转化漏斗 / ROI趋势 / 跨品牌对比。
    各模块独立降级，上游不可用时返回 error 字段而非整体失败。
    """
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_private_domain_dashboard(
        tenant_id=tenant_id,
        group_id=group_id,
        roi_days=roi_days,
        reach_days=reach_days,
    )
    return {"ok": True, "data": data}


@router.get("/member-health")
async def api_member_health(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """
    会员健康度评分（0-100）

    基于 RFM 分层分布计算综合健康分，附带留存率、高价值率、流失风险率。
    """
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_member_health(tenant_id)
    return {"ok": True, "data": data}


@router.get("/wecom-reach")
async def api_wecom_reach(
    days: int = Query(7, ge=1, le=30, description="统计天数"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """
    企微触达效率

    返回企微好友总数、近N天新增、消息发送量、归因订单数、转化率、ROI。
    """
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_wecom_reach_efficiency(tenant_id, days=days)
    return {"ok": True, "data": data}


@router.get("/journey-funnel")
async def api_journey_funnel(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """
    旅程转化漏斗汇总

    汇总所有活跃旅程的进入数、完成数、转化数，计算整体完成率与转化率。
    """
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_journey_funnel(tenant_id)
    return {"ok": True, "data": data}


@router.get("/roi-trend")
async def api_roi_trend(
    days: int = Query(30, ge=7, le=90, description="趋势天数"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """
    私域 ROI 趋势（每日）

    返回近N天每日归因收入、营销成本、ROI。上游不可用时返回带 degraded=true 的空趋势。
    """
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_roi_trend(tenant_id, days=days)
    return {"ok": True, "data": data}


@router.get("/cross-brand")
async def api_cross_brand(
    group_id: str = Query(..., description="集团/品牌组ID"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """
    跨品牌私域指标对比

    返回集团下各品牌的会员总数、留存率、高价值率、RFM分布，按会员规模降序排列。
    """
    tenant_id = _require_tenant(x_tenant_id)
    data = await get_cross_brand_comparison(group_id, tenant_id)
    return {"ok": True, "data": data}
