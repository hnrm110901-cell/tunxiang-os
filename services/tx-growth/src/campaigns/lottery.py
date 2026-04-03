"""抽奖 — 大转盘/九宫格/抽奖机/旋转/抽签/盲盒 统一引擎

所有抽奖玩法共用同一套概率引擎, 仅前端展示形式不同。
约束: 所有奖品概率总和必须 = 100%
"""
import random
from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "prizes", "ui_type"],
    "properties": {
        "name": {"type": "string"},
        "ui_type": {
            "type": "string",
            "enum": ["wheel", "grid9", "slot_machine", "spin", "draw_lot", "blind_box"],
            "description": "前端展示形式",
        },
        "prizes": {
            "type": "array",
            "description": "奖品列表(概率总和必须=100)",
            "items": {
                "type": "object",
                "required": ["prize_id", "name", "probability"],
                "properties": {
                    "prize_id": {"type": "string"},
                    "name": {"type": "string"},
                    "probability": {"type": "number", "description": "中奖概率(百分比)"},
                    "reward": {"type": "object"},
                    "stock": {"type": "integer", "default": -1},
                    "is_thank_you": {"type": "boolean", "default": False, "description": "是否为谢谢参与"},
                },
            },
        },
        "max_per_customer_daily": {"type": "integer", "default": 1},
        "cost_points": {"type": "integer", "default": 0, "description": "每次抽奖消耗积分"},
    },
}


def validate_prizes(prizes: list[dict]) -> tuple[bool, str]:
    """校验奖品概率总和是否为100%"""
    total = sum(p.get("probability", 0) for p in prizes)
    # 允许浮点精度误差
    if abs(total - 100.0) > 0.01:
        return False, f"概率总和为{total}%, 必须等于100%"
    return True, ""


def draw_prize(prizes: list[dict]) -> dict:
    """根据概率抽取奖品"""
    if not prizes:
        return {"error": "无奖品配置"}

    # 过滤掉库存为0的奖品, 重新分配概率
    available = [p for p in prizes if p.get("stock", -1) != 0]
    if not available:
        return {"error": "所有奖品库存已清零"}

    # 加权随机选择
    weights = [p.get("probability", 0) for p in available]
    total_weight = sum(weights)
    if total_weight <= 0:
        return available[0]

    rand = random.uniform(0, total_weight)
    cumulative = 0.0
    for prize in available:
        cumulative += prize.get("probability", 0)
        if rand <= cumulative:
            return prize

    return available[-1]


async def execute(
    customer_id: str,
    config: dict,
    trigger_event: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """执行抽奖"""
    prizes = config.get("prizes", [])
    ui_type = config.get("ui_type", "wheel")

    # 概率校验
    valid, msg = validate_prizes(prizes)
    if not valid:
        return {"success": False, "reason": msg}

    # 抽奖
    won_prize = draw_prize(prizes)
    if "error" in won_prize:
        return {"success": False, "reason": won_prize["error"]}

    is_thank_you = won_prize.get("is_thank_you", False)

    # 扣减库存
    stock = won_prize.get("stock", -1)
    if stock > 0:
        won_prize["stock"] = stock - 1

    log.info(
        "campaign.lottery.executed",
        customer_id=customer_id,
        ui_type=ui_type,
        prize_name=won_prize.get("name", ""),
        is_thank_you=is_thank_you,
        tenant_id=tenant_id,
    )
    return {
        "success": True,
        "customer_id": customer_id,
        "ui_type": ui_type,
        "prize": won_prize,
        "is_thank_you": is_thank_you,
        "reward": {} if is_thank_you else won_prize.get("reward", {}),
    }
