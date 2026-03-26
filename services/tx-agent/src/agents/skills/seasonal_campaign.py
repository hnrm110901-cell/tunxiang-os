"""节气活动 Agent — P1 | 云端

节气日历管理、节气活动策划、节气菜品推荐、活动效果预测、活动执行跟踪、历史活动复盘。
"""
import uuid
from typing import Any
from ..base import SkillAgent, AgentResult


# 24节气+重要节日日历
SEASONAL_CALENDAR = {
    "spring_festival": {"name": "春节", "month": 1, "type": "festival", "heat": 10},
    "lantern": {"name": "元宵节", "month": 2, "type": "festival", "heat": 7},
    "valentines": {"name": "情人节", "month": 2, "type": "festival", "heat": 8},
    "womens_day": {"name": "三八妇女节", "month": 3, "type": "festival", "heat": 6},
    "qingming": {"name": "清明", "month": 4, "type": "solar_term", "heat": 5},
    "labor_day": {"name": "五一劳动节", "month": 5, "type": "festival", "heat": 9},
    "dragon_boat": {"name": "端午节", "month": 6, "type": "festival", "heat": 8},
    "qixi": {"name": "七夕", "month": 8, "type": "festival", "heat": 8},
    "mid_autumn": {"name": "中秋节", "month": 9, "type": "festival", "heat": 9},
    "national_day": {"name": "国庆节", "month": 10, "type": "festival", "heat": 10},
    "double_eleven": {"name": "双十一", "month": 11, "type": "marketing", "heat": 7},
    "winter_solstice": {"name": "冬至", "month": 12, "type": "solar_term", "heat": 6},
    "laba": {"name": "腊八", "month": 1, "type": "festival", "heat": 5},
    "xiaoman": {"name": "小满", "month": 5, "type": "solar_term", "heat": 4},
    "dashu": {"name": "大暑", "month": 7, "type": "solar_term", "heat": 5},
    "liqiu": {"name": "立秋", "month": 8, "type": "solar_term", "heat": 5},
}

# 节气菜品关联
SEASONAL_DISHES = {
    "spring_festival": ["年夜饭套餐", "饺子", "鱼", "年糕"],
    "lantern": ["汤圆", "元宵"],
    "dragon_boat": ["粽子", "咸鸭蛋", "雄黄酒"],
    "mid_autumn": ["月饼", "大闸蟹", "桂花糕"],
    "winter_solstice": ["羊肉汤", "饺子", "汤圆"],
    "laba": ["腊八粥", "腊肉"],
    "dashu": ["绿豆汤", "凉面", "酸梅汤"],
    "liqiu": ["贴秋膘套餐", "炖肉", "涮羊肉"],
}


