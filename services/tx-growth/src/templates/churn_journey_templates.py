"""流失干预旅程预制模板 — 3档自动触发

根据churn_scores评分自动匹配旅程：
  - warm (40-59分): 温和微信提醒，不带折扣
  - urgent (60-79分): 优惠券+SMS双渠道触达
  - critical (80+分): 店长亲邀任务（企微1v1）

集成点：
  - journey_executor (tx-growth) — 已有tick-based执行引擎
  - dormant_recall agent (tx-agent) — P0技能扩展score_and_intervene
  - churn_interventions 表 (v307) — 记录每次干预
"""

from typing import Any

CHURN_JOURNEY_TEMPLATES: dict[str, dict[str, Any]] = {
    "warm": {
        "name": "温和关怀旅程",
        "risk_tier": "warm",
        "score_range": (40, 59),
        "description": "发送温和的关怀消息，不带折扣，提醒门店存在感",
        "steps": [
            {
                "step": 1,
                "action": "send_message",
                "channel": "wechat_subscribe",
                "delay_hours": 0,
                "content_template": "warm_care",
                "content_vars": {
                    "tone": "亲切温暖",
                    "include_offer": False,
                    "message_hint": "好久不见，想念您的光临！最近我们上了几道新菜，欢迎来尝鲜~",
                },
            },
            {
                "step": 2,
                "action": "wait_and_check",
                "delay_hours": 72,
                "check": "has_visited_since_trigger",
                "if_true": "complete",
                "if_false": "continue",
            },
            {
                "step": 3,
                "action": "send_message",
                "channel": "wecom_chat",
                "delay_hours": 0,
                "content_template": "warm_followup",
                "content_vars": {
                    "tone": "轻松随意",
                    "include_offer": False,
                    "message_hint": "这周末天气不错，来坐坐？给您留了个好位置~",
                },
            },
        ],
        "intervention_type": "warm_touch",
        "max_duration_days": 7,
        "success_metric": "visit_within_14_days",
    },
    "urgent": {
        "name": "紧急召回旅程",
        "risk_tier": "urgent",
        "score_range": (60, 79),
        "description": "优惠券+SMS双渠道触达，带限时折扣",
        "steps": [
            {
                "step": 1,
                "action": "create_offer",
                "offer_type": "coupon",
                "offer_detail": {
                    "discount_type": "cash",
                    "discount_fen": 2500,  # 满80减25
                    "min_order_fen": 8000,
                    "expiry_days": 7,
                    "name": "想念您·专属回归券",
                },
            },
            {
                "step": 2,
                "action": "send_message",
                "channel": "sms",
                "delay_hours": 0,
                "content_template": "urgent_recall_sms",
                "content_vars": {
                    "tone": "真诚挽留",
                    "include_offer": True,
                    "message_hint": "【{store_name}】好久不见！特别为您准备了满80减25专属券，7天有效，期待您的回归~",
                },
            },
            {
                "step": 3,
                "action": "send_message",
                "channel": "wecom_chat",
                "delay_hours": 2,
                "content_template": "urgent_recall_wecom",
                "content_vars": {
                    "tone": "导购亲切",
                    "include_offer": True,
                    "message_hint": "您好，我是{store_name}的{employee_name}，为您准备了一张专属回归券，这周来的话还能享受新菜试吃~",
                },
            },
            {
                "step": 4,
                "action": "wait_and_check",
                "delay_hours": 120,  # 5天
                "check": "has_visited_since_trigger",
                "if_true": "complete",
                "if_false": "escalate_to_critical",
            },
        ],
        "intervention_type": "urgent_offer",
        "max_duration_days": 7,
        "success_metric": "order_within_7_days",
    },
    "critical": {
        "name": "店长亲邀旅程",
        "risk_tier": "critical",
        "score_range": (80, 100),
        "description": "店长/经理亲自企微邀约，高价值定制方案",
        "steps": [
            {
                "step": 1,
                "action": "create_offer",
                "offer_type": "coupon",
                "offer_detail": {
                    "discount_type": "cash",
                    "discount_fen": 3000,  # 满60减30
                    "min_order_fen": 6000,
                    "expiry_days": 14,
                    "name": "VIP回归礼·店长特批",
                    "bonus": "赠送招牌甜品一份",
                },
            },
            {
                "step": 2,
                "action": "create_task",
                "task_type": "manager_invite",
                "assignee_role": "store_manager",
                "task_detail": {
                    "title": "高价值客户流失预警 - 请亲自邀约",
                    "description": "该客户流失评分{score}分（{risk_tier}），请在24小时内通过企微发送个性化邀请",
                    "deadline_hours": 24,
                    "talking_points": [
                        "提及客户常点的菜品",
                        "介绍最近的新菜/活动",
                        "送上VIP回归礼",
                        "询问是否有不满意的地方",
                    ],
                },
            },
            {
                "step": 3,
                "action": "wait_and_check",
                "delay_hours": 48,
                "check": "manager_task_completed",
                "if_true": "continue",
                "if_false": "send_reminder_to_manager",
            },
            {
                "step": 4,
                "action": "send_message",
                "channel": "sms",
                "delay_hours": 72,
                "content_template": "critical_final_sms",
                "content_vars": {
                    "tone": "诚恳",
                    "include_offer": True,
                    "message_hint": "【{store_name}】{customer_name}您好，店长特别为您准备了满60减30+招牌甜品，14天内有效，随时恭候~",
                },
            },
        ],
        "intervention_type": "manager_invite",
        "max_duration_days": 14,
        "success_metric": "order_within_14_days",
    },
}


def get_journey_for_tier(risk_tier: str) -> dict[str, Any] | None:
    """根据风险等级获取对应的旅程模板"""
    return CHURN_JOURNEY_TEMPLATES.get(risk_tier)


def get_all_templates() -> list[dict[str, Any]]:
    """获取所有旅程模板列表"""
    return [
        {
            "tier": k,
            "name": v["name"],
            "description": v["description"],
            "steps_count": len(v["steps"]),
            "max_days": v["max_duration_days"],
        }
        for k, v in CHURN_JOURNEY_TEMPLATES.items()
    ]
