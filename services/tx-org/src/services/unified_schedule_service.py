"""统一排班服务层 — 基于 unified_schedules 表

核心方法：
  get_week_schedule         查询一周排班 + JOIN 员工名 + 模板名
  create_schedule           创建 + 冲突校验
  batch_create_schedules    批量创建
  detect_conflicts          冲突检测 SQL
  swap_schedules            调班逻辑
  auto_detect_gaps          对比岗位编制需求 vs 实际排班，找出缺口
  get_fill_suggestions      推荐可补位员工（本店空闲 + 临近门店）

依赖表：unified_schedules, shift_templates, shift_gaps, employees,
        store_staffing_requirements（岗位编制需求表）
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  周排班查询
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_week_schedule(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    start_date: date,
) -> dict[str, Any]:
    """查询一周排班 + JOIN 员工名 + 模板名，按员工分组返回7天排班矩阵。"""
    end_date = start_date + timedelta(days=6)
    dates = [(start_date + timedelta(days=i)).isoformat() for i in range(7)]

    result = await db.execute(
        text(
            "SELECT us.id, us.employee_id, us.schedule_date, "
            "us.shift_start::text, us.shift_end::text, "
            "us.template_id, us.role, us.status, us.notes, "
            "e.name AS employee_name, e.position AS employee_position, "
            "st.name AS template_name, st.color AS template_color "
            "FROM unified_schedules us "
            "LEFT JOIN employees e ON e.id = us.employee_id "
            "  AND e.tenant_id = us.tenant_id AND e.is_deleted = FALSE "
            "LEFT JOIN shift_templates st ON st.id = us.template_id "
            "  AND st.tenant_id = us.tenant_id AND st.is_deleted = FALSE "
            "WHERE us.tenant_id = :tid::uuid "
            "AND us.store_id = :store_id::uuid "
            "AND us.schedule_date BETWEEN :start AND :end "
            "AND us.is_deleted = FALSE "
            "ORDER BY us.employee_id, us.schedule_date, us.shift_start"
        ),
        {"tid": tenant_id, "store_id": store_id, "start": start_date, "end": end_date},
    )
    rows = [dict(r) for r in result.mappings().fetchall()]

    # 按员工聚合
    emp_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        eid = str(row["employee_id"])
        if eid not in emp_map:
            emp_map[eid] = {
                "employee_id": eid,
                "name": row.get("employee_name"),
                "position": row.get("employee_position"),
                "shifts": [],
            }
        emp_map[eid]["shifts"].append({
            "schedule_id": str(row["id"]),
            "date": row["schedule_date"].isoformat() if hasattr(row["schedule_date"], "isoformat") else str(row["schedule_date"]),
            "shift_start": str(row["shift_start"]),
            "shift_end": str(row["shift_end"]),
            "status": row.get("status", "scheduled"),
            "role": row.get("role"),
            "template_id": str(row["template_id"]) if row.get("template_id") else None,
            "template_name": row.get("template_name"),
            "template_color": row.get("template_color"),
            "notes": row.get("notes"),
        })

    return {
        "store_id": store_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "dates": dates,
        "employees": list(emp_map.values()),
        "total_shifts": len(rows),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  创建排班（含冲突校验）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_schedule(
    db: AsyncSession,
    tenant_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """创建单条排班，创建前自动校验冲突。

    Args:
        data: 包含 employee_id, store_id, schedule_date, shift_start, shift_end,
              template_id(可选), role(可选), notes(可选)

    Returns:
        创建成功的排班记录字典

    Raises:
        ValueError: 存在时间冲突
    """
    employee_id = data["employee_id"]
    schedule_date = data["schedule_date"]
    shift_start = data["shift_start"]
    shift_end = data["shift_end"]

    # 冲突校验：同一员工、同一天，是否有时间重叠的排班
    conflict_check = await db.execute(
        text(
            "SELECT id, shift_start::text, shift_end::text "
            "FROM unified_schedules "
            "WHERE tenant_id = :tid::uuid AND employee_id = :eid::uuid "
            "AND schedule_date = :d AND is_deleted = FALSE "
            "AND status != 'cancelled' "
            "AND shift_start < :new_end::time AND shift_end > :new_start::time"
        ),
        {
            "tid": tenant_id, "eid": employee_id,
            "d": schedule_date, "new_start": shift_start, "new_end": shift_end,
        },
    )
    conflict_row = conflict_check.mappings().first()
    if conflict_row is not None:
        conflict = dict(conflict_row)
        raise ValueError(
            f"排班冲突：员工 {employee_id} 在 {schedule_date} "
            f"已有排班 {conflict['shift_start']}-{conflict['shift_end']}，"
            f"与新排班 {shift_start}-{shift_end} 时间重叠"
        )

    result = await db.execute(
        text(
            "INSERT INTO unified_schedules "
            "(tenant_id, store_id, employee_id, schedule_date, shift_start, shift_end, "
            "template_id, role, status, notes) "
            "VALUES (:tid::uuid, :store_id::uuid, :eid::uuid, :d, "
            ":start::time, :end::time, :tmpl_id::uuid, :role, 'scheduled', :notes) "
            "RETURNING id, schedule_date, shift_start::text, shift_end::text, status"
        ),
        {
            "tid": tenant_id,
            "store_id": data["store_id"],
            "eid": employee_id,
            "d": schedule_date,
            "start": shift_start,
            "end": shift_end,
            "tmpl_id": data.get("template_id"),
            "role": data.get("role"),
            "notes": data.get("notes"),
        },
    )
    row = result.mappings().first()
    if row is None:
        raise RuntimeError("创建排班失败：INSERT 未返回记录")

    row_data = dict(row)
    log.info(
        "schedule_created_svc",
        schedule_id=str(row_data["id"]),
        employee_id=employee_id,
        schedule_date=str(schedule_date),
    )
    return {
        "schedule_id": str(row_data["id"]),
        "employee_id": employee_id,
        "store_id": data["store_id"],
        "schedule_date": row_data["schedule_date"].isoformat() if hasattr(row_data["schedule_date"], "isoformat") else str(row_data["schedule_date"]),
        "shift_start": str(row_data["shift_start"]),
        "shift_end": str(row_data["shift_end"]),
        "status": row_data["status"],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  批量创建排班
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def batch_create_schedules(
    db: AsyncSession,
    tenant_id: str,
    template_id: str,
    employee_ids: list[str],
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """按模板 + 员工列表 + 日期范围批量创建排班。

    从 shift_templates 获取班次时间，为每个员工在日期范围内的每天创建排班。
    冲突时跳过（ON CONFLICT DO NOTHING）。

    Returns:
        包含 inserted / skipped_conflicts / total_attempted 的统计字典
    """
    # 获取模板信息
    tmpl_result = await db.execute(
        text(
            "SELECT id, store_id, name, shift_start::text, shift_end::text "
            "FROM shift_templates "
            "WHERE id = :tid_tmpl::uuid AND tenant_id = :tid::uuid AND is_deleted = FALSE"
        ),
        {"tid_tmpl": template_id, "tid": tenant_id},
    )
    tmpl_row = tmpl_result.mappings().first()
    if tmpl_row is None:
        raise ValueError(f"班次模板 {template_id} 不存在")

    tmpl = dict(tmpl_row)
    store_id = str(tmpl["store_id"])
    shift_start = str(tmpl["shift_start"])
    shift_end = str(tmpl["shift_end"])

    inserted = 0
    skipped = 0
    total_days = (end_date - start_date).days + 1

    for eid in employee_ids:
        for day_offset in range(total_days):
            target_date = start_date + timedelta(days=day_offset)
            result = await db.execute(
                text(
                    "INSERT INTO unified_schedules "
                    "(tenant_id, store_id, employee_id, schedule_date, "
                    "shift_start, shift_end, template_id, status) "
                    "VALUES (:tid::uuid, :store_id::uuid, :eid::uuid, :d, "
                    ":start::time, :end::time, :tmpl_id::uuid, 'scheduled') "
                    "ON CONFLICT (tenant_id, employee_id, schedule_date, shift_start) DO NOTHING "
                    "RETURNING id"
                ),
                {
                    "tid": tenant_id, "store_id": store_id,
                    "eid": eid, "d": target_date,
                    "start": shift_start, "end": shift_end,
                    "tmpl_id": template_id,
                },
            )
            row = result.mappings().first()
            if row is not None:
                inserted += 1
            else:
                skipped += 1

    total_attempted = inserted + skipped

    log.info(
        "batch_schedules_created_svc",
        template_id=template_id,
        employee_count=len(employee_ids),
        inserted=inserted,
        skipped=skipped,
    )
    return {
        "store_id": store_id,
        "template_id": template_id,
        "template_name": tmpl["name"],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "employee_count": len(employee_ids),
        "inserted": inserted,
        "skipped_conflicts": skipped,
        "total_attempted": total_attempted,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  冲突检测
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def detect_conflicts(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """检测指定门店、日期范围内的排班冲突。

    冲突定义：同一员工、同一天，两条排班记录存在时间重叠。
    SQL 使用自连接 + a.id < b.id 避免重复配对。
    """
    result = await db.execute(
        text(
            "SELECT a.id AS schedule_id_a, b.id AS schedule_id_b, "
            "a.employee_id, a.schedule_date, "
            "a.shift_start::text AS start_a, a.shift_end::text AS end_a, "
            "b.shift_start::text AS start_b, b.shift_end::text AS end_b, "
            "e.name AS employee_name "
            "FROM unified_schedules a "
            "JOIN unified_schedules b "
            "  ON a.tenant_id = b.tenant_id "
            "  AND a.employee_id = b.employee_id "
            "  AND a.schedule_date = b.schedule_date "
            "  AND a.id < b.id "
            "  AND a.shift_start < b.shift_end "
            "  AND a.shift_end > b.shift_start "
            "LEFT JOIN employees e ON e.id = a.employee_id "
            "  AND e.tenant_id = a.tenant_id AND e.is_deleted = FALSE "
            "WHERE a.tenant_id = :tid::uuid "
            "AND a.store_id = :store_id::uuid "
            "AND a.schedule_date BETWEEN :start AND :end "
            "AND a.is_deleted = FALSE AND b.is_deleted = FALSE "
            "AND a.status != 'cancelled' AND b.status != 'cancelled' "
            "ORDER BY a.schedule_date, a.employee_id"
        ),
        {"tid": tenant_id, "store_id": store_id, "start": start_date, "end": end_date},
    )
    rows = result.mappings().fetchall()

    conflicts = [
        {
            "employee_id": str(row["employee_id"]),
            "employee_name": row.get("employee_name"),
            "date": row["schedule_date"].isoformat() if hasattr(row["schedule_date"], "isoformat") else str(row["schedule_date"]),
            "conflict_a": {
                "schedule_id": str(row["schedule_id_a"]),
                "shift_start": str(row["start_a"]),
                "shift_end": str(row["end_a"]),
            },
            "conflict_b": {
                "schedule_id": str(row["schedule_id_b"]),
                "shift_start": str(row["start_b"]),
                "shift_end": str(row["end_b"]),
            },
        }
        for row in rows
    ]

    log.info(
        "conflicts_detected_svc",
        store_id=store_id,
        date_range=f"{start_date}~{end_date}",
        conflict_count=len(conflicts),
    )
    return conflicts


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  调班逻辑
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def swap_schedules(
    db: AsyncSession,
    tenant_id: str,
    from_schedule_id: str,
    to_employee_id: str,
) -> dict[str, Any]:
    """执行调班：将排班记录的 employee_id 更换为目标员工。

    调班前校验目标员工在该时段是否存在冲突。

    Returns:
        调班后的排班信息字典

    Raises:
        ValueError: 目标员工在该时段已有排班
    """
    # 获取原排班
    orig_result = await db.execute(
        text(
            "SELECT id, employee_id, store_id, schedule_date, "
            "shift_start::text, shift_end::text, role "
            "FROM unified_schedules "
            "WHERE id = :sid::uuid AND tenant_id = :tid::uuid AND is_deleted = FALSE"
        ),
        {"sid": from_schedule_id, "tid": tenant_id},
    )
    orig_row = orig_result.mappings().first()
    if orig_row is None:
        raise ValueError(f"排班记录 {from_schedule_id} 不存在")

    orig = dict(orig_row)
    from_employee_id = str(orig["employee_id"])

    # 检查目标员工在该时段是否有冲突
    conflict_check = await db.execute(
        text(
            "SELECT id FROM unified_schedules "
            "WHERE tenant_id = :tid::uuid AND employee_id = :eid::uuid "
            "AND schedule_date = :d AND is_deleted = FALSE "
            "AND status != 'cancelled' "
            "AND shift_start < :end::time AND shift_end > :start::time"
        ),
        {
            "tid": tenant_id, "eid": to_employee_id,
            "d": orig["schedule_date"],
            "start": str(orig["shift_start"]),
            "end": str(orig["shift_end"]),
        },
    )
    if conflict_check.mappings().first() is not None:
        raise ValueError(
            f"目标员工 {to_employee_id} 在 {orig['schedule_date']} "
            f"{orig['shift_start']}-{orig['shift_end']} 已有排班，无法调班"
        )

    # 执行调班
    await db.execute(
        text(
            "UPDATE unified_schedules "
            "SET employee_id = :new_eid::uuid, updated_at = NOW(), "
            "notes = COALESCE(notes, '') || ' [调班: ' || :from_eid || ' -> ' || :to_eid || ']' "
            "WHERE id = :sid::uuid AND tenant_id = :tid::uuid"
        ),
        {
            "new_eid": to_employee_id, "from_eid": from_employee_id,
            "to_eid": to_employee_id, "sid": from_schedule_id, "tid": tenant_id,
        },
    )

    log.info(
        "schedule_swapped_svc",
        schedule_id=from_schedule_id,
        from_employee=from_employee_id,
        to_employee=to_employee_id,
    )
    return {
        "schedule_id": from_schedule_id,
        "from_employee_id": from_employee_id,
        "to_employee_id": to_employee_id,
        "schedule_date": orig["schedule_date"].isoformat() if hasattr(orig["schedule_date"], "isoformat") else str(orig["schedule_date"]),
        "shift_start": str(orig["shift_start"]),
        "shift_end": str(orig["shift_end"]),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  缺口自动检测
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def auto_detect_gaps(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    target_date: date,
) -> list[dict[str, Any]]:
    """自动检测排班缺口：对比门店岗位编制需求与实际排班数量。

    逻辑：
    1. 从 store_staffing_requirements 获取当天各时段各岗位的最低人力需求
    2. 从 unified_schedules 统计实际排班人数
    3. 需求 > 实际排班 = 缺口

    如果 store_staffing_requirements 表尚不存在，降级为基于班次模板的简单对比。
    """
    gaps: list[dict[str, Any]] = []

    # 尝试从编制需求表读取
    try:
        req_result = await db.execute(
            text(
                "SELECT role, shift_start::text, shift_end::text, min_headcount "
                "FROM store_staffing_requirements "
                "WHERE tenant_id = :tid::uuid AND store_id = :store_id::uuid "
                "AND effective_date <= :d "
                "AND (expiry_date IS NULL OR expiry_date > :d) "
                "AND is_deleted = FALSE "
                "ORDER BY shift_start, role"
            ),
            {"tid": tenant_id, "store_id": store_id, "d": target_date},
        )
        requirements = [dict(r) for r in req_result.mappings().fetchall()]
    except Exception as exc:
        # 编制需求表可能尚未创建，降级处理
        if "does not exist" in str(exc) or "UndefinedTable" in type(exc).__name__:
            log.warning("staffing_requirements_table_missing", store_id=store_id)
            requirements = []
        else:
            raise

    if not requirements:
        # 降级策略：基于班次模板统计人力缺口
        # 查询该门店所有模板，假设每个模板每个时段至少需要1人
        tmpl_result = await db.execute(
            text(
                "SELECT DISTINCT shift_start::text, shift_end::text "
                "FROM shift_templates "
                "WHERE tenant_id = :tid::uuid AND store_id = :store_id::uuid "
                "AND is_deleted = FALSE"
            ),
            {"tid": tenant_id, "store_id": store_id},
        )
        templates = [dict(r) for r in tmpl_result.mappings().fetchall()]

        for tmpl in templates:
            actual_result = await db.execute(
                text(
                    "SELECT COUNT(*) AS cnt "
                    "FROM unified_schedules "
                    "WHERE tenant_id = :tid::uuid AND store_id = :store_id::uuid "
                    "AND schedule_date = :d AND is_deleted = FALSE "
                    "AND status != 'cancelled' "
                    "AND shift_start = :start::time AND shift_end = :end::time"
                ),
                {
                    "tid": tenant_id, "store_id": store_id,
                    "d": target_date, "start": tmpl["shift_start"], "end": tmpl["shift_end"],
                },
            )
            cnt = actual_result.scalar() or 0
            if cnt == 0:
                gaps.append({
                    "shift_start": tmpl["shift_start"],
                    "shift_end": tmpl["shift_end"],
                    "role": "general",
                    "required": 1,
                    "actual": 0,
                    "shortage": 1,
                    "detection_method": "template_fallback",
                })

        log.info("gaps_detected_fallback", store_id=store_id, date=str(target_date), gap_count=len(gaps))
        return gaps

    # 正式对比逻辑
    for req in requirements:
        actual_result = await db.execute(
            text(
                "SELECT COUNT(*) AS cnt "
                "FROM unified_schedules "
                "WHERE tenant_id = :tid::uuid AND store_id = :store_id::uuid "
                "AND schedule_date = :d AND is_deleted = FALSE "
                "AND status != 'cancelled' "
                "AND role = :role "
                "AND shift_start < :req_end::time AND shift_end > :req_start::time"
            ),
            {
                "tid": tenant_id, "store_id": store_id, "d": target_date,
                "role": req["role"],
                "req_start": req["shift_start"], "req_end": req["shift_end"],
            },
        )
        actual_count = actual_result.scalar() or 0
        min_headcount = req["min_headcount"]

        if actual_count < min_headcount:
            gaps.append({
                "shift_start": req["shift_start"],
                "shift_end": req["shift_end"],
                "role": req["role"],
                "required": min_headcount,
                "actual": actual_count,
                "shortage": min_headcount - actual_count,
                "detection_method": "staffing_requirement",
            })

    log.info("gaps_detected_svc", store_id=store_id, date=str(target_date), gap_count=len(gaps))
    return gaps


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  填补推荐
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_fill_suggestions(
    db: AsyncSession,
    tenant_id: str,
    gap_id: str,
) -> list[dict[str, Any]]:
    """推荐可补位员工：本店空闲员工 + 临近门店可调配员工。

    优先级：
    1. 本店、当天无排班的同岗位员工
    2. 本店、当天有排班但时段不冲突的员工
    3. 临近门店（同品牌）的空闲员工

    Returns:
        推荐员工列表，按优先级排序
    """
    # 获取缺口详情
    gap_result = await db.execute(
        text(
            "SELECT id, store_id, gap_date, shift_start::text, shift_end::text, role "
            "FROM shift_gaps "
            "WHERE id = :gid::uuid AND tenant_id = :tid::uuid AND is_deleted = FALSE"
        ),
        {"gid": gap_id, "tid": tenant_id},
    )
    gap_row = gap_result.mappings().first()
    if gap_row is None:
        raise ValueError(f"缺口记录 {gap_id} 不存在")

    gap = dict(gap_row)
    store_id = str(gap["store_id"])
    gap_date = gap["gap_date"]
    shift_start = str(gap["shift_start"])
    shift_end = str(gap["shift_end"])
    role = gap["role"]

    suggestions: list[dict[str, Any]] = []

    # 优先级1：本店当天完全空闲的同岗位员工
    free_result = await db.execute(
        text(
            "SELECT e.id AS employee_id, e.name, e.position "
            "FROM employees e "
            "WHERE e.tenant_id = :tid::uuid "
            "AND e.store_id = :store_id::uuid "
            "AND e.is_deleted = FALSE "
            "AND e.status = 'active' "
            "AND e.id NOT IN ( "
            "  SELECT us.employee_id FROM unified_schedules us "
            "  WHERE us.tenant_id = :tid::uuid AND us.schedule_date = :d "
            "  AND us.is_deleted = FALSE AND us.status != 'cancelled' "
            ") "
            "ORDER BY CASE WHEN e.position = :role THEN 0 ELSE 1 END, e.name "
            "LIMIT 10"
        ),
        {"tid": tenant_id, "store_id": store_id, "d": gap_date, "role": role},
    )
    for row in free_result.mappings().fetchall():
        suggestions.append({
            "employee_id": str(row["employee_id"]),
            "name": row["name"],
            "position": row.get("position"),
            "priority": 1,
            "reason": "本店当天无排班",
            "source_store_id": store_id,
        })

    # 优先级2：本店当天有排班但时段不冲突的员工
    no_conflict_result = await db.execute(
        text(
            "SELECT DISTINCT e.id AS employee_id, e.name, e.position "
            "FROM employees e "
            "JOIN unified_schedules us ON us.employee_id = e.id "
            "  AND us.tenant_id = e.tenant_id "
            "WHERE e.tenant_id = :tid::uuid "
            "AND e.store_id = :store_id::uuid "
            "AND e.is_deleted = FALSE AND e.status = 'active' "
            "AND us.schedule_date = :d AND us.is_deleted = FALSE "
            "AND us.status != 'cancelled' "
            "AND e.id NOT IN ( "
            "  SELECT us2.employee_id FROM unified_schedules us2 "
            "  WHERE us2.tenant_id = :tid::uuid AND us2.schedule_date = :d "
            "  AND us2.is_deleted = FALSE AND us2.status != 'cancelled' "
            "  AND us2.shift_start < :gap_end::time AND us2.shift_end > :gap_start::time "
            ") "
            "ORDER BY CASE WHEN e.position = :role THEN 0 ELSE 1 END, e.name "
            "LIMIT 10"
        ),
        {
            "tid": tenant_id, "store_id": store_id, "d": gap_date,
            "gap_start": shift_start, "gap_end": shift_end, "role": role,
        },
    )
    existing_ids = {s["employee_id"] for s in suggestions}
    for row in no_conflict_result.mappings().fetchall():
        eid = str(row["employee_id"])
        if eid not in existing_ids:
            suggestions.append({
                "employee_id": eid,
                "name": row["name"],
                "position": row.get("position"),
                "priority": 2,
                "reason": "本店当天有排班但时段不冲突",
                "source_store_id": store_id,
            })
            existing_ids.add(eid)

    # 优先级3：同品牌临近门店空闲员工
    try:
        nearby_result = await db.execute(
            text(
                "SELECT e.id AS employee_id, e.name, e.position, e.store_id AS source_store_id "
                "FROM employees e "
                "WHERE e.tenant_id = :tid::uuid "
                "AND e.store_id != :store_id::uuid "
                "AND e.is_deleted = FALSE AND e.status = 'active' "
                "AND e.id NOT IN ( "
                "  SELECT us.employee_id FROM unified_schedules us "
                "  WHERE us.tenant_id = :tid::uuid AND us.schedule_date = :d "
                "  AND us.is_deleted = FALSE AND us.status != 'cancelled' "
                ") "
                "ORDER BY CASE WHEN e.position = :role THEN 0 ELSE 1 END, e.name "
                "LIMIT 5"
            ),
            {"tid": tenant_id, "store_id": store_id, "d": gap_date, "role": role},
        )
        for row in nearby_result.mappings().fetchall():
            eid = str(row["employee_id"])
            if eid not in existing_ids:
                suggestions.append({
                    "employee_id": eid,
                    "name": row["name"],
                    "position": row.get("position"),
                    "priority": 3,
                    "reason": "临近门店当天无排班",
                    "source_store_id": str(row["source_store_id"]),
                })
                existing_ids.add(eid)
    except Exception as exc:
        log.warning("nearby_store_query_failed", error=str(exc))

    log.info("fill_suggestions_svc", gap_id=gap_id, suggestion_count=len(suggestions))
    return suggestions
