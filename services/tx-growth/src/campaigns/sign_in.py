"""签到送礼

典型场景: 每日签到送积分, 连续签到7天送大额优惠券
支持普通签到和连续签到两种奖励模式。
"""
from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "daily_reward"],
    "properties": {
        "name": {"type": "string"},
        "daily_reward": {
            "type": "object",
            "description": "每日签到奖励",
            "properties": {
                "type": {"type": "string"},
                "points": {"type": "integer", "default": 10},
            },
        },
        "streak_rewards": {
            "type": "array",
            "description": "连续签到阶梯奖励",
            "items": {
                "type": "object",
                "properties": {
                    "streak_days": {"type": "integer"},
                    "reward": {"type": "object"},
                },
            },
        },
        "reset_on_miss": {"type": "boolean", "default": True, "description": "断签是否重置"},
    },
}


async def execute(
    customer_id: str,
    config: dict,
    trigger_event: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """执行签到送礼"""
    streak_days = trigger_event.get("streak_days", 1)
    daily_reward = config.get("daily_reward", {"type": "points", "points": 10})

    # 检查连续签到奖励
    streak_rewards = config.get("streak_rewards", [])
    bonus_reward = None
    for sr in streak_rewards:
        if streak_days == sr.get("streak_days", 0):
            bonus_reward = sr.get("reward")
            break

    rewards = [daily_reward]
    if bonus_reward:
        rewards.append(bonus_reward)

    log.info(
        "campaign.sign_in.executed",
        customer_id=customer_id,
        streak_days=streak_days,
        has_bonus=bonus_reward is not None,
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "streak_days": streak_days,
        "rewards": rewards,
        "has_streak_bonus": bonus_reward is not None,
    }
