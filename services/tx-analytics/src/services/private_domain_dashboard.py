"""私域运营数据看板聚合服务

汇总 tx-member + tx-growth 数据，供总部驾驶舱使用。
- 会员健康度评分
- 企微触达效率
- 旅程转化漏斗
- ROI 趋势（近30天）
- 跨品牌对比
"""
import asyncio
import os
from datetime import datetime, date, timedelta
from typing import Any, Optional

import httpx
import structlog

log = structlog.get_logger()

_MEMBER_URL = os.getenv("TX_MEMBER_SERVICE_URL", "http://tx-member:8003")
_GROWTH_URL = os.getenv("TX_GROWTH_SERVICE_URL", "http://tx-growth:8004")
_TIMEOUT = 8.0


# ─── 内部 HTTP helpers ────────────────────────────────────────────────────────

async def _get(client: httpx.AsyncClient, url: str, params: dict | None = None) -> dict:
    """GET with graceful degradation on failure."""
    try:
        resp = await client.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        log.warning("private_domain_dashboard.fetch_failed", url=url, error=str(exc))
        return {}


# ─── 会员健康度评分 ────────────────────────────────────────────────────────────

def _compute_member_health_score(rfm_dist: dict) -> dict:
    """
    基于 RFM 分布计算会员健康度综合评分（0-100）。

    权重：
      S1(流失高危) → −20分
      S2(沉睡)     → −10分
      S3(活跃)     → +10分
      S4(重要)     → +20分
      S5(VIP)      → +30分
    基准 50 分，按分布比例加权。
    """
    distribution = rfm_dist.get("distribution", {})
    total = sum(distribution.values()) or 1

    weights = {"S1": -20, "S2": -10, "S3": 10, "S4": 20, "S5": 30}
    score = 50.0
    for level, cnt in distribution.items():
        score += weights.get(level, 0) * (cnt / total)

    score = max(0.0, min(100.0, score))

    # 留存率（S3+S4+S5 占比）
    retained = sum(distribution.get(l, 0) for l in ("S3", "S4", "S5"))
    retention_rate = round(retained / total * 100, 1)

    # 高价值客户比例（S4+S5）
    vip_cnt = distribution.get("S4", 0) + distribution.get("S5", 0)
    vip_rate = round(vip_cnt / total * 100, 1)

    # 流失风险客户比例（S1+S2）
    risk_cnt = distribution.get("S1", 0) + distribution.get("S2", 0)
    risk_rate = round(risk_cnt / total * 100, 1)

    return {
        "score": round(score, 1),
        "retention_rate": retention_rate,
        "vip_rate": vip_rate,
        "churn_risk_rate": risk_rate,
        "distribution": distribution,
        "total_members": total,
    }


