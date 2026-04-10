"""缺岗补位服务 — gap_filling_service

职责：
  - 查找门店可用补位员工
  - 按技能匹配度/当前状态排序候选人
  - 创建补位排班记录
  - 通知补位员工（预留IM接口）
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import OrgEventType, UniversalPublisher

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# ── 辅助 ────────────────────────────────────────────────────────────────────


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 查找可用员工 ─────────────────────────────────────────────────────────────


async def find_available_employees(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    target_date: date,
    position: str,
    time_start: time,
    time_end: time,
) -> List[Dict[str, Any]]:
    """查找可补位员工：

    优先级1: 本店今日有排班但在目标时段空闲的员工
    优先级2: 本店今日无排班但在职的员工
    """
    await _set_tenant(db, tenant_id)

    # ── 优先级1：本店有排班但目标时段空闲 ──
    sql_with_schedule = text("""
        SELECT DISTINCT e.id AS employee_id,
               e.emp_name,
               e.role,
               e.skills,
               e.skill_tags,
               'idle_on_shift' AS availability
        FROM employees e
        INNER JOIN unified_schedules us
            ON us.employee_id = e.id
            AND us.tenant_id = CAST(:tid AS uuid)
            AND us.store_id = CAST(:store_id AS uuid)
            AND us.schedule_date = :target_date
            AND us.status = 'scheduled'
        WHERE e.tenant_id = CAST(:tid AS uuid)
          AND e.store_id = CAST(:store_id AS uuid)
          AND e.is_deleted = FALSE
          AND e.is_active = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM unified_schedules us2
              WHERE us2.employee_id = e.id
                AND us2.tenant_id = CAST(:tid AS uuid)
                AND us2.schedule_date = :target_date
                AND us2.status = 'scheduled'
                AND us2.start_time < :time_end
                AND us2.end_time > :time_start
          )
    """)
    result1 = await db.execute(sql_with_schedule, {
        "tid": tenant_id,
        "store_id": store_id,
        "target_date": target_date,
        "time_start": time_start,
        "time_end": time_end,
    })
    rows_on_shift = result1.mappings().all()

    # ── 优先级2：本店在职但今日无排班 ──
    sql_no_schedule = text("""
        SELECT e.id AS employee_id,
               e.emp_name,
               e.role,
               e.skills,
               e.skill_tags,
               'off_duty' AS availability
        FROM employees e
        WHERE e.tenant_id = CAST(:tid AS uuid)
          AND e.store_id = CAST(:store_id AS uuid)
          AND e.is_deleted = FALSE
          AND e.is_active = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM unified_schedules us
              WHERE us.employee_id = e.id
                AND us.tenant_id = CAST(:tid AS uuid)
                AND us.schedule_date = :target_date
                AND us.status = 'scheduled'
          )
          AND NOT EXISTS (
              SELECT 1 FROM leave_requests lr
              WHERE lr.employee_id = CAST(e.id AS text)
                AND lr.tenant_id = CAST(:tid AS uuid)
                AND lr.status = 'approved'
                AND lr.start_date <= :target_date
                AND lr.end_date >= :target_date
          )
    """)
    result2 = await db.execute(sql_no_schedule, {
        "tid": tenant_id,
        "store_id": store_id,
        "target_date": target_date,
    })
    rows_off_duty = result2.mappings().all()

    candidates: List[Dict[str, Any]] = []
    for row in rows_on_shift:
        candidates.append({
            "employee_id": str(row["employee_id"]),
            "emp_name": row["emp_name"],
            "role": row["role"],
            "skills": row["skills"] or [],
            "skill_tags": row["skill_tags"] if row["skill_tags"] else [],
            "availability": row["availability"],
        })
    for row in rows_off_duty:
        candidates.append({
            "employee_id": str(row["employee_id"]),
            "emp_name": row["emp_name"],
            "role": row["role"],
            "skills": row["skills"] or [],
            "skill_tags": row["skill_tags"] if row["skill_tags"] else [],
            "availability": row["availability"],
        })
    return candidates


# ── 候选人排序 ───────────────────────────────────────────────────────────────


def rank_candidates(
    candidates: List[Dict[str, Any]],
    gap_info: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """按技能匹配度和可用性排序候选人。

    排序权重：
      1. 岗位匹配（role 直接匹配目标 position）  +50
      2. 技能标签匹配（skill_tags 包含目标 position） +30
      3. 当班空闲 > 休息日  +20 / +10
    """
    target_position = (gap_info.get("position") or "").lower()

    scored: List[Tuple[int, Dict[str, Any]]] = []
    for c in candidates:
        score = 0
        role = (c.get("role") or "").lower()
        # 角色直接匹配
        if _role_matches_position(role, target_position):
            score += 50
        # 技能标签匹配
        skills_lower = [s.lower() for s in (c.get("skills") or [])]
        tags_lower = [t.lower() for t in (c.get("skill_tags") or [])]
        if target_position in skills_lower or target_position in tags_lower:
            score += 30
        # 可用性
        if c.get("availability") == "idle_on_shift":
            score += 20
        else:
            score += 10
        c["match_score"] = score
        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored]


_ROLE_POSITION_MAP: Dict[str, List[str]] = {
    "cashier": ["收银", "cashier"],
    "waiter": ["服务", "waiter", "服务员"],
    "chef": ["后厨", "chef", "厨师"],
    "cleaner": ["清洁", "cleaner", "保洁"],
    "manager": ["店长", "manager"],
}


def _role_matches_position(role: str, position: str) -> bool:
    """判断 role 是否匹配目标 position。"""
    for r, positions in _ROLE_POSITION_MAP.items():
        if role == r and position in positions:
            return True
        if role in positions and position in positions:
            return True
    return role == position


# ── 创建补位排班 ─────────────────────────────────────────────────────────────


async def create_fill_schedule(
    db: AsyncSession,
    tenant_id: str,
    gap_id: str,
    employee_id: str,
    fill_type: str,
) -> Dict[str, Any]:
    """创建补位排班记录 + 更新缺口状态为 filled。

    Args:
        fill_type: internal_transfer | cross_store | overtime
    """
    await _set_tenant(db, tenant_id)

    # 查询缺口详情
    gap_sql = text("""
        SELECT id, store_id, schedule_date, position, shift_template_id
        FROM shift_gaps
        WHERE id = CAST(:gap_id AS uuid)
          AND tenant_id = CAST(:tid AS uuid)
          AND status = 'open'
    """)
    gap_result = await db.execute(gap_sql, {"gap_id": gap_id, "tid": tenant_id})
    gap_row = gap_result.mappings().first()
    if not gap_row:
        raise ValueError(f"Gap {gap_id} not found or already filled")

    # 查询班次时间（从 shift_template 或默认）
    start_time = time(8, 0)
    end_time = time(17, 0)
    if gap_row["shift_template_id"]:
        tmpl_sql = text("""
            SELECT start_time, end_time FROM shift_templates
            WHERE id = CAST(:tmpl_id AS uuid)
              AND tenant_id = CAST(:tid AS uuid)
        """)
        tmpl_result = await db.execute(tmpl_sql, {
            "tmpl_id": str(gap_row["shift_template_id"]),
            "tid": tenant_id,
        })
        tmpl_row = tmpl_result.mappings().first()
        if tmpl_row:
            start_time = tmpl_row["start_time"]
            end_time = tmpl_row["end_time"]

    schedule_id = str(uuid.uuid4())

    # 插入新排班
    insert_sql = text("""
        INSERT INTO unified_schedules
            (id, tenant_id, store_id, employee_id, schedule_date,
             shift_template_id, start_time, end_time, position,
             status, source, notes)
        VALUES
            (CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:store_id AS uuid),
             CAST(:emp_id AS uuid), :schedule_date,
             :tmpl_id, :start_time, :end_time, :position,
             'scheduled', :source, :notes)
        RETURNING id
    """)
    source_label = {
        "internal_transfer": "fill_internal",
        "cross_store": "fill_cross_store",
        "overtime": "fill_overtime",
    }.get(fill_type, "fill_manual")

    await db.execute(insert_sql, {
        "id": schedule_id,
        "tid": tenant_id,
        "store_id": str(gap_row["store_id"]),
        "emp_id": employee_id,
        "schedule_date": gap_row["schedule_date"],
        "tmpl_id": str(gap_row["shift_template_id"]) if gap_row["shift_template_id"] else None,
        "start_time": start_time,
        "end_time": end_time,
        "position": gap_row["position"],
        "source": source_label,
        "notes": f"补位(gap={gap_id}, type={fill_type})",
    })

    # 更新缺口状态
    update_gap_sql = text("""
        UPDATE shift_gaps
        SET status = 'filled',
            claimed_by = CAST(:emp_id AS uuid),
            filled_at = NOW()
        WHERE id = CAST(:gap_id AS uuid)
          AND tenant_id = CAST(:tid AS uuid)
    """)
    await db.execute(update_gap_sql, {
        "emp_id": employee_id,
        "gap_id": gap_id,
        "tid": tenant_id,
    })

    await db.commit()

    log.info(
        "fill_schedule_created",
        gap_id=gap_id,
        employee_id=employee_id,
        fill_type=fill_type,
        schedule_id=schedule_id,
    )

    return {
        "schedule_id": schedule_id,
        "gap_id": gap_id,
        "employee_id": employee_id,
        "store_id": str(gap_row["store_id"]),
        "schedule_date": str(gap_row["schedule_date"]),
        "position": gap_row["position"],
        "fill_type": fill_type,
        "start_time": str(start_time),
        "end_time": str(end_time),
    }


# ── 通知补位员工（预留IM接口）─────────────────────────────────────────────


async def notify_fill(
    tenant_id: str,
    employee_id: str,
    gap_info: Dict[str, Any],
) -> None:
    """通知补位员工 — 预留IM接口，当前仅记录日志。

    后续对接企微/钉钉 IM 推送。
    """
    log.info(
        "fill_notification_sent",
        tenant_id=tenant_id,
        employee_id=employee_id,
        gap_id=gap_info.get("gap_id"),
        position=gap_info.get("position"),
        schedule_date=gap_info.get("schedule_date"),
    )
    # TODO: 对接 im_sync_service 推送消息
