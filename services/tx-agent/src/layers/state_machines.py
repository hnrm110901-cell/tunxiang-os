"""L5 状态机与规则引擎 — 核心业务状态机定义

所有高确定性业务在此层执行。Agent 可查询状态但不能绕过状态机直接修改。

包含：
- 桌态状态机 (TableStateMachine)
- 订单状态机 (OrderStateMachine)
- 出品状态机 (KitchenStateMachine)
- 结算状态机 (SettlementStateMachine)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import structlog

logger = structlog.get_logger()


# ── 通用状态转换 ──────────────────────────────────────────────────────────────

class TransitionError(Exception):
    """非法状态转换"""


@dataclass
class StateTransition:
    """状态转换记录"""
    from_state: str
    to_state: str
    trigger: str
    actor_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class StateMachine:
    """通用状态机基类"""

    # 子类定义: {当前状态: [允许的目标状态]}
    TRANSITIONS: dict[str, list[str]] = {}

    def __init__(self, entity_id: str, initial_state: str):
        self.entity_id = entity_id
        self.current_state = initial_state
        self.history: list[StateTransition] = []

    def can_transition(self, to_state: str) -> bool:
        allowed = self.TRANSITIONS.get(self.current_state, [])
        return to_state in allowed

    def transition(
        self,
        to_state: str,
        trigger: str,
        actor_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> StateTransition:
        if not self.can_transition(to_state):
            raise TransitionError(
                f"{self.__class__.__name__}: {self.current_state} → {to_state} 不允许。"
                f"允许的转换: {self.TRANSITIONS.get(self.current_state, [])}"
            )

        record = StateTransition(
            from_state=self.current_state,
            to_state=to_state,
            trigger=trigger,
            actor_id=actor_id,
            metadata=metadata or {},
        )
        self.history.append(record)
        prev = self.current_state
        self.current_state = to_state

        logger.info(
            "state_transition",
            machine=self.__class__.__name__,
            entity_id=self.entity_id,
            from_state=prev,
            to_state=to_state,
            trigger=trigger,
        )
        return record

    def get_allowed_transitions(self) -> list[str]:
        return self.TRANSITIONS.get(self.current_state, [])


# ── 桌态状态机 ────────────────────────────────────────────────────────────────

class TableState(str, Enum):
    AVAILABLE = "available"       # 空闲
    RESERVED = "reserved"         # 已预订
    SEATING = "seating"           # 入座中
    OCCUPIED = "occupied"         # 用餐中
    CLEANING = "cleaning"         # 清台中
    MAINTENANCE = "maintenance"   # 维护中


class TableStateMachine(StateMachine):
    """桌态状态机

    状态流转：
    available → reserved → seating → occupied → cleaning → available
                                                         → maintenance
    """
    TRANSITIONS = {
        TableState.AVAILABLE.value: [
            TableState.RESERVED.value,
            TableState.SEATING.value,
            TableState.MAINTENANCE.value,
        ],
        TableState.RESERVED.value: [
            TableState.SEATING.value,
            TableState.AVAILABLE.value,   # 取消预订
        ],
        TableState.SEATING.value: [
            TableState.OCCUPIED.value,
            TableState.AVAILABLE.value,   # 客人未到
        ],
        TableState.OCCUPIED.value: [
            TableState.CLEANING.value,
        ],
        TableState.CLEANING.value: [
            TableState.AVAILABLE.value,
            TableState.MAINTENANCE.value,
        ],
        TableState.MAINTENANCE.value: [
            TableState.AVAILABLE.value,
        ],
    }

    def __init__(self, table_id: str, initial_state: str = TableState.AVAILABLE.value):
        super().__init__(table_id, initial_state)


# ── 订单状态机 ────────────────────────────────────────────────────────────────

class OrderState(str, Enum):
    CREATED = "created"           # 已创建
    CONFIRMED = "confirmed"       # 已确认
    PREPARING = "preparing"       # 制作中
    PARTIALLY_SERVED = "partially_served"  # 部分出餐
    SERVED = "served"             # 已出齐
    PAYING = "paying"             # 结账中
    PAID = "paid"                 # 已支付
    COMPLETED = "completed"       # 已完成
    CANCELLED = "cancelled"       # 已取消
    REFUNDING = "refunding"       # 退款中
    REFUNDED = "refunded"         # 已退款


class OrderStateMachine(StateMachine):
    """订单状态机

    主流程: created → confirmed → preparing → served → paying → paid → completed
    异常流程: 任意阶段可取消（支付后需退款）
    """
    TRANSITIONS = {
        OrderState.CREATED.value: [
            OrderState.CONFIRMED.value,
            OrderState.CANCELLED.value,
        ],
        OrderState.CONFIRMED.value: [
            OrderState.PREPARING.value,
            OrderState.CANCELLED.value,
        ],
        OrderState.PREPARING.value: [
            OrderState.PARTIALLY_SERVED.value,
            OrderState.SERVED.value,
            OrderState.CANCELLED.value,
        ],
        OrderState.PARTIALLY_SERVED.value: [
            OrderState.SERVED.value,
            OrderState.CANCELLED.value,
        ],
        OrderState.SERVED.value: [
            OrderState.PAYING.value,
        ],
        OrderState.PAYING.value: [
            OrderState.PAID.value,
            OrderState.SERVED.value,  # 支付失败回退
        ],
        OrderState.PAID.value: [
            OrderState.COMPLETED.value,
            OrderState.REFUNDING.value,
        ],
        OrderState.COMPLETED.value: [
            OrderState.REFUNDING.value,
        ],
        OrderState.REFUNDING.value: [
            OrderState.REFUNDED.value,
        ],
        OrderState.CANCELLED.value: [],
        OrderState.REFUNDED.value: [],
    }

    def __init__(self, order_id: str, initial_state: str = OrderState.CREATED.value):
        super().__init__(order_id, initial_state)


# ── 出品状态机 ────────────────────────────────────────────────────────────────

class KitchenItemState(str, Enum):
    QUEUED = "queued"             # 排队中
    ACCEPTED = "accepted"         # 已接单
    PREPARING = "preparing"       # 制作中
    QUALITY_CHECK = "quality_check"  # 质检
    READY = "ready"               # 待传菜
    DELIVERING = "delivering"     # 传菜中
    DELIVERED = "delivered"       # 已上桌
    RETURNED = "returned"         # 退菜


class KitchenStateMachine(StateMachine):
    """出品状态机（单道菜）

    流程: queued → accepted → preparing → quality_check → ready → delivering → delivered
    异常: 任意制作前可退菜
    """
    TRANSITIONS = {
        KitchenItemState.QUEUED.value: [
            KitchenItemState.ACCEPTED.value,
            KitchenItemState.RETURNED.value,
        ],
        KitchenItemState.ACCEPTED.value: [
            KitchenItemState.PREPARING.value,
            KitchenItemState.RETURNED.value,
        ],
        KitchenItemState.PREPARING.value: [
            KitchenItemState.QUALITY_CHECK.value,
            KitchenItemState.READY.value,   # 小店可跳过质检
            KitchenItemState.RETURNED.value,
        ],
        KitchenItemState.QUALITY_CHECK.value: [
            KitchenItemState.READY.value,
            KitchenItemState.PREPARING.value,  # 质检不通过重做
        ],
        KitchenItemState.READY.value: [
            KitchenItemState.DELIVERING.value,
        ],
        KitchenItemState.DELIVERING.value: [
            KitchenItemState.DELIVERED.value,
            KitchenItemState.RETURNED.value,  # 上桌被退
        ],
        KitchenItemState.DELIVERED.value: [],
        KitchenItemState.RETURNED.value: [],
    }

    def __init__(self, item_id: str, initial_state: str = KitchenItemState.QUEUED.value):
        super().__init__(item_id, initial_state)


# ── 结算状态机 ────────────────────────────────────────────────────────────────

class SettlementState(str, Enum):
    OPEN = "open"                 # 营业中
    PRE_CLOSING = "pre_closing"   # 预结算（日清检查）
    CLOSING = "closing"           # 结算中
    CLOSED = "closed"             # 已结算
    AUDITED = "audited"           # 已审核
    LOCKED = "locked"             # 已锁账


class SettlementStateMachine(StateMachine):
    """结算状态机（日清日结）

    流程: open → pre_closing → closing → closed → audited → locked
    """
    TRANSITIONS = {
        SettlementState.OPEN.value: [
            SettlementState.PRE_CLOSING.value,
        ],
        SettlementState.PRE_CLOSING.value: [
            SettlementState.CLOSING.value,
            SettlementState.OPEN.value,  # 发现问题回退
        ],
        SettlementState.CLOSING.value: [
            SettlementState.CLOSED.value,
        ],
        SettlementState.CLOSED.value: [
            SettlementState.AUDITED.value,
        ],
        SettlementState.AUDITED.value: [
            SettlementState.LOCKED.value,
            SettlementState.CLOSED.value,  # 审核不通过回退
        ],
        SettlementState.LOCKED.value: [],
    }

    def __init__(self, store_date_id: str, initial_state: str = SettlementState.OPEN.value):
        super().__init__(store_date_id, initial_state)


# ── 状态机注册表 ──────────────────────────────────────────────────────────────

class StateMachineRegistry:
    """状态机注册表 — 管理所有活跃状态机实例

    Agent 通过此注册表查询业务状态，但不能绕过状态机直接修改。
    """

    def __init__(self) -> None:
        self._tables: dict[str, TableStateMachine] = {}
        self._orders: dict[str, OrderStateMachine] = {}
        self._kitchen_items: dict[str, KitchenStateMachine] = {}
        self._settlements: dict[str, SettlementStateMachine] = {}

    # ── 桌台 ──

    def get_or_create_table(
        self, table_id: str, initial_state: str = TableState.AVAILABLE.value,
    ) -> TableStateMachine:
        if table_id not in self._tables:
            self._tables[table_id] = TableStateMachine(table_id, initial_state)
        return self._tables[table_id]

    def get_table(self, table_id: str) -> Optional[TableStateMachine]:
        return self._tables.get(table_id)

    # ── 订单 ──

    def get_or_create_order(
        self, order_id: str, initial_state: str = OrderState.CREATED.value,
    ) -> OrderStateMachine:
        if order_id not in self._orders:
            self._orders[order_id] = OrderStateMachine(order_id, initial_state)
        return self._orders[order_id]

    def get_order(self, order_id: str) -> Optional[OrderStateMachine]:
        return self._orders.get(order_id)

    # ── 厨房出品 ──

    def get_or_create_kitchen_item(
        self, item_id: str, initial_state: str = KitchenItemState.QUEUED.value,
    ) -> KitchenStateMachine:
        if item_id not in self._kitchen_items:
            self._kitchen_items[item_id] = KitchenStateMachine(item_id, initial_state)
        return self._kitchen_items[item_id]

    def get_kitchen_item(self, item_id: str) -> Optional[KitchenStateMachine]:
        return self._kitchen_items.get(item_id)

    # ── 日结 ──

    def get_or_create_settlement(
        self, store_date_id: str, initial_state: str = SettlementState.OPEN.value,
    ) -> SettlementStateMachine:
        if store_date_id not in self._settlements:
            self._settlements[store_date_id] = SettlementStateMachine(store_date_id, initial_state)
        return self._settlements[store_date_id]

    def get_settlement(self, store_date_id: str) -> Optional[SettlementStateMachine]:
        return self._settlements.get(store_date_id)

    def get_store_status_summary(self, store_id: str) -> dict:
        """获取门店状态摘要（供 Agent 查询）"""
        tables_by_state: dict[str, int] = {}
        for t in self._tables.values():
            tables_by_state[t.current_state] = tables_by_state.get(t.current_state, 0) + 1

        orders_by_state: dict[str, int] = {}
        for o in self._orders.values():
            orders_by_state[o.current_state] = orders_by_state.get(o.current_state, 0) + 1

        kitchen_by_state: dict[str, int] = {}
        for k in self._kitchen_items.values():
            kitchen_by_state[k.current_state] = kitchen_by_state.get(k.current_state, 0) + 1

        return {
            "store_id": store_id,
            "tables": tables_by_state,
            "orders": orders_by_state,
            "kitchen_items": kitchen_by_state,
            "total_tables": len(self._tables),
            "total_orders": len(self._orders),
            "total_kitchen_items": len(self._kitchen_items),
        }
