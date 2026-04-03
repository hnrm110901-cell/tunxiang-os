"""D8 问题追踪 — 门店问题清单、派发、进度、红黄绿看板、跨店对标

支持问题全生命周期管理：创建→派发→处理中→已解决→已验证。
红黄绿分级：overdue=红, deadline<3d=黄, on_track=绿。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

# 问题状态机
VALID_STATUSES = ("open", "assigned", "in_progress", "resolved", "verified")
STATUS_TRANSITIONS = {
    "open": ("assigned",),
    "assigned": ("in_progress", "open"),
    "in_progress": ("resolved", "assigned"),
    "resolved": ("verified", "in_progress"),
    "verified": (),
}

# 红黄绿分级阈值
_YELLOW_THRESHOLD_DAYS = 3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  创建问题
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_issue(
    store_id: str,
    issue_type: str,
    description: str,
    reporter_id: str,
    tenant_id: str,
    db: Any,
    *,
    priority: str = "medium",
    deadline: Optional[str] = None,
) -> Dict[str, Any]:
    """创建门店问题。

    Args:
        store_id: 门店 ID
        issue_type: 问题类型 (food_safety/cost/service/equipment/hygiene/other)
        description: 问题描述
        reporter_id: 报告人 ID
        tenant_id: 租户 ID
        db: 数据库会话
        priority: 优先级 (low/medium/high/critical)
        deadline: 截止日期 (YYYY-MM-DD)

    Returns:
        {"issue_id", "store_id", "type", "status", "priority", ...}
    """
    issue_id = f"issue_{store_id}_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()

    issue = {
        "issue_id": issue_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "type": issue_type,
        "description": description,
        "reporter_id": reporter_id,
        "assignee_id": None,
        "status": "open",
        "priority": priority,
        "deadline": deadline,
        "notes": [],
        "created_at": now,
        "updated_at": now,
    }

    log.info(
        "issue_created",
        issue_id=issue_id,
        store_id=store_id,
        tenant_id=tenant_id,
        issue_type=issue_type,
        priority=priority,
    )
    return issue


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  派发
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def assign_issue(
    issue_id: str,
    assignee_id: str,
    deadline: str,
    tenant_id: str,
    db: Any,
    *,
    issue: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """将问题派发给责任人。

    Args:
        issue_id: 问题 ID
        assignee_id: 责任人 ID
        deadline: 截止日期 (YYYY-MM-DD)
        tenant_id: 租户 ID
        db: 数据库会话
        issue: 已加载的问题对象（测试注入用）

    Returns:
        {"issue_id", "assignee_id", "deadline", "status": "assigned"}
    """
    if issue is not None:
        current_status = issue.get("status", "open")
        if "assigned" not in STATUS_TRANSITIONS.get(current_status, ()):
            raise ValueError(
                f"Cannot transition from '{current_status}' to 'assigned'"
            )
        issue["assignee_id"] = assignee_id
        issue["deadline"] = deadline
        issue["status"] = "assigned"
        issue["updated_at"] = datetime.utcnow().isoformat()

    log.info(
        "issue_assigned",
        issue_id=issue_id,
        tenant_id=tenant_id,
        assignee_id=assignee_id,
        deadline=deadline,
    )

    return {
        "issue_id": issue_id,
        "assignee_id": assignee_id,
        "deadline": deadline,
        "status": "assigned",
        "updated_at": datetime.utcnow().isoformat(),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  进度更新
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def update_issue_status(
    issue_id: str,
    status: str,
    notes: str,
    tenant_id: str,
    db: Any,
    *,
    issue: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """更新问题状态及备注。

    Args:
        issue_id: 问题 ID
        status: 目标状态
        notes: 进度备注
        tenant_id: 租户 ID
        db: 数据库会话
        issue: 已加载的问题对象（测试注入用）

    Returns:
        {"issue_id", "status", "notes", "updated_at"}
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    if issue is not None:
        current_status = issue.get("status", "open")
        allowed = STATUS_TRANSITIONS.get(current_status, ())
        if status not in allowed:
            raise ValueError(
                f"Cannot transition from '{current_status}' to '{status}'"
            )
        issue["status"] = status
        issue["updated_at"] = datetime.utcnow().isoformat()
        issue.setdefault("notes", []).append({
            "text": notes,
            "timestamp": datetime.utcnow().isoformat(),
        })

    log.info(
        "issue_status_updated",
        issue_id=issue_id,
        tenant_id=tenant_id,
        status=status,
    )

    return {
        "issue_id": issue_id,
        "status": status,
        "notes": notes,
        "updated_at": datetime.utcnow().isoformat(),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  红黄绿看板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_store_issue_board(
    store_id: str,
    tenant_id: str,
    db: Any,
    *,
    issues: Optional[List[Dict[str, Any]]] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """获取门店问题红黄绿看板。

    分级逻辑：
        红: 已过截止日 (overdue)
        黄: 距截止日 <3 天
        绿: 进度正常

    Args:
        store_id: 门店 ID
        tenant_id: 租户 ID
        db: 数据库会话
        issues: 问题列表（测试注入用）
        today: 当前日期（测试注入用）

    Returns:
        {"store_id", "red", "yellow", "green", "summary"}
    """
    today_ = today or date.today()
    all_issues = issues or []

    red: List[Dict[str, Any]] = []
    yellow: List[Dict[str, Any]] = []
    green: List[Dict[str, Any]] = []

    for iss in all_issues:
        # 已完结的不计入看板
        if iss.get("status") in ("resolved", "verified"):
            green.append({**iss, "color": "green"})
            continue

        color = _classify_issue_color(iss, today_)
        tagged = {**iss, "color": color}
        if color == "red":
            red.append(tagged)
        elif color == "yellow":
            yellow.append(tagged)
        else:
            green.append(tagged)

    log.info(
        "issue_board_queried",
        store_id=store_id,
        tenant_id=tenant_id,
        red=len(red),
        yellow=len(yellow),
        green=len(green),
    )

    return {
        "store_id": store_id,
        "tenant_id": tenant_id,
        "red": red,
        "yellow": yellow,
        "green": green,
        "summary": {
            "red_count": len(red),
            "yellow_count": len(yellow),
            "green_count": len(green),
            "total": len(all_issues),
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  区域问题汇总
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_regional_issues(
    region_id: str,
    tenant_id: str,
    db: Any,
    *,
    store_boards: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """获取区域问题汇总。

    Args:
        region_id: 区域 ID
        tenant_id: 租户 ID
        db: 数据库会话
        store_boards: 各门店看板数据（测试注入用）

    Returns:
        {"region_id", "total_red", "total_yellow", "store_breakdown"}
    """
    boards = store_boards or []
    total_red = 0
    total_yellow = 0
    total_green = 0
    breakdown: List[Dict[str, Any]] = []

    for board in boards:
        summary = board.get("summary", {})
        r = summary.get("red_count", 0)
        y = summary.get("yellow_count", 0)
        g = summary.get("green_count", 0)
        total_red += r
        total_yellow += y
        total_green += g
        breakdown.append({
            "store_id": board.get("store_id", ""),
            "red": r,
            "yellow": y,
            "green": g,
        })

    # 按红色数量降序排列（问题最多的门店排前面）
    breakdown.sort(key=lambda x: x["red"], reverse=True)

    log.info(
        "regional_issues_queried",
        region_id=region_id,
        tenant_id=tenant_id,
        total_red=total_red,
        total_yellow=total_yellow,
    )

    return {
        "region_id": region_id,
        "tenant_id": tenant_id,
        "total_red": total_red,
        "total_yellow": total_yellow,
        "total_green": total_green,
        "store_breakdown": breakdown,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  跨店对标
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def cross_store_benchmark(
    issue_type: str,
    tenant_id: str,
    db: Any,
    *,
    store_issue_counts: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """跨店同类问题对标。

    Args:
        issue_type: 问题类型
        tenant_id: 租户 ID
        db: 数据库会话
        store_issue_counts: 各门店该类问题数量（测试注入用）

    Returns:
        {"issue_type", "benchmark", "stores"}
    """
    counts = store_issue_counts or {}

    stores: List[Dict[str, Any]] = []
    for store_id, count in counts.items():
        stores.append({"store_id": store_id, "count": count})
    stores.sort(key=lambda x: x["count"], reverse=True)

    total = sum(counts.values())
    avg = round(total / len(counts), 2) if counts else 0.0

    log.info(
        "cross_store_benchmark",
        tenant_id=tenant_id,
        issue_type=issue_type,
        store_count=len(counts),
    )

    return {
        "issue_type": issue_type,
        "tenant_id": tenant_id,
        "benchmark": {
            "avg_count": avg,
            "max_count": stores[0]["count"] if stores else 0,
            "min_count": stores[-1]["count"] if stores else 0,
            "total_stores": len(stores),
        },
        "stores": stores,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _classify_issue_color(issue: Dict[str, Any], today: date) -> str:
    """对单个问题判定红黄绿。"""
    deadline_str = issue.get("deadline")
    if not deadline_str:
        return "green"

    try:
        deadline = date.fromisoformat(deadline_str)
    except (ValueError, TypeError):
        return "green"

    if deadline < today:
        return "red"
    if (deadline - today).days < _YELLOW_THRESHOLD_DAYS:
        return "yellow"
    return "green"
