"""报名抽奖

典型场景: 活动报名后参与抽奖, 抽取免单/大额优惠
区别于 lottery(即时抽奖), 本模板是先报名再统一开奖。
"""
import random
from typing import Any

import structlog

log = structlog.get_logger()

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "prizes", "draw_time"],
    "properties": {
        "name": {"type": "string"},
        "draw_time": {"type": "string", "description": "开奖时间 ISO8601"},
        "max_participants": {"type": "integer", "default": 0, "description": "最大报名人数(0=不限)"},
        "prizes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["prize_id", "name", "winner_count"],
                "properties": {
                    "prize_id": {"type": "string"},
                    "name": {"type": "string"},
                    "winner_count": {"type": "integer", "description": "中奖人数"},
                    "reward": {"type": "object"},
                },
            },
        },
    },
}

# 内存存储报名名单
_report_entries: dict[str, list[str]] = {}  # campaign_id -> [customer_id]


async def execute(
    customer_id: str,
    config: dict,
    trigger_event: dict,
    tenant_id: str,
    db: Any = None,
) -> dict:
    """执行报名(非开奖)"""
    campaign_id = trigger_event.get("campaign_id", "")
    action = trigger_event.get("action", "report")

    if action == "report":
        # 报名
        if campaign_id not in _report_entries:
            _report_entries[campaign_id] = []

        entries = _report_entries[campaign_id]
        max_p = config.get("max_participants", 0)
        if max_p > 0 and len(entries) >= max_p:
            return {"success": False, "reason": "报名人数已满"}

        if customer_id in entries:
            return {"success": False, "reason": "已报名"}

        entries.append(customer_id)
        log.info(
            "campaign.report_draw.reported",
            customer_id=customer_id,
            campaign_id=campaign_id,
            tenant_id=tenant_id,
        )
        return {
            "success": True,
            "customer_id": customer_id,
            "action": "reported",
            "position": len(entries),
        }

    elif action == "draw":
        # 开奖
        entries = _report_entries.get(campaign_id, [])
        if not entries:
            return {"success": False, "reason": "无人报名"}

        prizes = config.get("prizes", [])
        winners: list[dict] = []
        remaining = list(entries)

        for prize in prizes:
            count = min(prize.get("winner_count", 1), len(remaining))
            selected = random.sample(remaining, count)
            for cid in selected:
                winners.append({
                    "customer_id": cid,
                    "prize": prize,
                })
                remaining.remove(cid)

        log.info(
            "campaign.report_draw.drawn",
            campaign_id=campaign_id,
            winners_count=len(winners),
            tenant_id=tenant_id,
        )
        return {
            "success": True,
            "action": "drawn",
            "total_participants": len(entries),
            "winners": winners,
        }

    return {"success": False, "reason": f"未知操作: {action}"}


def clear_report_entries() -> None:
    """清空报名数据(仅测试用)"""
    _report_entries.clear()
