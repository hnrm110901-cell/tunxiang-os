"""拼团活动

典型场景: 2人拼团享5折, 3人拼团享3折, 限时24小时成团
支持普通拼团和阶梯拼团（人越多越便宜）。
"""
from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "product_id", "group_size", "group_price_fen"],
    "properties": {
        "name": {"type": "string"},
        "product_id": {"type": "string", "description": "拼团商品ID"},
        "product_name": {"type": "string"},
        "group_size": {
            "type": "integer",
            "minimum": 2,
            "maximum": 20,
            "description": "成团人数",
        },
        "group_price_fen": {"type": "integer", "description": "拼团价（分）"},
        "original_price_fen": {"type": "integer", "description": "原价（分）"},
        "time_limit_minutes": {
            "type": "integer",
            "default": 1440,
            "description": "拼团时限（分钟），默认24小时",
        },
        "max_teams": {
            "type": "integer",
            "default": 100,
            "description": "最大开团数",
        },
        "ladder_prices": {
            "type": "array",
            "description": "阶梯拼团价（人越多越便宜）",
            "items": {
                "type": "object",
                "properties": {
                    "size": {"type": "integer"},
                    "price_fen": {"type": "integer"},
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
    """拼团成团后执行奖励发放

    trigger_event 包含:
      - team_id: 成团的团队ID
      - team_members: 团队成员列表
      - final_price_fen: 最终成交价
    """
    team_id = trigger_event.get("team_id", "")
    team_members = trigger_event.get("team_members", [])
    group_price = config.get("group_price_fen", 0)
    original_price = config.get("original_price_fen", 0)
    savings_fen = original_price - group_price if original_price > group_price else 0

    log.info(
        "campaign.group_buy.executed",
        customer_id=customer_id,
        team_id=team_id,
        team_size=len(team_members),
        savings_fen=savings_fen,
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "team_id": team_id,
        "customer_id": customer_id,
        "group_price_fen": group_price,
        "original_price_fen": original_price,
        "savings_fen": savings_fen,
        "team_size": len(team_members),
        "reward": {
            "type": "group_discount",
            "discount_fen": savings_fen,
            "product_id": config.get("product_id"),
        },
    }