async def get_member_health(tenant_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        data = await _get(
            client,
            f"{_MEMBER_URL}/api/v1/rfm/distribution",
            params={"tenant_id": tenant_id},
        )
    if not data:
        return {"score": None, "error": "tx-member unavailable"}
    return _compute_member_health_score(data.get("data", {}))


# ─── 企微触达效率 ─────────────────────────────────────────────────────────────

async def get_wecom_reach_efficiency(tenant_id: str, days: int = 7) -> dict:
    """
    调用 tx-growth attribution dashboard，提取企微渠道指标。
    补充：企微好友总数、近N天新增好友数（从 tx-member 获取）。
    """
    async with httpx.AsyncClient() as client:
        attribution_task = _get(
            client,
            f"{_GROWTH_URL}/api/v1/attribution/dashboard",
            params={"tenant_id": tenant_id, "days": days},
        )
        wecom_binding_task = _get(
            client,
            f"{_MEMBER_URL}/api/v1/members/wecom/stats",
            params={"tenant_id": tenant_id, "days": days},
        )
        attribution_data, wecom_data = await asyncio.gather(
            attribution_task, wecom_binding_task
        )

    attr = attribution_data.get("data", {})
    wecom = wecom_data.get("data", {})

    # 企微渠道的 ROI、触达数、转化率
    channels = attr.get("channels", [])
    wecom_channel = next((c for c in channels if "wecom" in c.get("channel", "").lower()), {})

    return {
        "period_days": days,
        "total_wecom_contacts": wecom.get("total_bound", 0),
        "new_contacts_in_period": wecom.get("new_bound_in_period", 0),
        "messages_sent": wecom_channel.get("touches", 0),
        "orders_attributed": wecom_channel.get("orders", 0),
        "revenue_attributed_fen": wecom_channel.get("revenue_fen", 0),
        "conversion_rate": wecom_channel.get("conversion_rate", 0.0),
        "roi": wecom_channel.get("roi", 0.0),
        "avg_response_hours": wecom.get("avg_response_hours", None),
    }


# ─── 旅程转化漏斗 ─────────────────────────────────────────────────────────────

async def get_journey_funnel(tenant_id: str) -> dict:
    """
    聚合所有活跃旅程的转化漏斗数据。
    tx-growth 提供按旅程维度的节点通过率。
    """
    async with httpx.AsyncClient() as client:
        data = await _get(
            client,
            f"{_GROWTH_URL}/api/v1/journeys/funnel-summary",
            params={"tenant_id": tenant_id},
        )

    if not data:
        return {"journeys": [], "error": "tx-growth unavailable"}

    journeys = data.get("data", {}).get("journeys", [])

    # 计算汇总漏斗
    total_entered = sum(j.get("entered", 0) for j in journeys)
    total_completed = sum(j.get("completed", 0) for j in journeys)
    total_converted = sum(j.get("converted", 0) for j in journeys)

    overall_completion = (
        round(total_completed / total_entered * 100, 1) if total_entered else 0.0
    )
    overall_conversion = (
        round(total_converted / total_entered * 100, 1) if total_entered else 0.0
    )

    return {
        "total_active_journeys": len(journeys),
        "total_entered": total_entered,
        "total_completed": total_completed,
        "total_converted": total_converted,
        "overall_completion_rate": overall_completion,
        "overall_conversion_rate": overall_conversion,
        "journeys": journeys,
    }


# ─── ROI 趋势（近30天每日） ──────────────────────────────────────────────────

async def get_roi_trend(tenant_id: str, days: int = 30) -> dict:
    """
    从 tx-growth attribution 获取每日 ROI 趋势。
    返回近 N 天的 revenue_attributed / marketing_cost 趋势线。
    """
    async with httpx.AsyncClient() as client:
        data = await _get(
            client,
            f"{_GROWTH_URL}/api/v1/attribution/roi-trend",
            params={"tenant_id": tenant_id, "days": days},
        )

    if not data:
        # 降级：返回空趋势
        today = date.today()
        return {
            "period_days": days,
            "trend": [
                {
                    "date": (today - timedelta(days=i)).isoformat(),
                    "roi": None,
                    "revenue_fen": None,
                    "cost_fen": None,
                }
                for i in range(days - 1, -1, -1)
            ],
            "degraded": True,
        }

    trend = data.get("data", {}).get("trend", [])
    return {
        "period_days": days,
        "trend": trend,
        "degraded": False,
    }


# ─── 跨品牌对比 ──────────────────────────────────────────────────────────────

async def get_cross_brand_comparison(group_id: str, tenant_id: str) -> dict:
    """
    跨品牌私域指标对比（总部视角）。
    tx-member /api/v1/groups/{group_id}/analytics 提供各品牌汇总。
    """
    async with httpx.AsyncClient() as client:
        data = await _get(
            client,
            f"{_MEMBER_URL}/api/v1/groups/{group_id}/analytics",
            params={"tenant_id": tenant_id},
        )

    if not data:
        return {"brands": [], "error": "tx-member unavailable"}

    brands = data.get("data", {}).get("brands", [])

    # 计算品牌健康度排名
    for brand in brands:
        dist = brand.get("rfm_distribution", {})
        total = sum(dist.values()) or 1
        retained = sum(dist.get(l, 0) for l in ("S3", "S4", "S5"))
        brand["retention_rate"] = round(retained / total * 100, 1)
        vip = dist.get("S4", 0) + dist.get("S5", 0)
        brand["vip_rate"] = round(vip / total * 100, 1)

    # 按总会员数降序排列
    brands.sort(key=lambda b: b.get("total_members", 0), reverse=True)

    return {
        "group_id": group_id,
        "brand_count": len(brands),
        "brands": brands,
    }


# ─── 汇总仪表盘（并发聚合） ───────────────────────────────────────────────────

async def get_private_domain_dashboard(
    tenant_id: str,
    group_id: Optional[str] = None,
    roi_days: int = 30,
    reach_days: int = 7,
) -> dict:
    """
    并发聚合所有私域运营模块，返回驾驶舱完整数据。
    各模块独立降级，不因单个上游故障影响整体响应。
    """
    tasks: list[Any] = [
        get_member_health(tenant_id),
        get_wecom_reach_efficiency(tenant_id, days=reach_days),
        get_journey_funnel(tenant_id),
        get_roi_trend(tenant_id, days=roi_days),
    ]
    if group_id:
        tasks.append(get_cross_brand_comparison(group_id, tenant_id))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    def _safe(val: Any, fallback: dict) -> dict:
        if isinstance(val, Exception):
            log.error("private_domain_dashboard.module_error", error=str(val))
            return {**fallback, "error": str(val)}
        return val

    member_health = _safe(results[0], {"score": None})
    wecom_reach = _safe(results[1], {"messages_sent": None})
    journey_funnel = _safe(results[2], {"total_active_journeys": 0})
    roi_trend = _safe(results[3], {"trend": []})
    cross_brand = _safe(results[4], {"brands": []}) if group_id else None

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "tenant_id": tenant_id,
        "member_health": member_health,
        "wecom_reach_efficiency": wecom_reach,
        "journey_funnel": journey_funnel,
        "roi_trend": roi_trend,
        **({"cross_brand_comparison": cross_brand} if group_id else {}),
    }
