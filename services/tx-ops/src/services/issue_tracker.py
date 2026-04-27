"""D8 问题追踪 — 门店问题清单、派发、进度、红黄绿看板、跨店对标

支持问题全生命周期管理：创建→派发→处理中→已解决→已验证。
红黄绿分级：overdue=红, deadline<3d=黄, on_track=绿。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _serialize_row(row_mapping: dict) -> dict:
    result = {}
    for key, val in row_mapping.items():
        if val is None:
            result[key] = None
        elif hasattr(val, "isoformat"):
            result[key] = val.isoformat()
        elif hasattr(val, "hex"):
            result[key] = str(val)
        else:
            result[key] = val
    return result


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
    """创建门店问题并写入 DB。"""
    issue_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

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
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    if db is not None:
        try:
            await _set_rls(db, tenant_id)
            await db.execute(
                text(
                    """
                    INSERT INTO store_issues
                      (id, tenant_id, store_id, issue_type, description, reporter_id,
                       priority, deadline, status, created_at, updated_at)
                    VALUES
                      (:id, NULLIF(current_setting('app.tenant_id', true), '')::uuid,
                       :store_id, :issue_type, :description, :reporter_id,
                       :priority, :deadline, 'open', :now, :now)
                    """
                ),
                {
                    "id": issue_id,
                    "store_id": store_id,
                    "issue_type": issue_type,
                    "description": description,
                    "reporter_id": reporter_id,
                    "priority": priority,
                    "deadline": deadline,
                    "now": now,
                },
            )
        except SQLAlchemyError as exc:
            log.error("issue_create_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)

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
    """将问题派发给责任人。"""
    now = datetime.now(timezone.utc)

    if db is not None:
        try:
            await _set_rls(db, tenant_id)
            check_result = await db.execute(
                text(
                    """
                    SELECT id, status FROM store_issues
                    WHERE id = :id
                      AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND is_deleted = false
                    LIMIT 1
                    """
                ),
                {"id": issue_id},
            )
            row = check_result.fetchone()
            if row:
                current_status = row.status
                if "assigned" not in STATUS_TRANSITIONS.get(current_status, ()):
                    raise ValueError(f"Cannot transition from '{current_status}' to 'assigned'")
                await db.execute(
                    text(
                        """
                        UPDATE store_issues
                        SET assignee_id = :assignee_id, deadline = :deadline,
                            status = 'assigned', updated_at = :now
                        WHERE id = :id
                          AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        """
                    ),
                    {"assignee_id": assignee_id, "deadline": deadline, "now": now, "id": issue_id},
                )
        except ValueError:
            raise
        except SQLAlchemyError as exc:
            log.error("issue_assign_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)
    elif issue is not None:
        current_status = issue.get("status", "open")
        if "assigned" not in STATUS_TRANSITIONS.get(current_status, ()):
            raise ValueError(f"Cannot transition from '{current_status}' to 'assigned'")
        issue["assignee_id"] = assignee_id
        issue["deadline"] = deadline
        issue["status"] = "assigned"
        issue["updated_at"] = now.isoformat()

    log.info("issue_assigned", issue_id=issue_id, tenant_id=tenant_id, assignee_id=assignee_id, deadline=deadline)

    return {
        "issue_id": issue_id,
        "assignee_id": assignee_id,
        "deadline": deadline,
        "status": "assigned",
        "updated_at": now.isoformat(),
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
    """更新问题状态及备注。"""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    now = datetime.now(timezone.utc)

    if db is not None:
        try:
            await _set_rls(db, tenant_id)
            check_result = await db.execute(
                text(
                    """
                    SELECT id, status FROM store_issues
                    WHERE id = :id
                      AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND is_deleted = false
                    LIMIT 1
                    """
                ),
                {"id": issue_id},
            )
            row = check_result.fetchone()
            if row:
                current_status = row.status
                allowed = STATUS_TRANSITIONS.get(current_status, ())
                if status not in allowed:
                    raise ValueError(f"Cannot transition from '{current_status}' to '{status}'")
                await db.execute(
                    text(
                        """
                        UPDATE store_issues
                        SET status = :status, updated_at = :now
                        WHERE id = :id
                          AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        """
                    ),
                    {"status": status, "now": now, "id": issue_id},
                )
        except ValueError:
            raise
        except SQLAlchemyError as exc:
            log.error("issue_update_status_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)
    elif issue is not None:
        current_status = issue.get("status", "open")
        allowed = STATUS_TRANSITIONS.get(current_status, ())
        if status not in allowed:
            raise ValueError(f"Cannot transition from '{current_status}' to '{status}'")
        issue["status"] = status
        issue["updated_at"] = now.isoformat()
        issue.setdefault("notes", []).append(
            {
                "text": notes,
                "timestamp": now.isoformat(),
            }
        )

    log.info("issue_status_updated", issue_id=issue_id, tenant_id=tenant_id, status=status)

    return {
        "issue_id": issue_id,
        "status": status,
        "notes": notes,
        "updated_at": now.isoformat(),
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
    """获取门店问题红黄绿看板（从 DB 查询）。"""
    today_ = today or date.today()

    all_issues: List[Dict[str, Any]] = issues or []

    if db is not None and not issues:
        try:
            await _set_rls(db, tenant_id)
            rows_result = await db.execute(
                text(
                    """
                    SELECT id, store_id, issue_type AS type, description, reporter_id,
                           assignee_id, status, priority, deadline, created_at, updated_at
                    FROM store_issues
                    WHERE store_id = :store_id
                      AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND is_deleted = false
                      AND status NOT IN ('resolved', 'verified')
                    ORDER BY created_at DESC
                    """
                ),
                {"store_id": store_id},
            )
            all_issues = [_serialize_row(dict(row._mapping)) for row in rows_result]
        except SQLAlchemyError as exc:
            log.error("issue_board_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)

    red: List[Dict[str, Any]] = []
    yellow: List[Dict[str, Any]] = []
    green: List[Dict[str, Any]] = []

    for iss in all_issues:
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
    """获取区域问题汇总。"""
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
        breakdown.append(
            {
                "store_id": board.get("store_id", ""),
                "red": r,
                "yellow": y,
                "green": g,
            }
        )

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
    """跨店同类问题对标。"""
    counts: Dict[str, int] = store_issue_counts or {}

    if db is not None and not store_issue_counts:
        try:
            await _set_rls(db, tenant_id)
            rows_result = await db.execute(
                text(
                    """
                    SELECT store_id, COUNT(*) AS cnt
                    FROM store_issues
                    WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND issue_type = :issue_type
                      AND is_deleted = false
                    GROUP BY store_id
                    """
                ),
                {"issue_type": issue_type},
            )
            counts = {row.store_id: row.cnt for row in rows_result}
        except SQLAlchemyError as exc:
            log.error("cross_store_benchmark_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)

    stores: List[Dict[str, Any]] = [{"store_id": sid, "count": count} for sid, count in counts.items()]
    stores.sort(key=lambda x: x["count"], reverse=True)

    total = sum(counts.values())
    avg = round(total / len(counts), 2) if counts else 0.0

    log.info("cross_store_benchmark", tenant_id=tenant_id, issue_type=issue_type, store_count=len(counts))

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
        deadline = date.fromisoformat(str(deadline_str)[:10])
    except (ValueError, TypeError):
        return "green"

    if deadline < today:
        return "red"
    if (deadline - today).days < _YELLOW_THRESHOLD_DAYS:
        return "yellow"
    return "green"
