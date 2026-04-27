"""沉睡天数检测 — 品智借鉴 P1-8

检测支付方式/营销方案/优惠券的沉睡状态（N天未使用），
帮助清理不再使用的配置，减轻 POS 选择列表的负担。
"""

from datetime import datetime, timezone
from typing import Optional


def compute_dormancy_days(last_used_at: Optional[str], now: Optional[datetime] = None) -> int:
    """计算沉睡天数

    Args:
        last_used_at: 最后使用时间 ISO 格式，None 表示从未使用
        now: 当前时间，默认 UTC now

    Returns:
        沉睡天数，从未使用返回 9999
    """
    if not last_used_at:
        return 9999

    now = now or datetime.now(timezone.utc)
    try:
        last = datetime.fromisoformat(last_used_at.replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        delta = now - last
        return max(0, delta.days)
    except (ValueError, TypeError):
        return 9999


def classify_dormancy(days: int) -> str:
    """分类沉睡等级

    Returns:
        active(≤7天) / idle(≤30天) / dormant(≤90天) / dead(>90天) / never(未使用)
    """
    if days >= 9999:
        return "never"
    if days > 90:
        return "dead"
    if days > 30:
        return "dormant"
    if days > 7:
        return "idle"
    return "active"


def scan_dormant_items(items: list[dict], threshold_days: int = 30) -> dict:
    """扫描沉睡配置项

    Args:
        items: [{"id": "x", "name": "微信支付", "last_used_at": "2026-01-01T00:00:00"}]
        threshold_days: 沉睡阈值天数

    Returns:
        {"dormant": [...], "active": [...], "total": N, "dormant_count": N}
    """
    dormant = []
    active = []

    for item in items:
        days = compute_dormancy_days(item.get("last_used_at"))
        status = classify_dormancy(days)
        enriched = {**item, "dormancy_days": days, "dormancy_status": status}

        if days >= threshold_days:
            dormant.append(enriched)
        else:
            active.append(enriched)

    dormant.sort(key=lambda x: x["dormancy_days"], reverse=True)

    return {
        "dormant": dormant,
        "active": active,
        "total": len(items),
        "dormant_count": len(dormant),
        "dormant_pct": round(len(dormant) / max(1, len(items)) * 100, 1),
    }


def suggest_cleanup(scan_result: dict) -> list[str]:
    """生成清理建议"""
    suggestions = []
    for item in scan_result.get("dormant", []):
        status = item.get("dormancy_status")
        name = item.get("name", "unknown")
        days = item.get("dormancy_days", 0)

        if status == "never":
            suggestions.append(f"「{name}」从未使用，建议删除")
        elif status == "dead":
            suggestions.append(f"「{name}」已 {days} 天未使用，建议停用")
        elif status == "dormant":
            suggestions.append(f"「{name}」已 {days} 天未使用，建议关注")

    return suggestions
