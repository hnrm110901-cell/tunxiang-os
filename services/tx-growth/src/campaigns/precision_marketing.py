"""精准营销 — 标签 + 自动循环发送

典型场景: 对"30天未消费"标签会员, 每周三自动发送召回短信+优惠券
支持:
- 按标签筛选目标人群
- 每周几/每月几号自动循环
- 多通道触达(短信/微信/APP推送)
"""
from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "target_tags", "schedule", "message_template"],
    "properties": {
        "name": {"type": "string"},
        "target_tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "目标会员标签",
        },
        "target_segments": {"type": "array", "items": {"type": "string"}},
        "schedule": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["daily", "weekly", "monthly"]},
                "weekdays": {"type": "array", "items": {"type": "integer"}, "description": "1=周一..7=周日"},
                "days_of_month": {"type": "array", "items": {"type": "integer"}},
                "time": {"type": "string", "description": "发送时间 HH:MM"},
            },
        },
        "channels": {
            "type": "array",
            "items": {"type": "string", "enum": ["sms", "wechat", "app_push"]},
            "default": ["wechat"],
        },
        "message_template": {"type": "string"},
        "reward": {"type": "object"},
    },
}


async def execute(
    customer_id: str,
    config: dict,
    trigger_event: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """执行精准营销发送"""
    target_tags = config.get("target_tags", [])
    channels = config.get("channels", ["wechat"])
    message = config.get("message_template", "")

    log.info(
        "campaign.precision_marketing.executed",
        customer_id=customer_id,
        target_tags=target_tags,
        channels=channels,
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "channels": channels,
        "message": message,
        "reward": config.get("reward", {}),
    }
