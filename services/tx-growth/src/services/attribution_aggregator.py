"""归因聚合服务 — 计算活动汇总、渠道效果、人群效果

核心职责：
  1. compute_campaign_summary()       — 活动维度 ROI/转化率/CAC 汇总
  2. compute_channel_performance()    — 渠道效果对比（wecom/sms/miniapp_push/poster_qr）
  3. compute_segment_performance()    — 人群效果对比（基于 customer RFM 分层）
  4. upsert_campaign_summary()        — 聚合结果写入 campaign_summaries 表

所有查询加 tenant_id 过滤（RLS 二次保障）。
金额单位：元（NUMERIC(12,2)）。
"""
import uuid
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone, timedelta
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class CampaignSummary:
    tenant_id: uuid.UUID
    campaign_id: Optional[uuid.UUID]
    campaign_name: str
    period_start: date
    period_end: date
    total_touches: int
    delivered_count: int
    clicked_count: int
    click_rate: float           # 点击率
    delivery_rate: float        # 送达率
    reservations_attributed: int
    orders_attributed: int
    revenue_attributed: float
    cac: float
    roi: float
    top_segments: list


@dataclass
class ChannelPerformance:
    channel: str
    total_touches: int
    delivered_count: int
    clicked_count: int
    click_rate: float
    conversions: int
    revenue: float
    conversion_rate: float


@dataclass
class SegmentPerformance:
    segment_name: str
    total_touches: int
    conversions: int
    revenue: float
    conversion_rate: float
    avg_order_value: float


# ---------------------------------------------------------------------------
# AttributionAggregator
# ---------------------------------------------------------------------------


