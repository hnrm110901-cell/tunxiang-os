"""生日营销

典型场景: 生日当天送长寿面+生日蛋糕+双倍积分
支持提前N天触发, 生日当天触发, 生日月触发。
"""

from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "reward"],
    "properties": {
        "name": {"type": "string"},
        "trigger_mode": {
            "type": "string",
            "enum": ["birthday_day", "birthday_month", "advance_days"],
            "default": "birthday_day",
        },
        "advance_days": {"type": "integer", "default": 3, "description": "提前N天触发"},
        "reward": {"type": "object"},
        "birthday_message": {"type": "string", "default": "祝您生日快乐!"},
        "extra_points_multiplier": {"type": "number", "default": 2.0},
    },
}


async def execute(
    customer_id: str,
    config: dict,
    trigger_event: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """执行生日营销"""
    reward = config.get("reward", {})
    message = config.get("birthday_message", "祝您生日快乐!")
    multiplier = config.get("extra_points_multiplier", 2.0)

    log.info(
        "campaign.birthday.executed",
        customer_id=customer_id,
        trigger_mode=config.get("trigger_mode", "birthday_day"),
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "reward": reward,
        "birthday_message": message,
        "extra_points_multiplier": multiplier,
    }
