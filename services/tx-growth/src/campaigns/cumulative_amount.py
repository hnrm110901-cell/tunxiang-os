"""累计金额送券

典型场景: 累计消费满1000元送50元券
按周期(月/季/年)累计, 达标自动发券。
"""

from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "cumulative_threshold_fen", "reward"],
    "properties": {
        "name": {"type": "string"},
        "cumulative_threshold_fen": {"type": "integer", "description": "累计金额门槛(分)"},
        "period": {"type": "string", "enum": ["month", "quarter", "year", "forever"], "default": "month"},
        "reward": {"type": "object"},
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
    """执行累计金额送券"""
    cumulative_fen = trigger_event.get("cumulative_amount_fen", 0)
    threshold_fen = config.get("cumulative_threshold_fen", 0)

    if cumulative_fen < threshold_fen:
        return {
            "success": False,
            "reason": f"累计金额{cumulative_fen}分未达标{threshold_fen}分",
            "progress": round(cumulative_fen / max(1, threshold_fen), 4),
        }

    log.info(
        "campaign.cumulative_amount.executed",
        customer_id=customer_id,
        cumulative_fen=cumulative_fen,
        threshold_fen=threshold_fen,
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "cumulative_fen": cumulative_fen,
        "reward": config.get("reward", {}),
    }
