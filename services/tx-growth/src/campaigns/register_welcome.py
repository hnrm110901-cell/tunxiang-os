"""开卡有礼 — 新会员注册即赠

典型场景: 新会员注册送10元无门槛券 + 100积分
支持多种奖励组合: 券/积分/储值
"""
from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "reward"],
    "properties": {
        "name": {"type": "string"},
        "reward": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["coupon", "points", "stored_value"]},
                "amount_fen": {"type": "integer"},
                "points": {"type": "integer"},
                "coupon_id": {"type": "string"},
                "validity_days": {"type": "integer", "default": 30},
            },
        },
        "welcome_message": {"type": "string", "description": "欢迎语"},
    },
}


async def execute(
    customer_id: str,
    config: dict,
    trigger_event: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """执行开卡有礼"""
    reward_config = config.get("reward", {})
    reward_type = reward_config.get("type", "coupon")

    result = {
        "success": True,
        "customer_id": customer_id,
        "reward": reward_config,
        "welcome_message": config.get("welcome_message", "欢迎成为会员!"),
    }

    log.info(
        "campaign.register_welcome.executed",
        customer_id=customer_id,
        reward_type=reward_type,
        tenant_id=tenant_id,
    )
    return result
