"""低峰引流 Agent — P1 | 云端

低峰时段识别、低峰专属优惠设计、预约引流、团购引流、低峰效果分析、客流预测调整。
"""
import uuid
from typing import Any

from ..base import AgentResult, SkillAgent

# 标准营业时段定义
TIME_SLOTS = {
    "morning": {"start": "09:00", "end": "11:00", "label": "早茶", "default_peak": False},
    "lunch_peak": {"start": "11:00", "end": "13:00", "label": "午餐高峰", "default_peak": True},
    "afternoon": {"start": "13:00", "end": "17:00", "label": "下午时段", "default_peak": False},
    "dinner_peak": {"start": "17:00", "end": "20:00", "label": "晚餐高峰", "default_peak": True},
    "late_night": {"start": "20:00", "end": "22:00", "label": "夜宵时段", "default_peak": False},
}

# 低峰引流策略模板
OFF_PEAK_STRATEGIES = {
    "early_bird": {"name": "早鸟优惠", "discount": 0.85, "desc": "早茶时段8.5折"},
    "afternoon_tea": {"name": "下午茶特惠", "discount": 0.7, "desc": "下午茶套餐7折"},
    "late_night_snack": {"name": "夜宵买一赠一", "discount": 0.5, "desc": "指定小食买一赠一"},
    "weekday_special": {"name": "工作日特价", "discount": 0.8, "desc": "周一至周四8折"},
    "happy_hour": {"name": "欢乐时光", "discount": 0.6, "desc": "14:00-17:00酒水6折"},
}


