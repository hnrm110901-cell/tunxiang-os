"""积分兑换

典型场景: 500积分兑换一份甜品, 1000积分兑换50元代金券
支持兑换商品和兑换优惠券两种模式。
"""
from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "exchange_items"],
    "properties": {
        "name": {"type": "string"},
        "exchange_items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["item_id", "points_cost"],
                "properties": {
                    "item_id": {"type": "string"},
                    "item_name": {"type": "string"},
                    "item_type": {"type": "string", "enum": ["dish", "coupon", "gift"]},
                    "points_cost": {"type": "integer"},
                    "stock": {"type": "integer", "default": -1, "description": "-1=无限"},
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
    """执行积分兑换"""
    item_id = trigger_event.get("item_id", "")
    customer_points = trigger_event.get("customer_points", 0)

    items = config.get("exchange_items", [])
    target_item = next((i for i in items if i["item_id"] == item_id), None)

    if not target_item:
        return {"success": False, "reason": f"兑换商品不存在: {item_id}"}

    points_cost = target_item["points_cost"]
    if customer_points < points_cost:
        return {
            "success": False,
            "reason": f"积分不足: 需要{points_cost}, 当前{customer_points}",
        }

    stock = target_item.get("stock", -1)
    if stock == 0:
        return {"success": False, "reason": "库存不足"}

    log.info(
        "campaign.points_exchange.executed",
        customer_id=customer_id,
        item_id=item_id,
        points_cost=points_cost,
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "item": target_item,
        "points_cost": points_cost,
        "remaining_points": customer_points - points_cost,
    }
