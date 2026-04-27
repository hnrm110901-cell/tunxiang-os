"""屯象OS tx-org 域绩效在线打分服务。金额相关字段在关联业务表中单位为分（fen）；本表 weighted_total 为加权总分非金额。RLS：每次 DB 操作前设置 app.tenant_id。"""

from __future__ import annotations

import json
import math
from calendar import monthrange
from datetime import date
from typing import Any, Mapping
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

SCORING_DIMENSIONS: dict[str, dict[str, Any]] = {
    "service": {"name": "服务质量", "weight": 0.25, "max_score": 100},
    "sales": {"name": "销售业绩", "weight": 0.25, "max_score": 100},
    "attendance": {"name": "出勤纪律", "weight": 0.20, "max_score": 100},
    "skill": {"name": "技能成长", "weight": 0.15, "max_score": 100},
    "teamwork": {"name": "团队协作", "weight": 0.10, "max_score": 100},
    "innovation": {"name": "创新改善", "weight": 0.05, "max_score": 100},
}

ROLE_WEIGHT_OVERRIDES: dict[str, dict[str, float]] = {
    "chef": {
        "service": 0.15,
        "sales": 0.10,
        "skill": 0.30,
        "attendance": 0.25,
        "teamwork": 0.15,
        "innovation": 0.05,
    },
    "waiter": {
        "service": 0.35,
        "sales": 0.20,
        "attendance": 0.20,
        "skill": 0.10,
        "teamwork": 0.10,
        "innovation": 0.05,
    },
    "manager": {
        "service": 0.15,
        "sales": 0.25,
        "attendance": 0.15,
        "skill": 0.10,
        "teamwork": 0.20,
        "innovation": 0.15,
    },
}


async def _set_tenant(db: AsyncSession, tenant_id: UUID) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


def _base_weights() -> dict[str, float]:
    return {k: float(v["weight"]) for k, v in SCORING_DIMENSIONS.items()}


def _weights_for_role(role: str | None) -> dict[str, float]:
    key = (role or "").strip().lower()
    if key in ROLE_WEIGHT_OVERRIDES:
        return dict(ROLE_WEIGHT_OVERRIDES[key])
    return _base_weights()


