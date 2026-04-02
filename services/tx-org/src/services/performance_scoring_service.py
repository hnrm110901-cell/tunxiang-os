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
            SELECT
                ps.id, ps.employee_id, ps.scorer_id, ps.month,
                ps.dimension_scores, ps.weighted_total, ps.comment, ps.created_at,
                e.emp_name, e.role, e.store_id
            FROM performance_scores ps
            JOIN employees e ON e.id = ps.employee_id AND e.tenant_id = ps.tenant_id
            WHERE {where_sql}
            ORDER BY ps.created_at DESC
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
    present, absent, leave, late_like = await _attendance_month_stats(
        db, tenant_id, employee_id, start, end
    )
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