class SeasonalCampaignAgent(SkillAgent):
    agent_id = "seasonal_campaign"
    agent_name = "节气活动"
    description = "节气日历管理、活动策划、节气菜品推荐、效果预测、执行跟踪、历史复盘"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "get_seasonal_calendar",
            "plan_seasonal_campaign",
            "recommend_seasonal_dishes",
            "predict_campaign_effect",
            "track_campaign_execution",
            "review_past_campaigns",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "get_seasonal_calendar": self._get_calendar,
            "plan_seasonal_campaign": self._plan_campaign,
            "recommend_seasonal_dishes": self._recommend_dishes,
            "predict_campaign_effect": self._predict_effect,
            "track_campaign_execution": self._track_execution,
            "review_past_campaigns": self._review_past,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _get_calendar(self, params: dict) -> AgentResult:
        """节气日历管理"""
        month = params.get("month", 0)
        upcoming_days = params.get("upcoming_days", 30)

        events = []
        for key, info in SEASONAL_CALENDAR.items():
            if month and info["month"] != month:
                continue
            events.append({
                "event_id": key,
                "name": info["name"],
                "month": info["month"],
                "type": info["type"],
                "heat_score": info["heat"],
                "recommended_prep_days": 14 if info["heat"] >= 8 else 7,
            })

        events.sort(key=lambda x: (x["month"], -x["heat_score"]))
        return AgentResult(
            success=True, action="get_seasonal_calendar",
            data={"events": events, "total": len(events)},
            reasoning=f"返回 {len(events)} 个节气/节日活动",
            confidence=0.95,
        )

    async def _plan_campaign(self, params: dict) -> AgentResult:
        """节气活动策划"""
        event_id = params.get("event_id", "")
        budget_fen = params.get("budget_fen", 500000)
        target_revenue_increase_pct = params.get("target_revenue_increase_pct", 20)

        event_info = SEASONAL_CALENDAR.get(event_id, {"name": event_id, "heat": 5})
        campaign_id = str(uuid.uuid4())[:8]

        # 根据热度调整策略
        heat = event_info.get("heat", 5)
        if heat >= 8:
            strategy = "全渠道大促"
            channels = ["门店", "微信", "抖音", "美团", "大众点评"]
            discount_rate = 0.15
        elif heat >= 6:
            strategy = "主题营销"
            channels = ["门店", "微信", "美团"]
            discount_rate = 0.1
        else:
            strategy = "轻量推广"
            channels = ["门店", "微信"]
            discount_rate = 0.05

        return AgentResult(
            success=True, action="plan_seasonal_campaign",
            data={
                "campaign_id": campaign_id,
                "event_id": event_id,
                "event_name": event_info.get("name", event_id),
                "strategy": strategy,
                "channels": channels,
                "budget_yuan": round(budget_fen / 100, 2),
                "discount_rate": discount_rate,
                "target_revenue_increase_pct": target_revenue_increase_pct,
                "prep_checklist": [
                    "确定活动菜品和套餐",
                    "设计活动海报和物料",
                    "配置线上活动页面",
                    "通知门店准备食材",
                    "培训服务员活动话术",
                ],
                "timeline_days": 14 if heat >= 8 else 7,
            },
            reasoning=f"为「{event_info.get('name', event_id)}」策划{strategy}，预算 ¥{budget_fen / 100:.0f}",
            confidence=0.8,
        )

    async def _recommend_dishes(self, params: dict) -> AgentResult:
        """节气菜品推荐"""
        event_id = params.get("event_id", "")
        existing_menu = params.get("existing_menu", [])

        seasonal_items = SEASONAL_DISHES.get(event_id, [])
        event_name = SEASONAL_CALENDAR.get(event_id, {}).get("name", event_id)

        recommendations = []
        for dish in seasonal_items:
            in_menu = dish in existing_menu
            recommendations.append({
                "dish_name": dish,
                "already_in_menu": in_menu,
                "action": "主推" if in_menu else "新增",
                "expected_order_increase_pct": 30 if in_menu else 50,
            })

        # 补充套餐建议
        if len(seasonal_items) >= 3:
            recommendations.append({
                "dish_name": f"{event_name}限定套餐",
                "already_in_menu": False,
                "action": "新增套餐",
                "expected_order_increase_pct": 40,
                "includes": seasonal_items[:4],
            })

        return AgentResult(
            success=True, action="recommend_seasonal_dishes",
            data={
                "event_id": event_id,
                "event_name": event_name,
                "recommendations": recommendations,
                "new_items_needed": sum(1 for r in recommendations if not r.get("already_in_menu")),
            },
            reasoning=f"为「{event_name}」推荐 {len(recommendations)} 款节气菜品/套餐",
            confidence=0.8,
        )

    async def _predict_effect(self, params: dict) -> AgentResult:
        """活动效果预测"""
        event_id = params.get("event_id", "")
        budget_fen = params.get("budget_fen", 500000)
        historical_lift_pct = params.get("historical_lift_pct", 0)
        base_daily_revenue_fen = params.get("base_daily_revenue_fen", 5000000)
        campaign_days = params.get("campaign_days", 3)

        heat = SEASONAL_CALENDAR.get(event_id, {}).get("heat", 5)

        # 预测模型：基于热度+历史+预算
        predicted_lift = heat * 2.5  # 热度贡献
        if historical_lift_pct > 0:
            predicted_lift = predicted_lift * 0.5 + historical_lift_pct * 0.5  # 历史加权
        budget_boost = min(10, budget_fen / 100000)  # 预算加成
        predicted_lift += budget_boost

        incremental_revenue_fen = int(base_daily_revenue_fen * campaign_days * predicted_lift / 100)
        roi = round(incremental_revenue_fen / max(1, budget_fen), 2)

        return AgentResult(
            success=True, action="predict_campaign_effect",
            data={
                "event_id": event_id,
                "predicted_lift_pct": round(predicted_lift, 1),
                "incremental_revenue_yuan": round(incremental_revenue_fen / 100, 2),
                "campaign_days": campaign_days,
                "predicted_roi": roi,
                "confidence_interval": {
                    "low_pct": round(predicted_lift * 0.7, 1),
                    "high_pct": round(predicted_lift * 1.3, 1),
                },
            },
            reasoning=f"预测营收提升 {predicted_lift:.1f}%，增量 ¥{incremental_revenue_fen / 100:.0f}，ROI {roi}",
            confidence=0.65,
        )

    async def _track_execution(self, params: dict) -> AgentResult:
        """活动执行跟踪"""
        campaign_id = params.get("campaign_id", "")
        tasks = params.get("tasks", [])

        completed = sum(1 for t in tasks if t.get("status") == "done")
        in_progress = sum(1 for t in tasks if t.get("status") == "in_progress")
        pending = sum(1 for t in tasks if t.get("status") == "pending")
        total = len(tasks)
        progress_pct = round(completed / max(1, total) * 100, 1)

        blockers = [t for t in tasks if t.get("is_blocked")]

        return AgentResult(
            success=True, action="track_campaign_execution",
            data={
                "campaign_id": campaign_id,
                "total_tasks": total,
                "completed": completed,
                "in_progress": in_progress,
                "pending": pending,
                "progress_pct": progress_pct,
                "blockers": [{"task": b.get("name"), "reason": b.get("block_reason")} for b in blockers],
                "on_track": progress_pct >= 60 and not blockers,
            },
            reasoning=f"活动执行进度 {progress_pct}%，{len(blockers)} 个阻塞项",
            confidence=0.9,
        )

    async def _review_past(self, params: dict) -> AgentResult:
        """历史活动复盘"""
        campaigns = params.get("campaigns", [])

        reviews = []
        for c in campaigns:
            actual_lift = c.get("actual_lift_pct", 0)
            predicted_lift = c.get("predicted_lift_pct", 0)
            accuracy = round(100 - abs(actual_lift - predicted_lift), 1)

            reviews.append({
                "campaign_id": c.get("campaign_id"),
                "event_name": c.get("event_name"),
                "actual_lift_pct": actual_lift,
                "predicted_lift_pct": predicted_lift,
                "prediction_accuracy": accuracy,
                "revenue_yuan": round(c.get("revenue_fen", 0) / 100, 2),
                "roi": c.get("roi", 0),
                "rating": "优秀" if actual_lift >= predicted_lift else "达标" if actual_lift >= predicted_lift * 0.8 else "未达标",
            })

        avg_accuracy = round(sum(r["prediction_accuracy"] for r in reviews) / max(1, len(reviews)), 1)

        return AgentResult(
            success=True, action="review_past_campaigns",
            data={
                "campaigns": reviews,
                "total": len(reviews),
                "avg_prediction_accuracy": avg_accuracy,
                "best_campaign": max(reviews, key=lambda x: x["roi"])["event_name"] if reviews else "无",
            },
            reasoning=f"复盘 {len(reviews)} 场活动，预测准确度 {avg_accuracy}%",
            confidence=0.85,
        )
