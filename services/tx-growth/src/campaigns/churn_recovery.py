"""挽回流失会员

典型场景: 60天未消费会员自动发送召回短信+高面额优惠券
支持多级流失(30天/60天/90天)差异化召回策略。
"""
from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "churn_levels"],
    "properties": {
        "name": {"type": "string"},
        "churn_levels": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["inactive_days", "reward"],
                "properties": {
                    "inactive_days": {"type": "integer", "description": "未消费天数"},
                    "label": {"type": "string"},
                    "reward": {"type": "object"},
                    "message_template": {"type": "string"},
                    "channels": {"type": "array", "items": {"type": "string"}},
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
    """执行挽回流失会员"""
    inactive_days = trigger_event.get("inactive_days", 0)
    churn_levels = config.get("churn_levels", [])

    # 匹配流失级别(取最接近的)
    matched_level = None
    for level in sorted(churn_levels, key=lambda x: x["inactive_days"], reverse=True):
        if inactive_days >= level["inactive_days"]:
            matched_level = level
            break

    if not matched_level:
        return {"success": False, "reason": "未达到流失标准"}

    log.info(
        "campaign.churn_recovery.executed",
        customer_id=customer_id,
        inactive_days=inactive_days,
        level=matched_level.get("label", ""),
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "inactive_days": inactive_days,
        "churn_level": matched_level.get("label", ""),
        "reward": matched_level.get("reward", {}),
        "message": matched_level.get("message_template", ""),
    }