class AttributionAggregator:
    """归因聚合器 — 基于 touch_events + attribution_conversions 表聚合指标"""

    # ------------------------------------------------------------------
    # A. 活动汇总
    # ------------------------------------------------------------------

    async def compute_campaign_summary(
        self,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
        db: AsyncSession,
        *,
        campaign_id: Optional[uuid.UUID] = None,
    ) -> CampaignSummary:
        """计算活动（或全部触达）在指定日期范围内的汇总指标。

        Args:
            tenant_id:    租户 UUID
            period_start: 统计开始日期（含）
            period_end:   统计结束日期（含）
            db:           AsyncSession
            campaign_id:  指定活动 UUID；为 None 时统计该租户所有触达

        Returns:
            CampaignSummary dataclass
        """
        # ---- 触达漏斗指标 ----
        campaign_filter = (
            "AND campaign_id = :campaign_id" if campaign_id else ""
        )
        touch_rows = await db.execute(
            f"""
            SELECT
                COUNT(*)                                    AS total_touches,
                COUNT(delivered_at)                         AS delivered_count,
                COUNT(clicked_at)                           AS clicked_count,
                MAX(COALESCE(content_snapshot->>'campaign_name', ''))  AS campaign_name
            FROM touch_events
            WHERE tenant_id   = :tenant_id
              AND sent_at::date >= :period_start
              AND sent_at::date <= :period_end
              {campaign_filter}
            """,
            {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end,
                "campaign_id": campaign_id,
            },
        )
        tr = touch_rows.fetchone()
        total_touches: int = int(tr.total_touches or 0)
        delivered_count: int = int(tr.delivered_count or 0)
        clicked_count: int = int(tr.clicked_count or 0)
        campaign_name: str = tr.campaign_name or ""

        click_rate = round(clicked_count / max(1, delivered_count), 4)
        delivery_rate = round(delivered_count / max(1, total_touches), 4)

        # ---- 转化指标（join touch_events） ----
        conv_rows = await db.execute(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE ac.conversion_type = 'reservation') AS reservations,
                COUNT(*) FILTER (WHERE ac.conversion_type IN ('order', 'repurchase')) AS orders,
                COALESCE(SUM(ac.conversion_value), 0)                      AS revenue
            FROM attribution_conversions ac
            JOIN touch_events te ON te.touch_id = ac.touch_id
            WHERE ac.tenant_id  = :tenant_id
              AND ac.converted_at::date >= :period_start
              AND ac.converted_at::date <= :period_end
              {campaign_filter.replace('campaign_id', 'te.campaign_id')}
            """,
            {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end,
                "campaign_id": campaign_id,
            },
        )
        cr = conv_rows.fetchone()
        reservations: int = int(cr.reservations or 0)
        orders: int = int(cr.orders or 0)
        revenue: float = float(cr.revenue or 0)

        # ---- 效率指标 ----
        # CAC：本版本无活动成本表，预留为 0；有成本时 = cost / new_customers
        cac = 0.0
        roi = 0.0

        # ---- 各人群效果（按 content_type 或 channel 分组近似人群） ----
        seg_rows = await db.execute(
            f"""
            SELECT
                te.channel                                          AS segment_name,
                COUNT(DISTINCT te.customer_id)                      AS touches,
                COUNT(DISTINCT ac.customer_id)                      AS conversions,
                COALESCE(SUM(ac.conversion_value), 0)               AS revenue
            FROM touch_events te
            LEFT JOIN attribution_conversions ac
                ON ac.touch_id = te.touch_id
               AND ac.tenant_id = te.tenant_id
            WHERE te.tenant_id  = :tenant_id
              AND te.sent_at::date >= :period_start
              AND te.sent_at::date <= :period_end
              {campaign_filter.replace('campaign_id', 'te.campaign_id')}
            GROUP BY te.channel
            ORDER BY revenue DESC
            """,
            {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end,
                "campaign_id": campaign_id,
            },
        )
        top_segments = [
            {
                "segment_name": row.segment_name,
                "touches": int(row.touches),
                "conversions": int(row.conversions),
                "revenue": float(row.revenue),
                "conversion_rate": round(
                    int(row.conversions) / max(1, int(row.touches)), 4
                ),
            }
            for row in seg_rows.fetchall()
        ]

        return CampaignSummary(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            period_start=period_start,
            period_end=period_end,
            total_touches=total_touches,
            delivered_count=delivered_count,
            clicked_count=clicked_count,
            click_rate=click_rate,
            delivery_rate=delivery_rate,
            reservations_attributed=reservations,
            orders_attributed=orders,
            revenue_attributed=revenue,
            cac=cac,
            roi=roi,
            top_segments=top_segments,
        )

    # ------------------------------------------------------------------
    # B. 渠道效果对比
    # ------------------------------------------------------------------

    async def compute_channel_performance(
        self,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
        db: AsyncSession,
    ) -> list[ChannelPerformance]:
        """各渠道效果对比：wecom / sms / miniapp_push / poster_qr。

        Returns:
            按转化率降序排列的 ChannelPerformance 列表
        """
        rows = await db.execute(
            """
            SELECT
                te.channel,
                COUNT(DISTINCT te.id)                   AS total_touches,
                COUNT(DISTINCT te.id) FILTER (WHERE te.delivered_at IS NOT NULL) AS delivered_count,
                COUNT(DISTINCT te.id) FILTER (WHERE te.clicked_at IS NOT NULL)   AS clicked_count,
                COUNT(DISTINCT ac.id)                   AS conversions,
                COALESCE(SUM(ac.conversion_value), 0)   AS revenue
            FROM touch_events te
            LEFT JOIN attribution_conversions ac
                ON ac.touch_id = te.touch_id
               AND ac.tenant_id = te.tenant_id
            WHERE te.tenant_id  = :tenant_id
              AND te.sent_at::date >= :period_start
              AND te.sent_at::date <= :period_end
            GROUP BY te.channel
            ORDER BY revenue DESC
            """,
            {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end,
            },
        )

        results: list[ChannelPerformance] = []
        for row in rows.fetchall():
            total = int(row.total_touches)
            delivered = int(row.delivered_count)
            clicked = int(row.clicked_count)
            conversions = int(row.conversions)
            revenue = float(row.revenue)
            results.append(
                ChannelPerformance(
                    channel=row.channel,
                    total_touches=total,
                    delivered_count=delivered,
                    clicked_count=clicked,
                    click_rate=round(clicked / max(1, delivered), 4),
                    conversions=conversions,
                    revenue=revenue,
                    conversion_rate=round(conversions / max(1, total), 4),
                )
            )

        log.info(
            "channel_performance_computed",
            tenant_id=str(tenant_id),
            channels=[r.channel for r in results],
        )
        return results

    # ------------------------------------------------------------------
    # C. 人群效果对比
    # ------------------------------------------------------------------

    async def compute_segment_performance(
        self,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
        db: AsyncSession,
    ) -> list[SegmentPerformance]:
        """各 content_type 效果对比（以 content_type 作为人群代理维度）。

        当 customer RFM 分层数据可获取时，可将此处的 GROUP BY content_type
        替换为 GROUP BY customer_rfm_segment 实现真正的人群对比。

        Returns:
            按转化率降序排列的 SegmentPerformance 列表
        """
        rows = await db.execute(
            """
            SELECT
                te.content_type                         AS segment_name,
                COUNT(DISTINCT te.customer_id)          AS total_touches,
                COUNT(DISTINCT ac.customer_id)          AS conversions,
                COALESCE(SUM(ac.conversion_value), 0)   AS revenue
            FROM touch_events te
            LEFT JOIN attribution_conversions ac
                ON ac.touch_id = te.touch_id
               AND ac.tenant_id = te.tenant_id
            WHERE te.tenant_id  = :tenant_id
              AND te.sent_at::date >= :period_start
              AND te.sent_at::date <= :period_end
            GROUP BY te.content_type
            ORDER BY revenue DESC
            """,
            {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end,
            },
        )

        results: list[SegmentPerformance] = []
        for row in rows.fetchall():
            touches = int(row.total_touches)
            convs = int(row.conversions)
            rev = float(row.revenue)
            results.append(
                SegmentPerformance(
                    segment_name=row.segment_name,
                    total_touches=touches,
                    conversions=convs,
                    revenue=rev,
                    conversion_rate=round(convs / max(1, touches), 4),
                    avg_order_value=round(rev / max(1, convs), 2),
                )
            )

        log.info(
            "segment_performance_computed",
            tenant_id=str(tenant_id),
            segments=[r.segment_name for r in results],
        )
        return results

    # ------------------------------------------------------------------
    # D. 写入 / 更新 campaign_summaries 表
    # ------------------------------------------------------------------

    async def upsert_campaign_summary(
        self,
        summary: CampaignSummary,
        db: AsyncSession,
    ) -> None:
        """将 CampaignSummary 写入 campaign_summaries 表（upsert）。

        使用 ON CONFLICT DO UPDATE 保证幂等，定时任务每天调用一次。
        """
        campaign_id_str = str(summary.campaign_id) if summary.campaign_id else None

        await db.execute(
            """
            INSERT INTO campaign_summaries
              (id, tenant_id, campaign_id, campaign_name,
               period_start, period_end,
               total_touches, delivered_count, clicked_count,
               reservations_attributed, orders_attributed, revenue_attributed,
               cac, roi, top_segments, created_at, updated_at)
            VALUES
              (gen_random_uuid(), :tenant_id, :campaign_id, :campaign_name,
               :period_start, :period_end,
               :total_touches, :delivered_count, :clicked_count,
               :reservations, :orders, :revenue,
               :cac, :roi, :top_segments::jsonb, NOW(), NOW())
            ON CONFLICT (tenant_id, campaign_id, period_start, period_end)
            WHERE campaign_id IS NOT NULL
            DO UPDATE SET
                campaign_name           = EXCLUDED.campaign_name,
                total_touches           = EXCLUDED.total_touches,
                delivered_count         = EXCLUDED.delivered_count,
                clicked_count           = EXCLUDED.clicked_count,
                reservations_attributed = EXCLUDED.reservations_attributed,
                orders_attributed       = EXCLUDED.orders_attributed,
                revenue_attributed      = EXCLUDED.revenue_attributed,
                cac                     = EXCLUDED.cac,
                roi                     = EXCLUDED.roi,
                top_segments            = EXCLUDED.top_segments,
                updated_at              = NOW()
            """,
            {
                "tenant_id": summary.tenant_id,
                "campaign_id": campaign_id_str,
                "campaign_name": summary.campaign_name,
                "period_start": summary.period_start,
                "period_end": summary.period_end,
                "total_touches": summary.total_touches,
                "delivered_count": summary.delivered_count,
                "clicked_count": summary.clicked_count,
                "reservations": summary.reservations_attributed,
                "orders": summary.orders_attributed,
                "revenue": summary.revenue_attributed,
                "cac": summary.cac,
                "roi": summary.roi,
                "top_segments": json.dumps(summary.top_segments, ensure_ascii=False),
            },
        )

        log.info(
            "campaign_summary_upserted",
            tenant_id=str(summary.tenant_id),
            campaign_id=str(summary.campaign_id) if summary.campaign_id else "all",
            period=f"{summary.period_start}~{summary.period_end}",
            revenue=summary.revenue_attributed,
        )
