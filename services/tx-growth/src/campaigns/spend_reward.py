"""消费满额送

典型场景: 消费满200送30元券, 满500送100元券
支持多档位阶梯奖励。
"""

from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "tiers"],
    "properties": {
        "name": {"type": "string"},
        "tiers": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["threshold_fen"],
                "properties": {
                    "threshold_fen": {"type": "integer", "description": "消费满额门槛(分)"},
                    "reward": {"type": "object"},
                },
            },
        },
        "max_per_customer": {"type": "integer", "default": 1},
    },
}


async def execute(
    customer_id: str,
    config: dict,
    trigger_event: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """执行消费满额送"""
    order_total_fen = trigger_event.get("order", {}).get("total_fen", 0)
    tiers = config.get("tiers", [])

    matched_tier = None
    for tier in sorted(tiers, key=lambda t: t["threshold_fen"], reverse=True):
        if order_total_fen >= tier["threshold_fen"]:
            matched_tier = tier
            break

    if not matched_tier:
        return {"success": False, "reason": "未达到满额门槛"}

    log.info(
        "campaign.spend_reward.executed",
        customer_id=customer_id,
        order_total_fen=order_total_fen,
        threshold_fen=matched_tier["threshold_fen"],
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "order_total_fen": order_total_fen,
        "matched_threshold_fen": matched_tier["threshold_fen"],
        "reward": matched_tier.get("reward", {}),
    }
