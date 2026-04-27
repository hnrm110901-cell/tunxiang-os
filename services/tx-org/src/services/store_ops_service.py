"""门店人力作战台 — 业务服务层

封装门店作战台核心聚合逻辑，被 store_ops_routes.py 调用。

公共方法：
  get_today_dashboard  — 聚合今日人力作战台首页数据
  get_position_detail  — 岗位在岗/离岗明细
  get_anomalies        — 今日考勤异常列表
  get_fill_suggestions — 缺岗补位候选人
  execute_fill_gap     — 执行补位
  get_weekly_summary   — 本周人力概览
  get_labor_metrics    — 月度人力指标
  execute_quick_action — 店长快速操作
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import OrgEventType, UniversalPublisher

from .gap_filling_service import (
    create_fill_schedule,
    find_available_employees,
    notify_fill,
    rank_candidates,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# ── 辅助 ────────────────────────────────────────────────────────────────────


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _today() -> date:
    return datetime.now(timezone.utc).date()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  今日作战台
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_today_dashboard(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    target_date: Optional[date] = None,
) -> Dict[str, Any]:
    """聚合今日人力作战台首页全部数据。"""
    await _set_tenant(db, tenant_id)
    d = target_date or _today()

    # 并行执行多个查询
    (
        store_info,
        headcount,
        positions,
        gaps,
        pending_actions,
        labor_cost,
        timeline,
    ) = await asyncio.gather(
        _query_store_info(db, tenant_id, store_id),
        _query_headcount(db, tenant_id, store_id, d),
        _query_positions(db, tenant_id, store_id, d),
        _query_gaps(db, tenant_id, store_id, d),
        _query_pending_actions(db, tenant_id, store_id, d),
        _query_labor_cost(db, tenant_id, store_id, d),
        _query_timeline(db, tenant_id, store_id, d),
    )

    return {
        "date": str(d),
        "store_id": store_id,
        "store_name": store_info.get("store_name", ""),
        "headcount": headcount,
        "positions": positions,
        "gaps": gaps,
        "pending_actions": pending_actions,
        "labor_cost": labor_cost,
        "timeline": timeline,
    }


async def _query_store_info(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
) -> Dict[str, Any]:
    sql = text("""
        SELECT id, store_name
        FROM stores
        WHERE id = CAST(:store_id AS uuid)
          AND tenant_id = CAST(:tid AS uuid)
          AND is_deleted = FALSE
        LIMIT 1
    """)
    result = await db.execute(sql, {"store_id": store_id, "tid": tenant_id})
    row = result.mappings().first()
    if not row:
        return {"store_name": ""}
    return {"store_name": row["store_name"]}


async def _query_headcount(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    d: date,
) -> Dict[str, Any]:
    """查排班数、实到、缺勤、请假、迟到。"""
    # 应排班人数
    scheduled_sql = text("""
        SELECT COUNT(DISTINCT employee_id) AS cnt
        FROM unified_schedules
        WHERE tenant_id = CAST(:tid AS uuid)
          AND store_id = CAST(:store_id AS uuid)
          AND schedule_date = :d
          AND status = 'scheduled'
    """)
    # 实到（打卡正常或迟到）
    clocked_in_sql = text("""
        SELECT COUNT(DISTINCT employee_id) AS cnt
        FROM daily_attendance
        WHERE tenant_id = CAST(:tid AS uuid)
          AND store_id = :store_id
          AND date = :d
          AND status IN ('normal', 'late', 'early_leave', 'overtime')
    """)
    # 缺勤
    absent_sql = text("""
        SELECT COUNT(DISTINCT employee_id) AS cnt
        FROM daily_attendance
        WHERE tenant_id = CAST(:tid AS uuid)
          AND store_id = :store_id
          AND date = :d
          AND status = 'absent'
    """)
    # 请假
    on_leave_sql = text("""
        SELECT COUNT(DISTINCT employee_id) AS cnt
        FROM leave_requests
        WHERE tenant_id = CAST(:tid AS uuid)
          AND store_id = :store_id
          AND status = 'approved'
          AND start_date <= :d
          AND end_date >= :d
    """)
    # 迟到
    late_sql = text("""
        SELECT COUNT(DISTINCT employee_id) AS cnt
        FROM daily_attendance
        WHERE tenant_id = CAST(:tid AS uuid)
          AND store_id = :store_id
          AND date = :d
          AND status = 'late'
    """)

    params = {"tid": tenant_id, "store_id": store_id, "d": d}
    r_sched, r_in, r_abs, r_leave, r_late = await asyncio.gather(
        db.execute(scheduled_sql, params),
        db.execute(clocked_in_sql, params),
        db.execute(absent_sql, params),
        db.execute(on_leave_sql, params),
        db.execute(late_sql, params),
    )

    return {
        "scheduled": r_sched.scalar() or 0,
        "clocked_in": r_in.scalar() or 0,
        "absent": r_abs.scalar() or 0,
        "on_leave": r_leave.scalar() or 0,
        "late": r_late.scalar() or 0,
    }


async def _query_positions(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    d: date,
) -> List[Dict[str, Any]]:
    """按岗位统计应到/实到/缺口。"""
    sql = text("""
        WITH required AS (
            SELECT position, COUNT(DISTINCT employee_id) AS required_cnt
            FROM unified_schedules
            WHERE tenant_id = CAST(:tid AS uuid)
              AND store_id = CAST(:store_id AS uuid)
              AND schedule_date = :d
              AND status = 'scheduled'
              AND position IS NOT NULL
            GROUP BY position
        ),
        actual AS (
            SELECT us.position, COUNT(DISTINCT da.employee_id) AS actual_cnt
            FROM daily_attendance da
            INNER JOIN unified_schedules us
                ON us.employee_id = CAST(da.employee_id AS uuid)
                AND us.tenant_id = da.tenant_id
                AND us.store_id = CAST(da.store_id AS uuid)
                AND us.schedule_date = da.date
            WHERE da.tenant_id = CAST(:tid AS uuid)
              AND da.store_id = :store_id
              AND da.date = :d
              AND da.status IN ('normal', 'late', 'early_leave', 'overtime')
              AND us.position IS NOT NULL
            GROUP BY us.position
        )
        SELECT r.position,
               r.required_cnt AS required,
               COALESCE(a.actual_cnt, 0) AS actual,
               r.required_cnt - COALESCE(a.actual_cnt, 0) AS gap
        FROM required r
        LEFT JOIN actual a ON a.position = r.position
        ORDER BY r.position
    """)
    result = await db.execute(sql, {"tid": tenant_id, "store_id": store_id, "d": d})
    rows = result.mappings().all()
    out: List[Dict[str, Any]] = []
    for row in rows:
        gap_val = row["gap"]
        out.append(
            {
                "position": row["position"],
                "required": row["required"],
                "actual": row["actual"],
                "gap": gap_val,
                "status": "gap" if gap_val > 0 else "ok",
            }
        )
    return out


async def _query_gaps(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    d: date,
) -> List[Dict[str, Any]]:
    """查当前未填补缺口。"""
    sql = text("""
        SELECT sg.id, sg.position, sg.urgency, sg.status,
               st.name AS shift_name, st.start_time, st.end_time
        FROM shift_gaps sg
        LEFT JOIN shift_templates st
            ON st.id = sg.shift_template_id AND st.tenant_id = sg.tenant_id
        WHERE sg.tenant_id = CAST(:tid AS uuid)
          AND sg.store_id = CAST(:store_id AS uuid)
          AND sg.schedule_date = :d
          AND sg.status = 'open'
        ORDER BY sg.urgency DESC, sg.created_at
    """)
    result = await db.execute(sql, {"tid": tenant_id, "store_id": store_id, "d": d})
    rows = result.mappings().all()
    return [
        {
            "gap_id": str(row["id"]),
            "position": row["position"],
            "urgency": row["urgency"],
            "shift_name": row["shift_name"],
            "start_time": str(row["start_time"]) if row["start_time"] else None,
            "end_time": str(row["end_time"]) if row["end_time"] else None,
        }
        for row in rows
    ]


async def _query_pending_actions(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    d: date,
) -> Dict[str, int]:
    """查待处理事项数量。"""
    pending_leaves_sql = text("""
        SELECT COUNT(*) FROM leave_requests
        WHERE tenant_id = CAST(:tid AS uuid)
          AND store_id = :store_id
          AND status = 'pending'
    """)
    pending_swaps_sql = text("""
        SELECT COUNT(*) FROM crew_shift_swaps
        WHERE tenant_id = CAST(:tid AS uuid)
          AND status = 'pending'
    """)
    anomalies_sql = text("""
        SELECT COUNT(*) FROM daily_attendance
        WHERE tenant_id = CAST(:tid AS uuid)
          AND store_id = :store_id
          AND date = :d
          AND status IN ('absent', 'late', 'early_leave', 'missing_clock_out')
    """)
    alerts_sql = text("""
        SELECT COUNT(*) FROM compliance_alerts
        WHERE tenant_id = CAST(:tid AS uuid)
          AND store_id = CAST(:store_id AS uuid)
          AND status = 'open'
    """)

    params = {"tid": tenant_id, "store_id": store_id, "d": d}

    # crew_shift_swaps 可能不存在，安全降级
    try:
        r_leaves, r_swaps, r_anomalies, r_alerts = await asyncio.gather(
            db.execute(pending_leaves_sql, params),
            db.execute(pending_swaps_sql, params),
            db.execute(anomalies_sql, params),
            db.execute(alerts_sql, params),
        )
        swaps_count = r_swaps.scalar() or 0
    except Exception as exc:  # noqa: BLE001 — 换班表可能未建立，降级查询
        log.warning("store_ops.pending_swaps_unavailable", error=str(exc))
        r_leaves, r_anomalies, r_alerts = await asyncio.gather(
            db.execute(pending_leaves_sql, params),
            db.execute(anomalies_sql, params),
            db.execute(alerts_sql, params),
        )
        swaps_count = 0

    return {
        "pending_leaves": r_leaves.scalar() or 0,
        "pending_swaps": swaps_count,
        "unresolved_anomalies": r_anomalies.scalar() or 0,
        "compliance_alerts": r_alerts.scalar() or 0,
    }


async def _query_labor_cost(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    d: date,
) -> Dict[str, Any]:
    """今日预估人工成本 + 本月累计。"""
    # 今日：按出勤员工的日薪标准估算
    today_sql = text("""
        SELECT COALESCE(SUM(e.daily_wage_standard_fen), 0) AS today_fen
        FROM daily_attendance da
        INNER JOIN employees e
            ON CAST(e.id AS text) = da.employee_id
            AND e.tenant_id = da.tenant_id
        WHERE da.tenant_id = CAST(:tid AS uuid)
          AND da.store_id = :store_id
          AND da.date = :d
          AND da.status IN ('normal', 'late', 'early_leave', 'overtime')
    """)
    # 本月累计
    month_start = d.replace(day=1)
    month_sql = text("""
        SELECT COALESCE(SUM(e.daily_wage_standard_fen), 0) AS month_fen
        FROM daily_attendance da
        INNER JOIN employees e
            ON CAST(e.id AS text) = da.employee_id
            AND e.tenant_id = da.tenant_id
        WHERE da.tenant_id = CAST(:tid AS uuid)
          AND da.store_id = :store_id
          AND da.date >= :month_start
          AND da.date <= :d
          AND da.status IN ('normal', 'late', 'early_leave', 'overtime')
    """)

    params = {"tid": tenant_id, "store_id": store_id, "d": d, "month_start": month_start}
    r_today, r_month = await asyncio.gather(
        db.execute(today_sql, params),
        db.execute(month_sql, params),
    )

    return {
        "today_estimated_fen": r_today.scalar() or 0,
        "month_accumulated_fen": r_month.scalar() or 0,
        "labor_cost_rate": None,  # 需营收数据联动，暂留空
    }


async def _query_timeline(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    d: date,
) -> List[Dict[str, str]]:
    """今日事件时间线（打卡+请假，最近50条）。"""
    sql = text("""
        (
            SELECT clock_in_time AS event_time,
                   CASE status
                       WHEN 'late' THEN e.emp_name || ' 迟到'
                       WHEN 'normal' THEN e.emp_name || ' 打卡上班'
                       ELSE e.emp_name || ' 打卡(' || status || ')'
                   END AS event_desc
            FROM daily_attendance da
            INNER JOIN employees e
                ON CAST(e.id AS text) = da.employee_id
                AND e.tenant_id = da.tenant_id
            WHERE da.tenant_id = CAST(:tid AS uuid)
              AND da.store_id = :store_id
              AND da.date = :d
              AND da.clock_in_time IS NOT NULL
        )
        UNION ALL
        (
            SELECT lr.created_at AS event_time,
                   e.emp_name || ' 请假(' || lr.leave_type || ')' AS event_desc
            FROM leave_requests lr
            INNER JOIN employees e
                ON lr.employee_id = CAST(e.id AS text)
                AND e.tenant_id = lr.tenant_id
            WHERE lr.tenant_id = CAST(:tid AS uuid)
              AND lr.store_id = :store_id
              AND lr.start_date <= :d
              AND lr.end_date >= :d
              AND lr.status = 'approved'
        )
        ORDER BY event_time ASC
        LIMIT 50
    """)
    result = await db.execute(sql, {"tid": tenant_id, "store_id": store_id, "d": d})
    rows = result.mappings().all()
    return [
        {
            "time": row["event_time"].strftime("%H:%M") if row["event_time"] else "",
            "event": row["event_desc"] or "",
        }
        for row in rows
    ]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  岗位明细
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_position_detail(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    target_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """岗位在岗/离岗详情。每个排班员工附带出勤状态。"""
    await _set_tenant(db, tenant_id)
    d = target_date or _today()

    sql = text("""
        SELECT us.id AS schedule_id,
               us.employee_id,
               e.emp_name,
               us.position,
               us.start_time,
               us.end_time,
               da.status AS attendance_status,
               da.clock_in_time,
               da.clock_out_time
        FROM unified_schedules us
        INNER JOIN employees e
            ON e.id = us.employee_id AND e.tenant_id = us.tenant_id
        LEFT JOIN daily_attendance da
            ON da.employee_id = CAST(us.employee_id AS text)
            AND da.tenant_id = us.tenant_id
            AND da.store_id = CAST(us.store_id AS text)
            AND da.date = us.schedule_date
        WHERE us.tenant_id = CAST(:tid AS uuid)
          AND us.store_id = CAST(:store_id AS uuid)
          AND us.schedule_date = :d
          AND us.status = 'scheduled'
        ORDER BY us.position, us.start_time
    """)
    result = await db.execute(sql, {"tid": tenant_id, "store_id": store_id, "d": d})
    rows = result.mappings().all()
    return [
        {
            "schedule_id": str(row["schedule_id"]),
            "employee_id": str(row["employee_id"]),
            "emp_name": row["emp_name"],
            "position": row["position"],
            "start_time": str(row["start_time"]),
            "end_time": str(row["end_time"]),
            "attendance_status": row["attendance_status"] or "pending",
            "clock_in_time": row["clock_in_time"].isoformat() if row["clock_in_time"] else None,
            "clock_out_time": row["clock_out_time"].isoformat() if row["clock_out_time"] else None,
        }
        for row in rows
    ]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  考勤异常
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_anomalies(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    target_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """今日考勤异常列表（迟到/未打卡/早退/缺勤）。"""
    await _set_tenant(db, tenant_id)
    d = target_date or _today()

    sql = text("""
        SELECT da.id,
               da.employee_id,
               e.emp_name,
               da.status,
               da.late_minutes,
               da.early_leave_minutes,
               da.clock_in_time,
               da.clock_out_time,
               da.scheduled_shift,
               da.remark
        FROM daily_attendance da
        INNER JOIN employees e
            ON CAST(e.id AS text) = da.employee_id
            AND e.tenant_id = da.tenant_id
        WHERE da.tenant_id = CAST(:tid AS uuid)
          AND da.store_id = :store_id
          AND da.date = :d
          AND da.status IN ('late', 'absent', 'early_leave', 'missing_clock_out')
        ORDER BY da.clock_in_time NULLS LAST
    """)
    result = await db.execute(sql, {"tid": tenant_id, "store_id": store_id, "d": d})
    rows = result.mappings().all()
    return [
        {
            "id": str(row["id"]),
            "employee_id": row["employee_id"],
            "emp_name": row["emp_name"],
            "anomaly_type": row["status"],
            "late_minutes": row["late_minutes"],
            "early_leave_minutes": row["early_leave_minutes"],
            "clock_in_time": row["clock_in_time"].isoformat() if row["clock_in_time"] else None,
            "clock_out_time": row["clock_out_time"].isoformat() if row["clock_out_time"] else None,
            "scheduled_shift": row["scheduled_shift"],
            "remark": row["remark"],
        }
        for row in rows
    ]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  补位建议
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_fill_suggestions(
    db: AsyncSession,
    tenant_id: str,
    gap_id: str,
) -> Dict[str, Any]:
    """获取缺岗补位候选人列表。"""
    await _set_tenant(db, tenant_id)

    # 查询缺口详情
    gap_sql = text("""
        SELECT sg.id, sg.store_id, sg.schedule_date, sg.position,
               sg.shift_template_id, sg.urgency,
               st.start_time, st.end_time
        FROM shift_gaps sg
        LEFT JOIN shift_templates st
            ON st.id = sg.shift_template_id AND st.tenant_id = sg.tenant_id
        WHERE sg.id = CAST(:gap_id AS uuid)
          AND sg.tenant_id = CAST(:tid AS uuid)
    """)
    gap_result = await db.execute(gap_sql, {"gap_id": gap_id, "tid": tenant_id})
    gap_row = gap_result.mappings().first()
    if not gap_row:
        return {"gap_id": gap_id, "error": "gap_not_found", "candidates": []}

    time_start = gap_row["start_time"] or time(8, 0)
    time_end = gap_row["end_time"] or time(17, 0)

    candidates = await find_available_employees(
        db,
        tenant_id,
        str(gap_row["store_id"]),
        gap_row["schedule_date"],
        gap_row["position"],
        time_start,
        time_end,
    )

    gap_info = {
        "gap_id": gap_id,
        "position": gap_row["position"],
        "schedule_date": str(gap_row["schedule_date"]),
        "urgency": gap_row["urgency"],
    }
    ranked = rank_candidates(candidates, gap_info)

    return {
        "gap_id": gap_id,
        "position": gap_row["position"],
        "schedule_date": str(gap_row["schedule_date"]),
        "urgency": gap_row["urgency"],
        "candidates": ranked,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  执行补位
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def execute_fill_gap(
    db: AsyncSession,
    tenant_id: str,
    gap_id: str,
    employee_id: str,
    fill_type: str,
) -> Dict[str, Any]:
    """执行缺岗补位：创建排班 + 更新缺口 + 发事件 + 通知。"""
    result = await create_fill_schedule(db, tenant_id, gap_id, employee_id, fill_type)

    # 发射事件（不阻塞主流程）
    publisher = UniversalPublisher(tenant_id=tenant_id)
    asyncio.create_task(
        publisher.publish(
            event_type=OrgEventType.SHIFT_GAP_FILLED,
            payload={
                "gap_id": gap_id,
                "employee_id": employee_id,
                "fill_type": fill_type,
                "store_id": result["store_id"],
                "position": result["position"],
                "schedule_date": result["schedule_date"],
            },
        )
    )

    # 异步通知
    asyncio.create_task(notify_fill(tenant_id, employee_id, result))

    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  快速操作
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


_QUICK_ACTION_HANDLERS = {
    "acknowledge_late",
    "mark_absent",
    "approve_leave",
    "assign_fill",
}


async def execute_quick_action(
    db: AsyncSession,
    tenant_id: str,
    action_type: str,
    target_id: str,
    operator_id: str,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """店长快速操作分发。"""
    await _set_tenant(db, tenant_id)

    if action_type not in _QUICK_ACTION_HANDLERS:
        raise ValueError(f"Unsupported action_type: {action_type}")

    if action_type == "acknowledge_late":
        return await _action_acknowledge_late(db, tenant_id, target_id, operator_id, note)
    elif action_type == "mark_absent":
        return await _action_mark_absent(db, tenant_id, target_id, operator_id, note)
    elif action_type == "approve_leave":
        return await _action_approve_leave(db, tenant_id, target_id, operator_id, note)
    elif action_type == "assign_fill":
        return await _action_assign_fill(db, tenant_id, target_id, operator_id, note)
    # 不可达，上面已校验
    raise ValueError(f"Unsupported action_type: {action_type}")  # pragma: no cover


async def _action_acknowledge_late(
    db: AsyncSession,
    tenant_id: str,
    target_id: str,
    operator_id: str,
    note: Optional[str],
) -> Dict[str, Any]:
    """确认迟到（添加备注，不改变状态）。"""
    sql = text("""
        UPDATE daily_attendance
        SET remark = COALESCE(remark, '') || :note_append,
            updated_at = NOW()
        WHERE id = CAST(:target_id AS uuid)
          AND tenant_id = CAST(:tid AS uuid)
          AND status = 'late'
        RETURNING id, employee_id, status
    """)
    note_append = f"\n[店长确认] {note or ''} (by {operator_id})"
    result = await db.execute(
        sql,
        {
            "target_id": target_id,
            "tid": tenant_id,
            "note_append": note_append,
        },
    )
    row = result.mappings().first()
    await db.commit()
    if not row:
        return {"ok": False, "error": "record_not_found_or_not_late"}
    return {"ok": True, "action": "acknowledge_late", "target_id": target_id}


async def _action_mark_absent(
    db: AsyncSession,
    tenant_id: str,
    target_id: str,
    operator_id: str,
    note: Optional[str],
) -> Dict[str, Any]:
    """手动标记旷工。"""
    sql = text("""
        UPDATE daily_attendance
        SET status = 'absent',
            remark = COALESCE(remark, '') || :note_append,
            updated_at = NOW()
        WHERE id = CAST(:target_id AS uuid)
          AND tenant_id = CAST(:tid AS uuid)
          AND status IN ('pending', 'missing_clock_out')
        RETURNING id, employee_id
    """)
    note_append = f"\n[手动标记旷工] {note or ''} (by {operator_id})"
    result = await db.execute(
        sql,
        {
            "target_id": target_id,
            "tid": tenant_id,
            "note_append": note_append,
        },
    )
    row = result.mappings().first()
    await db.commit()
    if not row:
        return {"ok": False, "error": "record_not_found_or_invalid_status"}

    # 发事件
    publisher = UniversalPublisher(tenant_id=tenant_id)
    asyncio.create_task(
        publisher.publish(
            event_type=OrgEventType.ATTENDANCE_ABSENT,
            payload={
                "attendance_id": target_id,
                "employee_id": row["employee_id"],
                "operator_id": operator_id,
            },
        )
    )
    return {"ok": True, "action": "mark_absent", "target_id": target_id}


async def _action_approve_leave(
    db: AsyncSession,
    tenant_id: str,
    target_id: str,
    operator_id: str,
    note: Optional[str],
) -> Dict[str, Any]:
    """快速审批请假。"""
    sql = text("""
        UPDATE leave_requests
        SET status = 'approved',
            approved_by = :operator_id,
            approved_at = NOW(),
            updated_at = NOW()
        WHERE id = CAST(:target_id AS uuid)
          AND tenant_id = CAST(:tid AS uuid)
          AND status = 'pending'
        RETURNING id, employee_id, leave_type, start_date, end_date
    """)
    result = await db.execute(
        sql,
        {
            "target_id": target_id,
            "tid": tenant_id,
            "operator_id": operator_id,
        },
    )
    row = result.mappings().first()
    await db.commit()
    if not row:
        return {"ok": False, "error": "leave_not_found_or_not_pending"}

    publisher = UniversalPublisher(tenant_id=tenant_id)
    asyncio.create_task(
        publisher.publish(
            event_type=OrgEventType.LEAVE_APPROVED,
            payload={
                "leave_id": target_id,
                "employee_id": row["employee_id"],
                "leave_type": row["leave_type"],
                "start_date": str(row["start_date"]),
                "end_date": str(row["end_date"]),
                "approved_by": operator_id,
            },
        )
    )
    return {"ok": True, "action": "approve_leave", "target_id": target_id}


async def _action_assign_fill(
    db: AsyncSession,
    tenant_id: str,
    target_id: str,
    operator_id: str,
    note: Optional[str],
) -> Dict[str, Any]:
    """快速指派补位（target_id = gap_id，note 中包含 employee_id）。"""
    if not note:
        return {"ok": False, "error": "note must contain employee_id for assign_fill"}
    # note 格式：employee_id=xxx 或直接就是 UUID
    employee_id = note.strip()
    if employee_id.startswith("employee_id="):
        employee_id = employee_id.split("=", 1)[1].strip()

    result = await execute_fill_gap(
        db,
        tenant_id,
        target_id,
        employee_id,
        "internal_transfer",
    )
    return {"ok": True, "action": "assign_fill", "target_id": target_id, "fill_result": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  周汇总
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_weekly_summary(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
) -> Dict[str, Any]:
    """本周人力概览：7天出勤率/工时/成本趋势。"""
    await _set_tenant(db, tenant_id)
    today = _today()
    # 本周一
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    sql = text("""
        WITH daily_stats AS (
            SELECT da.date,
                   COUNT(DISTINCT da.employee_id) AS attendance_cnt,
                   COALESCE(SUM(da.work_hours), 0) AS total_hours,
                   COALESCE(SUM(da.overtime_hours), 0) AS total_overtime,
                   COUNT(DISTINCT CASE WHEN da.status = 'late' THEN da.employee_id END) AS late_cnt,
                   COUNT(DISTINCT CASE WHEN da.status = 'absent' THEN da.employee_id END) AS absent_cnt
            FROM daily_attendance da
            WHERE da.tenant_id = CAST(:tid AS uuid)
              AND da.store_id = :store_id
              AND da.date BETWEEN :week_start AND :week_end
            GROUP BY da.date
        ),
        daily_scheduled AS (
            SELECT schedule_date,
                   COUNT(DISTINCT employee_id) AS scheduled_cnt
            FROM unified_schedules
            WHERE tenant_id = CAST(:tid AS uuid)
              AND store_id = CAST(:store_id AS uuid)
              AND schedule_date BETWEEN :week_start AND :week_end
              AND status = 'scheduled'
            GROUP BY schedule_date
        )
        SELECT ds.schedule_date AS date,
               COALESCE(dsc.scheduled_cnt, 0) AS scheduled,
               COALESCE(dst.attendance_cnt, 0) AS attended,
               COALESCE(dst.total_hours, 0) AS total_hours,
               COALESCE(dst.total_overtime, 0) AS overtime_hours,
               COALESCE(dst.late_cnt, 0) AS late_cnt,
               COALESCE(dst.absent_cnt, 0) AS absent_cnt,
               CASE WHEN COALESCE(dsc.scheduled_cnt, 0) > 0
                    THEN ROUND(COALESCE(dst.attendance_cnt, 0)::numeric
                               / dsc.scheduled_cnt * 100, 1)
                    ELSE 0 END AS attendance_rate
        FROM daily_scheduled ds
        LEFT JOIN daily_stats dst ON dst.date = ds.schedule_date
        LEFT JOIN daily_scheduled dsc ON dsc.schedule_date = ds.schedule_date
        ORDER BY ds.schedule_date
    """)
    result = await db.execute(
        sql,
        {
            "tid": tenant_id,
            "store_id": store_id,
            "week_start": week_start,
            "week_end": week_end,
        },
    )
    rows = result.mappings().all()

    daily_data = []
    for row in rows:
        daily_data.append(
            {
                "date": str(row["date"]),
                "scheduled": row["scheduled"],
                "attended": row["attended"],
                "total_hours": float(row["total_hours"]),
                "overtime_hours": float(row["overtime_hours"]),
                "late_cnt": row["late_cnt"],
                "absent_cnt": row["absent_cnt"],
                "attendance_rate": float(row["attendance_rate"]),
            }
        )

    # 汇总
    total_scheduled = sum(d["scheduled"] for d in daily_data)
    total_attended = sum(d["attended"] for d in daily_data)
    avg_rate = round(total_attended / total_scheduled * 100, 1) if total_scheduled > 0 else 0

    return {
        "week_start": str(week_start),
        "week_end": str(week_end),
        "store_id": store_id,
        "daily": daily_data,
        "summary": {
            "avg_attendance_rate": avg_rate,
            "total_work_hours": sum(d["total_hours"] for d in daily_data),
            "total_overtime_hours": sum(d["overtime_hours"] for d in daily_data),
            "total_late": sum(d["late_cnt"] for d in daily_data),
            "total_absent": sum(d["absent_cnt"] for d in daily_data),
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  月度人力指标
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_labor_metrics(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    month: str,
) -> Dict[str, Any]:
    """月度人力指标：出勤率/人均工时/人工成本率/加班率/缺勤率。

    Args:
        month: 'YYYY-MM' 格式
    """
    await _set_tenant(db, tenant_id)

    year_int, month_int = int(month[:4]), int(month[5:7])
    month_start = date(year_int, month_int, 1)
    if month_int == 12:
        month_end = date(year_int + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(year_int, month_int + 1, 1) - timedelta(days=1)

    # 出勤统计
    attendance_sql = text("""
        SELECT COUNT(DISTINCT employee_id) AS total_employees,
               COUNT(*) AS total_records,
               COUNT(*) FILTER (WHERE status IN ('normal', 'late', 'early_leave', 'overtime'))
                   AS attended_records,
               COUNT(*) FILTER (WHERE status = 'absent') AS absent_records,
               COUNT(*) FILTER (WHERE status = 'late') AS late_records,
               COALESCE(SUM(work_hours), 0) AS total_work_hours,
               COALESCE(SUM(overtime_hours), 0) AS total_overtime_hours
        FROM daily_attendance
        WHERE tenant_id = CAST(:tid AS uuid)
          AND store_id = :store_id
          AND date BETWEEN :month_start AND :month_end
    """)

    # 排班总数
    scheduled_sql = text("""
        SELECT COUNT(*) AS total_scheduled
        FROM unified_schedules
        WHERE tenant_id = CAST(:tid AS uuid)
          AND store_id = CAST(:store_id AS uuid)
          AND schedule_date BETWEEN :month_start AND :month_end
          AND status = 'scheduled'
    """)

    # 人工成本（从 payroll_batches）
    cost_sql = text("""
        SELECT COALESCE(SUM(total_labor_cost_fen), 0) AS labor_cost_fen
        FROM payroll_batches
        WHERE tenant_id = CAST(:tid AS uuid)
          AND store_id = :store_id
          AND month = :month
          AND status IN ('approved', 'paid')
    """)

    params = {
        "tid": tenant_id,
        "store_id": store_id,
        "month_start": month_start,
        "month_end": month_end,
        "month": month,
    }

    r_att, r_sched, r_cost = await asyncio.gather(
        db.execute(attendance_sql, params),
        db.execute(scheduled_sql, params),
        db.execute(cost_sql, params),
    )

    att = r_att.mappings().first()
    sched = r_sched.mappings().first()
    cost = r_cost.mappings().first()

    total_employees = att["total_employees"] if att else 0
    total_records = att["total_records"] if att else 0
    attended = att["attended_records"] if att else 0
    absent = att["absent_records"] if att else 0
    late = att["late_records"] if att else 0
    total_hours = float(att["total_work_hours"]) if att else 0.0
    overtime = float(att["total_overtime_hours"]) if att else 0.0
    scheduled_total = sched["total_scheduled"] if sched else 0
    labor_cost_fen = cost["labor_cost_fen"] if cost else 0

    attendance_rate = round(attended / scheduled_total * 100, 1) if scheduled_total > 0 else 0
    avg_hours = round(total_hours / total_employees, 1) if total_employees > 0 else 0
    overtime_rate = round(overtime / total_hours * 100, 1) if total_hours > 0 else 0
    absent_rate = round(absent / scheduled_total * 100, 1) if scheduled_total > 0 else 0

    return {
        "month": month,
        "store_id": store_id,
        "total_employees": total_employees,
        "metrics": {
            "attendance_rate": attendance_rate,
            "avg_work_hours_per_person": avg_hours,
            "labor_cost_fen": labor_cost_fen,
            "labor_cost_rate": None,  # 需营收数据
            "overtime_rate": overtime_rate,
            "absent_rate": absent_rate,
            "late_count": late,
        },
        "raw": {
            "scheduled_total": scheduled_total,
            "attended_total": attended,
            "absent_total": absent,
            "total_work_hours": total_hours,
            "total_overtime_hours": overtime,
        },
    }
