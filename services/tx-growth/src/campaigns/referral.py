"""裂变拉新 + 推荐有礼

典型场景: 老会员分享链接, 新客注册后双方各得20元券
支持多级裂变: A推荐B, B推荐C, A也可获得间接奖励
"""
from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "referrer_reward", "referee_reward"],
    "properties": {
        "name": {"type": "string"},
        "referrer_reward": {
            "type": "object",
            "description": "推荐人奖励",
            "properties": {
                "type": {"type": "string"},
                "amount_fen": {"type": "integer"},
            },
        },
        "referee_reward": {
            "type": "object",
            "description": "被推荐人奖励",
            "properties": {
                "type": {"type": "string"},
                "amount_fen": {"type": "integer"},
            },
        },
        "max_referrals": {"type": "integer", "default": 10, "description": "每人最多推荐数"},
        "multi_level": {"type": "boolean", "default": False, "description": "是否开启多级裂变"},
        "level2_reward_fen": {"type": "integer", "default": 0, "description": "二级间接奖励(分)"},
    },
}


async def execute(
    customer_id: str,
    config: dict,
    trigger_event: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """执行裂变拉新"""
    referrer_id = trigger_event.get("referrer_id", "")
    referee_id = customer_id

    referrer_reward = config.get("referrer_reward", {})
    referee_reward = config.get("referee_reward", {})

    rewards = []
    if referrer_id:
        rewards.append({
            "customer_id": referrer_id,
            "role": "referrer",
            "reward": referrer_reward,
        })
    rewards.append({
        "customer_id": referee_id,
        "role": "referee",
        "reward": referee_reward,
    })

    # 多级裂变
    if config.get("multi_level") and trigger_event.get("level2_referrer_id"):
        level2_id = trigger_event["level2_referrer_id"]
        level2_fen = config.get("level2_reward_fen", 0)
        if level2_fen > 0:
            rewards.append({
                "customer_id": level2_id,
                "role": "level2_referrer",
                "reward": {"type": "coupon", "amount_fen": level2_fen},
            })

    log.info(
        "campaign.referral.executed",
        referrer_id=referrer_id,
        referee_id=referee_id,
        rewards_count=len(rewards),
        tenant_id=tenant_id,
    )
    return {"success": True, "rewards": rewards}
