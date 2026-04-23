"""付费券包

典型场景: 9.9元购买价值50元优惠券包(含3张不同面额券)
"""

from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "price_fen", "coupons"],
    "properties": {
        "name": {"type": "string"},
        "price_fen": {"type": "integer", "description": "售价(分)"},
        "original_value_fen": {"type": "integer", "description": "原价总价值(分)"},
        "coupons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "coupon_id": {"type": "string"},
                    "name": {"type": "string"},
                    "amount_fen": {"type": "integer"},
                    "threshold_fen": {"type": "integer", "default": 0},
                    "validity_days": {"type": "integer", "default": 30},
                },
            },
        },
        "total_quota": {"type": "integer", "description": "总售卖限额"},
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
    """执行付费券包购买"""
    price_fen = config.get("price_fen", 0)
    coupons = config.get("coupons", [])
    total_value = sum(c.get("amount_fen", 0) for c in coupons)

    log.info(
        "campaign.paid_coupon_pack.executed",
        customer_id=customer_id,
        price_fen=price_fen,
        coupons_count=len(coupons),
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "price_fen": price_fen,
        "total_value_fen": total_value,
        "coupons": coupons,
        "saving_fen": total_value - price_fen,
    }
