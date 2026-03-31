"""增长归因 Agent — 增长型 | 云端

营收增长归因分析、营销活动ROI评估、增长驱动因素识别、增长轨迹预测。
通过 ModelRouter (MODERATE) 调用 LLM 生成增长洞察。

v088 新增：
  - get_customer_touch_history — 客户触达历史（近 N 天）
  - get_campaign_roi           — 活动 ROI（从 campaign_summaries 读取）
  - get_attribution_report     — 租户级归因汇总报告
"""
import statistics
from typing import Any

import structlog

from ..base import SkillAgent, AgentResult

try:
    from services.tunxiang_api.src.shared.core.model_router import model_router
except ImportError:
    model_router = None  # 独立测试时无跨服务依赖

logger = structlog.get_logger()

# 增长来源分类
GROWTH_SOURCES = {
    "new_customer": {"label": "新客贡献", "weight": 0.3},
    "repeat_purchase": {"label": "复购提升", "weight": 0.3},
    "ticket_increase": {"label": "客单提升", "weight": 0.2},
    "channel_expansion": {"label": "渠道拓展", "weight": 0.1},
    "price_adjustment": {"label": "价格调整", "weight": 0.1},
}

# ROI评价标准
ROI_GRADES = {
    "excellent": {"min_roi": 5.0, "label": "优秀"},
    "good": {"min_roi": 2.0, "label": "良好"},
    "fair": {"min_roi": 1.0, "label": "一般"},
    "poor": {"min_roi": 0.0, "label": "较差"},
    "negative": {"min_roi": -999, "label": "亏损"},
}


