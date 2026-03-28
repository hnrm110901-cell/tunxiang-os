"""消费券返券

典型场景: 每次消费后返一张下次使用的优惠券, 形成消费闭环
支持不同消费金额返不同面额券。
"""
from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "return_rules"],
    "properties": {
        "name": {"type": "string"},
        "return_rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "min_spend_fen": {"type": "integer", "default": 0},
                    "return_coupon": {
                        "type": "object",
                        "properties": {
                            "amount_fen": {"type": "integer"},
                            "threshold_fen": {"type": "integer", "default": 0},
                            "validity_days": {"type": "integer", "default": 14},
                        },
                    },
                },
            },
        },
        "max_return_per_day": {"type": "integer", "default": 1},
    },
}


async def execute(
    customer_id: str,
    config: dict,
    trigger_event: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """执行消费券返券"""
    order_total_fen = trigger_event.get("order", {}).get("total_fen", 0)
    return_rules = config.get("return_rules", [])

    matched_rule = None
    for rule in sorted(return_rules, key=lambda r: r.get("min_spend_fen", 0), reverse=True):
        if order_total_fen >= rule.get("min_spend_fen", 0):
            matched_rule = rule
            break

    if not matched_rule:
        return {"success": False, "reason": "未满足返券条件"}

    coupon = matched_rule.get("return_coupon", {})
    log.info(
        "campaign.coupon_return.executed",
        customer_id=customer_id,
        order_total_fen=order_total_fen,
        return_amount_fen=coupon.get("amount_fen", 0),
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "order_total_fen": order_total_fen,
        "return_coupon": coupon,
        "reward": {"type": "coupon", **coupon},
    }
