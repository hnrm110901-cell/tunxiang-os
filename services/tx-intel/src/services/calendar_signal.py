"""节庆日历服务 — 节假日/纪念日/行业节点对增长策略的影响"""

from datetime import date, timedelta
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class CalendarSignalService:
    """节庆日历 → 旅程触发增强

    识别三类时间节点:
    1. 法定节假日（春节/国庆/中秋/端午...）
    2. 消费节日（情人节/母亲节/父亲节/七夕/圣诞...）
    3. 餐饮行业节点（火锅季/烧烤季/小龙虾季/大闸蟹季...）
    """

    # 2026年关键节庆（可配置化）
    CALENDAR_2026: list[dict] = [
        # 法定节假日
        {"date": "2026-01-01", "name": "元旦", "type": "national", "impact": "medium", "days_before_push": 3},
        {"date": "2026-02-17", "name": "春节", "type": "national", "impact": "high", "days_before_push": 7},
        {"date": "2026-04-05", "name": "清明节", "type": "national", "impact": "low", "days_before_push": 2},
        {"date": "2026-05-01", "name": "劳动节", "type": "national", "impact": "medium", "days_before_push": 3},
        {"date": "2026-06-19", "name": "端午节", "type": "national", "impact": "medium", "days_before_push": 3},
        {"date": "2026-09-25", "name": "中秋节", "type": "national", "impact": "high", "days_before_push": 5},
        {"date": "2026-10-01", "name": "国庆节", "type": "national", "impact": "high", "days_before_push": 5},
        # 消费节日
        {
            "date": "2026-02-14",
            "name": "情人节",
            "type": "consumer",
            "impact": "high",
            "days_before_push": 5,
            "target_segment": "couple",
            "suggested_journey": "banquet_repurchase_v1",
        },
        {
            "date": "2026-05-10",
            "name": "母亲节",
            "type": "consumer",
            "impact": "high",
            "days_before_push": 7,
            "target_segment": "family_host",
            "suggested_journey": "banquet_repurchase_v1",
        },
        {
            "date": "2026-06-21",
            "name": "父亲节",
            "type": "consumer",
            "impact": "medium",
            "days_before_push": 5,
            "target_segment": "family_host",
            "suggested_journey": "banquet_repurchase_v1",
        },
        {
            "date": "2026-08-25",
            "name": "七夕",
            "type": "consumer",
            "impact": "high",
            "days_before_push": 5,
            "target_segment": "couple",
            "suggested_journey": "banquet_repurchase_v1",
        },
        {"date": "2026-12-25", "name": "圣诞节", "type": "consumer", "impact": "medium", "days_before_push": 5},
        # 餐饮行业节点
        {
            "date": "2026-05-01",
            "name": "小龙虾季开始",
            "type": "industry",
            "impact": "medium",
            "days_before_push": 7,
            "seasonal_dish": "小龙虾",
        },
        {
            "date": "2026-09-20",
            "name": "大闸蟹季开始",
            "type": "industry",
            "impact": "high",
            "days_before_push": 7,
            "seasonal_dish": "大闸蟹",
        },
        {
            "date": "2026-11-01",
            "name": "火锅季开始",
            "type": "industry",
            "impact": "high",
            "days_before_push": 5,
            "seasonal_dish": "火锅",
        },
        {
            "date": "2026-06-01",
            "name": "烧烤季开始",
            "type": "industry",
            "impact": "medium",
            "days_before_push": 5,
            "seasonal_dish": "烧烤",
        },
    ]

    def get_upcoming_events(self, days_ahead: int = 14) -> list:
        """获取未来N天内的节庆事件"""
        today = date.today()
        end = today + timedelta(days=days_ahead)

        events: list[dict] = []
        for evt in self.CALENDAR_2026:
            evt_date = date.fromisoformat(evt["date"])
            push_date = evt_date - timedelta(days=evt.get("days_before_push", 3))

            if push_date <= end and evt_date >= today:
                events.append(
                    {
                        **evt,
                        "push_start_date": str(push_date),
                        "days_until": (evt_date - today).days,
                        "should_push_now": push_date <= today,
                    }
                )

        return sorted(events, key=lambda e: e["date"])

    def get_growth_triggers(self) -> list:
        """获取当前应触发的增长动作"""
        upcoming = self.get_upcoming_events(days_ahead=7)
        triggers: list[dict] = []

        for evt in upcoming:
            if not evt.get("should_push_now"):
                continue

            trigger: dict = {
                "event_name": evt["name"],
                "event_date": evt["date"],
                "event_type": evt["type"],
                "impact": evt["impact"],
                "days_until": evt["days_until"],
            }

            if evt["type"] == "consumer" and evt.get("target_segment"):
                trigger["action"] = "trigger_segment_journey"
                trigger["target_segment"] = evt["target_segment"]
                trigger["suggested_journey"] = evt.get("suggested_journey", "banquet_repurchase_v1")
                trigger["description"] = (
                    f"{evt['name']}即将到来，建议对{evt['target_segment']}客户群发起{evt['name']}主题旅程"
                )
            elif evt["type"] == "industry" and evt.get("seasonal_dish"):
                trigger["action"] = "seasonal_promotion"
                trigger["seasonal_dish"] = evt["seasonal_dish"]
                trigger["description"] = f"{evt['name']}，建议推出{evt['seasonal_dish']}相关主题触达"
            elif evt["type"] == "national":
                trigger["action"] = "holiday_reactivation"
                trigger["description"] = f"{evt['name']}假期临近，建议对沉默客发起召回旅程"
                trigger["suggested_journey"] = "reactivation_loss_aversion_v2"

            triggers.append(trigger)

        return triggers

    def get_event_by_date(self, target_date: str) -> Optional[dict]:
        """查询特定日期的节庆事件"""
        for evt in self.CALENDAR_2026:
            if evt["date"] == target_date:
                return evt
        return None
