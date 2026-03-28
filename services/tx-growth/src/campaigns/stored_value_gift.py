"""储值套餐 — 充X送Y

典型场景: 充500送80, 充1000送200
支持多档位配置, 每个档位独立的充值金额和赠送金额。
金额单位: 分(fen)
"""
from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "tiers"],
    "properties": {
        "name": {"type": "string", "description": "活动名称"},
        "tiers": {
            "type": "array",
            "description": "储值档位列表",
            "items": {
                "type": "object",
                "required": ["charge_fen", "bonus_fen"],
                "properties": {
                    "charge_fen": {"type": "integer", "description": "充值金额(分)"},
                    "bonus_fen": {"type": "integer", "description": "赠送金额(分)"},
                },
            },
        },
        "max_per_customer": {"type": "integer", "default": 0, "description": "每人限充次数(0=不限)"},
        "target_stores": {"type": "array", "items": {"type": "string"}},
        "reward": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "const": "stored_value"},
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
    """执行储值套餐活动

    Args:
        customer_id: 客户ID
        config: 活动配置 (含 tiers)
        trigger_event: 触发事件 (含 charge_fen)
        tenant_id: 租户ID
    """
    charge_fen = trigger_event.get("charge_fen", 0)
    tiers = config.get("tiers", [])

    # 匹配最高档位
    matched_tier = None
    for tier in sorted(tiers, key=lambda t: t["charge_fen"], reverse=True):
        if charge_fen >= tier["charge_fen"]:
            matched_tier = tier
            break

    if not matched_tier:
        return {
            "success": False,
            "reason": f"充值金额{charge_fen}分未达到最低档位",
        }

    bonus_fen = matched_tier["bonus_fen"]
    log.info(
        "campaign.stored_value_gift.executed",
        customer_id=customer_id,
        charge_fen=charge_fen,
        bonus_fen=bonus_fen,
        tenant_id=tenant_id,
    )

    return {
        "success": True,
        "customer_id": customer_id,
        "charge_fen": charge_fen,
        "bonus_fen": bonus_fen,
        "total_fen": charge_fen + bonus_fen,
        "reward": {"type": "stored_value", "amount_fen": bonus_fen},
    }
