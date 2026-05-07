"""桌台 + 订单状态机 — 完整状态流转定义

蓝图定义（state_machine 内部词表，蓝图层）：
- 桌台 8 状态：空台/已预留/待入座/用餐中/待结账/待清台/锁台/维修停用
- 订单 9 状态：草稿/已下单/制作中/部分上菜/已上齐/待结账/已结账/已取消/异常

ORM 实际词表（shared.ontology.OrderStatus，业务层）：
- 7 状态：pending/confirmed/preparing/ready/served/completed/cancelled

两套词表当前并存。`can_order_transition` 沿用蓝图词表，
`can_order_status_transition` / `transition_order` 走 ORM 词表（业务实际使用）。
两套词表对齐与否由产品决定，不在本 P0-3 范围。
"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from shared.ontology.src.entities import Order
    from shared.ontology.src.enums import OrderStatus

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
    "reserved": ["waiting_seat", "empty"],  # 到时入座 or 取消预订
    "waiting_seat": ["dining", "empty"],  # 入座 or 爽约
    "dining": ["pending_checkout"],  # 用餐结束
    "pending_checkout": ["pending_cleanup"],  # 结账完成
    "pending_cleanup": ["empty"],  # 清台完成
    "locked": ["empty"],  # 解锁
    "maintenance": ["empty"],  # 维修完成
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
    "paid": [],  # 终态
    "cancelled": [],  # 终态
    "abnormal": ["preparing", "cancelled"],  # 可恢复或取消
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
                "detail": f"非法转换: {transitions[i]}({ORDER_STATES.get(transitions[i])}) → {transitions[i + 1]}({ORDER_STATES.get(transitions[i + 1])})",
            }
    return {"valid": True, "invalid_at": None, "detail": "全部合法"}


# ─── ORM 词表订单状态机（OrderStatus 枚举）───
#
# OrderStatus 枚举 vs 蓝图 ORDER_STATES 是两套词表并存。
# 业务代码（cashier_engine / order_service / 支付回调 / split_settle）实际使用 OrderStatus。
# 这套 transition 表保留业务现状的"简化路径"——pending → confirmed → completed | cancelled，
# 同时也允许走完整路径 preparing/ready/served，方便未来对齐。
# 关键作用：拦住非法转换（completed → preparing / cancelled → completed / completed → cancelled 等）。

ORDER_STATUS_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["confirmed", "cancelled"],
    "confirmed": ["preparing", "completed", "cancelled"],
    "preparing": ["ready", "completed", "cancelled"],
    "ready": ["served", "completed", "cancelled"],
    "served": ["completed", "cancelled"],
    "completed": [],  # 终态
    "cancelled": [],  # 终态
}


class InvalidTransitionError(ValueError):
    """订单状态非法转换异常 — Tier1 状态机守卫违规时抛出"""


def can_order_status_transition(current: str, target: str) -> bool:
    """检查 ORM OrderStatus 词表下的订单状态转换是否合法

    与 `can_order_transition` (蓝图词表) 区别：本函数对应 shared.ontology.OrderStatus
    枚举的 7 状态，是业务代码实际使用的词表。
    """
    if current == target:
        # 幂等：相同状态视为合法（避免 idempotent 重试触发 guard 误报）
        return True
    return target in ORDER_STATUS_TRANSITIONS.get(current, [])


def transition_order(order: "Order", target: "OrderStatus") -> "Order":
    """订单状态机守卫 — 业务代码统一入口

    替代直接 `order.status = OrderStatus.X.value` 的赋值。
    内部先校验 `can_order_status_transition`，非法转换抛 `InvalidTransitionError`。

    参数：
        order:  Order ORM 实例（必须已加载，含 .status 字段）
        target: 目标 OrderStatus 枚举值

    返回：
        order（同一实例，便于链式赋值）

    抛出：
        InvalidTransitionError: 当前状态 → 目标状态不合法时
    """
    target_value = target.value if hasattr(target, "value") else str(target)
    current_value = order.status if isinstance(order.status, str) else getattr(order.status, "value", str(order.status))

    if not can_order_status_transition(current_value, target_value):
        raise InvalidTransitionError(
            f"订单状态非法转换: {current_value}({ORDER_STATUS_LABELS.get(current_value, '?')}) "
            f"→ {target_value}({ORDER_STATUS_LABELS.get(target_value, '?')})"
        )

    order.status = target_value
    return order


# ORM OrderStatus 中文标签（用于日志和异常消息）
ORDER_STATUS_LABELS: dict[str, str] = {
    "pending": "待确认",
    "confirmed": "已确认",
    "preparing": "制作中",
    "ready": "就绪",
    "served": "已上菜",
    "completed": "已结账",
    "cancelled": "已取消",
}


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
