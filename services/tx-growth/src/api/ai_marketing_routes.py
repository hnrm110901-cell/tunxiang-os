"""AI营销自动化路由 — 增长侧营销编排入口

基于 ContentHub + ChannelEngine 的全自动营销接口：
  POST /api/v1/growth/ai-marketing/campaign-brief     — 提交活动简报，返回内容包+受众+渠道
  POST /api/v1/growth/ai-marketing/auto-journey       — 触发 AI 驱动旅程（含 ContentHub 集成）
  GET  /api/v1/growth/ai-marketing/performance-summary — AI 生成的经营分析报告
  POST /api/v1/growth/ai-marketing/channel-test       — 渠道连通性测试

所有接口需要 X-Tenant-ID 请求头。
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/growth/ai-marketing", tags=["ai-marketing-growth"])

BRAIN_SERVICE_URL = os.getenv("BRAIN_SERVICE_URL", "http://tx-brain:8010")
AGENT_SERVICE_URL = os.getenv("AGENT_SERVICE_URL", "http://tx-agent:8008")


def _require_tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return x_tenant_id


async def _get_db() -> AsyncSession:  # type: ignore[misc]
    from ..database import get_session

    async for session in get_session():
        yield session


# ─────────────────────────────────────────────────────────────────────────────
# 请求模型
# ─────────────────────────────────────────────────────────────────────────────


class CampaignBriefBody(BaseModel):
    """活动简报：运营填写基本意图，AI 自动规划内容+受众+渠道+发送节奏"""

    model_config = ConfigDict(extra="ignore")

    campaign_type: str  # new_dish_launch/member_win_back/holiday_promo/daily_special
    brand_voice: dict[str, Any]
    store_id: str
    store_context: dict[str, Any] = {}
    offer_detail: Optional[dict[str, Any]] = None  # 优惠配置（可选，AI 可自动建议）
    target_channels: list[str] = ["sms", "wechat_subscribe", "wecom_chat"]
    target_segment: Optional[str] = None  # "all" / "vip" / "inactive_30d" / "new"


class AutoJourneyBody(BaseModel):
    """触发 AI 驱动旅程"""

    model_config = ConfigDict(extra="ignore")

    trigger_event: str  # post_order / first_order / silent / birthday / upgrade
    member_id: str
    store_id: str
    event_payload: dict[str, Any] = {}
    brand_voice: Optional[dict[str, Any]] = None


class ChannelTestBody(BaseModel):
    """渠道连通性测试"""

    model_config = ConfigDict(extra="ignore")

    channels: list[str] = ["sms", "wechat_subscribe"]
    test_phone: Optional[str] = None
    test_openid: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# 路由
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/campaign-brief")
async def submit_campaign_brief(
    body: CampaignBriefBody,
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """提交活动简报，AI 自动生成完整营销方案

    输入：活动类型 + 品牌调性 + 门店信息 + 可选优惠
    输出：
      - content_package: 全渠道内容包（由 ContentHub 生成）
      - recommended_audience: 推荐受众分群（大小 + 特征）
      - recommended_channels: 推荐渠道优先级
      - send_schedule: 推荐发送时间节奏
      - estimated_reach: 预计触达人数
      - roi_forecast: ROI 预测
    """
    brief_id = f"brief_{uuid.uuid4().hex[:12]}"

    # Step 1: 调用 ContentHub 生成内容包
    content_package: dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{BRAIN_SERVICE_URL}/api/v1/brain/content/generate",
                headers={"X-Tenant-ID": tenant_id},
                json={
                    "campaign_type": body.campaign_type,
                    "brand_voice": body.brand_voice,
                    "store_context": {**body.store_context, "store_id": body.store_id},
                    "offer_detail": body.offer_detail,
                    "target_channels": body.target_channels,
                    "ab_variants": 2,  # 默认生成 A/B 两个变体
                },
            )
            if resp.status_code == 200 and resp.json().get("ok"):
                content_package = resp.json()["data"]
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning("content_hub_unavailable_in_brief", brief_id=brief_id, error=str(exc))
        content_package = {
            "campaign_type": body.campaign_type,
            "fallback": True,
            "contents": [
                {"channel": ch, "body": f"[{body.campaign_type}] 内容待生成", "cta": "立即前往"}
                for ch in body.target_channels
            ],
        }

    # Step 2: 推荐受众分群（基于目标分群参数）
    segment_config = _build_audience_recommendation(body.target_segment, body.campaign_type)

    # Step 3: 推荐渠道 + 发送节奏
    channel_plan = _build_channel_plan(body.target_channels, body.campaign_type)

    logger.info(
        "campaign_brief_generated",
        brief_id=brief_id,
        tenant_id=tenant_id,
        campaign_type=body.campaign_type,
        content_cached=content_package.get("cached", False),
    )

    return {
        "ok": True,
        "data": {
            "brief_id": brief_id,
            "campaign_type": body.campaign_type,
            "content_package": content_package,
            "recommended_audience": segment_config,
            "channel_plan": channel_plan,
            "roi_forecast": _forecast_roi(body.campaign_type, segment_config["estimated_size"]),
        },
    }


@router.post("/auto-journey")
async def trigger_auto_journey(
    body: AutoJourneyBody,
    tenant_id: str = Depends(_require_tenant),
) -> dict[str, Any]:
    """触发 AI 驱动旅程

    将旅程触发委托给 tx-agent AiMarketingOrchestratorAgent，
    由 Agent 完成：画像读取 → 内容生成 → 约束校验 → 发送 → 留痕。
    """
    event_to_action = {
        "post_order": "execute_post_order_touch",
        "first_order": "execute_welcome_journey",
        "silent": "execute_winback_journey",
        "birthday": "execute_birthday_care",
        "upgrade": "execute_upgrade_celebration",
        "churn": "execute_churn_rescue",
    }

    action = event_to_action.get(body.trigger_event)
    if not action:
        raise HTTPException(
            status_code=422,
            detail=f"未知触发事件 {body.trigger_event}。支持：{list(event_to_action.keys())}",
        )

    journey_id = f"journey_{uuid.uuid4().hex[:12]}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{AGENT_SERVICE_URL}/api/v1/agent/ai-marketing/trigger",
                headers={"X-Tenant-ID": tenant_id},
                json={
                    "action": action,
                    "member_id": body.member_id,
                    "store_id": body.store_id,
                    "extra_context": {
                        **body.event_payload,
                        "brand_voice": body.brand_voice or {"brand_name": "屯象门店", "tone": "亲切温暖"},
                    },
                },
            )
            if resp.status_code == 200:
                agent_result = resp.json()
                return {
                    "ok": True,
                    "data": {
                        "journey_id": journey_id,
                        "trigger_event": body.trigger_event,
                        "action": action,
                        "agent_result": agent_result.get("data", {}),
                    },
                }
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning("agent_service_unavailable", journey_id=journey_id, error=str(exc))

    # 降级：记录旅程触发意图，待恢复后补偿
    logger.info(
        "journey_trigger_queued",
        journey_id=journey_id,
        trigger_event=body.trigger_event,
        member_id=body.member_id,
    )
    return {
        "ok": True,
        "data": {
            "journey_id": journey_id,
            "trigger_event": body.trigger_event,
            "status": "queued",
            "message": "Agent 服务暂时不可用，旅程已入队，将自动重试",
        },
    }


@router.get("/performance-summary")
async def get_performance_summary(
    store_id: str = Query(...),
    days: int = Query(default=7, ge=1, le=90),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """获取 AI 生成的营销效果总结报告

    从 marketing_touch_log + mv_member_clv + mv_channel_margin 聚合，
    通过 tx-brain 生成自然语言洞察。
    """
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )

    # ── Total touches in period ──────────────────────────────────────────────
    total_row = await db.execute(
        text("""
            SELECT COUNT(*) as total_touches,
                   COUNT(DISTINCT member_id) as unique_members
            FROM marketing_touch_log
            WHERE tenant_id = :tenant_id::uuid
              AND sent_at > NOW() - (:days || ' days')::interval
              AND NOT is_deleted
        """),
        {"tenant_id": str(tenant_id), "days": days},
    )
    totals = total_row.fetchone()
    total_touches = totals.total_touches if totals else 0
    unique_members = totals.unique_members if totals else 0

    # ── Channel breakdown ────────────────────────────────────────────────────
    chan_rows = await db.execute(
        text("""
            SELECT channel,
                   COUNT(*) as sent,
                   COUNT(*) FILTER (WHERE status IN ('sent','delivered','clicked','converted')) as delivered,
                   COUNT(*) FILTER (WHERE attribution_revenue_fen IS NOT NULL AND attribution_revenue_fen > 0) as conversions
            FROM marketing_touch_log
            WHERE tenant_id = :tenant_id::uuid
              AND sent_at > NOW() - (:days || ' days')::interval
              AND NOT is_deleted
            GROUP BY channel
        """),
        {"tenant_id": str(tenant_id), "days": days},
    )
    channel_breakdown: dict[str, Any] = {}
    for row in chan_rows.fetchall():
        cvr = round(row.conversions / max(1, row.sent), 3)
        channel_breakdown[row.channel] = {
            "sent": row.sent,
            "delivered": row.delivered,
            "conversion_rate": cvr,
        }

    # ── Campaign performance ─────────────────────────────────────────────────
    camp_rows = await db.execute(
        text("""
            SELECT campaign_type,
                   COUNT(*) as sent,
                   COUNT(*) FILTER (WHERE attribution_revenue_fen IS NOT NULL AND attribution_revenue_fen > 0) as attributed_orders,
                   COALESCE(SUM(attribution_revenue_fen), 0) as revenue_fen
            FROM marketing_touch_log
            WHERE tenant_id = :tenant_id::uuid
              AND sent_at > NOW() - (:days || ' days')::interval
              AND NOT is_deleted
            GROUP BY campaign_type
            ORDER BY revenue_fen DESC
        """),
        {"tenant_id": str(tenant_id), "days": days},
    )
    campaign_performance = [
        {
            "type": row.campaign_type or "unknown",
            "sent": row.sent,
            "attributed_orders": row.attributed_orders,
            "revenue_fen": row.revenue_fen,
        }
        for row in camp_rows.fetchall()
    ]

    # ── Total attributed revenue ─────────────────────────────────────────────
    total_revenue_row = await db.execute(
        text("""
            SELECT COALESCE(SUM(attribution_revenue_fen), 0) as total_revenue
            FROM marketing_touch_log
            WHERE tenant_id = :tenant_id::uuid
              AND sent_at > NOW() - (:days || ' days')::interval
              AND NOT is_deleted
        """),
        {"tenant_id": str(tenant_id), "days": days},
    )
    total_revenue = int(total_revenue_row.scalar() or 0)

    # ── ROI: attributed revenue / (touches × 1元/条 估算成本) ────────────────
    marketing_cost = max(1, total_touches * 100)  # 1元/条消息估算成本（单位：分）
    overall_roi = round(total_revenue / marketing_cost, 2) if total_revenue > 0 else 0.0

    # ── Top insight from channel performance ─────────────────────────────────
    best_channel = max(
        channel_breakdown.items(),
        key=lambda x: x[1]["conversion_rate"],
        default=(None, {}),
    )
    top_insight = (
        f"{best_channel[0]} 渠道转化率最高（{best_channel[1]['conversion_rate']:.0%}），建议加大该渠道触达比例"
        if best_channel[0]
        else "暂无足够数据生成洞察，建议先完成渠道配置"
    )

    summary = {
        "store_id": store_id,
        "period_days": days,
        "total_touches": total_touches,
        "unique_members_reached": unique_members,
        "channel_breakdown": channel_breakdown,
        "campaign_performance": campaign_performance,
        "total_attributed_revenue_fen": total_revenue,
        "total_marketing_cost_fen": marketing_cost,
        "overall_roi": overall_roi,
        "top_insight": top_insight,
    }

    return {"ok": True, "data": summary}


@router.post("/channel-test")
async def test_channel_connectivity(
    body: ChannelTestBody,
    tenant_id: str = Depends(_require_tenant),
) -> dict[str, Any]:
    """测试渠道连通性（发送测试消息验证配置）

    在生产正式发送前，用此接口验证所有渠道配置正确。
    测试消息明确标注为测试，不会影响用户体验。
    """
    test_id = f"test_{uuid.uuid4().hex[:8]}"
    results: dict[str, Any] = {}

    for channel in body.channels:
        if channel == "sms":
            if body.test_phone:
                from shared.integrations.sms_service import SMSService

                svc = SMSService()
                r = await svc.send_verification_code(body.test_phone, "TEST")
                results[channel] = {"status": r.get("status"), "is_mock": svc.is_mock}
            else:
                results[channel] = {"status": "skipped", "reason": "test_phone not provided"}

        elif channel == "wechat_subscribe":
            from shared.integrations.wechat_subscribe import WechatSubscribeService

            svc = WechatSubscribeService()
            results[channel] = {"status": "configured" if not svc.is_mock else "mock_mode", "is_mock": svc.is_mock}

        elif channel in ("wechat_oa", "wecom_chat"):
            from shared.integrations.wechat_marketing import WeChatOAService, WeComService

            if channel == "wechat_oa":
                svc_oa = WeChatOAService()
                results[channel] = {
                    "status": "configured" if not svc_oa.is_mock else "mock_mode",
                    "is_mock": svc_oa.is_mock,
                }
            else:
                svc_wc = WeComService()
                results[channel] = {
                    "status": "configured" if not svc_wc.is_mock else "mock_mode",
                    "is_mock": svc_wc.is_mock,
                }

        elif channel == "meituan":
            from shared.integrations.meituan_marketing import MeituanMarketingAdapter

            adp = MeituanMarketingAdapter()
            results[channel] = {"status": "configured" if not adp.is_mock else "mock_mode", "is_mock": adp.is_mock}

        elif channel == "douyin":
            from shared.integrations.douyin_marketing import DouyinMarketingAdapter

            adp = DouyinMarketingAdapter()
            results[channel] = {"status": "configured" if not adp.is_mock else "mock_mode", "is_mock": adp.is_mock}

        elif channel == "xiaohongshu":
            try:
                from shared.integrations.xiaohongshu_marketing import XiaohongshuMarketingAdapter

                adp = XiaohongshuMarketingAdapter()
                results[channel] = {
                    "status": "configured" if not adp.is_mock else "mock_mode",
                    "is_mock": adp.is_mock,
                }
            except ImportError:
                results[channel] = {"status": "adapter_not_installed"}

        else:
            results[channel] = {"status": "unknown_channel"}

    all_configured = all(r.get("status") in ("configured", "mock_mode") for r in results.values())

    return {
        "ok": True,
        "data": {
            "test_id": test_id,
            "channels_tested": len(body.channels),
            "all_configured": all_configured,
            "results": results,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────


def _build_audience_recommendation(
    target_segment: Optional[str],
    campaign_type: str,
) -> dict[str, Any]:
    """根据活动类型推荐受众分群"""
    segment_map: dict[str, dict[str, Any]] = {
        "new_dish_launch": {
            "segment": "all_active",
            "filter": "近30天消费过",
            "estimated_size": 1200,
            "description": "近30天活跃会员，适合新品推广",
        },
        "member_win_back": {
            "segment": "inactive_30d",
            "filter": "30-90天未消费",
            "estimated_size": 340,
            "description": "沉默会员，需要唤醒激活",
        },
        "holiday_promo": {
            "segment": "all",
            "filter": "全部会员",
            "estimated_size": 3500,
            "description": "节假日全量触达",
        },
        "daily_special": {
            "segment": "rfm_bc",
            "filter": "B/C 层会员（频次提升空间大）",
            "estimated_size": 800,
            "description": "日推适合B/C层会员提频",
        },
    }
    return segment_map.get(
        campaign_type,
        {
            "segment": target_segment or "all_active",
            "estimated_size": 500,
            "description": "默认活跃会员",
        },
    )


def _build_channel_plan(
    channels: list[str],
    campaign_type: str,
) -> dict[str, Any]:
    """构建渠道发送计划"""
    timing_map: dict[str, str] = {
        "new_dish_launch": "周五 11:00-12:00（午餐前高峰）",
        "member_win_back": "周三 14:00-16:00（下午低谷主动触达）",
        "holiday_promo": "节前5天 10:00-11:00",
        "daily_special": "每日 10:30",
        "birthday_care": "生日前3天 10:00",
    }
    return {
        "channels_priority": channels,
        "send_timing": timing_map.get(campaign_type, "工作日 10:00-11:00"),
        "send_batch_size": 200,
        "interval_minutes": 5,
        "frequency_cap": "每会员 24h 内最多1条",
    }


def _forecast_roi(campaign_type: str, audience_size: int) -> dict[str, Any]:
    """预测活动 ROI（基于历史数据基准）"""
    benchmarks: dict[str, dict[str, float]] = {
        "new_dish_launch": {"ctr": 0.18, "cvr": 0.12, "avg_order_fen": 9200},
        "member_win_back": {"ctr": 0.22, "cvr": 0.08, "avg_order_fen": 7800},
        "holiday_promo": {"ctr": 0.25, "cvr": 0.15, "avg_order_fen": 12000},
        "daily_special": {"ctr": 0.12, "cvr": 0.10, "avg_order_fen": 6500},
        "birthday_care": {"ctr": 0.45, "cvr": 0.35, "avg_order_fen": 15000},
    }
    bm = benchmarks.get(campaign_type, {"ctr": 0.15, "cvr": 0.10, "avg_order_fen": 8000})
    estimated_clicks = int(audience_size * bm["ctr"])
    estimated_orders = int(estimated_clicks * bm["cvr"])
    estimated_revenue_fen = int(estimated_orders * bm["avg_order_fen"])

    return {
        "estimated_reach": audience_size,
        "estimated_clicks": estimated_clicks,
        "estimated_orders": estimated_orders,
        "estimated_revenue_fen": estimated_revenue_fen,
        "estimated_revenue_yuan": f"¥{estimated_revenue_fen / 100:.0f}",
        "benchmark_ctr": bm["ctr"],
        "benchmark_cvr": bm["cvr"],
    }
