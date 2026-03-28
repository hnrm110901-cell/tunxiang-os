"""储值赠券

典型场景: 充值500送3张20元满减券
区别于 stored_value_gift(充值送储值金额), 本模板充值送优惠券。
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
                "properties": {
                    "charge_fen": {"type": "integer"},
                    "coupons": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "coupon_id": {"type": "string"},
                                "amount_fen": {"type": "integer"},
                                "quantity": {"type": "integer", "default": 1},
                            },
                        },
                    },
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
    """执行储值赠券"""
    charge_fen = trigger_event.get("charge_fen", 0)
    tiers = config.get("tiers", [])

    matched_tier = None
    for tier in sorted(tiers, key=lambda t: t["charge_fen"], reverse=True):
        if charge_fen >= tier["charge_fen"]:
            matched_tier = tier
            break

    if not matched_tier:
        return {"success": False, "reason": "充值金额未达到最低档位"}

    coupons = matched_tier.get("coupons", [])
    log.info(
        "campaign.recharge_coupon.executed",
        customer_id=customer_id,
        charge_fen=charge_fen,
        coupons_count=len(coupons),
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "charge_fen": charge_fen,
        "coupons": coupons,
        "reward": {"type": "coupon", "coupons": coupons},
    }
