"""集点卡（印章卡）

典型场景: 集满5杯送1杯, 消费满30元自动盖章, 集满后自动发放奖励券
支持按消费次数或按消费金额门槛盖章。
"""

from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "target_stamps", "reward_config"],
    "properties": {
        "name": {"type": "string"},
        "target_stamps": {
            "type": "integer",
            "minimum": 2,
            "maximum": 50,
            "description": "集满次数",
        },
        "reward_config": {
            "type": "object",
            "description": "集满奖励配置",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["coupon", "free_item", "points", "stored_value"],
                },
                "coupon_amount_fen": {"type": "integer"},
                "free_item_id": {"type": "string"},
                "points": {"type": "integer"},
                "stored_value_fen": {"type": "integer"},
            },
        },
        "validity_days": {
            "type": "integer",
            "default": 90,
            "description": "集点卡有效天数",
        },
        "min_order_fen": {
            "type": "integer",
            "default": 0,
            "description": "单次盖章最低消费（分），0=不限",
        },
        "applicable_stores": {
            "type": "array",
            "description": "适用门店ID，空=全部门店",
            "items": {"type": "string"},
        },
        "auto_stamp": {
            "type": "boolean",
            "default": True,
            "description": "是否消费后自动盖章",
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
    """集满后执行奖励发放

    trigger_event 包含:
      - instance_id: 集点卡实例ID
      - stamp_count: 当前印章数
      - completed: 是否刚刚集满
    """
    instance_id = trigger_event.get("instance_id", "")
    stamp_count = trigger_event.get("stamp_count", 0)
    completed = trigger_event.get("completed", False)
    reward_config = config.get("reward_config", {})
    target = config.get("target_stamps", 5)

    if not completed:
        log.info(
            "campaign.stamp_card.stamped",
            customer_id=customer_id,
            instance_id=instance_id,
            progress=f"{stamp_count}/{target}",
            tenant_id=tenant_id,
        )
        return {
            "success": True,
            "customer_id": customer_id,
            "instance_id": instance_id,
            "stamp_count": stamp_count,
            "target_stamps": target,
            "completed": False,
        }

    log.info(
        "campaign.stamp_card.completed",
        customer_id=customer_id,
        instance_id=instance_id,
        reward_type=reward_config.get("type"),
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "instance_id": instance_id,
        "stamp_count": stamp_count,
        "target_stamps": target,
        "completed": True,
        "reward": reward_config,
    }
