"""
日清 E1-E8 运营节点追踪服务

设计：
- 每天开始时自动初始化当天的 DailyReviewState（8个节点全部 PENDING）
- 当业务事件触发时，对应节点变为 COMPLETED
- 超时未完成的节点标记为 OVERDUE
- 可以手动标记节点（管理员手动确认）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from enum import Enum
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class NodeStatus(str, Enum):
    PENDING = "pending"  # 未开始/未到时间
    IN_PROGRESS = "in_progress"  # 进行中
    COMPLETED = "completed"  # 已完成
    OVERDUE = "overdue"  # 超时未完成
    SKIPPED = "skipped"  # 已跳过（如今日未营业）


@dataclass
class DailyNode:
    node_id: str  # E1-E8
    name: str
    deadline: time  # 当天截止时间
    status: NodeStatus = NodeStatus.PENDING
    completed_at: Optional[str] = None
    completed_by: Optional[str] = None  # employee_id or "system"
    notes: Optional[str] = None
    trigger_event: Optional[str] = None  # 触发完成的事件类型


# E1-E8 节点定义
DAILY_NODES: list[dict] = [
    {"node_id": "E1", "name": "晨会确认", "deadline": time(9, 0), "icon": "🌅"},
    {"node_id": "E2", "name": "备料完成", "deadline": time(10, 30), "icon": "📦"},
    {"node_id": "E3", "name": "开店就绪", "deadline": time(11, 0), "icon": "🚪"},
    {"node_id": "E4", "name": "午市复盘", "deadline": time(14, 30), "icon": "📊"},
    {"node_id": "E5", "name": "下午备料", "deadline": time(15, 30), "icon": "🔄"},
    {"node_id": "E6", "name": "晚市开始", "deadline": time(17, 30), "icon": "🌆"},
    {"node_id": "E7", "name": "日结完成", "deadline": time(23, 0), "icon": "💰"},
    {"node_id": "E8", "name": "次日计划", "deadline": time(23, 59), "icon": "📋"},
]

# 事件类型 → 节点映射
EVENT_NODE_MAP: dict[str, str] = {
    "ops.daily_review.morning_meeting": "E1",
    "supply.receiving.completed": "E2",  # 收货完成 → 备料完成
    "trade.shift.opened": "E3",  # 开班 → 开店就绪
    "trade.daily_settlement.completed": "E7",  # 日结 → E7
    "ops.daily_review.e7_settlement_done": "E7",
    "ops.daily_review.next_day_plan": "E8",
}


@dataclass
class DailyReviewState:
    date: str  # YYYY-MM-DD
    store_id: str
    tenant_id: str
    nodes: list[DailyNode] = field(default_factory=list)

    @property
    def completion_rate(self) -> float:
        completed = sum(1 for n in self.nodes if n.status == NodeStatus.COMPLETED)
        return completed / len(self.nodes) if self.nodes else 0.0

    @property
    def overdue_nodes(self) -> list[DailyNode]:
        return [n for n in self.nodes if n.status == NodeStatus.OVERDUE]

    @property
    def health_score(self) -> int:
        """0-100 经营健康分"""
        base = int(self.completion_rate * 80)
        overdue_penalty = len(self.overdue_nodes) * 5
        return max(0, min(100, base - overdue_penalty))


class DailyReviewService:
    """日清状态管理（内存 + 定时刷新，生产可换 Redis）"""

    _states: dict[str, DailyReviewState] = {}  # key: f"{tenant_id}:{store_id}:{date}"

    @classmethod
    def _make_key(cls, tenant_id: str, store_id: str, date: str) -> str:
        return f"{tenant_id}:{store_id}:{date}"

    @classmethod
    def get_today_state(cls, tenant_id: str, store_id: str) -> DailyReviewState:
        """获取今日状态，不存在则初始化"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = cls._make_key(tenant_id, store_id, today)

        if key not in cls._states:
            nodes = [
                DailyNode(
                    node_id=n["node_id"],
                    name=n["name"],
                    deadline=n["deadline"],
                )
                for n in DAILY_NODES
            ]
            cls._states[key] = DailyReviewState(date=today, store_id=store_id, tenant_id=tenant_id, nodes=nodes)

        # 检查超时
        cls._check_overdue(cls._states[key])
        return cls._states[key]

    @classmethod
    def mark_node_completed(
        cls,
        tenant_id: str,
        store_id: str,
        node_id: str,
        completed_by: str = "system",
        notes: Optional[str] = None,
        trigger_event: Optional[str] = None,
    ) -> bool:
        """标记节点完成"""
        state = cls.get_today_state(tenant_id, store_id)
        for node in state.nodes:
            if node.node_id == node_id and node.status not in (
                NodeStatus.COMPLETED,
                NodeStatus.SKIPPED,
            ):
                node.status = NodeStatus.COMPLETED
                node.completed_at = datetime.now(timezone.utc).isoformat()
                node.completed_by = completed_by
                node.notes = notes
                node.trigger_event = trigger_event
                logger.info(
                    "daily_node_completed",
                    tenant_id=tenant_id,
                    store_id=store_id,
                    node_id=node_id,
                    by=completed_by,
                )
                return True
        return False

    @classmethod
    def handle_event(cls, tenant_id: str, store_id: str, event_type: str) -> Optional[str]:
        """根据事件类型自动推进节点，返回被推进的节点ID（如有）"""
        node_id = EVENT_NODE_MAP.get(event_type)
        if node_id:
            success = cls.mark_node_completed(
                tenant_id,
                store_id,
                node_id,
                completed_by="system",
                trigger_event=event_type,
            )
            return node_id if success else None
        return None

    @classmethod
    def _check_overdue(cls, state: DailyReviewState) -> None:
        now = datetime.now(timezone.utc).astimezone().time()
        for node in state.nodes:
            if node.status == NodeStatus.PENDING and now > node.deadline:
                node.status = NodeStatus.OVERDUE

    @classmethod
    def get_multi_store_summary(cls, tenant_id: str, store_ids: list[str]) -> list[dict]:
        """多门店日清汇总（用于总部驾驶舱）"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = []
        for store_id in store_ids:
            key = cls._make_key(tenant_id, store_id, today)
            if key in cls._states:
                state = cls._states[key]
                result.append(
                    {
                        "store_id": store_id,
                        "date": today,
                        "completion_rate": state.completion_rate,
                        "health_score": state.health_score,
                        "completed_count": sum(1 for n in state.nodes if n.status == NodeStatus.COMPLETED),
                        "overdue_count": len(state.overdue_nodes),
                        "nodes": [
                            {
                                "node_id": n.node_id,
                                "status": n.status,
                                "name": n.name,
                            }
                            for n in state.nodes
                        ],
                    }
                )
            else:
                result.append(
                    {
                        "store_id": store_id,
                        "date": today,
                        "completion_rate": 0.0,
                        "health_score": 0,
                        "completed_count": 0,
                        "overdue_count": 0,
                        "nodes": [
                            {
                                "node_id": n["node_id"],
                                "status": "pending",
                                "name": n["name"],
                            }
                            for n in DAILY_NODES
                        ],
                    }
                )
        return result
