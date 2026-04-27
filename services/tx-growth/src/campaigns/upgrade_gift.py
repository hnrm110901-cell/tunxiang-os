"""升级送礼

典型场景: 会员等级从银卡升至金卡, 赠送升级礼包
"""

from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "upgrade_rewards"],
    "properties": {
        "name": {"type": "string"},
        "upgrade_rewards": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["from_level", "to_level", "reward"],
                "properties": {
                    "from_level": {"type": "string"},
                    "to_level": {"type": "string"},
                    "reward": {"type": "object"},
                    "message": {"type": "string"},
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
    """执行升级送礼"""
    from_level = trigger_event.get("from_level", "")
    to_level = trigger_event.get("to_level", "")
    upgrade_rewards = config.get("upgrade_rewards", [])

    matched = next(
        (r for r in upgrade_rewards if r["from_level"] == from_level and r["to_level"] == to_level),
        None,
    )

    if not matched:
        return {"success": False, "reason": f"未配置 {from_level}->{to_level} 的升级奖励"}

    log.info(
        "campaign.upgrade_gift.executed",
        customer_id=customer_id,
        from_level=from_level,
        to_level=to_level,
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "from_level": from_level,
        "to_level": to_level,
        "reward": matched.get("reward", {}),
        "message": matched.get("message", f"恭喜升级至{to_level}!"),
    }
