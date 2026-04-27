"""请假数据仓库 — DB-backed Repository

负责：
- leave_requests 的 CRUD
- leave_balances 的查询与更新
- 审批通过后的余额扣减回调
- 请假期间 daily_attendance 标记回调

所有操作需调用方预先通过 set_config('app.tenant_id', ...) 设置租户上下文（RLS）。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .attendance_repository import update_daily_attendance_on_leave

log = logging.getLogger(__name__)

# 可扣款假期类型（事假全扣，病假按 60% 日薪扣）
DEDUCTIBLE_LEAVE_TYPES = frozenset(["personal", "sick"])
# 余额校验假期类型（超出则拒绝）
BALANCE_CHECKED_TYPES = frozenset(["annual", "toil"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  leave_balances
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_leave_balance(
    employee_id: str,
    year: int,
    leave_type: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[dict[str, Any]]:
    """查询员工指定年度+假期类型的余额"""
    row = await db.execute(
        text(
            "SELECT id, total_days, used_days, remaining_days, carried_over_days "
            "FROM leave_balances "
            "WHERE tenant_id = :tid AND employee_id = :eid "
            "AND year = :yr AND leave_type = :lt AND is_deleted = FALSE"
        ),
        {"tid": tenant_id, "eid": employee_id, "yr": year, "lt": leave_type},
    )
    result = row.mappings().first()
    return dict(result) if result else None


async def get_all_leave_balances(
    employee_id: str,
    year: int,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """查询员工指定年度所有假期余额"""
    rows = await db.execute(
        text(
            "SELECT id, leave_type, total_days, used_days, remaining_days, carried_over_days "
            "FROM leave_balances "
            "WHERE tenant_id = :tid AND employee_id = :eid AND year = :yr "
            "AND is_deleted = FALSE "
            "ORDER BY leave_type"
        ),
        {"tid": tenant_id, "eid": employee_id, "yr": year},
    )
    return [dict(r) for r in rows.mappings().fetchall()]


async def deduct_leave_balance(
    employee_id: str,
    year: int,
    leave_type: str,
    days: float,
    tenant_id: str,
    db: AsyncSession,
) -> None:
    """扣减假期余额（审批通过后调用）"""
    await db.execute(
        text(
            "UPDATE leave_balances "
            "SET used_days = used_days + :days, "
            "remaining_days = remaining_days - :days, "
            "updated_at = NOW() "
            "WHERE tenant_id = :tid AND employee_id = :eid "
            "AND year = :yr AND leave_type = :lt"
        ),
        {"days": days, "tid": tenant_id, "eid": employee_id, "yr": year, "lt": leave_type},
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  leave_requests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_leave_request(
    tenant_id: str,
    store_id: str,
    employee_id: str,
    leave_type: str,
    start_date: date,
    end_date: date,
    days_requested: float,
    reason: Optional[str],
    *,
    start_half_day: bool = False,
    end_half_day: bool = False,
    attachments: Optional[list[str]] = None,
    db: AsyncSession,
) -> dict[str, Any]:
    """创建请假申请（status=pending）"""
    import json as _json

    row = await db.execute(
        text(
            "INSERT INTO leave_requests "
            "(tenant_id, store_id, employee_id, leave_type, start_date, end_date, "
            "days_requested, reason, start_half_day, end_half_day, attachments, status) "
            "VALUES (:tid, :sid, :eid, :lt, :sd, :ed, "
            ":days, :reason, :shd, :ehd, :attach::jsonb, 'pending') "
            "RETURNING id, employee_id, leave_type, start_date, end_date, "
            "days_requested, status, created_at"
        ),
        {
            "tid": tenant_id,
            "sid": store_id,
            "eid": employee_id,
            "lt": leave_type,
            "sd": start_date,
            "ed": end_date,
            "days": days_requested,
            "reason": reason,
            "shd": start_half_day,
            "ehd": end_half_day,
            "attach": _json.dumps(attachments or []),
        },
    )
    await db.commit()
    result = row.mappings().first()
    return dict(result)


async def update_leave_request_approval_instance(
    leave_request_id: str,
    approval_instance_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> None:
    """绑定审批流实例 ID"""
    await db.execute(
        text(
            "UPDATE leave_requests SET approval_instance_id = :inst_id, updated_at = NOW() "
            "WHERE id = :lr_id AND tenant_id = :tid"
        ),
        {"inst_id": approval_instance_id, "lr_id": leave_request_id, "tid": tenant_id},
    )
    await db.commit()


async def get_leave_request(
    leave_request_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[dict[str, Any]]:
    """查询单条请假申请"""
    row = await db.execute(
        text(
            "SELECT id, tenant_id, store_id, employee_id, leave_type, start_date, end_date, "
            "days_requested, reason, start_half_day, end_half_day, "
            "status, approval_instance_id, deduction_fen, created_at, updated_at "
            "FROM leave_requests "
            "WHERE id = :lid AND tenant_id = :tid AND is_deleted = FALSE"
        ),
        {"lid": leave_request_id, "tid": tenant_id},
    )
    result = row.mappings().first()
    return dict(result) if result else None


async def list_leave_requests(
    tenant_id: str,
    db: AsyncSession,
    *,
    employee_id: Optional[str] = None,
    store_id: Optional[str] = None,
    status: Optional[str] = None,
    year: Optional[int] = None,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """列表查询请假申请"""
    conditions = ["tenant_id = :tid", "is_deleted = FALSE"]
    params: dict[str, Any] = {"tid": tenant_id}

    if employee_id:
        conditions.append("employee_id = :eid")
        params["eid"] = employee_id
    if store_id:
        conditions.append("store_id = :sid")
        params["sid"] = store_id
    if status:
        conditions.append("status = :status")
        params["status"] = status
    if year:
        conditions.append("EXTRACT(YEAR FROM start_date) = :yr")
        params["yr"] = year

    where = " AND ".join(conditions)
    offset = (page - 1) * size

    rows = await db.execute(
        text(
            f"SELECT id, employee_id, leave_type, start_date, end_date, "
            f"days_requested, status, approval_instance_id, deduction_fen, created_at "
            f"FROM leave_requests WHERE {where} "
            f"ORDER BY created_at DESC LIMIT :size OFFSET :offset"
        ),
        {**params, "size": size, "offset": offset},
    )
    count_row = await db.execute(text(f"SELECT COUNT(*) FROM leave_requests WHERE {where}"), params)
    total = count_row.scalar() or 0
    items = [dict(r) for r in rows.mappings().fetchall()]
    return {"items": items, "total": total}


async def cancel_leave_request(
    leave_request_id: str,
    employee_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """撤销请假申请（仅 pending 状态可撤，且只能本人撤）"""
    row = await db.execute(
        text(
            "UPDATE leave_requests SET status = 'cancelled', updated_at = NOW() "
            "WHERE id = :lid AND tenant_id = :tid AND employee_id = :eid "
            "AND status = 'pending' "
            "RETURNING id, status"
        ),
        {"lid": leave_request_id, "tid": tenant_id, "eid": employee_id},
    )
    await db.commit()
    result = row.mappings().first()
    if not result:
        raise ValueError("请假申请不存在、不属于本人，或状态非 pending，无法撤销")
    return dict(result)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  审批通过回调
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _date_range(start: date, end: date) -> list[date]:
    """生成 [start, end] 日期列表"""
    result = []
    current = start
    while current <= end:
        result.append(current)
        current += timedelta(days=1)
    return result


async def on_leave_approved(
    leave_request_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """审批通过回调：扣减余额 + 更新 daily_attendance

    由审批流引擎在状态变为 approved 时调用（POST /api/v1/leave-requests/{id}/approve-callback）。
    """
    # 1. 查询请假申请
    lr = await get_leave_request(leave_request_id, tenant_id, db)
    if not lr:
        raise ValueError(f"请假申请不存在: {leave_request_id}")
    if lr["status"] != "pending":
        raise ValueError(f"请假申请状态异常: {lr['status']}，已处理")

    # 2. 更新 status = approved
    await db.execute(
        text("UPDATE leave_requests SET status = 'approved', updated_at = NOW() WHERE id = :lid AND tenant_id = :tid"),
        {"lid": leave_request_id, "tid": tenant_id},
    )

    # 3. 扣减余额（年假/调休）
    if lr["leave_type"] in BALANCE_CHECKED_TYPES:
        start_year = (
            lr["start_date"].year
            if isinstance(lr["start_date"], date)
            else date.fromisoformat(str(lr["start_date"])).year
        )
        await deduct_leave_balance(
            employee_id=lr["employee_id"],
            year=start_year,
            leave_type=lr["leave_type"],
            days=float(lr["days_requested"]),
            tenant_id=tenant_id,
            db=db,
        )

    # 4. 更新请假期间 daily_attendance 为 on_leave
    start_dt = lr["start_date"] if isinstance(lr["start_date"], date) else date.fromisoformat(str(lr["start_date"]))
    end_dt = lr["end_date"] if isinstance(lr["end_date"], date) else date.fromisoformat(str(lr["end_date"]))
    leave_uuid = UUID(str(lr["id"]))

    for day in _date_range(start_dt, end_dt):
        await update_daily_attendance_on_leave(
            employee_id=lr["employee_id"],
            work_date=day,
            leave_id=leave_uuid,
            leave_type=lr["leave_type"],
            store_id=lr["store_id"],
            tenant_id=tenant_id,
            db=db,
        )

    await db.commit()
    log.info(
        "leave_approved",
        extra={
            "leave_request_id": leave_request_id,
            "employee_id": lr["employee_id"],
            "leave_type": lr["leave_type"],
            "days": lr["days_requested"],
        },
    )
    return {
        "leave_request_id": leave_request_id,
        "employee_id": lr["employee_id"],
        "leave_type": lr["leave_type"],
        "days_approved": lr["days_requested"],
        "status": "approved",
    }


async def on_leave_rejected(
    leave_request_id: str,
    reject_reason: Optional[str],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """审批拒绝回调：更新状态"""
    row = await db.execute(
        text(
            "UPDATE leave_requests SET status = 'rejected', "
            "reject_reason = :reason, updated_at = NOW() "
            "WHERE id = :lid AND tenant_id = :tid AND status = 'pending' "
            "RETURNING id, status"
        ),
        {"lid": leave_request_id, "reason": reject_reason, "tid": tenant_id},
    )
    await db.commit()
    result = row.mappings().first()
    if not result:
        raise ValueError(f"请假申请不存在或状态非 pending: {leave_request_id}")
    return dict(result)
