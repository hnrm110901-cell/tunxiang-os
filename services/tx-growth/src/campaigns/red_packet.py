"""红包雨

典型场景: 午市12:00开始红包雨, 限时5分钟, 随机金额红包
支持固定金额和随机金额两种模式。
"""
import random
from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "total_budget_fen", "mode"],
    "properties": {
        "name": {"type": "string"},
        "total_budget_fen": {"type": "integer", "description": "红包总预算(分)"},
        "mode": {
            "type": "string",
            "enum": ["fixed", "random"],
            "description": "固定金额/随机金额",
        },
        "fixed_amount_fen": {"type": "integer", "description": "固定模式下每个红包金额(分)"},
        "random_min_fen": {"type": "integer", "default": 50, "description": "随机最小金额(分)"},
        "random_max_fen": {"type": "integer", "default": 1000, "description": "随机最大金额(分)"},
        "duration_seconds": {"type": "integer", "default": 300, "description": "持续时间(秒)"},
        "max_per_customer": {"type": "integer", "default": 3},
    },
}


async def execute(
    customer_id: str,
    config: dict,
    trigger_event: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """执行红包雨"""
    mode = config.get("mode", "random")

    if mode == "fixed":
        amount_fen = config.get("fixed_amount_fen", 100)
    else:
        min_fen = config.get("random_min_fen", 50)
        max_fen = config.get("random_max_fen", 1000)
        amount_fen = random.randint(min_fen, max_fen)

    log.info(
        "campaign.red_packet.executed",
        customer_id=customer_id,
        mode=mode,
        amount_fen=amount_fen,
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "amount_fen": amount_fen,
        "mode": mode,
        "reward": {"type": "stored_value", "amount_fen": amount_fen},
    }