class OffPeakTrafficAgent(SkillAgent):
    agent_id = "off_peak_traffic"
    agent_name = "低峰引流"
    description = "低峰时段识别、专属优惠设计、预约引流、团购引流、效果分析、客流预测调整"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "identify_off_peak_slots",
            "design_off_peak_offer",
            "create_reservation_incentive",
            "create_group_deal",
            "analyze_off_peak_effect",
            "adjust_traffic_forecast",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "identify_off_peak_slots": self._identify_off_peak,
            "design_off_peak_offer": self._design_offer,
            "create_reservation_incentive": self._reservation_incentive,
            "create_group_deal": self._group_deal,
            "analyze_off_peak_effect": self._analyze_effect,
            "adjust_traffic_forecast": self._adjust_forecast,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _identify_off_peak(self, params: dict) -> AgentResult:
        """低峰时段识别"""
        hourly_traffic = params.get("hourly_traffic", {})
        threshold_pct = params.get("threshold_pct", 40)

        if not hourly_traffic:
            # 使用默认模型
            return AgentResult(
                success=True, action="identify_off_peak_slots",
                data={
                    "off_peak_slots": [
                        {"slot": "morning", "label": "早茶(09:00-11:00)", "utilization_pct": 25},
                        {"slot": "afternoon", "label": "下午(13:00-17:00)", "utilization_pct": 20},
                        {"slot": "late_night", "label": "夜宵(20:00-22:00)", "utilization_pct": 30},
                    ],
                    "peak_slots": [
                        {"slot": "lunch_peak", "label": "午餐(11:00-13:00)", "utilization_pct": 85},
                        {"slot": "dinner_peak", "label": "晚餐(17:00-20:00)", "utilization_pct": 90},
                    ],
                },
                reasoning="基于默认模型识别3个低峰时段",
                confidence=0.7,
            )

        max_traffic = max(hourly_traffic.values()) if hourly_traffic else 1
        off_peak = []
        peak = []

        for hour_str, count in sorted(hourly_traffic.items()):
            utilization = round(count / max_traffic * 100, 1)
            entry = {"hour": hour_str, "traffic": count, "utilization_pct": utilization}
            if utilization <= threshold_pct:
                off_peak.append(entry)
            else:
                peak.append(entry)

        return AgentResult(
            success=True, action="identify_off_peak_slots",
            data={
                "off_peak_hours": off_peak,
                "peak_hours": peak,
                "off_peak_count": len(off_peak),
                "threshold_pct": threshold_pct,
                "avg_off_peak_utilization": round(
                    sum(h["utilization_pct"] for h in off_peak) / max(1, len(off_peak)), 1),
            },
            reasoning=f"识别到 {len(off_peak)} 个低峰时段（利用率<{threshold_pct}%）",
            confidence=0.85,
        )

    async def _design_offer(self, params: dict) -> AgentResult:
        """低峰专属优惠设计"""
        slot = params.get("slot", "afternoon")
        current_utilization_pct = params.get("current_utilization_pct", 20)
        target_utilization_pct = params.get("target_utilization_pct", 50)
        avg_ticket_fen = params.get("avg_ticket_fen", 8000)

        # 根据差距选择力度
        gap = target_utilization_pct - current_utilization_pct
        if gap >= 40:
            strategy_key = "afternoon_tea" if slot == "afternoon" else "late_night_snack"
        elif gap >= 20:
            strategy_key = "weekday_special"
        else:
            strategy_key = "early_bird"

        strategy = OFF_PEAK_STRATEGIES.get(strategy_key, OFF_PEAK_STRATEGIES["weekday_special"])
        offer_id = str(uuid.uuid4())[:8]

        discounted_ticket = int(avg_ticket_fen * strategy["discount"])
        margin_impact_fen = avg_ticket_fen - discounted_ticket

        return AgentResult(
            success=True, action="design_off_peak_offer",
            data={
                "offer_id": offer_id,
                "slot": slot,
                "strategy": strategy_key,
                "strategy_name": strategy["name"],
                "discount_rate": strategy["discount"],
                "description": strategy["desc"],
                "discounted_ticket_yuan": round(discounted_ticket / 100, 2),
                "margin_impact_yuan": round(margin_impact_fen / 100, 2),
                "target_utilization_pct": target_utilization_pct,
                "channels": ["门店立牌", "美团", "大众点评", "小程序"],
            },
            reasoning=f"为{TIME_SLOTS.get(slot, {}).get('label', slot)}设计「{strategy['name']}」，"
                      f"折扣 {strategy['discount']:.0%}",
            confidence=0.8,
        )

    async def _reservation_incentive(self, params: dict) -> AgentResult:
        """预约引流"""
        slot = params.get("slot", "afternoon")
        incentive_fen = params.get("incentive_fen", 1000)
        max_reservations = params.get("max_reservations", 20)

        slot_info = TIME_SLOTS.get(slot, {"label": slot, "start": "", "end": ""})

        return AgentResult(
            success=True, action="create_reservation_incentive",
            data={
                "slot": slot,
                "slot_label": slot_info["label"],
                "time_range": f"{slot_info.get('start', '')}-{slot_info.get('end', '')}",
                "incentive_yuan": round(incentive_fen / 100, 2),
                "incentive_type": "预约减免",
                "max_reservations": max_reservations,
                "message_template": f"提前预约{slot_info['label']}时段，立减 ¥{incentive_fen / 100:.0f}",
                "push_channels": ["微信服务号", "小程序弹窗"],
            },
            reasoning=f"创建{slot_info['label']}预约激励: 减免 ¥{incentive_fen / 100:.0f}，限 {max_reservations} 位",
            confidence=0.85,
        )

    async def _group_deal(self, params: dict) -> AgentResult:
        """团购引流"""
        slot = params.get("slot", "afternoon")
        original_price_fen = params.get("original_price_fen", 20000)
        group_price_fen = params.get("group_price_fen", 12800)
        max_sold = params.get("max_sold", 200)
        platform = params.get("platform", "美团")

        discount_rate = round(group_price_fen / max(1, original_price_fen), 2)
        deal_id = str(uuid.uuid4())[:8]

        return AgentResult(
            success=True, action="create_group_deal",
            data={
                "deal_id": deal_id,
                "slot": slot,
                "platform": platform,
                "original_price_yuan": round(original_price_fen / 100, 2),
                "group_price_yuan": round(group_price_fen / 100, 2),
                "discount_rate": discount_rate,
                "max_sold": max_sold,
                "valid_time": TIME_SLOTS.get(slot, {}).get("label", slot),
                "estimated_conversion_rate": 0.15 if discount_rate <= 0.7 else 0.1,
            },
            reasoning=f"创建{platform}团购: ¥{group_price_fen / 100:.0f}（原价 ¥{original_price_fen / 100:.0f}，{discount_rate:.0%}折）",
            confidence=0.8,
        )

    async def _analyze_effect(self, params: dict) -> AgentResult:
        """低峰效果分析"""
        before_traffic = params.get("before_avg_traffic", 0)
        after_traffic = params.get("after_avg_traffic", 0)
        campaign_cost_fen = params.get("campaign_cost_fen", 0)
        incremental_revenue_fen = params.get("incremental_revenue_fen", 0)
        period_days = params.get("period_days", 7)

        traffic_lift = round((after_traffic - before_traffic) / max(1, before_traffic) * 100, 1)
        roi = round(incremental_revenue_fen / max(1, campaign_cost_fen), 2)
        daily_incremental = round(incremental_revenue_fen / max(1, period_days) / 100, 2)

        return AgentResult(
            success=True, action="analyze_off_peak_effect",
            data={
                "before_avg_traffic": before_traffic,
                "after_avg_traffic": after_traffic,
                "traffic_lift_pct": traffic_lift,
                "campaign_cost_yuan": round(campaign_cost_fen / 100, 2),
                "incremental_revenue_yuan": round(incremental_revenue_fen / 100, 2),
                "daily_incremental_yuan": daily_incremental,
                "roi": roi,
                "period_days": period_days,
                "verdict": "效果显著" if traffic_lift >= 30 else "有效" if traffic_lift >= 10 else "效果有限",
            },
            reasoning=f"低峰引流效果: 客流提升 {traffic_lift}%，ROI {roi}",
            confidence=0.85,
        )

    async def _adjust_forecast(self, params: dict) -> AgentResult:
        """客流预测调整"""
        base_forecast = params.get("base_forecast", {})
        active_campaigns = params.get("active_campaigns", [])
        weather = params.get("weather", "晴")
        is_holiday = params.get("is_holiday", False)

        adjusted = {}
        for hour, base_count in base_forecast.items():
            multiplier = 1.0
            # 天气影响
            if weather in ("暴雨", "大雪"):
                multiplier *= 0.6
            elif weather in ("小雨", "阴"):
                multiplier *= 0.85
            # 节假日影响
            if is_holiday:
                multiplier *= 1.4
            # 活动影响
            for camp in active_campaigns:
                if hour in camp.get("target_hours", []):
                    multiplier *= 1 + camp.get("expected_lift_pct", 0) / 100

            adjusted[hour] = round(base_count * multiplier)

        total_base = sum(base_forecast.values())
        total_adjusted = sum(adjusted.values())

        return AgentResult(
            success=True, action="adjust_traffic_forecast",
            data={
                "base_forecast": base_forecast,
                "adjusted_forecast": adjusted,
                "total_base": total_base,
                "total_adjusted": total_adjusted,
                "adjustment_pct": round((total_adjusted - total_base) / max(1, total_base) * 100, 1),
                "factors": {"weather": weather, "is_holiday": is_holiday,
                           "active_campaigns": len(active_campaigns)},
            },
            reasoning=f"客流预测调整: {total_base}→{total_adjusted}人次"
                      f"（天气:{weather}，节假日:{'是' if is_holiday else '否'}，活动:{len(active_campaigns)}个）",
            confidence=0.7,
        )
