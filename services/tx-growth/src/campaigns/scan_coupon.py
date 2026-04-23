"""扫码领券

典型场景: 桌台扫码领取当桌优惠券, 或扫描活动海报二维码领券
"""

from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "coupon_config"],
    "properties": {
        "name": {"type": "string"},
        "coupon_config": {
            "type": "object",
            "properties": {
                "coupon_id": {"type": "string"},
                "amount_fen": {"type": "integer"},
                "threshold_fen": {"type": "integer", "default": 0, "description": "满减门槛"},
                "validity_days": {"type": "integer", "default": 7},
            },
        },
        "total_quota": {"type": "integer", "description": "总发放限额"},
        "max_per_customer": {"type": "integer", "default": 1},
        "qr_code_type": {"type": "string", "enum": ["table", "poster", "receipt"], "default": "poster"},
    },
}


async def execute(
    customer_id: str,
    config: dict,
    trigger_event: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """执行扫码领券"""
    coupon_config = config.get("coupon_config", {})
    qr_type = trigger_event.get("qr_code_type", config.get("qr_code_type", "poster"))

    log.info(
        "campaign.scan_coupon.executed",
        customer_id=customer_id,
        qr_type=qr_type,
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "coupon": coupon_config,
        "qr_code_type": qr_type,
        "reward": {"type": "coupon", **coupon_config},
    }
