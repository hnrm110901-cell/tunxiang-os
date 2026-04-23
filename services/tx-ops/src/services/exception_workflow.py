"""E4 异常处置 — 异常上报、升级处理、关闭、查询

异常类型: discount/refund/cashier/food_safety/shortage/complaint/equipment
集成 workflow_engine 状态机做升级流转。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from .workflow_engine import WorkflowStatus, transition

log = structlog.get_logger(__name__)

# ─── 异常类型定义 ───

EXCEPTION_TYPES = {
    "discount": "折扣异常",
    "refund": "退款/退菜",
    "cashier": "收银差异",
    "food_safety": "食品安全",
    "shortage": "缺料/断货",
    "complaint": "客户投诉",
    "equipment": "设备故障",
}

# 升级层级定义
ESCALATION_LEVELS = {
    1: "门店值班经理",
    2: "门店店长",
    3: "区域经理",
    4: "运营总监",
}

# 食安类异常默认直接升级到区域经理
FOOD_SAFETY_ESCALATION_LEVEL = 3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  异常上报
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def report_exception(
    store_id: str,
    type_: str,
    detail: Dict[str, Any],
    reporter_id: str,
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """上报异常。

    Args:
        store_id: 门店 ID
        type_: 异常类型 (discount/refund/cashier/food_safety/shortage/complaint/equipment)
        detail: 异常详情 {"description": str, "amount_fen": int, "related_order_id": str, ...}
        reporter_id: 上报人 ID
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"exception_id": str, "type": str, "status": str, "level": int, ...}

    Raises:
        ValueError: 未知的异常类型
    """
    if type_ not in EXCEPTION_TYPES:
        valid = ", ".join(EXCEPTION_TYPES.keys())
        raise ValueError(f"Unknown exception type: '{type_}'. Valid types: {valid}")

    exception_id = f"exc_{store_id}_{uuid.uuid4().hex[:8]}"

    # 食安类异常自动升级到区域经理
    initial_level = FOOD_SAFETY_ESCALATION_LEVEL if type_ == "food_safety" else 1

    exception = {
        "exception_id": exception_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "type": type_,
        "type_label": EXCEPTION_TYPES[type_],
        "detail": detail,
        "status": WorkflowStatus.PENDING.value,
        "level": initial_level,
        "level_label": ESCALATION_LEVELS.get(initial_level, ""),
        "reporter_id": reporter_id,
        "reported_at": datetime.utcnow().isoformat(),
        "resolution": None,
        "resolved_by": None,
        "resolved_at": None,
        "history": [
            {
                "action": "reported",
                "by": reporter_id,
                "at": datetime.utcnow().isoformat(),
                "note": f"异常上报: {EXCEPTION_TYPES[type_]}",
            }
        ],
    }

    log.info(
        "exception_reported",
        store_id=store_id,
        tenant_id=tenant_id,
        exception_id=exception_id,
        type=type_,
        level=initial_level,
        reporter_id=reporter_id,
    )
    return exception


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  升级处理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def escalate_exception(
    exception_id: str,
    to_level: int,
    tenant_id: str,
    db: Any,
    *,
    exception: Optional[Dict[str, Any]] = None,
    operator_id: str = "system",
) -> Dict[str, Any]:
    """升级异常处理层级。

    Args:
        exception_id: 异常 ID
        to_level: 目标层级
        tenant_id: 租户 ID
        db: 数据库会话
        exception: 已加载的异常（避免重复查库）
        operator_id: 操作人 ID

    Returns:
        {"escalated": bool, "exception_id": str, "from_level": int,
         "to_level": int, "level_label": str}

    Raises:
        ValueError: 无效的升级目标
    """
    if to_level not in ESCALATION_LEVELS:
        raise ValueError(f"Invalid escalation level: {to_level}. Valid: {list(ESCALATION_LEVELS.keys())}")

    if exception is None:
        raise ValueError(f"Exception '{exception_id}' not found — pass exception explicitly or implement DB lookup")

    from_level = exception.get("level", 1)
    if to_level <= from_level:
        raise ValueError(f"Cannot escalate from level {from_level} to {to_level} (must escalate upward)")

    current_status = WorkflowStatus(exception.get("status", "pending"))
    new_status = transition(current_status, WorkflowStatus.ESCALATED)

    exception["level"] = to_level
    exception["level_label"] = ESCALATION_LEVELS[to_level]
    exception["status"] = new_status.value
    exception.get("history", []).append(
        {
            "action": "escalated",
            "by": operator_id,
            "at": datetime.utcnow().isoformat(),
            "note": f"升级至 {ESCALATION_LEVELS[to_level]} (Level {to_level})",
        }
    )

    log.info(
        "exception_escalated",
        exception_id=exception_id,
        tenant_id=tenant_id,
        from_level=from_level,
        to_level=to_level,
    )

    return {
        "escalated": True,
        "exception_id": exception_id,
        "from_level": from_level,
        "to_level": to_level,
        "level_label": ESCALATION_LEVELS[to_level],
        "status": new_status.value,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  关闭异常
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def resolve_exception(
    exception_id: str,
    resolution: Dict[str, Any],
    resolver_id: str,
    tenant_id: str,
    db: Any,
    *,
    exception: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """关闭/解决异常。

    Args:
        exception_id: 异常 ID
        resolution: 解决方案 {"action_taken": str, "root_cause": str, "preventive_measure": str}
        resolver_id: 解决人 ID
        tenant_id: 租户 ID
        db: 数据库会话
        exception: 已加载的异常

    Returns:
        {"resolved": bool, "exception_id": str, "resolved_by": str, "resolved_at": str}

    Raises:
        ValueError: 异常已关闭 / 状态不允许
    """
    if exception is None:
        raise ValueError(f"Exception '{exception_id}' not found — pass exception explicitly or implement DB lookup")

    current_status = WorkflowStatus(exception.get("status", "pending"))
    if current_status in (WorkflowStatus.EXECUTED, WorkflowStatus.CANCELLED):
        raise ValueError(f"Exception already in terminal state: {current_status.value}")

    # pending/escalated -> approved -> executed
    if current_status in (WorkflowStatus.PENDING, WorkflowStatus.ESCALATED):
        approved_status = transition(current_status, WorkflowStatus.APPROVED)
        final_status = transition(approved_status, WorkflowStatus.EXECUTED)
    elif current_status == WorkflowStatus.APPROVED:
        final_status = transition(current_status, WorkflowStatus.EXECUTED)
    else:
        raise ValueError(f"Cannot resolve from status: {current_status.value}")

    resolved_at = datetime.utcnow().isoformat()
    exception["status"] = final_status.value
    exception["resolution"] = resolution
    exception["resolved_by"] = resolver_id
    exception["resolved_at"] = resolved_at
    exception.get("history", []).append(
        {
            "action": "resolved",
            "by": resolver_id,
            "at": resolved_at,
            "note": f"异常已解决: {resolution.get('action_taken', '')}",
        }
    )

    log.info(
        "exception_resolved",
        exception_id=exception_id,
        tenant_id=tenant_id,
        resolver_id=resolver_id,
    )

    return {
        "resolved": True,
        "exception_id": exception_id,
        "resolved_by": resolver_id,
        "resolved_at": resolved_at,
        "status": final_status.value,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  查询未关闭异常
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_open_exceptions(
    store_id: str,
    tenant_id: str,
    db: Any,
    *,
    exceptions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """获取门店未关闭异常列表。

    Args:
        store_id: 门店 ID
        tenant_id: 租户 ID
        db: 数据库会话
        exceptions: 全部异常列表（测试注入用，实际从 db 查询）

    Returns:
        {"store_id": str, "items": [...], "total": int,
         "by_type": {...}, "by_level": {...}}
    """
    terminal_statuses = {WorkflowStatus.EXECUTED.value, WorkflowStatus.CANCELLED.value}
    open_items = [
        exc
        for exc in (exceptions or [])
        if exc.get("status") not in terminal_statuses and exc.get("store_id") == store_id
    ]

    # 按类型统计
    by_type: Dict[str, int] = {}
    for exc in open_items:
        t = exc.get("type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1

    # 按层级统计
    by_level: Dict[int, int] = {}
    for exc in open_items:
        lvl = exc.get("level", 0)
        by_level[lvl] = by_level.get(lvl, 0) + 1

    return {
        "store_id": store_id,
        "tenant_id": tenant_id,
        "items": open_items,
        "total": len(open_items),
        "by_type": by_type,
        "by_level": by_level,
    }
