"""全链路归因分析 API — AM-1.4 ROI 归因

提供经营分析侧的全链路营销归因能力：
  GET  /api/v1/analytics/attribution/overview        — 营销归因总览看板
  GET  /api/v1/analytics/attribution/campaigns       — 跨活动 ROI 对比
  GET  /api/v1/analytics/attribution/campaigns/{id}  — 单活动归因详情
  GET  /api/v1/analytics/attribution/channels        — 渠道归因分布
  GET  /api/v1/analytics/attribution/trends          — 归因趋势（日/周/月）
  GET  /api/v1/analytics/attribution/funnel          — 曝光→核销转化漏斗

数据来源：
  - marketing_touch_log（触达记录）
  - attribution_conversions（归因转化）
  - orders / order_items（订单核销）
  - member（会员画像）

与 tx-growth/attribution 的边界：
  tx-growth 负责运营操作（记录触达/订单归因/活动 ROI），
  tx-analytics 负责经营分析（聚合看板/趋势/跨活动对比/渠道贡献）。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analytics/attribution", tags=["analytics-attribution"])


# ─── 工具函数 ───────────────────────────────────────────────────────────────


def _parse_uuid(raw: str, field: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} 格式无效: {raw}")


def _require_tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    return x_tenant_id


def ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


# ─── 路由 ────────────────────────────────────────────────────────────────────


@router.get("/overview")
async def attribution_overview(
    tenant_id: str = Depends(_require_tenant),
    start_date: Optional[str] = Query(None, alias="start", description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, alias="end", description="结束日期 YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """营销归因总览看板（曝光/触达/核销/ROI 聚合）。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    # 默认最近30天
    end = date.today()
    start = end - timedelta(days=30)
    if start_date:
        try:
            start = date.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="start 日期格式无效")
    if end_date:
        try:
            end = date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="end 日期格式无效")

    try:
        # 触达汇总
        touch_row = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total_touches,
                    COUNT(DISTINCT customer_id) AS unique_members,
                    COUNT(*) FILTER (WHERE status = 'opened') AS opened_count,
                    COUNT(*) FILTER (WHERE status = 'clicked') AS clicked_count
                FROM marketing_touch_log
                WHERE tenant_id = current_setting('app.tenant_id')::uuid
                  AND touched_at::date >= :start
                  AND touched_at::date <= :end
                  AND NOT is_deleted
            """),
            {"start": start, "end": end},
        )
        touch_stats = touch_row.mappings().one()

        # 归因转化汇总
        conv_row = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total_conversions,
                    COALESCE(SUM(order_amount_fen), 0) AS attributed_revenue_fen,
                    COUNT(*) FILTER (WHERE order_amount_fen > 0) AS paid_orders
                FROM attribution_conversions
                WHERE tenant_id = current_setting('app.tenant_id')::uuid
                  AND converted_at::date >= :start
                  AND converted_at::date <= :end
                  AND NOT is_deleted
            """),
            {"start": start, "end": end},
        )
        conv_stats = conv_row.mappings().one()

        total_touches = touch_stats["total_touches"] or 0
        total_conv = conv_stats["total_conversions"] or 0
        revenue_fen = conv_stats["attributed_revenue_fen"] or 0

        # ROI 估算（假设单次触达成本约 30 分）
        estimated_cost_fen = total_touches * 30
        roi = round((revenue_fen - estimated_cost_fen) / max(estimated_cost_fen, 1), 4)

        return ok({
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "touches": {
                "total": total_touches,
                "unique_members": touch_stats["unique_members"] or 0,
                "open_rate": round(
                    (touch_stats["opened_count"] or 0) / max(total_touches, 1), 4
                ),
                "click_rate": round(
                    (touch_stats["clicked_count"] or 0) / max(total_touches, 1), 4
                ),
            },
            "conversions": {
                "total": total_conv,
                "paid_orders": conv_stats["paid_orders"] or 0,
                "attributed_revenue_yuan": round(revenue_fen / 100, 2),
                "conversion_rate": round(
                    total_conv / max(total_touches, 1), 4
                ),
            },
            "roi": {
                "estimated_cost_yuan": round(estimated_cost_fen / 100, 2),
                "attributed_revenue_yuan": round(revenue_fen / 100, 2),
                "roi_ratio": roi,
            },
        })
    except Exception as exc:
        logger.error("attribution_overview_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="获取归因总览失败")


@router.get("/campaigns")
async def list_campaign_attribution(
    tenant_id: str = Depends(_require_tenant),
    start_date: Optional[str] = Query(None, alias="start"),
    end_date: Optional[str] = Query(None, alias="end"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """跨活动 ROI 对比列表。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    end = date.today()
    start = end - timedelta(days=90)
    if start_date:
        try:
            start = date.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="start 日期格式无效")
    if end_date:
        try:
            end = date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="end 日期格式无效")

    try:
        rows = await db.execute(
            text("""
                SELECT
                    ac.campaign_id,
                    ac.campaign_name,
                    COUNT(DISTINCT mtl.id) AS touches,
                    COUNT(DISTINCT mtl.customer_id) AS reached_members,
                    COUNT(DISTINCT ac.order_id) AS conversions,
                    COALESCE(SUM(ac.order_amount_fen), 0) AS revenue_fen,
                    MIN(ac.converted_at) AS first_conv,
                    MAX(ac.converted_at) AS last_conv
                FROM attribution_conversions ac
                LEFT JOIN marketing_touch_log mtl
                    ON mtl.source_id = ac.campaign_id::text
                    AND mtl.tenant_id = current_setting('app.tenant_id')::uuid
                    AND NOT mtl.is_deleted
                WHERE ac.tenant_id = current_setting('app.tenant_id')::uuid
                  AND ac.converted_at::date >= :start
                  AND ac.converted_at::date <= :end
                  AND NOT ac.is_deleted
                GROUP BY ac.campaign_id, ac.campaign_name
                ORDER BY revenue_fen DESC
                LIMIT 50
            """),
            {"start": start, "end": end},
        )
        campaigns = []
        for r in rows.mappings():
            revenue_fen = r["revenue_fen"] or 0
            touches = r["touches"] or 0
            cost_fen = touches * 30
            campaigns.append({
                "campaign_id": str(r["campaign_id"]) if r["campaign_id"] else "",
                "campaign_name": r["campaign_name"] or "未命名活动",
                "touches": touches,
                "reached_members": r["reached_members"] or 0,
                "conversions": r["conversions"] or 0,
                "revenue_yuan": round(revenue_fen / 100, 2),
                "cost_yuan": round(cost_fen / 100, 2),
                "roi_ratio": round((revenue_fen - cost_fen) / max(cost_fen, 1), 4),
                "conversion_rate": round(
                    (r["conversions"] or 0) / max(touches, 1), 4
                ),
                "first_conversion": r["first_conv"].isoformat() if r["first_conv"] else None,
                "last_conversion": r["last_conv"].isoformat() if r["last_conv"] else None,
            })

        return ok({
            "campaigns": campaigns,
            "total": len(campaigns),
            "period": {"start": start.isoformat(), "end": end.isoformat()},
        })
    except Exception as exc:
        logger.error("list_campaign_attribution_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="获取活动归因失败")


@router.get("/campaigns/{campaign_id}")
async def get_campaign_attribution_detail(
    campaign_id: str,
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """单活动归因详情（含渠道分解）。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    try:
        # 活动汇总
        summary_row = await db.execute(
            text("""
                SELECT
                    COUNT(DISTINCT mtl.id) AS total_touches,
                    COUNT(DISTINCT mtl.customer_id) AS unique_members,
                    COUNT(DISTINCT ac.order_id) AS conversions,
                    COALESCE(SUM(ac.order_amount_fen), 0) AS revenue_fen,
                    COUNT(*) FILTER (WHERE mtl.status = 'opened') AS opened
                FROM attribution_conversions ac
                LEFT JOIN marketing_touch_log mtl
                    ON mtl.source_id = ac.campaign_id::text
                    AND mtl.tenant_id = current_setting('app.tenant_id')::uuid
                    AND NOT mtl.is_deleted
                WHERE ac.campaign_id::text = :cid
                  AND ac.tenant_id = current_setting('app.tenant_id')::uuid
                  AND NOT ac.is_deleted
                GROUP BY ac.campaign_id
            """),
            {"cid": campaign_id},
        )
        summary = summary_row.mappings().one_or_none()

        if not summary or (summary["total_touches"] or 0) == 0:
            raise HTTPException(status_code=404, detail="活动未找到或无归因数据")

        # 渠道分解
        channel_rows = await db.execute(
            text("""
                SELECT
                    mtl.channel,
                    COUNT(*) AS touches,
                    COUNT(DISTINCT mtl.customer_id) AS members
                FROM marketing_touch_log mtl
                WHERE mtl.source_id = :cid
                  AND mtl.tenant_id = current_setting('app.tenant_id')::uuid
                  AND NOT mtl.is_deleted
                GROUP BY mtl.channel
                ORDER BY touches DESC
            """),
            {"cid": campaign_id},
        )
        channels = [
            {
                "channel": r["channel"],
                "touches": r["touches"],
                "members": r["members"],
            }
            for r in channel_rows.mappings()
        ]

        touches = summary["total_touches"] or 0
        revenue_fen = summary["revenue_fen"] or 0
        cost_fen = touches * 30

        return ok({
            "campaign_id": campaign_id,
            "summary": {
                "touches": touches,
                "unique_members": summary["unique_members"] or 0,
                "open_rate": round((summary["opened"] or 0) / max(touches, 1), 4),
                "conversions": summary["conversions"] or 0,
                "conversion_rate": round((summary["conversions"] or 0) / max(touches, 1), 4),
                "revenue_yuan": round(revenue_fen / 100, 2),
                "cost_yuan": round(cost_fen / 100, 2),
                "roi_ratio": round((revenue_fen - cost_fen) / max(cost_fen, 1), 4),
            },
            "channel_breakdown": channels,
        })
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("campaign_attribution_detail_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="获取活动归因详情失败")


@router.get("/channels")
async def channel_attribution(
    tenant_id: str = Depends(_require_tenant),
    start_date: Optional[str] = Query(None, alias="start"),
    end_date: Optional[str] = Query(None, alias="end"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """各触达渠道的归因贡献分布。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    end = date.today()
    start = end - timedelta(days=30)
    if start_date:
        start = date.fromisoformat(start_date)
    if end_date:
        end = date.fromisoformat(end_date)

    try:
        rows = await db.execute(
            text("""
                SELECT
                    mtl.channel,
                    COUNT(*) AS touches,
                    COUNT(DISTINCT mtl.customer_id) AS reached_members,
                    COUNT(DISTINCT ac.order_id) AS conversions,
                    COALESCE(SUM(ac.order_amount_fen), 0) AS revenue_fen
                FROM marketing_touch_log mtl
                LEFT JOIN attribution_conversions ac
                    ON ac.tenant_id = mtl.tenant_id
                    AND ac.customer_id = mtl.customer_id
                    AND ac.converted_at::date >= mtl.touched_at::date
                    AND ac.converted_at::date <= mtl.touched_at::date + 7
                    AND NOT ac.is_deleted
                WHERE mtl.tenant_id = current_setting('app.tenant_id')::uuid
                  AND mtl.touched_at::date >= :start
                  AND mtl.touched_at::date <= :end
                  AND NOT mtl.is_deleted
                GROUP BY mtl.channel
                ORDER BY revenue_fen DESC
            """),
            {"start": start, "end": end},
        )
        channels = []
        total_revenue = 0
        for r in rows.mappings():
            rev = r["revenue_fen"] or 0
            total_revenue += rev
            channels.append({
                "channel": r["channel"],
                "touches": r["touches"],
                "reached_members": r["reached_members"] or 0,
                "conversions": r["conversions"] or 0,
                "revenue_yuan": round(rev / 100, 2),
            })

        # 计算占比
        for ch in channels:
            ch["revenue_share"] = round(ch["revenue_yuan"] / max(total_revenue / 100, 0.01), 4)

        return ok({
            "channels": channels,
            "total_revenue_yuan": round(total_revenue / 100, 2),
            "period": {"start": start.isoformat(), "end": end.isoformat()},
        })
    except Exception as exc:
        logger.error("channel_attribution_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="获取渠道归因失败")


@router.get("/trends")
async def attribution_trends(
    tenant_id: str = Depends(_require_tenant),
    granularity: str = Query("day", alias="granularity", description="日/周/月"),
    days: int = Query(30, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """归因趋势（日/周/月粒度）。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    if granularity not in ("day", "week", "month"):
        raise HTTPException(status_code=400, detail="granularity 须为 day/week/month")

    trunc_map = {"day": "day", "week": "week", "month": "month"}
    trunc = trunc_map[granularity]

    try:
        rows = await db.execute(
            text(f"""
                SELECT
                    DATE_TRUNC(:trunc, ac.converted_at) AS period,
                    COUNT(*) AS conversions,
                    COALESCE(SUM(ac.order_amount_fen), 0) AS revenue_fen
                FROM attribution_conversions ac
                WHERE ac.tenant_id = current_setting('app.tenant_id')::uuid
                  AND ac.converted_at >= NOW() - (:days || ' days')::interval
                  AND NOT ac.is_deleted
                GROUP BY DATE_TRUNC(:trunc, ac.converted_at)
                ORDER BY period
            """),
            {"trunc": trunc, "days": days},
        )
        trend_data = [
            {
                "period": r["period"].isoformat() if r["period"] else None,
                "conversions": r["conversions"],
                "revenue_yuan": round((r["revenue_fen"] or 0) / 100, 2),
            }
            for r in rows.mappings()
        ]

        return ok({
            "granularity": granularity,
            "days": days,
            "trends": trend_data,
        })
    except Exception as exc:
        logger.error("attribution_trends_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="获取归因趋势失败")


@router.get("/funnel")
async def conversion_funnel(
    tenant_id: str = Depends(_require_tenant),
    start_date: Optional[str] = Query(None, alias="start"),
    end_date: Optional[str] = Query(None, alias="end"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """曝光→领券→核销全链路转化漏斗。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    end = date.today()
    start = end - timedelta(days=30)
    if start_date:
        start = date.fromisoformat(start_date)
    if end_date:
        end = date.fromisoformat(end_date)

    try:
        # 触达（曝光）
        exposed_row = await db.execute(
            text("""
                SELECT COUNT(*) AS total, COUNT(DISTINCT customer_id) AS unique_members
                FROM marketing_touch_log
                WHERE tenant_id = current_setting('app.tenant_id')::uuid
                  AND touched_at::date >= :start
                  AND touched_at::date <= :end
                  AND NOT is_deleted
            """),
            {"start": start, "end": end},
        )
        exposed = exposed_row.mappings().one()
        exposed_total = exposed["total"] or 0
        exposed_unique = exposed["unique_members"] or 0

        # 点击（兴趣）
        clicked_row = await db.execute(
            text("""
                SELECT COUNT(*) AS total, COUNT(DISTINCT customer_id) AS unique_members
                FROM marketing_touch_log
                WHERE tenant_id = current_setting('app.tenant_id')::uuid
                  AND touched_at::date >= :start
                  AND touched_at::date <= :end
                  AND status IN ('clicked', 'opened')
                  AND NOT is_deleted
            """),
            {"start": start, "end": end},
        )
        clicked = clicked_row.mappings().one()
        clicked_total = clicked["total"] or 0
        clicked_unique = clicked["unique_members"] or 0

        # 转化（核销）
        converted_row = await db.execute(
            text("""
                SELECT COUNT(*) AS total, COUNT(DISTINCT customer_id) AS unique_members,
                       COALESCE(SUM(order_amount_fen), 0) AS revenue_fen
                FROM attribution_conversions
                WHERE tenant_id = current_setting('app.tenant_id')::uuid
                  AND converted_at::date >= :start
                  AND converted_at::date <= :end
                  AND NOT is_deleted
            """),
            {"start": start, "end": end},
        )
        converted = converted_row.mappings().one()

        return ok({
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "funnel": [
                {
                    "stage": "exposed",
                    "label": "曝光触达",
                    "count": exposed_total,
                    "unique_members": exposed_unique,
                    "rate": 1.0,
                },
                {
                    "stage": "interested",
                    "label": "点击兴趣",
                    "count": clicked_total,
                    "unique_members": clicked_unique,
                    "rate": round(clicked_total / max(exposed_total, 1), 4),
                },
                {
                    "stage": "converted",
                    "label": "核销转化",
                    "count": converted["total"] or 0,
                    "unique_members": converted["unique_members"] or 0,
                    "rate": round((converted["total"] or 0) / max(exposed_total, 1), 4),
                    "revenue_yuan": round((converted["revenue_fen"] or 0) / 100, 2),
                },
            ],
            "overall_conversion_rate": round(
                (converted["total"] or 0) / max(exposed_total, 1), 4
            ),
        })
    except Exception as exc:
        logger.error("conversion_funnel_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="获取转化漏斗失败")
