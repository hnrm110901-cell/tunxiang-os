"""付费权益卡 — 年卡/月卡

典型场景: 月卡39元享每日1份特价菜, 年卡399元享全年8折+生日双倍积分
"""

from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "plans"],
    "properties": {
        "name": {"type": "string"},
        "plans": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["plan_id", "price_fen", "duration_days"],
                "properties": {
                    "plan_id": {"type": "string"},
                    "plan_name": {"type": "string"},
                    "price_fen": {"type": "integer"},
                    "duration_days": {"type": "integer"},
                    "privileges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "daily_dish",
                                        "discount",
                                        "points_multiplier",
                                        "free_delivery",
                                    ],
                                },
                                "value": {"type": "number"},
                                "description": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    },
}


async def execute(
    customer_id: str,
    config: dict,
    trigger_event: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """执行付费权益卡购买"""
    plan_id = trigger_event.get("plan_id", "")
    plans = config.get("plans", [])
    target_plan = next((p for p in plans if p["plan_id"] == plan_id), None)

    if not target_plan:
        return {"success": False, "reason": f"权益卡方案不存在: {plan_id}"}

    log.info(
        "campaign.paid_privilege.executed",
        customer_id=customer_id,
        plan_id=plan_id,
        price_fen=target_plan["price_fen"],
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "plan": target_plan,
        "reward": {
            "type": "privilege",
            "privilege_id": plan_id,
            "days": target_plan["duration_days"],
        },
    }
