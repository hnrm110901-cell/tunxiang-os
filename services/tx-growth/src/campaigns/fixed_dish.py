"""定食营销

典型场景: 每周三剁椒鱼头半价, 点指定菜品即享特价/赠品
支持指定菜品ID列表, 生效时段, 优惠方式(折扣/减免/赠品)。
"""
from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "target_dish_ids", "discount_type"],
    "properties": {
        "name": {"type": "string"},
        "target_dish_ids": {"type": "array", "items": {"type": "string"}, "description": "目标菜品ID"},
        "discount_type": {
            "type": "string",
            "enum": ["half_price", "fixed_reduce", "percentage", "free_gift"],
        },
        "discount_value": {"type": "integer", "description": "折扣值: 折扣百分比/减免金额(分)"},
        "gift_dish_id": {"type": "string", "description": "赠品菜品ID (free_gift时使用)"},
        "time_slots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "weekdays": {"type": "array", "items": {"type": "integer"}},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
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
    """执行定食营销"""
    order_dishes = trigger_event.get("order", {}).get("dish_ids", [])
    target_dishes = config.get("target_dish_ids", [])
    matched = list(set(order_dishes) & set(target_dishes))

    if not matched:
        return {"success": False, "reason": "未点到目标菜品"}

    discount_type = config.get("discount_type", "half_price")
    discount_value = config.get("discount_value", 50)

    log.info(
        "campaign.fixed_dish.executed",
        customer_id=customer_id,
        matched_dishes=matched,
        discount_type=discount_type,
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "matched_dishes": matched,
        "discount_type": discount_type,
        "discount_value": discount_value,
    }
