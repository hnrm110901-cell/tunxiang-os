"""
工作流 & 审批工单引擎 -- 纯函数实现（无 DB 依赖）

从 V2.x workflow_engine.py + approval_engine.py 迁移提取。
所有函数接受参数、返回结果，不依赖数据库或外部服务。

核心能力：
- 工作流状态机（pending -> approved -> executed 或 pending -> rejected）
- 审批节点定义（单人审批 / 多人会签 / 自动审批）
- 审批链路由与升级
- 阶段 deadline 计算
- 版本 diff
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  状态定义
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"


class ApprovalNodeType(str, Enum):
    """审批节点类型"""
    SINGLE = "single"           # 单人审批
    COUNTERSIGN = "countersign"  # 多人会签（全部通过才算通过）
    AUTO = "auto"               # 自动审批（满足条件自动通过）


class PhaseStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    REVIEWING = "reviewing"
    LOCKED = "locked"
    SKIPPED = "skipped"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  状态机转换
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 合法状态转换表
_VALID_TRANSITIONS: Dict[WorkflowStatus, List[WorkflowStatus]] = {
    WorkflowStatus.PENDING: [
        WorkflowStatus.APPROVED,
        WorkflowStatus.REJECTED,
        WorkflowStatus.ESCALATED,
        WorkflowStatus.CANCELLED,
    ],
    WorkflowStatus.APPROVED: [
        WorkflowStatus.EXECUTED,
    ],
    WorkflowStatus.ESCALATED: [
        WorkflowStatus.APPROVED,
        WorkflowStatus.REJECTED,
        WorkflowStatus.CANCELLED,
    ],
    WorkflowStatus.REJECTED: [],
    WorkflowStatus.EXECUTED: [],
    WorkflowStatus.CANCELLED: [],
}


def can_transition(
    current: WorkflowStatus,
    target: WorkflowStatus,
) -> bool:
    """
    检查工作流状态是否可以从 current 转换到 target。

    Args:
        current: 当前状态
        target: 目标状态

    Returns:
        True 如果转换合法
    """
    allowed = _VALID_TRANSITIONS.get(current, [])
    return target in allowed


def transition(
    current: WorkflowStatus,
    target: WorkflowStatus,
) -> WorkflowStatus:
    """
    执行状态转换。非法转换抛出 ValueError。

    Args:
        current: 当前状态
        target: 目标状态

    Returns:
        新状态

    Raises:
        ValueError: 如果转换不合法
    """
    if not can_transition(current, target):
        raise ValueError(
            f"非法状态转换: {current.value} -> {target.value}"
        )
    return target


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  审批链定义 & 路由
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def build_approval_chain(
    chain_config: List[Dict[str, Any]],
    amount_fen: Optional[int] = None,
    amount_thresholds: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    根据模板配置和金额阈值构建最终审批链。

    Args:
        chain_config: 基础审批链配置
            [{"level": 1, "role": "store_manager", "timeout_hours": 24, "node_type": "single"}, ...]
        amount_fen: 审批金额（分），None 则不触发金额阈值
        amount_thresholds: 金额阈值配置
            [{"threshold_fen": 100000, "extra_approver_role": "area_manager"}, ...]

    Returns:
        排序后的完整审批链
    """
    chain = [step.copy() for step in chain_config]

    if amount_fen is not None and amount_thresholds:
        existing_roles = {step.get("role") for step in chain}
        for threshold in sorted(amount_thresholds, key=lambda t: t.get("threshold_fen", 0)):
            thr = threshold.get("threshold_fen", 0)
            extra_role = threshold.get("extra_approver_role")
            if amount_fen >= thr and extra_role and extra_role not in existing_roles:
                new_level = max((s.get("level", 0) for s in chain), default=0) + 1
                chain.append({
                    "level": new_level,
                    "role": extra_role,
                    "timeout_hours": threshold.get("timeout_hours", 72),
                    "node_type": threshold.get("node_type", "single"),
                })
                existing_roles.add(extra_role)

    chain.sort(key=lambda s: s.get("level", 0))
    return chain


def find_step_by_level(
    chain: List[Dict[str, Any]],
    level: int,
) -> Optional[Dict[str, Any]]:
    """
    在审批链中找到指定 level 的步骤。

    Args:
        chain: 审批链
        level: 目标级别

    Returns:
        匹配的步骤 dict，或 None
    """
    for step in chain:
        if step.get("level") == level:
            return step
    return None


