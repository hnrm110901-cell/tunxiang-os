"""完善资料送礼

典型场景: 填写生日/手机号/性别等信息后获得积分/优惠券奖励
"""

from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "required_fields", "reward"],
    "properties": {
        "name": {"type": "string"},
        "required_fields": {
            "type": "array",
            "items": {"type": "string"},
            "description": "需要完善的字段: birthday/phone/gender/address",
        },
        "reward": {"type": "object"},
    },
}


async def execute(
    customer_id: str,
    config: dict,
    trigger_event: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """执行完善资料送礼"""
    required_fields = config.get("required_fields", [])
    completed_fields = trigger_event.get("completed_fields", [])
    missing = [f for f in required_fields if f not in completed_fields]

    if missing:
        return {
            "success": False,
            "reason": f"尚未完善: {', '.join(missing)}",
            "progress": round(len(completed_fields) / max(1, len(required_fields)), 4),
        }

    log.info(
        "campaign.profile_reward.executed",
        customer_id=customer_id,
        completed_fields=completed_fields,
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "completed_fields": completed_fields,
        "reward": config.get("reward", {}),
    }
