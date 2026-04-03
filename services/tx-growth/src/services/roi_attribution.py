"""ROI归因引擎 — 证明增长中枢是赚钱系统

完整的营销归因链路：
touch → open → click → reserve → visit → order → repeat

支持三种归因模型：
  last_touch  — 默认。归因给归因窗口内最近一次触达（最接近下单的那次）
  first_touch — 归因给客户在归因窗口内最早一次触达
  linear      — 归因窗口内所有触达均分订单金额

归因窗口：ATTRIBUTION_WINDOW_HOURS（默认72小时）

金额单位：分(fen)
"""
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from models.attribution import AttributionSummary, MarketingTouch
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 全局配置
# ---------------------------------------------------------------------------

ATTRIBUTION_WINDOW_HOURS: int = 72


# ---------------------------------------------------------------------------
# ROIAttributionService
# ---------------------------------------------------------------------------


class ROIAttributionService:
    """ROI归因引擎 — 将每笔订单归因到具体营销活动/旅程/渠道

    核心逻辑：
    1. 每次营销触达（旅程节点执行、活动推送）调用 record_touch() 写入 marketing_touches
    2. 订单产生时调用 attribute_order() 查找最近触点并回写转化信息
    3. 聚合查询用于仪表盘和报表
    """

    # 支持的归因模型
    ATTRIBUTION_MODELS = ["last_touch", "first_touch", "linear"]

    # ------------------------------------------------------------------
    # A. 记录营销触达
    # ------------------------------------------------------------------

    async def record_touch(
        self,
        touch_data: dict,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> MarketingTouch:
        """记录一次营销触达事件。

        每次旅程节点执行（send_content / send_offer）或活动推送后调用。

        Args:
            touch_data: {
                customer_id: str | UUID,
                touch_type: str,        # campaign | journey | referral | manual
                source_id: str,         # 活动ID / 旅程ID
                source_name: str,       # 活动/旅程名称
                channel: str,           # wecom | sms | miniapp | pos_receipt
                message_title: str | None,
                offer_id: str | None,
                touched_at: datetime | None,  # 默认 now()
            }
            tenant_id: 租户 UUID
            db: AsyncSession

        Returns:
            已写入 DB 的 MarketingTouch 实例
        """
        now = datetime.now(timezone.utc)

        customer_id_raw = touch_data["customer_id"]
        customer_uuid = (
            customer_id_raw
            if isinstance(customer_id_raw, uuid.UUID)
            else uuid.UUID(str(customer_id_raw))
        )

        touched_at_raw = touch_data.get("touched_at")
        touched_at: datetime
        if touched_at_raw is None:
            touched_at = now
        elif isinstance(touched_at_raw, datetime):
            touched_at = touched_at_raw
        else:
            touched_at = datetime.fromisoformat(str(touched_at_raw))

        touch = MarketingTouch(
            tenant_id=tenant_id,
            customer_id=customer_uuid,
            touch_type=touch_data["touch_type"],
            source_id=touch_data["source_id"],
            source_name=touch_data.get("source_name", ""),
            channel=touch_data["channel"],
            message_title=touch_data.get("message_title"),
            offer_id=touch_data.get("offer_id"),
            is_converted=False,
            touched_at=touched_at,
        )
        db.add(touch)
        await db.flush()

        log.info(
            "marketing_touch_recorded",
            touch_id=str(touch.id),
            customer_id=str(customer_uuid),
            source_id=touch_data["source_id"],
            touch_type=touch_data["touch_type"],
            channel=touch_data["channel"],
            tenant_id=str(tenant_id),
        )
        return touch

    # ------------------------------------------------------------------
    # B. 订单归因
    # ------------------------------------------------------------------

    async def attribute_order(
        self,
        order_id: uuid.UUID,
        customer_id: uuid.UUID,
        order_amount_fen: int,
        order_time: datetime,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        model: str = "last_touch",
        ab_test_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        """将一笔订单归因到营销触点。

        归因逻辑（以 last_touch 为例）：
          1. 查询该客户在 [order_time - ATTRIBUTION_WINDOW_HOURS, order_time]
             内所有未转化的 MarketingTouch，按 touched_at DESC 排序
          2. 取最近一条作为归因来源
          3. 回写 is_converted=True, order_id, order_amount_fen, converted_at
          4. 触发汇总更新 _update_summary()

        Args:
            order_id:           订单 UUID
            customer_id:        下单客户 UUID
            order_amount_fen:   订单金额（分）
            order_time:         下单时间（带时区）
            tenant_id:          租户 UUID
            db:                 AsyncSession
            model:              归因模型，默认 last_touch
            ab_test_id:         若订单来源于AB测试，同时回写 ABTestAssignment 转化记录

        Returns:
            {
              "attributed": bool,
              "model": str,
              "touch_id": str | None,
              "source_id": str | None,
              "source_name": str | None,
              "touch_type": str | None,
              "channel": str | None,
            }
        """
        if model not in self.ATTRIBUTION_MODELS:
            log.warning(
                "unsupported_attribution_model",
                model=model,
                order_id=str(order_id),
            )
            model = "last_touch"

        window_start = order_time - timedelta(hours=ATTRIBUTION_WINDOW_HOURS)

        # 查询归因窗口内该客户所有未转化触点
        stmt = (
            select(MarketingTouch)
            .where(
                and_(
                    MarketingTouch.tenant_id == tenant_id,
                    MarketingTouch.customer_id == customer_id,
                    MarketingTouch.is_converted.is_(False),
                    MarketingTouch.touched_at >= window_start,
                    MarketingTouch.touched_at <= order_time,
                )
            )
            .order_by(MarketingTouch.touched_at.asc())
        )
        result = await db.execute(stmt)
        touches: list[MarketingTouch] = list(result.scalars().all())

        if not touches:
            log.info(
                "attribution_no_touch_found",
                order_id=str(order_id),
                customer_id=str(customer_id),
                window_hours=ATTRIBUTION_WINDOW_HOURS,
            )
            return {
                "attributed": False,
                "model": model,
                "touch_id": None,
                "source_id": None,
                "source_name": None,
                "touch_type": None,
                "channel": None,
            }

        # 按归因模型选取目标触点
        selected_touch: MarketingTouch

        if model == "last_touch":
            # 最近一次触达
            selected_touch = touches[-1]
            await self._mark_touch_converted(
                db, selected_touch, order_id, order_amount_fen, order_time
            )
            await self._update_summary(
                db, tenant_id, selected_touch, order_amount_fen,
                order_time.date(), model
            )

        elif model == "first_touch":
            # 最早一次触达
            selected_touch = touches[0]
            await self._mark_touch_converted(
                db, selected_touch, order_id, order_amount_fen, order_time
            )
            await self._update_summary(
                db, tenant_id, selected_touch, order_amount_fen,
                order_time.date(), model
            )

        elif model == "linear":
            # 所有触点均分收入
            share_fen = order_amount_fen // len(touches)
            remainder = order_amount_fen - share_fen * len(touches)

            for i, touch in enumerate(touches):
                # 最后一条多分余数，避免精度丢失
                amount = share_fen + (remainder if i == len(touches) - 1 else 0)
                await self._mark_touch_converted(
                    db, touch, order_id, amount, order_time
                )
                await self._update_summary(
                    db, tenant_id, touch, amount,
                    order_time.date(), model
                )
            # 返回最后一个触点作为代表
            selected_touch = touches[-1]

        log.info(
            "order_attributed",
            order_id=str(order_id),
            customer_id=str(customer_id),
            source_id=selected_touch.source_id,
            source_name=selected_touch.source_name,
            touch_type=selected_touch.touch_type,
            channel=selected_touch.channel,
            model=model,
            order_amount_fen=order_amount_fen,
            tenant_id=str(tenant_id),
        )

        # ── AB测试转化回写 ────────────────────────────────────────────
        # 若此次归因关联了 AB 测试，同步记录 ABTestAssignment 的转化
        if ab_test_id is not None:
            try:
                from services.ab_test_service import ABTestService
                ab_svc = ABTestService()
                await ab_svc.record_conversion(
                    test_id=ab_test_id,
                    customer_id=customer_id,
                    order_id=order_id,
                    order_amount_fen=order_amount_fen,
                    tenant_id=tenant_id,
                    db=db,
                )
            except (ValueError, KeyError) as exc:
                # AB测试回写失败不影响主归因流程
                log.warning(
                    "ab_test.conversion_record_failed",
                    ab_test_id=str(ab_test_id),
                    order_id=str(order_id),
                    customer_id=str(customer_id),
                    error=str(exc),
                )

        return {
            "attributed": True,
            "model": model,
            "touch_id": str(selected_touch.id),
            "source_id": selected_touch.source_id,
            "source_name": selected_touch.source_name,
            "touch_type": selected_touch.touch_type,
            "channel": selected_touch.channel,
        }

    async def _mark_touch_converted(
        self,
        db: AsyncSession,
        touch: MarketingTouch,
        order_id: uuid.UUID,
        order_amount_fen: int,
        converted_at: datetime,
    ) -> None:
        """回写触点的转化字段。"""
        await db.execute(
            update(MarketingTouch)
            .where(MarketingTouch.id == touch.id)
            .values(
                is_converted=True,
                order_id=order_id,
                order_amount_fen=order_amount_fen,
                converted_at=converted_at,
            )
        )

    async def _update_summary(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        touch: MarketingTouch,
        revenue_fen: int,
        stat_date: date,
        model: str,
    ) -> None:
        """更新（或创建）当日归因汇总行。

        采用 SELECT + conditional UPDATE/INSERT 模式（不依赖 ON CONFLICT，
        兼容无 UNIQUE 约束的情况）。
        """
        stmt = select(AttributionSummary).where(
            and_(
                AttributionSummary.tenant_id == tenant_id,
                AttributionSummary.source_id == touch.source_id,
                AttributionSummary.stat_date == stat_date,
                AttributionSummary.model == model,
            )
        )
        result = await db.execute(stmt)
        summary: Optional[AttributionSummary] = result.scalar_one_or_none()

        if summary is None:
            # 首次插入该来源当日汇总
            new_summary = AttributionSummary(
                tenant_id=tenant_id,
                source_type=touch.touch_type,
                source_id=touch.source_id,
                source_name=touch.source_name,
                stat_date=stat_date,
                total_touches=1,
                unique_customers=1,
                converted_customers=1,
                conversion_rate=1.0,
                attributed_revenue_fen=revenue_fen,
                cost_fen=0,
                roi=0.0,
                model=model,
            )
            db.add(new_summary)
            await db.flush()
        else:
            new_converted = summary.converted_customers + 1
            new_revenue = summary.attributed_revenue_fen + revenue_fen
            new_rate = (
                round(new_converted / summary.unique_customers, 4)
                if summary.unique_customers > 0
                else 0.0
            )
            new_roi = (
                round((new_revenue - summary.cost_fen) / summary.cost_fen, 4)
                if summary.cost_fen > 0
                else 0.0
            )
            await db.execute(
                update(AttributionSummary)
                .where(AttributionSummary.id == summary.id)
                .values(
                    converted_customers=new_converted,
                    attributed_revenue_fen=new_revenue,
                    conversion_rate=new_rate,
                    roi=new_roi,
                )
            )

        log.debug(
            "attribution_summary_updated",
            source_id=touch.source_id,
            stat_date=str(stat_date),
            revenue_fen=revenue_fen,
            model=model,
        )

    # ------------------------------------------------------------------
    # C. 活动 ROI 计算
    # ------------------------------------------------------------------

    async def calculate_campaign_roi(
        self,
        campaign_id: str,
        start_date: date,
        end_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        model: str = "last_touch",
    ) -> dict[str, Any]:
        """计算某活动在指定日期范围内的 ROI。

        Args:
            campaign_id:  活动 ID
            start_date:   统计开始日期（含）
            end_date:     统计结束日期（含）
            tenant_id:    租户 UUID
            db:           AsyncSession
            model:        归因模型

        Returns:
            详细 ROI 报告 dict
        """
        # 查询该活动在时间范围内的所有触点
        stmt = select(MarketingTouch).where(
            and_(
                MarketingTouch.tenant_id == tenant_id,
                MarketingTouch.source_id == campaign_id,
                MarketingTouch.touched_at >= datetime.combine(
                    start_date, datetime.min.time(), tzinfo=timezone.utc
                ),
                MarketingTouch.touched_at <= datetime.combine(
                    end_date, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc
                ),
            )
        )
        result = await db.execute(stmt)
        touches: list[MarketingTouch] = list(result.scalars().all())

        if not touches:
            return {
                "campaign_id": campaign_id,
                "model": model,
                "start_date": str(start_date),
                "end_date": str(end_date),
                "total_touches": 0,
                "unique_customers": 0,
                "converted_customers": 0,
                "conversion_rate": 0.0,
                "attributed_revenue_fen": 0,
                "attributed_revenue_yuan": 0.0,
                "cost_fen": 0,
                "cost_yuan": 0.0,
                "roi": 0.0,
                "cac_fen": 0,
                "cac_yuan": 0.0,
            }

        total_touches = len(touches)
        unique_customers = len({t.customer_id for t in touches})
        converted = [t for t in touches if t.is_converted]
        converted_customers = len({t.customer_id for t in converted})
        attributed_revenue_fen = sum(
            t.order_amount_fen or 0 for t in converted
        )

        # 活动优惠成本：从汇总表取最新 cost_fen（由业务层写入）
        cost_stmt = select(func.sum(AttributionSummary.cost_fen)).where(
            and_(
                AttributionSummary.tenant_id == tenant_id,
                AttributionSummary.source_id == campaign_id,
                AttributionSummary.stat_date >= start_date,
                AttributionSummary.stat_date <= end_date,
                AttributionSummary.model == model,
            )
        )
        cost_result = await db.execute(cost_stmt)
        cost_fen: int = cost_result.scalar_one_or_none() or 0

        conversion_rate = round(
            converted_customers / unique_customers, 4
        ) if unique_customers > 0 else 0.0
        roi = round(
            (attributed_revenue_fen - cost_fen) / cost_fen, 4
        ) if cost_fen > 0 else 0.0
        cac_fen = (
            cost_fen // converted_customers
            if converted_customers > 0
            else 0
        )

        # 渠道分布
        channel_dist: dict[str, int] = defaultdict(int)
        for t in touches:
            channel_dist[t.channel] += 1

        return {
            "campaign_id": campaign_id,
            "model": model,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "total_touches": total_touches,
            "unique_customers": unique_customers,
            "converted_customers": converted_customers,
            "conversion_rate": conversion_rate,
            "attributed_revenue_fen": attributed_revenue_fen,
            "attributed_revenue_yuan": round(attributed_revenue_fen / 100, 2),
            "cost_fen": cost_fen,
            "cost_yuan": round(cost_fen / 100, 2),
            "roi": roi,
            "cac_fen": cac_fen,
            "cac_yuan": round(cac_fen / 100, 2),
            "channel_breakdown": dict(channel_dist),
        }

    # ------------------------------------------------------------------
    # D. 旅程 ROI 计算
    # ------------------------------------------------------------------

    async def calculate_journey_roi(
        self,
        journey_id: str,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        model: str = "last_touch",
    ) -> dict[str, Any]:
        """计算营销旅程的 ROI，并分析各节点漏斗。

        Returns:
            {
              journey_id, total_touches, converted_customers,
              attributed_revenue_fen, roi,
              funnel: [{channel, touches, converted, rate}],
              bottleneck_channel: str  # 流失最多的渠道
            }
        """
        stmt = select(MarketingTouch).where(
            and_(
                MarketingTouch.tenant_id == tenant_id,
                MarketingTouch.source_id == journey_id,
            )
        )
        result = await db.execute(stmt)
        touches: list[MarketingTouch] = list(result.scalars().all())

        if not touches:
            return {
                "journey_id": journey_id,
                "model": model,
                "total_touches": 0,
                "unique_customers": 0,
                "converted_customers": 0,
                "attributed_revenue_fen": 0,
                "attributed_revenue_yuan": 0.0,
                "cost_fen": 0,
                "roi": 0.0,
                "funnel": [],
                "bottleneck_channel": None,
            }

        # 按渠道分组统计（旅程节点通过 channel 区分步骤）
        channel_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"touches": 0, "customers": set(), "converted": 0, "revenue_fen": 0}
        )
        for t in touches:
            ch = t.channel
            channel_stats[ch]["touches"] += 1
            channel_stats[ch]["customers"].add(t.customer_id)
            if t.is_converted:
                channel_stats[ch]["converted"] += 1
                channel_stats[ch]["revenue_fen"] += t.order_amount_fen or 0

        funnel: list[dict] = []
        min_rate: float = 1.0
        bottleneck_channel: Optional[str] = None

        for ch, stats in channel_stats.items():
            unique = len(stats["customers"])
            converted = stats["converted"]
            rate = round(converted / unique, 4) if unique > 0 else 0.0
            funnel.append({
                "channel": ch,
                "touches": stats["touches"],
                "unique_customers": unique,
                "converted": converted,
                "conversion_rate": rate,
                "revenue_fen": stats["revenue_fen"],
                "revenue_yuan": round(stats["revenue_fen"] / 100, 2),
            })
            if rate < min_rate:
                min_rate = rate
                bottleneck_channel = ch

        total_converted = len({t.customer_id for t in touches if t.is_converted})
        total_revenue = sum(t.order_amount_fen or 0 for t in touches if t.is_converted)

        # 汇总成本
        cost_stmt = select(func.sum(AttributionSummary.cost_fen)).where(
            and_(
                AttributionSummary.tenant_id == tenant_id,
                AttributionSummary.source_id == journey_id,
            )
        )
        cost_result = await db.execute(cost_stmt)
        cost_fen: int = cost_result.scalar_one_or_none() or 0

        roi = round(
            (total_revenue - cost_fen) / cost_fen, 4
        ) if cost_fen > 0 else 0.0

        return {
            "journey_id": journey_id,
            "model": model,
            "total_touches": len(touches),
            "unique_customers": len({t.customer_id for t in touches}),
            "converted_customers": total_converted,
            "attributed_revenue_fen": total_revenue,
            "attributed_revenue_yuan": round(total_revenue / 100, 2),
            "cost_fen": cost_fen,
            "cost_yuan": round(cost_fen / 100, 2),
            "roi": roi,
            "funnel": funnel,
            "bottleneck_channel": bottleneck_channel,
        }

    # ------------------------------------------------------------------
    # E. 营销总览仪表盘
    # ------------------------------------------------------------------

    async def get_attribution_dashboard(
        self,
        tenant_id: uuid.UUID,
        date_range: dict,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """营销总览仪表盘。

        Args:
            tenant_id:   租户 UUID
            date_range:  {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
            db:          AsyncSession

        Returns:
            {
              total_touches, total_converted, total_revenue,
              avg_roi, top_campaigns, channel_breakdown, daily_trend
            }
        """
        start_str: str = date_range.get("start", "")
        end_str: str = date_range.get("end", "")

        # 日期解析（默认近30天）
        today = datetime.now(timezone.utc).date()
        start_date: date = date.fromisoformat(start_str) if start_str else (
            date(today.year, today.month, 1)
            if today.day > 30
            else date.fromordinal(today.toordinal() - 29)
        )
        end_date: date = date.fromisoformat(end_str) if end_str else today

        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = datetime.combine(end_date, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)

        # 全量触点统计
        total_stmt = select(
            func.count(MarketingTouch.id).label("total_touches"),
            func.count(MarketingTouch.id).filter(
                MarketingTouch.is_converted.is_(True)
            ).label("total_converted"),
            func.coalesce(
                func.sum(MarketingTouch.order_amount_fen).filter(
                    MarketingTouch.is_converted.is_(True)
                ), 0
            ).label("total_revenue"),
        ).where(
            and_(
                MarketingTouch.tenant_id == tenant_id,
                MarketingTouch.touched_at >= start_dt,
                MarketingTouch.touched_at <= end_dt,
            )
        )
        total_result = await db.execute(total_stmt)
        row = total_result.one()
        total_touches: int = row.total_touches or 0
        total_converted: int = row.total_converted or 0
        total_revenue: int = row.total_revenue or 0

        # 平均 ROI（来自汇总表）
        roi_stmt = select(func.avg(AttributionSummary.roi)).where(
            and_(
                AttributionSummary.tenant_id == tenant_id,
                AttributionSummary.stat_date >= start_date,
                AttributionSummary.stat_date <= end_date,
                AttributionSummary.roi != 0.0,
            )
        )
        roi_result = await db.execute(roi_stmt)
        avg_roi: float = round(roi_result.scalar_one_or_none() or 0.0, 4)

        # 渠道转化率对比
        channel_stmt = select(
            MarketingTouch.channel,
            func.count(MarketingTouch.id).label("touches"),
            func.count(MarketingTouch.id).filter(
                MarketingTouch.is_converted.is_(True)
            ).label("converted"),
        ).where(
            and_(
                MarketingTouch.tenant_id == tenant_id,
                MarketingTouch.touched_at >= start_dt,
                MarketingTouch.touched_at <= end_dt,
            )
        ).group_by(MarketingTouch.channel)
        channel_result = await db.execute(channel_stmt)
        channel_breakdown: list[dict] = []
        for ch_row in channel_result.all():
            ch_touches = ch_row.touches or 0
            ch_converted = ch_row.converted or 0
            channel_breakdown.append({
                "channel": ch_row.channel,
                "touches": ch_touches,
                "converted": ch_converted,
                "conversion_rate": round(
                    ch_converted / ch_touches, 4
                ) if ch_touches > 0 else 0.0,
            })

        # ROI 最高的 5 个活动（来自汇总表）
        top_stmt = (
            select(
                AttributionSummary.source_id,
                AttributionSummary.source_name,
                AttributionSummary.source_type,
                func.sum(AttributionSummary.attributed_revenue_fen).label("total_revenue"),
                func.sum(AttributionSummary.cost_fen).label("total_cost"),
                func.avg(AttributionSummary.roi).label("avg_roi"),
            )
            .where(
                and_(
                    AttributionSummary.tenant_id == tenant_id,
                    AttributionSummary.stat_date >= start_date,
                    AttributionSummary.stat_date <= end_date,
                )
            )
            .group_by(
                AttributionSummary.source_id,
                AttributionSummary.source_name,
                AttributionSummary.source_type,
            )
            .order_by(func.avg(AttributionSummary.roi).desc())
            .limit(5)
        )
        top_result = await db.execute(top_stmt)
        top_campaigns: list[dict] = [
            {
                "source_id": r.source_id,
                "source_name": r.source_name,
                "source_type": r.source_type,
                "attributed_revenue_fen": int(r.total_revenue or 0),
                "attributed_revenue_yuan": round((r.total_revenue or 0) / 100, 2),
                "cost_fen": int(r.total_cost or 0),
                "roi": round(r.avg_roi or 0.0, 4),
            }
            for r in top_result.all()
        ]

        # 近30天每日归因收入趋势（来自汇总表）
        daily_stmt = (
            select(
                AttributionSummary.stat_date,
                func.sum(AttributionSummary.attributed_revenue_fen).label("revenue"),
                func.sum(AttributionSummary.converted_customers).label("converted"),
            )
            .where(
                and_(
                    AttributionSummary.tenant_id == tenant_id,
                    AttributionSummary.stat_date >= start_date,
                    AttributionSummary.stat_date <= end_date,
                )
            )
            .group_by(AttributionSummary.stat_date)
            .order_by(AttributionSummary.stat_date.asc())
        )
        daily_result = await db.execute(daily_stmt)
        daily_trend: list[dict] = [
            {
                "date": str(r.stat_date),
                "attributed_revenue_fen": int(r.revenue or 0),
                "attributed_revenue_yuan": round((r.revenue or 0) / 100, 2),
                "converted_customers": int(r.converted or 0),
            }
            for r in daily_result.all()
        ]

        return {
            "date_range": {"start": str(start_date), "end": str(end_date)},
            "total_touches": total_touches,
            "total_converted": total_converted,
            "total_revenue_fen": total_revenue,
            "total_revenue_yuan": round(total_revenue / 100, 2),
            "overall_conversion_rate": round(
                total_converted / total_touches, 4
            ) if total_touches > 0 else 0.0,
            "avg_roi": avg_roi,
            "top_campaigns": top_campaigns,
            "channel_breakdown": channel_breakdown,
            "daily_trend": daily_trend,
        }

    # ------------------------------------------------------------------
    # F. 转化漏斗
    # ------------------------------------------------------------------

    async def get_conversion_funnel(
        self,
        source_id: str,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """获取某活动/旅程的转化漏斗数据。

        漏斗步骤基于渠道序列：
          触达 → 渠道A推送 → 渠道B推送 → ... → 下单

        Returns:
            {
              source_id,
              steps: ["触达", "wecom推送", "sms推送", "下单"],
              counts: [1000, 350, 120, 85],
              rates:  ["100%", "35.0%", "34.3%", "70.8%"]
            }
        """
        stmt = select(MarketingTouch).where(
            and_(
                MarketingTouch.tenant_id == tenant_id,
                MarketingTouch.source_id == source_id,
            )
        ).order_by(MarketingTouch.touched_at.asc())
        result = await db.execute(stmt)
        touches: list[MarketingTouch] = list(result.scalars().all())

        if not touches:
            return {
                "source_id": source_id,
                "steps": ["触达", "下单"],
                "counts": [0, 0],
                "rates": ["100%", "0%"],
            }

        total_customers = len({t.customer_id for t in touches})

        # 统计各渠道触达的去重客户数
        channel_customers: dict[str, set] = defaultdict(set)
        for t in touches:
            channel_customers[t.channel].add(t.customer_id)

        # 构建漏斗步骤
        steps = ["触达"]
        counts: list[int] = [total_customers]

        for ch, customers in channel_customers.items():
            steps.append(f"{ch}推送")
            counts.append(len(customers))

        # 最后一步：下单
        converted_customers = len({t.customer_id for t in touches if t.is_converted})
        steps.append("下单")
        counts.append(converted_customers)

        # 计算各步转化率（相对于第一步）
        first = counts[0] if counts[0] > 0 else 1
        rates: list[str] = []
        for c in counts:
            pct = round(c / first * 100, 1)
            rates.append(f"{pct}%")

        return {
            "source_id": source_id,
            "steps": steps,
            "counts": counts,
            "rates": rates,
        }

    # ------------------------------------------------------------------
    # G. TOP ROI 排名
    # ------------------------------------------------------------------

    async def get_top_performers(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        limit: int = 10,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """获取 ROI 最高的活动/旅程排名。

        Args:
            tenant_id: 租户 UUID
            db:        AsyncSession
            limit:     返回条数，默认 10
            days:      统计近多少天，默认 30

        Returns:
            按 ROI 降序排列的来源列表
        """
        today = datetime.now(timezone.utc).date()
        start_date = date.fromordinal(today.toordinal() - days + 1)

        stmt = (
            select(
                AttributionSummary.source_id,
                AttributionSummary.source_name,
                AttributionSummary.source_type,
                func.sum(AttributionSummary.total_touches).label("total_touches"),
                func.sum(AttributionSummary.unique_customers).label("unique_customers"),
                func.sum(AttributionSummary.converted_customers).label("converted_customers"),
                func.sum(AttributionSummary.attributed_revenue_fen).label("total_revenue"),
                func.sum(AttributionSummary.cost_fen).label("total_cost"),
                func.avg(AttributionSummary.roi).label("avg_roi"),
            )
            .where(
                and_(
                    AttributionSummary.tenant_id == tenant_id,
                    AttributionSummary.stat_date >= start_date,
                    AttributionSummary.stat_date <= today,
                )
            )
            .group_by(
                AttributionSummary.source_id,
                AttributionSummary.source_name,
                AttributionSummary.source_type,
            )
            .order_by(func.avg(AttributionSummary.roi).desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = result.all()

        return [
            {
                "rank": i + 1,
                "source_id": r.source_id,
                "source_name": r.source_name,
                "source_type": r.source_type,
                "total_touches": int(r.total_touches or 0),
                "unique_customers": int(r.unique_customers or 0),
                "converted_customers": int(r.converted_customers or 0),
                "conversion_rate": round(
                    int(r.converted_customers or 0) / int(r.unique_customers or 1), 4
                ),
                "attributed_revenue_fen": int(r.total_revenue or 0),
                "attributed_revenue_yuan": round((r.total_revenue or 0) / 100, 2),
                "cost_fen": int(r.total_cost or 0),
                "cost_yuan": round((r.total_cost or 0) / 100, 2),
                "roi": round(r.avg_roi or 0.0, 4),
            }
            for i, r in enumerate(rows)
        ]