def find_next_step(
    chain: List[Dict[str, Any]],
    current_level: int,
) -> Optional[Dict[str, Any]]:
    """
    找到下一级审批步骤。

    Args:
        chain: 审批链（需已排序）
        current_level: 当前级别

    Returns:
        下一步骤 dict，或 None（已是最后一级）
    """
    sorted_chain = sorted(chain, key=lambda s: s.get("level", 0))
    for step in sorted_chain:
        if step.get("level", 0) > current_level:
            return step
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  审批动作处理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def process_approve(
    current_status: WorkflowStatus,
    current_level: int,
    chain: List[Dict[str, Any]],
    approver_id: str,
    comment: str = "",
) -> Dict[str, Any]:
    """
    处理审批通过动作。

    Args:
        current_status: 当前工单状态
        current_level: 当前审批级别
        chain: 完整审批链
        approver_id: 审批人 ID
        comment: 审批意见

    Returns:
        {
            "new_status": WorkflowStatus,
            "new_level": int | None,
            "is_final": bool,
            "next_step": dict | None,
            "record": dict,  # 审批记录
        }

    Raises:
        ValueError: 当前状态不允许审批
    """
    if current_status not in (WorkflowStatus.PENDING, WorkflowStatus.ESCALATED):
        raise ValueError(f"当前状态 {current_status.value} 不允许审批操作")

    current_step = find_step_by_level(chain, current_level)
    current_role = current_step.get("role", "") if current_step else ""

    next_step = find_next_step(chain, current_level)

    record = {
        "level": current_level,
        "approver_id": approver_id,
        "approver_role": current_role,
        "action": "approve",
        "comment": comment,
    }

    if next_step is None:
        # 最后一级，审批完成
        return {
            "new_status": WorkflowStatus.APPROVED,
            "new_level": None,
            "is_final": True,
            "next_step": None,
            "record": record,
        }
    else:
        # 推进到下一级
        return {
            "new_status": current_status,  # 状态保持 PENDING/ESCALATED
            "new_level": next_step.get("level"),
            "is_final": False,
            "next_step": next_step,
            "record": record,
        }


def process_reject(
    current_status: WorkflowStatus,
    current_level: int,
    chain: List[Dict[str, Any]],
    approver_id: str,
    reason: str = "",
) -> Dict[str, Any]:
    """
    处理审批驳回动作。

    Args:
        current_status: 当前工单状态
        current_level: 当前审批级别
        chain: 完整审批链
        approver_id: 审批人 ID
        reason: 驳回原因

    Returns:
        {
            "new_status": WorkflowStatus.REJECTED,
            "record": dict,
        }

    Raises:
        ValueError: 当前状态不允许驳回
    """
    if current_status not in (WorkflowStatus.PENDING, WorkflowStatus.ESCALATED):
        raise ValueError(f"当前状态 {current_status.value} 不允许驳回操作")

    current_step = find_step_by_level(chain, current_level)
    current_role = current_step.get("role", "") if current_step else ""

    return {
        "new_status": WorkflowStatus.REJECTED,
        "record": {
            "level": current_level,
            "approver_id": approver_id,
            "approver_role": current_role,
            "action": "reject",
            "comment": reason,
        },
    }


