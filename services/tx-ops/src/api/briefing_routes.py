"""经营简报中心 API 路由（Mock 数据版）

端点:
  GET   /api/v1/analytics/briefings              简报列表
  GET   /api/v1/analytics/briefings/{id}         简报详情
  POST  /api/v1/analytics/briefings/subscribe    订阅设置

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/analytics/briefings", tags=["analytics-briefings"])
log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class SubscribeRequest(BaseModel):
    user_id: str = Field(..., description="用户ID")
    briefing_types: List[str] = Field(..., description="订阅的简报类型: daily/weekly/monthly/custom")
    channels: List[str] = Field(default_factory=lambda: ["app"], description="推送渠道: app/email/wecom/sms")
    store_ids: Optional[List[str]] = Field(None, description="关注的门店列表（空=全部）")
    push_time: Optional[str] = Field("08:00", description="推送时间 HH:MM")
    enabled: bool = Field(True, description="是否启用")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Mock 数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MOCK_BRIEFINGS: List[Dict[str, Any]] = [
    {
        "id": "brief-001",
        "type": "daily",
        "title": "2026-04-09 日经营简报",
        "subtitle": "全品牌12店整体数据",
        "generated_at": "2026-04-10T07:00:00+08:00",
        "period": {"start": "2026-04-09", "end": "2026-04-09"},
        "status": "published",
        "summary": "昨日全品牌营收158.6万元，同比增长8.2%。客流4,872人次，客单价32.5元。3店营收超额完成日目标。",
        "highlights": [
            {"icon": "trending_up", "text": "五一广场店营收同比增长15%，连续3天超额"},
            {"icon": "warning", "text": "万达店午高峰出餐超时率12%，需关注"},
            {"icon": "star", "text": "新品酸汤牛肉点击率达18%，表现优异"},
        ],
        "kpis": {
            "total_revenue_fen": 15860000,
            "revenue_yoy_pct": 8.2,
            "total_orders": 4872,
            "avg_ticket_fen": 32550,
            "table_turnover": 2.9,
            "food_cost_pct": 33.2,
            "labor_cost_pct": 22.1,
            "gross_margin_pct": 44.7,
            "customer_satisfaction": 4.6,
            "complaint_count": 3,
        },
        "store_rankings": [
            {"rank": 1, "store_name": "五一广场店", "revenue_fen": 3210000, "achievement_pct": 112},
            {"rank": 2, "store_name": "芙蓉广场店", "revenue_fen": 2860000, "achievement_pct": 105},
            {"rank": 3, "store_name": "万达店", "revenue_fen": 2480000, "achievement_pct": 98},
            {"rank": 4, "store_name": "河西店", "revenue_fen": 1950000, "achievement_pct": 95},
            {"rank": 5, "store_name": "岳麓店", "revenue_fen": 1680000, "achievement_pct": 88},
        ],
        "ai_insights": [
            "五一广场店午高峰(11:30-13:00)翻台率达3.8次，建议增加1名服务员配置。",
            "酸菜鱼品类近7日销量下滑6%，而酸汤牛肉增长22%，建议调整推荐位。",
            "万达店食材成本率35.1%偏高，主要因海鲜品类损耗率较高(8.2%)，建议优化采购批量。",
        ],
    },
    {
        "id": "brief-002",
        "type": "weekly",
        "title": "2026年第15周经营周报",
        "subtitle": "04/03 - 04/09 全品牌汇总",
        "generated_at": "2026-04-10T08:00:00+08:00",
        "period": {"start": "2026-04-03", "end": "2026-04-09"},
        "status": "published",
        "summary": "本周全品牌营收1,108万元，环比增长3.5%。周末两天贡献40%营收。会员消费占比达62%。",
        "highlights": [
            {"icon": "trophy", "text": "本周营收突破1100万，创近4周新高"},
            {"icon": "people", "text": "新增会员1,230人，转化率23%"},
            {"icon": "trending_down", "text": "外卖渠道利润率下降2pp，需优化渠道策略"},
        ],
        "kpis": {
            "total_revenue_fen": 110800000,
            "revenue_wow_pct": 3.5,
            "total_orders": 34100,
            "avg_ticket_fen": 32490,
            "table_turnover": 2.85,
            "food_cost_pct": 33.0,
            "labor_cost_pct": 22.5,
            "gross_margin_pct": 44.5,
            "new_members": 1230,
            "member_consume_pct": 62,
        },
        "store_rankings": [
            {"rank": 1, "store_name": "五一广场店", "revenue_fen": 22800000, "achievement_pct": 108},
            {"rank": 2, "store_name": "芙蓉广场店", "revenue_fen": 19600000, "achievement_pct": 103},
            {"rank": 3, "store_name": "万达店", "revenue_fen": 17200000, "achievement_pct": 96},
        ],
        "ai_insights": [
            "周末客流量占全周48%，建议加强周末备货量和人力排班。",
            "外卖渠道佣金成本本周增长5%，美团平台占比68%，建议推广自有小程序点单减少平台依赖。",
            "储值会员消费频次较非会员高2.3倍，建议加大会员储值营销力度。",
        ],
    },
    {
        "id": "brief-003",
        "type": "monthly",
        "title": "2026年3月经营月报",
        "subtitle": "全品牌12店月度经营分析",
        "generated_at": "2026-04-02T09:00:00+08:00",
        "period": {"start": "2026-03-01", "end": "2026-03-31"},
        "status": "published",
        "summary": "3月全品牌营收4,520万元，同比增长12.3%。净利润率11.2%。新开1店（梅溪湖店试营业）。",
        "highlights": [
            {"icon": "celebration", "text": "单月营收首次突破4500万大关"},
            {"icon": "store", "text": "梅溪湖店3月28日开业，首周日均营收18万"},
            {"icon": "savings", "text": "通过AI采购优化，食材成本降低1.2pp"},
        ],
        "kpis": {
            "total_revenue_fen": 452000000,
            "revenue_yoy_pct": 12.3,
            "total_orders": 139200,
            "avg_ticket_fen": 32470,
            "net_profit_pct": 11.2,
            "food_cost_pct": 32.8,
            "labor_cost_pct": 22.0,
            "rent_cost_pct": 12.5,
        },
        "store_rankings": [],
        "ai_insights": [
            "3月整体表现优于预算目标4.5%，主要受益于清明节前消费旺季和新店开业。",
            "建议4月重点关注梅溪湖新店运营效率提升，目前人效仅为成熟店的75%。",
        ],
    },
    {
        "id": "brief-004",
        "type": "custom",
        "title": "新品酸汤牛肉30天表现分析",
        "subtitle": "2026-03-10 至 04-09 专项分析",
        "generated_at": "2026-04-10T09:00:00+08:00",
        "period": {"start": "2026-03-10", "end": "2026-04-09"},
        "status": "draft",
        "summary": "酸汤牛肉上线30天累计售出8,520份，日均284份，点击率18%。毛利率48.2%，高于品类平均5pp。",
        "highlights": [
            {"icon": "local_fire_department", "text": "上线30天即进入TOP5热销菜品"},
            {"icon": "thumb_up", "text": "顾客好评率94%，复购率38%"},
        ],
        "kpis": {
            "total_sold": 8520,
            "daily_avg": 284,
            "click_rate_pct": 18,
            "gross_margin_pct": 48.2,
            "customer_rating": 4.7,
            "repurchase_rate_pct": 38,
        },
        "store_rankings": [],
        "ai_insights": [
            "建议将酸汤牛肉升级为常驻菜品，替换销量下滑的水煮牛肉。",
            "五一广场店和芙蓉广场店表现最佳，建议这两店作为新品孵化试点。",
        ],
    },
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("")
async def list_briefings(
    briefing_type: Optional[str] = Query(None, description="简报类型: daily/weekly/monthly/custom"),
    status: Optional[str] = Query(None, description="状态: draft/published"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """经营简报列表。"""
    log.info("briefings_listed", tenant_id=x_tenant_id, briefing_type=briefing_type)

    filtered = _MOCK_BRIEFINGS[:]
    if briefing_type:
        filtered = [b for b in filtered if b["type"] == briefing_type]
    if status:
        filtered = [b for b in filtered if b["status"] == status]

    total = len(filtered)
    offset = (page - 1) * size
    # 列表接口返回摘要信息（不含完整 ai_insights 和 store_rankings 详情）
    items = []
    for b in filtered[offset: offset + size]:
        items.append({
            "id": b["id"],
            "type": b["type"],
            "title": b["title"],
            "subtitle": b["subtitle"],
            "generated_at": b["generated_at"],
            "period": b["period"],
            "status": b["status"],
            "summary": b["summary"],
            "highlights": b["highlights"],
        })

    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/{briefing_id}")
async def get_briefing_detail(
    briefing_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """简报详情（含完整KPI、排名、AI洞察）。"""
    log.info("briefing_detail_requested", briefing_id=briefing_id, tenant_id=x_tenant_id)

    for b in _MOCK_BRIEFINGS:
        if b["id"] == briefing_id:
            return {"ok": True, "data": b}
    raise HTTPException(status_code=404, detail="简报不存在")


@router.post("/subscribe")
async def subscribe_briefings(
    body: SubscribeRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """订阅/更新简报推送设置。"""
    log.info("briefing_subscription_updated", user_id=body.user_id,
             types=body.briefing_types, channels=body.channels, tenant_id=x_tenant_id)

    return {
        "ok": True,
        "data": {
            "user_id": body.user_id,
            "briefing_types": body.briefing_types,
            "channels": body.channels,
            "store_ids": body.store_ids,
            "push_time": body.push_time,
            "enabled": body.enabled,
            "updated_at": "2026-04-10T15:30:00+08:00",
        },
    }
