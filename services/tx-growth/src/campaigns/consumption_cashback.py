"""消费返现 — 消费满额返现金到储值卡

区别于coupon_return（返券）：
- coupon_return返的是优惠券（有使用门槛和有效期限制）
- consumption_cashback返的是现金到储值卡（无门槛，直接抵扣，价值感更高）

典型场景：
- 消费满300元返30元现金到储值卡
- 消费满500元返60元现金到储值卡
- 消费满1000元返150元现金到储值卡

价值：比打折更有价值感（"300块钱消费返30块现金"比"95折"心理感受更强）
"""
from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "cashback_rules"],
    "properties": {
        "name": {"type": "string", "description": "活动名称"},
        "description": {"type": "string", "description": "活动描述"},
        "cashback_rules": {
            "type": "array",
            "description": "阶梯返现规则（按消费金额从高到低匹配）",
            "items": {
                "type": "object",
                "required": ["min_spend_fen", "cashback_fen"],
                "properties": {
                    "min_spend_fen": {"type": "integer", "description": "最低消费金额（分）"},
                    "cashback_fen": {"type": "integer", "description": "返现金额（分）"},
                    "cashback_type": {
                        "type": "string",
                        "enum": ["stored_value", "coupon"],
                        "default": "stored_value",
                        "description": "返现方式：stored_value=现金到储值卡, coupon=优惠券",
                    },
                    "coupon_validity_days": {
                        "type": "integer",
                        "default": 30,
                        "description": "优惠券有效期（仅coupon类型）",
                    },
                },
            },
        },
        "max_per_customer_day": {"type": "integer", "default": 1, "description": "每客每天最多返现次数"},
        "max_per_customer_total": {"type": "integer", "default": 0, "description": "每客累计最多返现次数（0=不限）"},
        "valid_from": {"type": "string", "description": "生效开始时间"},
        "valid_until": {"type": "string", "description": "生效结束时间"},
        "excluded_order_types": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": "排除的订单类型（如delivery/takeaway）",
        },
        "margin_floor_pct": {"type": "integer", "default": 30, "description": "毛利底线保护（%）"},
    },
}


async def execute(
    customer_id: str,
    config: dict,
    trigger_event: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """消费返现执行逻辑

    trigger_event格式:
    {
        "event_type": "order.paid",
        "order_id": "xxx",
        "total_fen": 30000,  # 消费金额（分）
        "order_type": "dine_in",
    }
    """
    order_total = trigger_event.get("total_fen", 0)
    order_type = trigger_event.get("order_type", "dine_in")
    order_id = trigger_event.get("order_id", "")

    # 1. 检查订单类型是否被排除
    excluded = config.get("excluded_order_types", [])
    if order_type in excluded:
        return {"success": False, "reason": "order_type_excluded", "order_type": order_type}

    # 2. 按消费金额从高到低匹配规则
    rules = sorted(config.get("cashback_rules", []), key=lambda r: r["min_spend_fen"], reverse=True)
    matched_rule = None
    for rule in rules:
        if order_total >= rule["min_spend_fen"]:
            matched_rule = rule
            break

    if not matched_rule:
        return {"success": False, "reason": "below_minimum_spend", "order_total_fen": order_total}

    cashback_fen = matched_rule["cashback_fen"]
    cashback_type = matched_rule.get("cashback_type", "stored_value")

    # 3. 毛利底线保护
    margin_floor = config.get("margin_floor_pct", 30)
    if order_total > 0:
        cashback_ratio = cashback_fen / order_total * 100
        if cashback_ratio > (100 - margin_floor):
            return {
                "success": False,
                "reason": "margin_floor_violation",
                "cashback_ratio": round(cashback_ratio, 1),
                "margin_floor": margin_floor,
            }

    # 4. 频次限制检查
    # 注意：实际频次检查需要查DB，此处返回成功结果由调用方校验
    _max_day = config.get("max_per_customer_day", 1)  # noqa: F841
    _max_total = config.get("max_per_customer_total", 0)  # noqa: F841

    # 5. 执行返现
    result: dict[str, Any] = {
        "success": True,
        "customer_id": customer_id,
        "order_id": order_id,
        "order_total_fen": order_total,
        "cashback_fen": cashback_fen,
        "cashback_type": cashback_type,
        "matched_rule": {
            "min_spend_fen": matched_rule["min_spend_fen"],
            "cashback_fen": cashback_fen,
        },
    }

    if cashback_type == "stored_value":
        # 返现到储值卡
        result["action"] = "recharge_stored_value"
        result["recharge_amount_fen"] = cashback_fen
        result["recharge_type"] = "cashback_gift"
        result["description"] = f"消费返现¥{cashback_fen / 100:.0f}（订单{order_id[-6:]}）"
    elif cashback_type == "coupon":
        # 返优惠券
        validity_days = matched_rule.get("coupon_validity_days", 30)
        result["action"] = "issue_coupon"
        result["coupon_amount_fen"] = cashback_fen
        result["coupon_validity_days"] = validity_days
        result["description"] = f"消费返券¥{cashback_fen / 100:.0f}（{validity_days}天有效）"

    log.info(
        "campaign.consumption_cashback.executed",
        customer_id=customer_id,
        order_total_fen=order_total,
        cashback_fen=cashback_fen,
        cashback_type=cashback_type,
        tenant_id=tenant_id,
    )

    return result
