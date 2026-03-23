"""桌台 + 订单状态机 — 完整状态流转定义

蓝图定义：
- 桌台 8 状态：空台/已预留/待入座/用餐中/待结账/待清台/锁台/维修停用
- 订单 7 状态：草稿/已下单/制作中/部分上菜/已上齐/待结账/已结账 (+异常分支)
"""
from typing import Optional


# ─── 桌台状态机 ───

TABLE_STATES = {
    "empty": "空台",
    "reserved": "已预留",
    "waiting_seat": "待入座",
    "dining": "用餐中",
    "pending_checkout": "待结账",
    "pending_cleanup": "待清台",
    "locked": "锁台",
    "maintenance": "维修停用",
}

TABLE_TRANSITIONS: dict[str, list[str]] = {
    "empty": ["reserved", "dining", "locked", "maintenance"],
    "reserved": ["waiting_seat", "empty"],           # 到时入座 or 取消预订
    "waiting_seat": ["dining", "empty"],             # 入座 or 爽约
    "dining": ["pending_checkout"],                  # 用餐结束
    "pending_checkout": ["pending_cleanup"],          # 结账完成
    "pending_cleanup": ["empty"],                    # 清台完成
    "locked": ["empty"],                             # 解锁
    "maintenance": ["empty"],                        # 维修完成
}


def can_table_transition(current: str, target: str) -> bool:
    """检查桌台状态转换是否合法"""
    return target in TABLE_TRANSITIONS.get(current, [])


def get_table_next_states(current: str) -> list[dict]:
    """获取桌台可用的下一步状态"""
    nexts = TABLE_TRANSITIONS.get(current, [])
    return [{"state": s, "label": TABLE_STATES.get(s, s)} for s in nexts]


# ─── 订单状态机 ───

ORDER_STATES = {
    "draft": "草稿",
    "placed": "已下单",
    "preparing": "制作中",
    "partial_served": "部分上菜",
    "all_served": "已上齐",
    "pending_payment": "待结账",
    "paid": "已结账",
    "cancelled": "已取消",
    "abnormal": "异常",
}

ORDER_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["placed", "cancelled"],
    "placed": ["preparing", "cancelled"],
    "preparing": ["partial_served", "all_served", "abnormal"],
    "partial_served": ["all_served", "abnormal"],
    "all_served": ["pending_payment"],
    "pending_payment": ["paid", "abnormal"],
    "paid": [],                                      # 终态
    "cancelled": [],                                 # 终态
    "abnormal": ["preparing", "cancelled"],          # 可恢复或取消
}


def can_order_transition(current: str, target: str) -> bool:
    """检查订单状态转换是否合法"""
    return target in ORDER_TRANSITIONS.get(current, [])


def get_order_next_states(current: str) -> list[dict]:
    """获取订单可用的下一步状态"""
    nexts = ORDER_TRANSITIONS.get(current, [])
    return [{"state": s, "label": ORDER_STATES.get(s, s)} for s in nexts]


def validate_order_lifecycle(transitions: list[str]) -> dict:
    """验证一组状态转换序列是否合法

    Args:
        transitions: ["draft", "placed", "preparing", "all_served", "pending_payment", "paid"]

    Returns:
        {"valid": True/False, "invalid_at": None/index, "detail": "..."}
    """
    for i in range(len(transitions) - 1):
        if not can_order_transition(transitions[i], transitions[i + 1]):
            return {
                "valid": False,
                "invalid_at": i,
                "detail": f"非法转换: {transitions[i]}({ORDER_STATES.get(transitions[i])}) → {transitions[i+1]}({ORDER_STATES.get(transitions[i+1])})",
            }
    return {"valid": True, "invalid_at": None, "detail": "全部合法"}


# ─── 状态联动：桌台 ↔ 订单 ───

def sync_table_on_order_change(order_state: str) -> Optional[str]:
    """订单状态变更时联动更新桌台状态

    Returns:
        建议的桌台目标状态，None 表示无需变更
    """
    mapping = {
        "placed": "dining",
        "paid": "pending_cleanup",
        "cancelled": "empty",
    }
    return mapping.get(order_state)