class GrowthAttributionAgent(SkillAgent):
    agent_id = "growth_attribution"
    agent_name = "增长归因"
    description = "营收增长归因、营销ROI评估、增长驱动因素识别、增长轨迹预测"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "attribute",
            "evaluate_roi",
            "identify_drivers",
            "predict",
            "get_customer_touch_history",
            "get_campaign_roi",
            "get_attribution_report",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "attribute": self._attribute_revenue_growth,
            "evaluate_roi": self._evaluate_campaign_roi,
            "identify_drivers": self._identify_growth_drivers,
            "predict": self._predict_growth_trajectory,
            "get_customer_touch_history": self._get_customer_touch_history,
            "get_campaign_roi": self._get_campaign_roi,
            "get_attribution_report": self._get_attribution_report,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _attribute_revenue_growth(self, params: dict) -> AgentResult:
        """营收增长归因（新客/复购/客单提升/渠道）"""
        store_id = params.get("store_id", self.store_id or "")
        period = params.get("period", "month")
        current_revenue_fen = params.get("current_revenue_fen", 0)
        previous_revenue_fen = params.get("previous_revenue_fen", 0)

        # 各维度数据
        new_customer_revenue_fen = params.get("new_customer_revenue_fen", 0)
        repeat_revenue_fen = params.get("repeat_revenue_fen", 0)
        current_avg_ticket_fen = params.get("current_avg_ticket_fen", 0)
        previous_avg_ticket_fen = params.get("previous_avg_ticket_fen", 0)
        current_customer_count = params.get("current_customer_count", 0)
        previous_customer_count = params.get("previous_customer_count", 0)
        channel_revenue = params.get("channel_revenue", {})
        previous_channel_revenue = params.get("previous_channel_revenue", {})

        # 总增长
        growth_fen = current_revenue_fen - previous_revenue_fen
        growth_rate = (
            round(growth_fen / max(1, previous_revenue_fen), 4)
            if previous_revenue_fen
            else 0
        )

        # 归因拆解
        attributions = {}

        # 新客贡献
        new_customer_contribution = new_customer_revenue_fen
        attributions["new_customer"] = {
            "label": "新客贡献",
            "revenue_fen": new_customer_contribution,
            "revenue_yuan": round(new_customer_contribution / 100, 2),
            "share_pct": round(
                new_customer_contribution / max(1, abs(growth_fen)) * 100, 1
            )
            if growth_fen != 0
            else 0,
        }

        # 复购贡献
        repeat_contribution = repeat_revenue_fen - max(
            0, previous_revenue_fen - new_customer_revenue_fen
        )
        repeat_contribution = max(0, repeat_contribution)
        attributions["repeat_purchase"] = {
            "label": "复购提升",
            "revenue_fen": repeat_contribution,
            "revenue_yuan": round(repeat_contribution / 100, 2),
            "share_pct": round(
                repeat_contribution / max(1, abs(growth_fen)) * 100, 1
            )
            if growth_fen != 0
            else 0,
        }

        # 客单提升
        ticket_diff = current_avg_ticket_fen - previous_avg_ticket_fen
        ticket_contribution_fen = ticket_diff * current_customer_count
        attributions["ticket_increase"] = {
            "label": "客单提升",
            "avg_ticket_change_fen": ticket_diff,
            "revenue_fen": ticket_contribution_fen,
            "revenue_yuan": round(ticket_contribution_fen / 100, 2),
            "share_pct": round(
                ticket_contribution_fen / max(1, abs(growth_fen)) * 100, 1
            )
            if growth_fen != 0
            else 0,
        }

        # 渠道增长
        channel_growth = {}
        channel_total_growth_fen = 0
        for ch, rev in channel_revenue.items():
            prev = previous_channel_revenue.get(ch, 0)
            ch_growth = rev - prev
            channel_growth[ch] = {
                "current_fen": rev,
                "previous_fen": prev,
                "growth_fen": ch_growth,
            }
            if ch_growth > 0:
                channel_total_growth_fen += ch_growth

        attributions["channel_expansion"] = {
            "label": "渠道拓展",
            "channels": channel_growth,
            "revenue_fen": channel_total_growth_fen,
            "revenue_yuan": round(channel_total_growth_fen / 100, 2),
        }

        # 主要增长来源
        sorted_sources = sorted(
            [
                (k, v.get("revenue_fen", 0))
                for k, v in attributions.items()
                if isinstance(v.get("revenue_fen"), (int, float))
            ],
            key=lambda x: x[1],
            reverse=True,
        )
        primary_source = sorted_sources[0][0] if sorted_sources else "unknown"

        return AgentResult(
            success=True,
            action="attribute",
            data={
                "store_id": store_id,
                "period": period,
                "current_revenue_yuan": round(current_revenue_fen / 100, 2),
                "previous_revenue_yuan": round(previous_revenue_fen / 100, 2),
                "growth_yuan": round(growth_fen / 100, 2),
                "growth_rate": growth_rate,
                "growth_rate_pct": round(growth_rate * 100, 1),
                "attributions": attributions,
                "primary_source": primary_source,
                "primary_source_label": GROWTH_SOURCES.get(primary_source, {}).get(
                    "label", primary_source
                ),
            },
            reasoning=(
                f"营收{'增长' if growth_fen >= 0 else '下降'} "
                f"{abs(growth_fen) / 100:.0f} 元（{growth_rate:.1%}），"
                f"主要来源: {GROWTH_SOURCES.get(primary_source, {}).get('label', primary_source)}"
            ),
            confidence=0.8,
        )

    async def _evaluate_campaign_roi(self, params: dict) -> AgentResult:
        """营销活动ROI评估"""
        campaign_id = params.get("campaign_id", "")
        campaign_name = params.get("campaign_name", "")
        campaign_cost_fen = params.get("campaign_cost_fen", 0)
        incremental_revenue_fen = params.get("incremental_revenue_fen", 0)
        new_customers = params.get("new_customers_acquired", 0)
        coupons_issued = params.get("coupons_issued", 0)
        coupons_redeemed = params.get("coupons_redeemed", 0)
        reach_count = params.get("reach_count", 0)
        order_count = params.get("order_count", 0)

        # 使用 ModelRouter (MODERATE)
        model = model_router.get_model("growth_analysis") if model_router else "claude-sonnet-4-6"

        # ROI计算
        if campaign_cost_fen > 0:
            roi = round(
                (incremental_revenue_fen - campaign_cost_fen) / campaign_cost_fen, 2
            )
        else:
            roi = 0.0

        # ROI评级
        grade = "negative"
        for g, info in ROI_GRADES.items():
            if roi >= info["min_roi"]:
                grade = g
                break

        # 转化漏斗
        redemption_rate = round(
            coupons_redeemed / max(1, coupons_issued) * 100, 1
        )
        conversion_rate = round(order_count / max(1, reach_count) * 100, 1)

        # 获客成本
        cac_fen = (
            int(campaign_cost_fen / max(1, new_customers)) if new_customers else 0
        )

        return AgentResult(
            success=True,
            action="evaluate_roi",
            data={
                "campaign_id": campaign_id,
                "campaign_name": campaign_name,
                "campaign_cost_yuan": round(campaign_cost_fen / 100, 2),
                "incremental_revenue_yuan": round(incremental_revenue_fen / 100, 2),
                "roi": roi,
                "roi_grade": grade,
                "roi_grade_label": ROI_GRADES[grade]["label"],
                "new_customers_acquired": new_customers,
                "cac_yuan": round(cac_fen / 100, 2),
                "redemption_rate_pct": redemption_rate,
                "conversion_rate_pct": conversion_rate,
                "funnel": {
                    "reach": reach_count,
                    "coupons_issued": coupons_issued,
                    "coupons_redeemed": coupons_redeemed,
                    "orders": order_count,
                    "new_customers": new_customers,
                },
            },
            reasoning=(
                f"活动 {campaign_name}: ROI {roi:.1f}（{ROI_GRADES[grade]['label']}），"
                f"新增 {new_customers} 客，转化率 {conversion_rate}%"
            ),
            confidence=0.85,
        )

    async def _identify_growth_drivers(self, params: dict) -> AgentResult:
        """增长驱动因素识别"""
        tenant_id = params.get("tenant_id", self.tenant_id)
        period = params.get("period", "month")
        stores_data = params.get("stores_data", [])

        drivers = []
        total_growth_fen = 0
        growing_stores = 0
        declining_stores = 0

        for store in stores_data:
            store_id = store.get("store_id", "")
            growth_fen = store.get("growth_fen", 0)
            total_growth_fen += growth_fen

            if growth_fen > 0:
                growing_stores += 1
            elif growth_fen < 0:
                declining_stores += 1

            # 识别该门店的增长/下降驱动因素
            factors = []
            if store.get("new_customer_growth_pct", 0) > 10:
                factors.append({
                    "factor": "new_customer",
                    "label": "新客增长",
                    "impact_pct": store.get("new_customer_growth_pct", 0),
                })
            if store.get("repeat_rate_change_pct", 0) > 5:
                factors.append({
                    "factor": "repeat_rate",
                    "label": "复购率提升",
                    "impact_pct": store.get("repeat_rate_change_pct", 0),
                })
            if store.get("avg_ticket_change_pct", 0) > 5:
                factors.append({
                    "factor": "ticket_size",
                    "label": "客单价提升",
                    "impact_pct": store.get("avg_ticket_change_pct", 0),
                })
            if store.get("campaign_contribution_pct", 0) > 10:
                factors.append({
                    "factor": "campaign",
                    "label": "营销活动",
                    "impact_pct": store.get("campaign_contribution_pct", 0),
                })
            if store.get("seasonal_impact_pct", 0) > 10:
                factors.append({
                    "factor": "seasonal",
                    "label": "季节效应",
                    "impact_pct": store.get("seasonal_impact_pct", 0),
                })

            if factors:
                drivers.append({
                    "store_id": store_id,
                    "store_name": store.get("store_name", ""),
                    "growth_fen": growth_fen,
                    "growth_yuan": round(growth_fen / 100, 2),
                    "drivers": sorted(
                        factors, key=lambda x: x["impact_pct"], reverse=True
                    ),
                    "primary_driver": max(factors, key=lambda x: x["impact_pct"])[
                        "label"
                    ]
                    if factors
                    else "未知",
                })

        # 全局驱动因素统计
        driver_freq: dict[str, int] = {}
        for d in drivers:
            for f in d["drivers"]:
                driver_freq[f["label"]] = driver_freq.get(f["label"], 0) + 1

        top_drivers = sorted(driver_freq.items(), key=lambda x: x[1], reverse=True)

        return AgentResult(
            success=True,
            action="identify_drivers",
            data={
                "tenant_id": tenant_id,
                "period": period,
                "total_growth_yuan": round(total_growth_fen / 100, 2),
                "growing_stores": growing_stores,
                "declining_stores": declining_stores,
                "store_drivers": drivers,
                "top_drivers": [
                    {"driver": d[0], "store_count": d[1]} for d in top_drivers[:5]
                ],
            },
            reasoning=(
                f"分析 {len(stores_data)} 家门店：增长 {growing_stores} 家、"
                f"下降 {declining_stores} 家，"
                f"主要驱动: {top_drivers[0][0] if top_drivers else '无'}"
            ),
            confidence=0.75,
        )

    async def _predict_growth_trajectory(self, params: dict) -> AgentResult:
        """增长轨迹预测"""
        store_id = params.get("store_id", self.store_id or "")
        historical_revenue = params.get("historical_revenue_fen", [])
        months = params.get("predict_months", 3)

        if len(historical_revenue) < 3:
            return AgentResult(
                success=False,
                action="predict",
                error="至少需要3个月历史数据",
            )

        # 简易线性趋势预测
        n = len(historical_revenue)
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(historical_revenue)

        numerator = sum(
            (i - x_mean) * (y - y_mean) for i, y in enumerate(historical_revenue)
        )
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        slope = numerator / max(1, denominator)
        intercept = y_mean - slope * x_mean

        # 预测未来月份
        predictions = []
        for m in range(1, months + 1):
            predicted = int(slope * (n - 1 + m) + intercept)
            predicted = max(0, predicted)  # 收入不能为负
            predictions.append({
                "month_offset": m,
                "predicted_revenue_fen": predicted,
                "predicted_revenue_yuan": round(predicted / 100, 2),
            })

        # 增长趋势判断
        if slope > 0:
            trend = "growing"
            trend_label = "增长"
        elif slope < 0:
            trend = "declining"
            trend_label = "下降"
        else:
            trend = "flat"
            trend_label = "平稳"

        monthly_growth_rate = round(slope / max(1, y_mean), 4)

        # 置信度基于数据波动性
        if n >= 6:
            residuals = [
                abs(y - (slope * i + intercept))
                for i, y in enumerate(historical_revenue)
            ]
            avg_residual = statistics.mean(residuals)
            fit_quality = max(0.3, 1.0 - avg_residual / max(1, y_mean))
        else:
            fit_quality = 0.5

        return AgentResult(
            success=True,
            action="predict",
            data={
                "store_id": store_id,
                "historical_months": n,
                "trend": trend,
                "trend_label": trend_label,
                "monthly_growth_rate": monthly_growth_rate,
                "monthly_growth_rate_pct": round(monthly_growth_rate * 100, 1),
                "predictions": predictions,
                "latest_revenue_yuan": round(historical_revenue[-1] / 100, 2),
                "avg_revenue_yuan": round(y_mean / 100, 2),
            },
            reasoning=(
                f"门店营收趋势: {trend_label}，"
                f"月均增长率 {monthly_growth_rate:.1%}，"
                f"预测未来 {months} 个月营收走势"
            ),
            confidence=round(fit_quality, 2),
        )

    # ------------------------------------------------------------------
    # v088 新增：触达归因链路查询 Actions
    # ------------------------------------------------------------------

    async def _get_customer_touch_history(self, params: dict) -> AgentResult:
        """查询客户最近 N 天的触达历史（从 touch_events 表读取）。

        params:
            customer_id (str): 客户 UUID
            tenant_id   (str): 租户 UUID
            days        (int): 查最近多少天，默认 30
            touches     (list[dict]): 触达记录（由调用方从 tx-growth 预查后传入）
        """
        customer_id = params.get("customer_id", "")
        tenant_id = params.get("tenant_id", self.tenant_id or "")
        days = int(params.get("days", 30))

        # 触达记录由调用方查询后通过 params 传入，Agent 负责分析层
        touches: list[dict] = params.get("touches", [])

        if not touches:
            return AgentResult(
                success=True,
                action="get_customer_touch_history",
                data={
                    "customer_id": customer_id,
                    "days": days,
                    "total_touches": 0,
                    "touches": [],
                    "channels": {},
                    "last_touch": None,
                },
                reasoning=f"客户 {customer_id} 近 {days} 天无触达记录",
                confidence=1.0,
            )

        # 渠道分布统计
        channel_counts: dict[str, int] = {}
        for t in touches:
            ch = t.get("channel", "unknown")
            channel_counts[ch] = channel_counts.get(ch, 0) + 1

        # 最近一次触达
        sorted_touches = sorted(touches, key=lambda x: x.get("sent_at", ""), reverse=True)
        last_touch = sorted_touches[0] if sorted_touches else None

        # 点击率
        clicked = sum(1 for t in touches if t.get("clicked_at"))
        click_rate = round(clicked / max(1, len(touches)), 4)

        return AgentResult(
            success=True,
            action="get_customer_touch_history",
            data={
                "customer_id": customer_id,
                "tenant_id": tenant_id,
                "days": days,
                "total_touches": len(touches),
                "clicked_touches": clicked,
                "click_rate": click_rate,
                "click_rate_pct": round(click_rate * 100, 1),
                "channels": channel_counts,
                "last_touch": last_touch,
                "touches": sorted_touches[:20],  # 最多返回最近20条
            },
            reasoning=(
                f"客户 {customer_id} 近 {days} 天共触达 {len(touches)} 次，"
                f"点击率 {click_rate:.1%}，"
                f"主要渠道: {max(channel_counts, key=channel_counts.get) if channel_counts else '无'}"
            ),
            confidence=0.95,
        )

    async def _get_campaign_roi(self, params: dict) -> AgentResult:
        """从 campaign_summaries 读取活动 ROI 数据，结合 LLM 生成分析报告。

        params:
            campaign_id   (str):  活动 UUID
            campaign_name (str):  活动名称（展示用）
            summary       (dict): campaign_summaries 行数据（由调用方预查后传入）
        """
        campaign_id = params.get("campaign_id", "")
        campaign_name = params.get("campaign_name", "")
        summary: dict = params.get("summary", {})

        if not summary:
            return AgentResult(
                success=False,
                action="get_campaign_roi",
                error=f"活动 {campaign_id} 暂无汇总数据，请稍后重试或触发手动聚合",
            )

        total_touches = summary.get("total_touches", 0)
        delivered = summary.get("delivered_count", 0)
        clicked = summary.get("clicked_count", 0)
        reservations = summary.get("reservations_attributed", 0)
        orders = summary.get("orders_attributed", 0)
        revenue = summary.get("revenue_attributed", 0.0)
        cac = summary.get("cac", 0.0)
        roi = summary.get("roi", 0.0)

        # ROI 评级
        if roi >= 5.0:
            roi_grade = "优秀"
        elif roi >= 2.0:
            roi_grade = "良好"
        elif roi >= 1.0:
            roi_grade = "一般"
        elif roi >= 0.0:
            roi_grade = "较差"
        else:
            roi_grade = "亏损"

        click_rate = round(clicked / max(1, delivered), 4)
        conversion_rate = round((reservations + orders) / max(1, total_touches), 4)

        return AgentResult(
            success=True,
            action="get_campaign_roi",
            data={
                "campaign_id": campaign_id,
                "campaign_name": campaign_name,
                "period": {
                    "start": summary.get("period_start", ""),
                    "end": summary.get("period_end", ""),
                },
                "funnel": {
                    "total_touches": total_touches,
                    "delivered": delivered,
                    "clicked": clicked,
                    "reservations": reservations,
                    "orders": orders,
                },
                "metrics": {
                    "click_rate": click_rate,
                    "click_rate_pct": round(click_rate * 100, 1),
                    "conversion_rate": conversion_rate,
                    "conversion_rate_pct": round(conversion_rate * 100, 1),
                    "revenue_attributed": revenue,
                    "cac": cac,
                    "roi": roi,
                    "roi_grade": roi_grade,
                },
                "top_segments": summary.get("top_segments", []),
            },
            reasoning=(
                f"活动《{campaign_name}》ROI {roi:.1f}（{roi_grade}），"
                f"触达 {total_touches} 人，转化率 {conversion_rate:.1%}，"
                f"归因收入 {revenue:.0f} 元"
            ),
            confidence=0.9,
        )

    async def _get_attribution_report(self, params: dict) -> AgentResult:
        """生成租户级归因汇总报告（多活动对比 + 渠道效果 + 人群效果）。

        params:
            tenant_id        (str):        租户 UUID
            period_start     (str):        开始日期 YYYY-MM-DD
            period_end       (str):        结束日期 YYYY-MM-DD
            campaign_summaries (list[dict]): 各活动汇总（由调用方预查后传入）
            channel_perf     (list[dict]): 渠道效果（由调用方预查后传入）
            segment_perf     (list[dict]): 人群效果（由调用方预查后传入）
        """
        tenant_id = params.get("tenant_id", self.tenant_id or "")
        period_start = params.get("period_start", "")
        period_end = params.get("period_end", "")

        campaigns: list[dict] = params.get("campaign_summaries", [])
        channel_perf: list[dict] = params.get("channel_perf", [])
        segment_perf: list[dict] = params.get("segment_perf", [])

        # 全局汇总
        total_revenue = sum(c.get("revenue_attributed", 0) for c in campaigns)
        total_touches = sum(c.get("total_touches", 0) for c in campaigns)
        total_orders = sum(c.get("orders_attributed", 0) for c in campaigns)
        total_reservations = sum(c.get("reservations_attributed", 0) for c in campaigns)

        overall_conversion_rate = round(
            (total_orders + total_reservations) / max(1, total_touches), 4
        )

        # Top 活动（按归因收入）
        top_campaigns = sorted(
            campaigns, key=lambda x: x.get("revenue_attributed", 0), reverse=True
        )[:5]

        # 最佳渠道
        best_channel = (
            max(channel_perf, key=lambda x: x.get("conversion_rate", 0))
            if channel_perf
            else None
        )

        # 最佳人群
        best_segment = (
            max(segment_perf, key=lambda x: x.get("conversion_rate", 0))
            if segment_perf
            else None
        )

        return AgentResult(
            success=True,
            action="get_attribution_report",
            data={
                "tenant_id": tenant_id,
                "period": {"start": period_start, "end": period_end},
                "overall": {
                    "total_touches": total_touches,
                    "total_orders_attributed": total_orders,
                    "total_reservations_attributed": total_reservations,
                    "total_revenue_attributed": round(total_revenue, 2),
                    "overall_conversion_rate": overall_conversion_rate,
                    "overall_conversion_rate_pct": round(overall_conversion_rate * 100, 1),
                },
                "top_campaigns": [
                    {
                        "campaign_name": c.get("campaign_name", ""),
                        "revenue_attributed": c.get("revenue_attributed", 0),
                        "roi": c.get("roi", 0),
                        "orders": c.get("orders_attributed", 0),
                    }
                    for c in top_campaigns
                ],
                "channel_performance": channel_perf,
                "segment_performance": segment_perf,
                "best_channel": best_channel.get("channel") if best_channel else None,
                "best_segment": best_segment.get("segment_name") if best_segment else None,
            },
            reasoning=(
                f"租户 {tenant_id} {period_start}~{period_end} 归因报告：\n"
                f"总触达 {total_touches} 次，转化率 {overall_conversion_rate:.1%}，"
                f"归因收入 {total_revenue:.0f} 元；\n"
                f"最佳渠道 {best_channel.get('channel') if best_channel else '无'}，"
                f"最佳人群 {best_segment.get('segment_name') if best_segment else '无'}"
            ),
            confidence=0.85,
        )
