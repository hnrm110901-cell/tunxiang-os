"""预订→排队→入座 全链路联动 (C3)

状态流转：
  预订确认 → 到店排队 → 叫号 → 分配桌台 → 开台 → 点餐

与桌台状态机联动：
  empty → reserved(预订确认) → waiting_seat(到店) → dining(入座开台)
"""
from datetime import datetime, timezone
from typing import Optional


# ─── 预订状态机 ───

RESERVATION_STATES = {
    "pending": "待确认",
    "confirmed": "已确认",
    "arrived": "已到店",
    "queuing": "排队中",
    "seated": "已入座",
    "completed": "已完成",
    "cancelled": "已取消",
    "no_show": "爽约",
}

RESERVATION_TRANSITIONS = {
    "pending": ["confirmed", "cancelled"],
    "confirmed": ["arrived", "cancelled", "no_show"],
    "arrived": ["queuing", "seated"],  # 到店后排队或直接入座
    "queuing": ["seated", "cancelled"],
    "seated": ["completed"],
    "completed": [],
    "cancelled": [],
    "no_show": [],
}


def can_reservation_transition(current: str, target: str) -> bool:
    return target in RESERVATION_TRANSITIONS.get(current, [])


# ─── 排队管理 ───

def generate_queue_number(store_id: str, guest_count: int, queue_data: list) -> dict:
    """生成排队号
    Args:
        queue_data: 当前排队列表
    Returns:
        {"queue_no": "A023", "position": 5, "estimated_wait_min": 25}
    """
    prefix = "A" if guest_count <= 4 else "B" if guest_count <= 8 else "C"
    existing = [q for q in queue_data if q.get("prefix") == prefix]
    next_num = max([q.get("number", 0) for q in existing], default=0) + 1
    queue_no = f"{prefix}{next_num:03d}"

    # 估算等待时间：每桌平均 45 分钟
    position = len([q for q in existing if q.get("status") == "waiting"])
    estimated_wait = position * 15  # 每位前面约 15 分钟

    return {
        "queue_no": queue_no,
        "prefix": prefix,
        "number": next_num,
        "guest_count": guest_count,
        "position": position + 1,
        "estimated_wait_min": estimated_wait,
        "status": "waiting",
        "taken_at": datetime.now(timezone.utc).isoformat(),
    }


def call_next(queue_data: list, prefix: str = "") -> dict | None:
    """叫号：取出队列中最早的等待者"""
    waiting = [q for q in queue_data if q.get("status") == "waiting"]
    if prefix:
        waiting = [q for q in waiting if q.get("prefix") == prefix]
    if not waiting:
        return None
    waiting.sort(key=lambda q: q.get("taken_at", ""))
    called = waiting[0]
    called["status"] = "called"
    called["called_at"] = datetime.now(timezone.utc).isoformat()
    return called


# ─── 全链路联动 ───

def reservation_to_queue(reservation: dict) -> dict:
    """预订到店 → 自动加入排队"""
    return generate_queue_number(
        store_id=reservation.get("store_id", ""),
        guest_count=reservation.get("guest_count", 2),
        queue_data=[],
    )


def queue_to_table(queue_item: dict, available_tables: list) -> dict | None:
    """排队叫号 → 分配最合适的桌台"""
    guest_count = queue_item.get("guest_count", 2)
    candidates = [t for t in available_tables
                  if t.get("status") == "free" and t.get("seats", 0) >= guest_count]
    if not candidates:
        return None

    # 选座位数最接近的桌（减少浪费）
    candidates.sort(key=lambda t: t.get("seats", 0) - guest_count)
    best = candidates[0]

    return {
        "table_no": best.get("table_no"),
        "seats": best.get("seats"),
        "area": best.get("area"),
        "guest_count": guest_count,
        "queue_no": queue_item.get("queue_no"),
        "table_status": "dining",  # 桌台联动
    }


def compute_queue_stats(queue_data: list) -> dict:
    """排队统计"""
    waiting = [q for q in queue_data if q.get("status") == "waiting"]
    seated = [q for q in queue_data if q.get("status") == "seated"]
    cancelled = [q for q in queue_data if q.get("status") in ("cancelled", "expired")]

    total = len(queue_data)
    abandon_rate = len(cancelled) / max(1, total) * 100

    # 按桌型分组
    by_prefix = {}
    for q in waiting:
        p = q.get("prefix", "A")
        by_prefix.setdefault(p, 0)
        by_prefix[p] += 1

    return {
        "total_today": total,
        "waiting": len(waiting),
        "seated": len(seated),
        "cancelled": len(cancelled),
        "abandon_rate_pct": round(abandon_rate, 1),
        "by_type": by_prefix,
        "avg_wait_min": 15 * len(waiting) // max(1, len(waiting)),  # 简化
    }
