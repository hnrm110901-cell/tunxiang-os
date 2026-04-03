"""Boss BI 集团驾驶舱 API 路由

Boss（集团总裁/CFO）专用移动端驾驶舱接口，提供跨品牌、跨门店的
汇总视角数据，支持实时预警推送和 AI 每日简报。

接口列表：
  GET /boss-bi/kpi/today                  — 今日集团核心 KPI
  GET /boss-bi/brands/ranking?days=7      — 多品牌对标排名（含环比）
  GET /boss-bi/alerts                     — 异常门店预警列表
  GET /boss-bi/daily-brief                — AI 每日简报（有预警/大波动时触发）
  GET /boss-bi/store/{id}/trend?days=30   — 单店 N 天营业趋势

鉴权：X-Tenant-ID header 必填
响应格式：{ "ok": bool, "data": {}, "error": {} }
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query

from ..services.group_dashboard_service import GroupDashboardService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/boss-bi", tags=["boss-bi"])

_svc = GroupDashboardService()


# ─── 公共辅助 ───────────────────────────────────────────


def _require_tenant(tenant_id: Optional[str]) -> str:
    """校验 X-Tenant-ID header 必填"""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return tenant_id


def _get_model_router():
    """获取 ModelRouter 实例（不可用时返回 None，降级处理）"""
    try:
        from tx_agent.model_router import ModelRouter  # type: ignore[import]
        return ModelRouter()
    except ImportError:
        log.warning("boss_bi_routes.model_router_not_available")
        return None


# ─── 今日集团核心 KPI ────────────────────────────────────


@router.get("/kpi/today")
async def api_boss_bi_kpi_today(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """今日集团核心 KPI 快照

    返回集团维度汇总：
    - 总营业额（分）
    - 平均客单价（分）
    - 平均翻台率（次/天）
    - 平均毛利率（%）
    - 活跃门店数
    - 今日预警数
    - 营业额周同比（%）
    """
    tenant_id = _require_tenant(x_tenant_id)
    snapshot = await _svc.get_today_group_kpi(tenant_id, db=None)
    return {"ok": True, "data": snapshot.model_dump()}


# ─── 多品牌对标排名 ──────────────────────────────────────


@router.get("/brands/ranking")
async def api_boss_bi_brands_ranking(
    days: int = Query(
        default=7,
        ge=1,
        le=90,
        description="统计天数（1~90），默认 7 天",
    ),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """多品牌经营表现排名

    按营业额倒序返回各品牌核心指标，含周同比环比增长率。

    Query params:
      - days: 统计天数，默认 7 天，最大 90 天
    """
    tenant_id = _require_tenant(x_tenant_id)
    ranking = await _svc.get_brand_ranking(tenant_id, days=days, db=None)
    return {"ok": True, "data": [b.model_dump() for b in ranking]}


# ─── 异常门店预警 ────────────────────────────────────────


@router.get("/alerts")
async def api_boss_bi_alerts(
    threshold_pct: float = Query(
        default=0.20,
        ge=0.01,
        le=1.0,
        description="预警阈值（0.20 = 低于均值 20%），默认 0.20",
    ),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """今日异常门店预警列表

    检测营业额低于集团均值超过阈值的门店，返回预警信息。
    预警严重级别：
    - critical：偏差 ≤ -40%
    - warning：偏差 ≤ -20%
    - info：其他

    Query params:
      - threshold_pct: 触发阈值（默认 0.20，即 20%）
    """
    tenant_id = _require_tenant(x_tenant_id)
    alerts = await _svc.get_store_alerts(tenant_id, threshold_pct=threshold_pct, db=None)
    return {
        "ok": True,
        "data": {
            "alerts": [a.model_dump() for a in alerts],
            "total": len(alerts),
            "threshold_pct": threshold_pct,
        },
    }


# ─── AI 每日简报 ─────────────────────────────────────────


@router.get("/daily-brief")
async def api_boss_bi_daily_brief(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """集团 AI 每日简报

    触发条件（满足任一则调用 AI）：
    - 存在异常门店预警
    - 营业额周同比变化超过 ±15%

    未达到触发条件时返回空 brief，节省 AI 调用成本。
    """
    tenant_id = _require_tenant(x_tenant_id)

    # 先获取 KPI + 预警，再决定是否触发 AI
    kpi = await _svc.get_today_group_kpi(tenant_id, db=None)
    alerts = await _svc.get_store_alerts(tenant_id, threshold_pct=0.20, db=None)
    model_router = _get_model_router()
    brief = await _svc.get_ai_daily_brief(tenant_id, kpi, alerts, model_router)

    return {
        "ok": True,
        "data": {
            "brief": brief,
            "triggered": bool(brief),
            "alert_count": len(alerts),
        },
    }


# ─── 单店营业趋势 ────────────────────────────────────────


@router.get("/store/{store_id}/trend")
async def api_boss_bi_store_trend(
    store_id: str,
    days: int = Query(
        default=30,
        ge=1,
        le=90,
        description="统计天数（1~90），默认 30 天",
    ),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """单店近 N 天营业额趋势

    返回按日期升序的营业数据，供折线图渲染。

    Path params:
      - store_id: 门店 ID

    Query params:
      - days: 统计天数，默认 30 天，最大 90 天
    """
    tenant_id = _require_tenant(x_tenant_id)
    trend = await _svc.get_store_trend(tenant_id, store_id, days=days, db=None)
    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "days": days,
            "trend": trend,
        },
    }