def process_escalate(
    current_status: WorkflowStatus,
    current_level: int,
    chain: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    处理超时自动升级动作。

    Args:
        current_status: 当前工单状态
        current_level: 当前审批级别
        chain: 完整审批链

    Returns:
        {
            "new_status": WorkflowStatus,
            "new_level": int | None,
            "next_step": dict | None,
            "escalated": bool,
            "record": dict,
        }
    """
    if current_status not in (WorkflowStatus.PENDING, WorkflowStatus.ESCALATED):
        raise ValueError(f"当前状态 {current_status.value} 不支持升级")

    next_step = find_next_step(chain, current_level)

    record = {
        "level": current_level,
        "approver_id": "system",
        "approver_role": "system",
        "action": "escalate",
        "comment": "",
    }

    if next_step:
        record["comment"] = f"审批超期，自动升级至第{next_step.get('level')}级"
        return {
            "new_status": WorkflowStatus.ESCALATED,
            "new_level": next_step.get("level"),
            "next_step": next_step,
            "escalated": True,
            "record": record,
        }
    else:
        # 已是最后一级，无法升级，保持当前状态
        record["comment"] = "已是最后一级，无法升级，发送催办"
        return {
            "new_status": current_status,
            "new_level": current_level,
            "next_step": None,
            "escalated": False,
            "record": record,
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  会签处理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def check_countersign_complete(
    required_approvers: List[str],
    approved_by: List[str],
) -> Tuple[bool, List[str]]:
    """
    检查会签是否已全部完成。

    Args:
        required_approvers: 需要审批的人员 ID 列表
        approved_by: 已通过审批的人员 ID 列表

    Returns:
        (is_complete, remaining_approvers)
    """
    remaining = [a for a in required_approvers if a not in approved_by]
    return (len(remaining) == 0, remaining)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Deadline 计算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def calc_phase_deadline(
    trigger_date: date,
    deadline_hour: int,
    deadline_minute: int = 0,
    custom_deadline: Optional[str] = None,
) -> datetime:
    """
    计算阶段硬 deadline。

    Args:
        trigger_date: 触发日期
        deadline_hour: 截止小时
        deadline_minute: 截止分钟
        custom_deadline: 自定义截止时间 "HH:MM"（覆盖默认值）

    Returns:
        deadline datetime
    """
    hour = deadline_hour
    minute = deadline_minute

    if custom_deadline and ":" in str(custom_deadline):
        parts = str(custom_deadline).split(":")
        hour = int(parts[0])
        minute = int(parts[1])

    return datetime(
        trigger_date.year,
        trigger_date.month,
        trigger_date.day,
        hour,
        minute,
        0,
    )


def calc_approval_deadline(
    timeout_hours: int = 24,
    from_time: Optional[datetime] = None,
) -> datetime:
    """
    计算审批超时时间。

    Args:
        timeout_hours: 超时小时数
        from_time: 起始时间（默认 utcnow）

    Returns:
        deadline datetime
    """
    base = from_time or datetime.utcnow()
    return base + timedelta(hours=timeout_hours)


def is_phase_expired(
    deadline: datetime,
    now: Optional[datetime] = None,
) -> bool:
    """
    判断阶段是否已过期。

    Args:
        deadline: 阶段截止时间
        now: 当前时间（默认 utcnow）

    Returns:
        True 如果已过期
    """
    current = now or datetime.utcnow()
    return current > deadline


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  版本 Diff
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def simple_diff(
    prev: Dict[str, Any],
    curr: Dict[str, Any],
) -> Dict[str, Any]:
    """
    计算两个 dict 的简单 diff（只处理一层 key 变化）。

    Args:
        prev: 前一版本内容
        curr: 当前版本内容

    Returns:
        {"added": {...}, "removed": {...}, "modified": {...}}
    """
    added = {k: curr[k] for k in curr if k not in prev}
    removed = {k: prev[k] for k in prev if k not in curr}
    modified = {
        k: {"before": prev[k], "after": curr[k]}
        for k in curr
        if k in prev and prev[k] != curr[k]
    }
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  角色映射（从 V2.x approval_engine 迁移）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


ROLE_TO_POSITION_MAP: Dict[str, List[str]] = {
    "store_manager": ["manager", "store_manager", "店长"],
    "area_manager": ["area_manager", "区域经理", "督导"],
    "hr_director": ["hr_director", "hr_manager", "人事总监", "人事经理"],
    "ceo": ["ceo", "boss", "总经理", "老板"],
    "finance_director": ["finance_director", "财务总监"],
    "chef_head": ["chef_head", "厨师长", "行政总厨"],
}


def resolve_role_from_position(position: str) -> Optional[str]:
    """
    根据职位名反查审批角色。

    Args:
        position: 员工职位名

    Returns:
        审批角色名，未匹配返回 None
    """
    for role, positions in ROLE_TO_POSITION_MAP.items():
        if position in positions:
            return role
    return None


def get_positions_for_role(role: str) -> List[str]:
    """
    获取审批角色对应的所有职位名称。

    Args:
        role: 审批角色名

    Returns:
        职位名称列表
    """
    return ROLE_TO_POSITION_MAP.get(role, [role])
