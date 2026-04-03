"""累计次数赠券

典型场景: 累计消费5次送菜品兑换券
"""
from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "cumulative_threshold_count", "reward"],
    "properties": {
        "name": {"type": "string"},
        "cumulative_threshold_count": {"type": "integer", "description": "累计次数门槛"},
        "period": {"type": "string", "enum": ["month", "quarter", "year", "forever"], "default": "month"},
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
    """执行累计次数赠券"""
    count = trigger_event.get("cumulative_count", 0)
    threshold = config.get("cumulative_threshold_count", 0)

    if count < threshold:
        return {
            "success": False,
            "reason": f"累计{count}次未达标{threshold}次",
            "progress": round(count / max(1, threshold), 4),
        }

    log.info(
        "campaign.cumulative_count.executed",
        customer_id=customer_id,
        count=count,
        threshold=threshold,
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "cumulative_count": count,
        "reward": config.get("reward", {}),
    }