def _validate_dimension_scores(dimension_scores: Mapping[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for dim in SCORING_DIMENSIONS:
        if dim not in dimension_scores:
            raise ValueError(f"缺少评分维度: {dim}")
        raw = dimension_scores[dim]
        if not isinstance(raw, (int, float)):
            raise ValueError(f"维度 {dim} 分值须为数字")
        mx = int(SCORING_DIMENSIONS[dim]["max_score"])
        s = float(raw)
        if s < 0 or s > mx:
            raise ValueError(f"维度 {dim} 分值须在 0～{mx} 之间")
        out[dim] = s
    return out


def _weighted_total(dimension_scores: Mapping[str, float], weights: Mapping[str, float]) -> float:
    total = sum(dimension_scores[d] * float(weights[d]) for d in SCORING_DIMENSIONS)
    return round(total, 2)


def _rank_hint_label(score: float) -> str:
    if score >= 90:
        return "领先组"
    if score >= 80:
        return "良好"
    if score >= 70:
        return "达标"
    return "待提升"


def _month_bounds(month: str) -> tuple[date, date]:
    parts = month.split("-")
    if len(parts) != 2:
        raise ValueError('月份格式须为 "YYYY-MM"')
    y, m = int(parts[0]), int(parts[1])
    if m < 1 or m > 12:
        raise ValueError("月份非法")
    start = date(y, m, 1)
    _, last = monthrange(y, m)
    end = date(y, m, last)
    return start, end


async def _fetch_employee_role(
    db: AsyncSession,
    tenant_id: UUID,
    employee_id: UUID,
) -> str | None:
    await _set_tenant(db, tenant_id)
    row = await db.execute(
        text(
            """
            SELECT role FROM employees
            WHERE tenant_id = :tid AND id = :eid AND is_deleted = FALSE
            """
        ),
        {"tid": tenant_id, "eid": employee_id},
    )
    one = row.mappings().first()
    if one is None:
        return None
    role_val = one["role"]
    return str(role_val) if role_val is not None else ""


async def submit_score(
    db: AsyncSession,
    tenant_id: UUID,
    scorer_id: UUID,
    employee_id: UUID,
    month: str,
    dimension_scores: dict[str, Any],
) -> dict[str, Any]:
    """提交绩效打分。"""
    validated = _validate_dimension_scores(dimension_scores)
    role = await _fetch_employee_role(db, tenant_id, employee_id)
    if role is None:
        raise ValueError(f"员工不存在: {employee_id}")
    weights = _weights_for_role(role)
    wtotal = _weighted_total(validated, weights)
    await _set_tenant(db, tenant_id)
    dim_json = json.dumps(validated, ensure_ascii=False)
    new_id = uuid4()
    await db.execute(
        text(
            """
            INSERT INTO performance_scores (
                id, tenant_id, employee_id, scorer_id, month,
                dimension_scores, weighted_total, created_at
            )
            VALUES (
                :id, :tid, :eid, :scid, :mon,
                CAST(:dim AS jsonb), :wt, NOW()
            )
            ON CONFLICT (tenant_id, employee_id, scorer_id, month)
            DO UPDATE SET
                dimension_scores = EXCLUDED.dimension_scores,
                weighted_total = EXCLUDED.weighted_total,
                created_at = NOW()
            """
        ),
        {
            "id": new_id,
            "tid": tenant_id,
            "eid": employee_id,
            "scid": scorer_id,
            "mon": month,
            "dim": dim_json,
            "wt": wtotal,
        },
    )
    log.info(
        "performance_score_submitted",
        tenant_id=str(tenant_id),
        employee_id=str(employee_id),
        scorer_id=str(scorer_id),
        month=month,
        weighted_total=wtotal,
    )
    return {
        "employee_id": str(employee_id),
        "month": month,
        "weighted_total": float(wtotal),
        "dimension_scores": {k: float(validated[k]) for k in validated},
        "rank_hint": _rank_hint_label(float(wtotal)),
    }


async def get_scores(
    db: AsyncSession,
    tenant_id: UUID,
    store_id: UUID | None = None,
    month: str | None = None,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """查询绩效得分列表。"""
    if page < 1:
        raise ValueError("page 须 >= 1")
    if size < 1 or size > 100:
        raise ValueError("size 须在 1～100 之间")
    await _set_tenant(db, tenant_id)
    conds = ["ps.tenant_id = :tid", "e.is_deleted = FALSE"]
    params: dict[str, Any] = {"tid": tenant_id}
    if store_id is not None:
        conds.append("e.store_id = :sid")
        params["sid"] = store_id
    if month is not None:
        conds.append("ps.month = :mon")
        params["mon"] = month
    where_sql = " AND ".join(conds)
    count_row = await db.execute(
        text(
            f"""
            SELECT COUNT(*) AS n
            FROM performance_scores ps
            JOIN employees e ON e.id = ps.employee_id AND e.tenant_id = ps.tenant_id
            WHERE {where_sql}
            """
        ),
        params,
    )
    total = int(count_row.scalar() or 0)
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset
    rows = await db.execute(
        text(
            f"""
            SELECT * FROM (
                SELECT
                    ps.id, ps.employee_id, ps.scorer_id, ps.month,
                    ps.dimension_scores, ps.weighted_total, ps.comment, ps.created_at,
                    e.emp_name, e.role, e.store_id,
                    s.store_name AS store_name,
                    RANK() OVER (
                        PARTITION BY e.store_id, ps.month
                        ORDER BY ps.weighted_total DESC NULLS LAST,
                                 ps.created_at DESC,
                                 ps.id
                    ) AS rank_in_store
                FROM performance_scores ps
                JOIN employees e ON e.id = ps.employee_id AND e.tenant_id = ps.tenant_id
                LEFT JOIN stores s
                    ON s.id = e.store_id AND s.tenant_id = e.tenant_id AND s.is_deleted = FALSE
                WHERE {where_sql}
            ) AS ranked
            ORDER BY ranked.created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )
    items: list[dict[str, Any]] = []
    for r in rows.mappings().fetchall():
        row = dict(r)
        ds = row.get("dimension_scores")
        if isinstance(ds, str):
            ds = json.loads(ds)
        row["dimension_scores"] = ds
        if row.get("weighted_total") is not None:
            row["weighted_total"] = float(row["weighted_total"])
        items.append(row)
    return {"items": items, "total": total}


async def get_rankings(
    db: AsyncSession,
    tenant_id: UUID,
    store_id: UUID,
    month: str,
) -> list[dict[str, Any]]:
    """获取门店月度排名。"""
    await _set_tenant(db, tenant_id)
    rows = await db.execute(
        text(
            """
            WITH best AS (
                SELECT DISTINCT ON (ps.employee_id)
                    ps.employee_id,
                    e.emp_name,
                    e.role,
                    ps.weighted_total
                FROM performance_scores ps
                JOIN employees e
                    ON e.id = ps.employee_id AND e.tenant_id = ps.tenant_id
                WHERE ps.tenant_id = :tid
                  AND e.store_id = :sid
                  AND ps.month = :mon
                  AND e.is_deleted = FALSE
                ORDER BY ps.employee_id, ps.weighted_total DESC, ps.created_at DESC
            )
            SELECT employee_id, emp_name, role, weighted_total
            FROM best
            ORDER BY weighted_total DESC NULLS LAST, employee_id
            """
        ),
        {"tid": tenant_id, "sid": store_id, "mon": month},
    )
    out: list[dict[str, Any]] = []
    rank = 0
    prev: float | None = None
    for i, r in enumerate(rows.mappings().fetchall(), start=1):
        wt = r["weighted_total"]
        wt_f = float(wt) if wt is not None else 0.0
        if prev is None or float(wt_f) != float(prev):
            rank = i
            prev = wt_f
        out.append(
            {
                "employee_id": str(r["employee_id"]),
                "emp_name": r["emp_name"],
                "role": r["role"],
                "weighted_total": wt_f,
                "rank": rank,
            }
        )
    return out


async def compute_horse_race(
    db: AsyncSession,
    tenant_id: UUID,
    store_ids: list[str],
    month: str,
) -> dict[str, Any]:
    """赛马机制 — 门店间绩效 PK。"""
    if not store_ids:
        return {"stores": []}
    uuids = [UUID(s) for s in store_ids]
    in_ph = ", ".join(f":sid{i}" for i in range(len(uuids)))
    params: dict[str, Any] = {"tid": tenant_id, "mon": month}
    for i, u in enumerate(uuids):
        params[f"sid{i}"] = u
    await _set_tenant(db, tenant_id)
    rows = await db.execute(
        text(
            f"""
            WITH best AS (
                SELECT DISTINCT ON (ps.employee_id)
                    ps.employee_id,
                    e.store_id,
                    ps.weighted_total
                FROM performance_scores ps
                JOIN employees e
                    ON e.id = ps.employee_id AND e.tenant_id = ps.tenant_id
                WHERE ps.tenant_id = :tid
                  AND ps.month = :mon
                  AND e.store_id IN ({in_ph})
                  AND e.is_deleted = FALSE
                ORDER BY ps.employee_id, ps.weighted_total DESC, ps.created_at DESC
            ),
            agg AS (
                SELECT
                    store_id,
                    AVG(weighted_total)::numeric(10,2) AS avg_score,
                    COUNT(*)::int AS employee_count
                FROM best
                GROUP BY store_id
            )
            SELECT
                s.id AS store_id,
                s.store_name,
                agg.avg_score,
                agg.employee_count
            FROM agg
            JOIN stores s ON s.id = agg.store_id AND s.tenant_id = :tid AND s.is_deleted = FALSE
            ORDER BY agg.avg_score DESC NULLS LAST, s.id
            """
        ),
        params,
    )
    raw = [dict(x) for x in rows.mappings().fetchall()]
    stores_out: list[dict[str, Any]] = []
    rnk = 0
    prev_avg: float | None = None
    for i, row in enumerate(raw, start=1):
        avg_s = row.get("avg_score")
        avg_f = float(avg_s) if avg_s is not None else 0.0
        if prev_avg is None or abs(avg_f - prev_avg) > 1e-9:
            rnk = i
            prev_avg = avg_f
        stores_out.append(
            {
                "store_id": str(row["store_id"]),
                "store_name": row["store_name"],
                "avg_score": avg_f,
                "employee_count": int(row["employee_count"] or 0),
                "rank": rnk,
            }
        )
    return {"stores": stores_out}


async def _attendance_month_stats(
    db: AsyncSession,
    tenant_id: UUID,
    employee_id: UUID,
    start: date,
    end: date,
) -> tuple[int, int, int, int]:
    await _set_tenant(db, tenant_id)
    row = await db.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE absence_type IS NULL) AS present_days,
                COUNT(*) FILTER (WHERE absence_type = 'absent') AS absent_days,
                COUNT(*) FILTER (
                    WHERE absence_type IN ('sick', 'personal')
                ) AS leave_days
            FROM attendance_records
            WHERE tenant_id = :tid
              AND employee_id = :eid
              AND work_date >= :d0
              AND work_date <= :d1
              AND is_deleted = FALSE
            """
        ),
        {"tid": tenant_id, "eid": employee_id, "d0": start, "d1": end},
    )
    m = row.mappings().first()
    if not m:
        return 0, 0, 0, 0
    present = int(m["present_days"] or 0)
    absent = int(m["absent_days"] or 0)
    leave = int(m["leave_days"] or 0)
    late_like = 0
    try:
        lr = await db.execute(
            text(
                """
                SELECT COUNT(*) AS c
                FROM daily_attendance
                WHERE tenant_id = :tid
                  AND employee_id = :eid
                  AND date >= :d0
                  AND date <= :d1
                  AND status IN ('late', 'early_leave')
                  AND is_deleted = FALSE
                """
            ),
            {"tid": tenant_id, "eid": str(employee_id), "d0": start, "d1": end},
        )
        late_like = int(lr.scalar() or 0)
    except (ProgrammingError, DBAPIError) as exc:
        log.warning(
            "performance.auto_score.daily_attendance_unavailable",
            tenant_id=str(tenant_id),
            employee_id=str(employee_id),
            error=str(exc),
        )
    return present, absent, leave, late_like


def _score_from_attendance(present: int, absent: int, leave: int, late_like: int) -> float:
    denom = present + absent + leave
    if denom <= 0:
        return 70.0
    rate = present / denom
    raw = rate * 100.0 - absent * 12.0 - leave * 3.0 - late_like * 2.0
    return round(min(100.0, max(0.0, raw)), 2)


def _score_from_commission_fen(commission_fen: int) -> float:
    if commission_fen <= 0:
        return 65.0
    ref = math.log1p(commission_fen / 100_000.0)
    s = 60.0 + min(40.0, ref * 18.0)
    return round(min(100.0, max(0.0, s)), 2)


async def _fetch_commission_fen(
    db: AsyncSession,
    tenant_id: UUID,
    employee_id: UUID,
    month: str,
) -> int | None:
    await _set_tenant(db, tenant_id)
    try:
        row = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(pi.commission_fen), 0) AS cf
                FROM payroll_items pi
                WHERE pi.tenant_id = :tid
                  AND pi.employee_id = :eid
                  AND pi.month = :mon
                """
            ),
            {"tid": tenant_id, "eid": str(employee_id), "mon": month},
        )
        one = row.mappings().first()
        if not one:
            return None
        return int(one["cf"] or 0)
    except (ProgrammingError, DBAPIError) as exc:
        log.warning(
            "performance.auto_score.payroll_items_unavailable",
            tenant_id=str(tenant_id),
            employee_id=str(employee_id),
            error=str(exc),
        )
        return None


async def auto_score_from_data(
    db: AsyncSession,
    tenant_id: UUID,
    employee_id: UUID,
    month: str,
) -> dict[str, Any]:
    """基于业务数据自动生成打分建议（AI 辅助）。"""
    start, end = _month_bounds(month)
    present, absent, leave, late_like = await _attendance_month_stats(db, tenant_id, employee_id, start, end)
    att_score = _score_from_attendance(present, absent, leave, late_like)
    commission = await _fetch_commission_fen(db, tenant_id, employee_id, month)
    if commission is None:
        sales_score = 72.0
        sales_src = "payroll_items 不可用，默认建议"
    else:
        sales_score = _score_from_commission_fen(commission)
        sales_src = "payroll_items.commission_fen（分）月度汇总"
    neutral = 75.0
    suggested = {
        "service": neutral,
        "sales": sales_score,
        "attendance": att_score,
        "skill": neutral,
        "teamwork": neutral,
        "innovation": neutral,
    }
    data_sources: dict[str, Any] = {
        "attendance": {
            "tables": ["attendance_records", "daily_attendance"],
            "present_days": present,
            "absent_days": absent,
            "leave_sick_personal_days": leave,
            "late_or_early_leave_days": late_like,
        },
        "sales": {
            "source": sales_src,
            "commission_fen_total": commission,
        },
    }
    log.info(
        "performance_auto_score_suggested",
        tenant_id=str(tenant_id),
        employee_id=str(employee_id),
        month=month,
    )
    return {"suggested_scores": suggested, "data_sources": data_sources}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 评审周期管理 (v254 review_cycles + review_scores)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VALID_CYCLE_STATUSES = ("draft", "scoring", "calibrating", "completed", "archived")
CYCLE_STATUS_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["scoring"],
    "scoring": ["calibrating"],
    "calibrating": ["completed"],
    "completed": ["archived"],
    "archived": [],
}


async def create_review_cycle(
    db: AsyncSession,
    tenant_id: UUID,
    data: dict[str, Any],
) -> dict[str, Any]:
    """创建评审周期。"""
    await _set_tenant(db, tenant_id)
    cycle_id = uuid4()
    dims_json = json.dumps(data.get("dimensions", []), ensure_ascii=False)
    await db.execute(
        text("""
            INSERT INTO review_cycles
                (id, tenant_id, cycle_name, cycle_type, start_date, end_date,
                 scoring_deadline, status, scope_type, scope_id, dimensions, created_by)
            VALUES
                (:id, :tid, :name, :ctype, :start, :end,
                 :deadline, 'draft', :scope_type, :scope_id, CAST(:dims AS jsonb), :created_by)
        """),
        {
            "id": cycle_id,
            "tid": tenant_id,
            "name": data["cycle_name"],
            "ctype": data["cycle_type"],
            "start": data["start_date"],
            "end": data["end_date"],
            "deadline": data.get("scoring_deadline"),
            "scope_type": data.get("scope_type", "brand"),
            "scope_id": data.get("scope_id"),
            "dims": dims_json,
            "created_by": data.get("created_by"),
        },
    )
    log.info("review_cycle_created", tenant_id=str(tenant_id), cycle_id=str(cycle_id))
    return {
        "id": str(cycle_id),
        "cycle_name": data["cycle_name"],
        "cycle_type": data["cycle_type"],
        "status": "draft",
    }


async def list_review_cycles(
    db: AsyncSession,
    tenant_id: UUID,
    status: str | None = None,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """列出评审周期。"""
    await _set_tenant(db, tenant_id)
    conds = ["tenant_id = :tid", "is_deleted = FALSE"]
    params: dict[str, Any] = {"tid": tenant_id}
    if status:
        conds.append("status = :status")
        params["status"] = status
    where = " AND ".join(conds)
    count_row = await db.execute(
        text(f"SELECT COUNT(*) FROM review_cycles WHERE {where}"),
        params,
    )
    total = int(count_row.scalar() or 0)
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset
    rows = await db.execute(
        text(f"""
            SELECT id, cycle_name, cycle_type, start_date, end_date,
                   scoring_deadline, status, scope_type, scope_id,
                   dimensions, created_by, created_at
            FROM review_cycles
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items: list[dict[str, Any]] = []
    for r in rows.mappings().fetchall():
        row = dict(r)
        row["id"] = str(row["id"])
        if row.get("scope_id"):
            row["scope_id"] = str(row["scope_id"])
        if row.get("created_by"):
            row["created_by"] = str(row["created_by"])
        dims = row.get("dimensions")
        if isinstance(dims, str):
            row["dimensions"] = json.loads(dims)
        for dt_field in ("start_date", "end_date", "scoring_deadline", "created_at"):
            val = row.get(dt_field)
            if val is not None and hasattr(val, "isoformat"):
                row[dt_field] = val.isoformat()
        items.append(row)
    return {"items": items, "total": total}


async def update_cycle_status(
    db: AsyncSession,
    tenant_id: UUID,
    cycle_id: UUID,
    new_status: str,
) -> dict[str, Any]:
    """更新评审周期状态（状态机校验）。"""
    if new_status not in VALID_CYCLE_STATUSES:
        raise ValueError(f"无效状态: {new_status}")
    await _set_tenant(db, tenant_id)
    row = await db.execute(
        text("""
            SELECT status FROM review_cycles
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {"cid": cycle_id, "tid": tenant_id},
    )
    current = row.scalar()
    if current is None:
        raise ValueError("评审周期不存在")
    allowed = CYCLE_STATUS_TRANSITIONS.get(current, [])
    if new_status not in allowed:
        raise ValueError(f"不能从 {current} 转换到 {new_status}，允许: {allowed}")
    await db.execute(
        text("""
            UPDATE review_cycles
            SET status = :status, updated_at = NOW()
            WHERE id = :cid AND tenant_id = :tid
        """),
        {"status": new_status, "cid": cycle_id, "tid": tenant_id},
    )
    log.info(
        "review_cycle_status_updated",
        tenant_id=str(tenant_id),
        cycle_id=str(cycle_id),
        old_status=current,
        new_status=new_status,
    )
    return {"cycle_id": str(cycle_id), "old_status": current, "new_status": new_status}


async def get_cycle_detail(
    db: AsyncSession,
    tenant_id: UUID,
    cycle_id: UUID,
) -> dict[str, Any]:
    """获取评审周期详情。"""
    await _set_tenant(db, tenant_id)
    row = await db.execute(
        text("""
            SELECT id, cycle_name, cycle_type, start_date, end_date,
                   scoring_deadline, status, scope_type, scope_id,
                   dimensions, created_by, created_at, updated_at
            FROM review_cycles
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {"cid": cycle_id, "tid": tenant_id},
    )
    r = row.mappings().first()
    if r is None:
        raise ValueError("评审周期不存在")
    d = dict(r)
    d["id"] = str(d["id"])
    if d.get("scope_id"):
        d["scope_id"] = str(d["scope_id"])
    if d.get("created_by"):
        d["created_by"] = str(d["created_by"])
    dims = d.get("dimensions")
    if isinstance(dims, str):
        d["dimensions"] = json.loads(dims)
    for dt_field in ("start_date", "end_date", "scoring_deadline", "created_at", "updated_at"):
        val = d.get(dt_field)
        if val is not None and hasattr(val, "isoformat"):
            d[dt_field] = val.isoformat()
    # 附加打分统计
    stats_row = await db.execute(
        text("""
            SELECT
                COUNT(DISTINCT employee_id) AS scored_employees,
                COUNT(*) AS total_scores
            FROM review_scores
            WHERE cycle_id = :cid AND tenant_id = :tid AND is_deleted = FALSE
                  AND status IN ('submitted', 'calibrated')
        """),
        {"cid": cycle_id, "tid": tenant_id},
    )
    stats = stats_row.mappings().first()
    d["scored_employees"] = int(stats["scored_employees"]) if stats else 0
    d["total_scores"] = int(stats["total_scores"]) if stats else 0
    return d


async def submit_review_score(
    db: AsyncSession,
    tenant_id: UUID,
    cycle_id: UUID,
    employee_id: UUID,
    reviewer_id: UUID,
    dimension_scores: dict[str, Any],
    comment: str | None = None,
    reviewer_name: str | None = None,
    reviewer_role: str | None = None,
    employee_name: str | None = None,
    store_id: UUID | None = None,
) -> dict[str, Any]:
    """提交评审打分。"""
    await _set_tenant(db, tenant_id)
    # 获取周期维度配置
    cycle_row = await db.execute(
        text("""
            SELECT status, dimensions FROM review_cycles
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {"cid": cycle_id, "tid": tenant_id},
    )
    cycle = cycle_row.mappings().first()
    if cycle is None:
        raise ValueError("评审周期不存在")
    if cycle["status"] != "scoring":
        raise ValueError(f"当前周期状态为 {cycle['status']}，仅 scoring 状态可打分")

    dims_config = cycle["dimensions"]
    if isinstance(dims_config, str):
        dims_config = json.loads(dims_config)

    # 计算总分和加权分
    total_score = 0.0
    weighted_score = 0.0
    total_weight = 0.0

    if dims_config:
        for dim_cfg in dims_config:
            dim_name = dim_cfg["name"]
            max_s = float(dim_cfg.get("max_score", 100))
            weight = float(dim_cfg.get("weight", 0))
            s = float(dimension_scores.get(dim_name, 0))
            if s < 0 or s > max_s:
                raise ValueError(f"维度 {dim_name} 分值须在 0~{max_s} 之间")
            total_score += s
            weighted_score += s * (weight / 100.0)
            total_weight += weight
        if total_weight > 0:
            weighted_score = round(
                weighted_score * (100.0 / total_weight) if total_weight != 100 else weighted_score, 2
            )
        total_score = round(total_score / len(dims_config), 2) if dims_config else 0
    else:
        # 无维度配置时取平均
        vals = [float(v) for v in dimension_scores.values()]
        total_score = round(sum(vals) / len(vals), 2) if vals else 0
        weighted_score = total_score

    score_id = uuid4()
    dim_json = json.dumps(dimension_scores, ensure_ascii=False)
    await db.execute(
        text("""
            INSERT INTO review_scores
                (id, tenant_id, cycle_id, employee_id, employee_name, store_id,
                 reviewer_id, reviewer_name, reviewer_role,
                 dimension_scores, total_score, weighted_score,
                 comment, status, submitted_at)
            VALUES
                (:id, :tid, :cid, :eid, :ename, :sid,
                 :rid, :rname, :rrole,
                 CAST(:dims AS jsonb), :total, :weighted,
                 :comment, 'submitted', NOW())
            ON CONFLICT (tenant_id, cycle_id, employee_id, reviewer_id)
                WHERE is_deleted = FALSE
            DO UPDATE SET
                dimension_scores = EXCLUDED.dimension_scores,
                total_score = EXCLUDED.total_score,
                weighted_score = EXCLUDED.weighted_score,
                comment = EXCLUDED.comment,
                status = 'submitted',
                submitted_at = NOW(),
                updated_at = NOW()
        """),
        {
            "id": score_id,
            "tid": tenant_id,
            "cid": cycle_id,
            "eid": employee_id,
            "ename": employee_name,
            "sid": store_id,
            "rid": reviewer_id,
            "rname": reviewer_name,
            "rrole": reviewer_role,
            "dims": dim_json,
            "total": total_score,
            "weighted": weighted_score,
            "comment": comment,
        },
    )
    log.info(
        "review_score_submitted",
        tenant_id=str(tenant_id),
        cycle_id=str(cycle_id),
        employee_id=str(employee_id),
        reviewer_id=str(reviewer_id),
        weighted_score=weighted_score,
    )
    return {
        "id": str(score_id),
        "employee_id": str(employee_id),
        "reviewer_id": str(reviewer_id),
        "total_score": total_score,
        "weighted_score": weighted_score,
        "status": "submitted",
    }


async def get_employee_scores(
    db: AsyncSession,
    tenant_id: UUID,
    cycle_id: UUID,
    employee_id: UUID | None = None,
    page: int = 1,
    size: int = 50,
) -> dict[str, Any]:
    """获取评审周期内的打分记录。支持按 employee_id 过滤。"""
    await _set_tenant(db, tenant_id)
    conds = ["tenant_id = :tid", "cycle_id = :cid", "is_deleted = FALSE"]
    params: dict[str, Any] = {"tid": tenant_id, "cid": cycle_id}
    if employee_id is not None:
        conds.append("employee_id = :eid")
        params["eid"] = employee_id
    where = " AND ".join(conds)
    count_row = await db.execute(
        text(f"SELECT COUNT(*) FROM review_scores WHERE {where}"),
        params,
    )
    total = int(count_row.scalar() or 0)
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset
    rows = await db.execute(
        text(f"""
            SELECT id, employee_id, employee_name, store_id,
                   reviewer_id, reviewer_name, reviewer_role,
                   dimension_scores, total_score, weighted_score,
                   comment, status, submitted_at,
                   calibrated_score, calibrated_by, calibrated_at
            FROM review_scores
            WHERE {where}
            ORDER BY submitted_at DESC NULLS LAST
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items: list[dict[str, Any]] = []
    for r in rows.mappings().fetchall():
        row = dict(r)
        for uid_field in ("id", "employee_id", "store_id", "reviewer_id", "calibrated_by"):
            if row.get(uid_field) is not None:
                row[uid_field] = str(row[uid_field])
        ds = row.get("dimension_scores")
        if isinstance(ds, str):
            row["dimension_scores"] = json.loads(ds)
        for num_field in ("total_score", "weighted_score", "calibrated_score"):
            if row.get(num_field) is not None:
                row[num_field] = float(row[num_field])
        for dt_field in ("submitted_at", "calibrated_at"):
            val = row.get(dt_field)
            if val is not None and hasattr(val, "isoformat"):
                row[dt_field] = val.isoformat()
        items.append(row)
    return {"items": items, "total": total}


async def aggregate_cycle_scores(
    db: AsyncSession,
    tenant_id: UUID,
    cycle_id: UUID,
    store_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """汇总评审周期所有员工的加权平均分并排名。"""
    await _set_tenant(db, tenant_id)
    conds = [
        "rs.tenant_id = :tid",
        "rs.cycle_id = :cid",
        "rs.is_deleted = FALSE",
        "rs.status IN ('submitted', 'calibrated')",
    ]
    params: dict[str, Any] = {"tid": tenant_id, "cid": cycle_id}
    if store_id is not None:
        conds.append("rs.store_id = :sid")
        params["sid"] = store_id
    where = " AND ".join(conds)
    rows = await db.execute(
        text(f"""
            SELECT
                rs.employee_id,
                MAX(rs.employee_name) AS employee_name,
                rs.store_id,
                AVG(COALESCE(rs.calibrated_score, rs.weighted_score))::numeric(5,2) AS avg_score,
                COUNT(*) AS reviewer_count
            FROM review_scores rs
            WHERE {where}
            GROUP BY rs.employee_id, rs.store_id
            ORDER BY avg_score DESC NULLS LAST, rs.employee_id
        """),
        params,
    )
    items: list[dict[str, Any]] = []
    rank = 0
    prev: float | None = None
    for i, r in enumerate(rows.mappings().fetchall(), start=1):
        avg_s = float(r["avg_score"]) if r["avg_score"] is not None else 0.0
        if prev is None or abs(avg_s - prev) > 1e-9:
            rank = i
            prev = avg_s
        items.append(
            {
                "rank": rank,
                "employee_id": str(r["employee_id"]),
                "employee_name": r["employee_name"],
                "store_id": str(r["store_id"]) if r["store_id"] else None,
                "avg_score": avg_s,
                "reviewer_count": int(r["reviewer_count"]),
            }
        )
    return items


async def calibrate_score(
    db: AsyncSession,
    tenant_id: UUID,
    cycle_id: UUID,
    employee_id: UUID,
    calibrated_score: float,
    calibrator_id: UUID,
) -> dict[str, Any]:
    """校准某员工在该周期的所有打分记录。"""
    if calibrated_score < 0 or calibrated_score > 100:
        raise ValueError("校准分数须在 0~100 之间")
    await _set_tenant(db, tenant_id)
    # 校验周期状态
    cycle_row = await db.execute(
        text("""
            SELECT status FROM review_cycles
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {"cid": cycle_id, "tid": tenant_id},
    )
    cycle_status = cycle_row.scalar()
    if cycle_status not in ("calibrating", "scoring"):
        raise ValueError(f"当前周期状态为 {cycle_status}，仅 calibrating/scoring 状态可校准")

    result = await db.execute(
        text("""
            UPDATE review_scores
            SET calibrated_score = :cscore,
                calibrated_by = :cby,
                calibrated_at = NOW(),
                status = 'calibrated',
                updated_at = NOW()
            WHERE tenant_id = :tid AND cycle_id = :cid AND employee_id = :eid
                  AND is_deleted = FALSE
            RETURNING id
        """),
        {
            "cscore": calibrated_score,
            "cby": calibrator_id,
            "tid": tenant_id,
            "cid": cycle_id,
            "eid": employee_id,
        },
    )
    updated_ids = [str(r[0]) for r in result.fetchall()]
    log.info(
        "review_score_calibrated",
        tenant_id=str(tenant_id),
        cycle_id=str(cycle_id),
        employee_id=str(employee_id),
        calibrated_score=calibrated_score,
        updated_count=len(updated_ids),
    )
    return {
        "employee_id": str(employee_id),
        "calibrated_score": calibrated_score,
        "updated_count": len(updated_ids),
    }


async def get_cycle_ranking(
    db: AsyncSession,
    tenant_id: UUID,
    cycle_id: UUID,
    store_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """获取评审周期排名（同 aggregate_cycle_scores 的别名）。"""
    return await aggregate_cycle_scores(db, tenant_id, cycle_id, store_id)


async def get_review_stats(
    db: AsyncSession,
    tenant_id: UUID,
    cycle_id: UUID,
) -> dict[str, Any]:
    """获取评审统计概览：已评/未评人数、平均分、分布。"""
    await _set_tenant(db, tenant_id)
    # 已评
    scored_row = await db.execute(
        text("""
            SELECT
                COUNT(DISTINCT employee_id) AS scored_count,
                AVG(COALESCE(calibrated_score, weighted_score))::numeric(5,2) AS avg_score,
                MIN(COALESCE(calibrated_score, weighted_score))::numeric(5,2) AS min_score,
                MAX(COALESCE(calibrated_score, weighted_score))::numeric(5,2) AS max_score,
                COUNT(*) AS total_score_records
            FROM review_scores
            WHERE tenant_id = :tid AND cycle_id = :cid AND is_deleted = FALSE
                  AND status IN ('submitted', 'calibrated')
        """),
        {"tid": tenant_id, "cid": cycle_id},
    )
    s = scored_row.mappings().first()
    scored_count = int(s["scored_count"]) if s else 0
    avg_score = float(s["avg_score"]) if s and s["avg_score"] is not None else 0.0
    min_score = float(s["min_score"]) if s and s["min_score"] is not None else 0.0
    max_score = float(s["max_score"]) if s and s["max_score"] is not None else 0.0
    total_records = int(s["total_score_records"]) if s else 0

    # 分数分布（按10分段）
    dist_rows = await db.execute(
        text("""
            SELECT
                CASE
                    WHEN score >= 90 THEN '90-100'
                    WHEN score >= 80 THEN '80-89'
                    WHEN score >= 70 THEN '70-79'
                    WHEN score >= 60 THEN '60-69'
                    ELSE '0-59'
                END AS bucket,
                COUNT(*) AS cnt
            FROM (
                SELECT COALESCE(calibrated_score, weighted_score) AS score
                FROM review_scores
                WHERE tenant_id = :tid AND cycle_id = :cid AND is_deleted = FALSE
                      AND status IN ('submitted', 'calibrated')
            ) sub
            GROUP BY bucket
            ORDER BY bucket DESC
        """),
        {"tid": tenant_id, "cid": cycle_id},
    )
    distribution: dict[str, int] = {}
    for dr in dist_rows.mappings().fetchall():
        distribution[dr["bucket"]] = int(dr["cnt"])

    # draft 状态打分数
    draft_row = await db.execute(
        text("""
            SELECT COUNT(*) AS c FROM review_scores
            WHERE tenant_id = :tid AND cycle_id = :cid AND is_deleted = FALSE
                  AND status = 'draft'
        """),
        {"tid": tenant_id, "cid": cycle_id},
    )
    draft_count = int(draft_row.scalar() or 0)

    return {
        "cycle_id": str(cycle_id),
        "scored_employee_count": scored_count,
        "total_score_records": total_records,
        "draft_count": draft_count,
        "avg_score": avg_score,
        "min_score": min_score,
        "max_score": max_score,
        "distribution": distribution,
    }
