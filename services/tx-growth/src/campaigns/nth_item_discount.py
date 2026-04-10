"""第N份M折 — 同一菜品第N份享M折优惠

典型场景：
- 烤鸭第二份半价（nth=2, discount_pct=50）
- 饮品第三杯3折（nth=3, discount_pct=30）
- 啤酒每第二瓶半价（nth=2, discount_pct=50）

价值：提升客单价+推动爆品销量，比直接打折更有心理吸引力
"""
from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "discount_rules"],
    "properties": {
        "name": {"type": "string", "description": "活动名称，如'烤鸭第二份半价'"},
        "description": {"type": "string"},
        "discount_rules": {
            "type": "array",
            "description": "折扣规则列表",
            "items": {
                "type": "object",
                "required": ["nth_item", "discount_pct"],
                "properties": {
                    "dish_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "适用菜品ID列表（空=全部菜品）",
                    },
                    "dish_category": {
                        "type": "string",
                        "description": "适用菜品分类（如'饮品'/'甜品'）",
                    },
                    "nth_item": {
                        "type": "integer",
                        "minimum": 2,
                        "description": "第几份享折扣（最小为2）",
                    },
                    "discount_pct": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 99,
                        "description": "折扣百分比（50=半价, 30=3折）",
                    },
                    "max_applications_per_order": {
                        "type": "integer",
                        "default": 3,
                        "description": "每单最多享几次（如最多3个第二份半价）",
                    },
                },
            },
        },
        "valid_from": {"type": "string"},
        "valid_until": {"type": "string"},
        "valid_time_ranges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "如 '14:00'"},
                    "end": {"type": "string", "description": "如 '17:00'"},
                },
            },
            "description": "生效时段（空=全天）",
        },
        "excluded_dish_ids": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": "排除的菜品ID",
        },
        "margin_floor_pct": {"type": "integer", "default": 30},
    },
}


async def execute(
    customer_id: str,
    config: dict,
    trigger_event: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """第N份M折执行逻辑

    trigger_event格式:
    {
        "event_type": "order.submitted",
        "order_id": "xxx",
        "items": [
            {"dish_id": "d1", "dish_name": "烤鸭", "quantity": 2, "unit_price_fen": 16800},
            {"dish_id": "d2", "dish_name": "啤酒", "quantity": 3, "unit_price_fen": 1800},
        ],
    }
    """
    order_items = trigger_event.get("items", [])
    order_id = trigger_event.get("order_id", "")

    if not order_items:
        return {"success": False, "reason": "no_items"}

    rules = config.get("discount_rules", [])
    excluded = set(config.get("excluded_dish_ids", []))

    total_discount_fen = 0
    discount_details: list[dict[str, Any]] = []

    for rule in rules:
        nth = rule.get("nth_item", 2)
        pct = rule.get("discount_pct", 50)
        max_apply = rule.get("max_applications_per_order", 3)
        applicable_dishes = set(rule.get("dish_ids", []))

        for item in order_items:
            dish_id = item.get("dish_id", "")
            quantity = item.get("quantity", 1)
            unit_price = item.get("unit_price_fen", 0)
            dish_name = item.get("dish_name", "")

            # 检查是否适用
            if dish_id in excluded:
                continue
            if applicable_dishes and dish_id not in applicable_dishes:
                continue

            # 计算第N份折扣次数
            # 例如：quantity=2, nth=2 -> 1次折扣（第2份）
            # quantity=4, nth=2 -> 2次折扣（第2份和第4份）
            # quantity=5, nth=3 -> 1次折扣（第3份）
            discount_count = quantity // nth
            discount_count = min(discount_count, max_apply)

            if discount_count > 0:
                discount_per_item = unit_price * (100 - pct) // 100  # 每份折扣金额
                item_discount = discount_per_item * discount_count
                total_discount_fen += item_discount

                discount_details.append({
                    "dish_id": dish_id,
                    "dish_name": dish_name,
                    "original_price_fen": unit_price,
                    "quantity": quantity,
                    "nth_item": nth,
                    "discount_pct": pct,
                    "discount_count": discount_count,
                    "discount_fen": item_discount,
                    "description": f"{dish_name}第{nth}份{pct}折 x{discount_count}",
                })

    if not discount_details:
        return {"success": False, "reason": "no_applicable_items"}

    # 毛利保护
    margin_floor = config.get("margin_floor_pct", 30)
    order_total = sum(i.get("unit_price_fen", 0) * i.get("quantity", 1) for i in order_items)
    if order_total > 0:
        discount_ratio = total_discount_fen / order_total * 100
        if discount_ratio > (100 - margin_floor):
            return {
                "success": False,
                "reason": "margin_floor_violation",
                "discount_ratio": round(discount_ratio, 1),
            }

    log.info(
        "campaign.nth_item_discount.executed",
        customer_id=customer_id,
        order_id=order_id,
        total_discount_fen=total_discount_fen,
        items=len(discount_details),
        tenant_id=tenant_id,
    )

    return {
        "success": True,
        "customer_id": customer_id,
        "order_id": order_id,
        "total_discount_fen": total_discount_fen,
        "discount_details": discount_details,
        "action": "apply_order_discount",
        "description": f"第N份折扣优惠-¥{total_discount_fen / 100:.2f}",
    }
