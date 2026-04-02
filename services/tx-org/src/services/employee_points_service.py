"""tx-org 员工积分与赛马排名服务。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Employee, Store

logger = structlog.get_logger(__name__)

EMPLOYEES_TABLE = Employee.__tablename__
STORES_TABLE = Store.__tablename__
POINT_LOGS_TABLE = "employee_point_logs"

POINT_RULES: dict[str, dict[str, str | int]] = {
    "attendance_perfect": {"name": "全勤", "points": 100, "period": "monthly"},
    "attendance_on_time": {"name": "准时打卡", "points": 2, "period": "daily"},
    "sales_target_hit": {"name": "达成销售目标", "points": 50, "period": "monthly"},
    "sales_upsell": {"name": "成功推荐菜品", "points": 5, "period": "per_action"},
    "customer_praise": {"name": "获得顾客好评", "points": 10, "period": "per_action"},
    "customer_complaint": {"name": "收到顾客投诉", "points": -20, "period": "per_action"},
    "training_complete": {"name": "完成培训课程", "points": 30, "period": "per_action"},
    "skill_cert": {"name": "获得技能认证", "points": 100, "period": "per_action"},
    "innovation_proposal": {"name": "提出改善建议", "points": 15, "period": "per_action"},
    "mentor_new_hire": {"name": "指导新员工", "points": 50, "period": "monthly"},
    "hygiene_pass": {"name": "卫生检查通过", "points": 10, "period": "per_action"},
    "hygiene_fail": {"name": "卫生检查不通过", "points": -30, "period": "per_action"},
    "overtime_voluntary": {"name": "主动加班支援", "points": 20, "period": "per_action"},
}

LEVEL_THRESHOLDS: list[tuple[int, str]] = [
    (0, "见习"),
    (500, "铜星"),
    (1500, "银星"),
    (3000, "金星"),
    (5000, "钻石"),
    (8000, "王者"),
]

PeriodLiteral = Literal["monthly", "quarterly", "yearly", "all"]


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"{field} 不是合法 UUID") from e


def _period_bounds(
    period: PeriodLiteral,
    ref: datetime | None = None,
) -> tuple[datetime | None, datetime | None]:
    r = (ref or datetime.now(timezone.utc)).astimezone(timezone.utc)
    y, m = r.year, r.month
    if period == "all":
        return None, None
    if period == "monthly":
        start = datetime(y, m, 1, tzinfo=timezone.utc)
        if m == 12:
            end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(y, m + 1, 1, tzinfo=timezone.utc)
        return start, end
    if period == "quarterly":
        q_start_m = (m - 1) // 3 * 3 + 1
        start = datetime(y, q_start_m, 1, tzinfo=timezone.utc)
        if q_start_m == 10:
            end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(y, q_start_m + 3, 1, tzinfo=timezone.utc)
        return start, end
    if period == "yearly":
        start = datetime(y, 1, 1, tzinfo=timezone.utc)
        end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
        return start, end
    raise ValueError(f"不支持的 period: {period}")


def compute_level(total_points: int) -> str:
    """根据总积分计算等级。"""
    current = LEVEL_THRESHOLDS[0][1]
    for threshold, label in LEVEL_THRESHOLDS:
        if total_points >= threshold:
            current = label
    return current


def _next_level_info(total_points: int) -> tuple[str, int]:
    idx = 0
    for i, (t, _) in enumerate(LEVEL_THRESHOLDS):
        if total_points >= t:
            idx = i
    if idx + 1 >= len(LEVEL_THRESHOLDS):
        return "", 0
    next_t, next_label = LEVEL_THRESHOLDS[idx + 1]
    return next_label, next_t - total_points


def _rule_name(rule_code: str) -> str:
    meta = POINT_RULES[rule_code]
    return str(meta["name"])


async def _sum_employee_points(
    db: AsyncSession,
    tenant_uuid: uuid.UUID,
    employee_uuid: uuid.UUID,
) -> int:
    r = await db.execute(
        text(
            f"""
            SELECT COALESCE(SUM(points), 0) AS s
            FROM {POINT_LOGS_TABLE}
            WHERE tenant_id = :tid AND employee_id = :eid
            """
        ),
        {"tid": tenant_uuid, "eid": employee_uuid},
    )
    row = r.mappings().one()
    return int(row["s"] or 0)


async def _fetch_recent_actions(
    db: AsyncSession,
    tenant_uuid: uuid.UUID,
    employee_ids: list[uuid.UUID],
    limit_per_employee: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    if not employee_ids:
        return {}
    r = await db.execute(
        text(
            f"""
            SELECT employee_id, rule_code, points, note, created_at,
                   ROW_NUMBER() OVER (PARTITION BY employee_id ORDER BY created_at DESC) AS rn
            FROM {POINT_LOGS_TABLE}
            WHERE tenant_id = :tid AND employee_id = ANY(:eids)
            """
        ),
        {"tid": tenant_uuid, "eids": employee_ids},
    )
    out: dict[str, list[dict[str, Any]]] = {str(eid): [] for eid in employee_ids}
    for row in r.mappings().all():
        if int(row["rn"]) > limit_per_employee:
            continue
        rc = str(row["rule_code"])
        name = _rule_name(rc) if rc in POINT_RULES else rc
        ca = row["created_at"]
        if hasattr(ca, "isoformat"):
            ds = ca.isoformat()
        else:
            ds = str(ca)
        eid_str = str(row["employee_id"])
        out.setdefault(eid_str, []).append(
            {
                "rule_code": rc,
                "rule_name": name,
                "points": int(row["points"]),
                "note": row["note"] or "",
                "date": ds,
            },
        )
    return out


async def award_points(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str,
    rule_code: str,
    extra_points: int = 0,
    note: str = "",
) -> dict[str, Any]:
    """发放积分。"""
    if rule_code not in POINT_RULES:
        raise ValueError(f"未知规则编码: {rule_code}")
    base = int(POINT_RULES[rule_code]["points"])
    awarded = base + int(extra_points)
    if awarded <= 0:
        raise ValueError("发放积分必须为正数，请使用 deduct_points 处理扣分规则")
    tid = _parse_uuid(tenant_id, "tenant_id")
    eid = _parse_uuid(employee_id, "employee_id")
    await _set_tenant(db, tenant_id)
    log_id = uuid.uuid4()
    await db.execute(
        text(
            f"""
            INSERT INTO {POINT_LOGS_TABLE}
                (id, tenant_id, employee_id, rule_code, points, note, created_at)
            VALUES
                (:id, :tid, :eid, :rcode, :pts, :note, NOW())
            """
        ),
        {
            "id": log_id,
            "tid": tid,
            "eid": eid,
            "rcode": rule_code,
            "pts": awarded,
            "note": note or None,
        },
    )
    await db.flush()
    new_total = await _sum_employee_points(db, tid, eid)
    lvl = compute_level(new_total)
    logger.info(
        "employee_points.award",
        tenant_id=tenant_id,
        employee_id=employee_id,
        rule_code=rule_code,
        points_awarded=awarded,
        new_total=new_total,
    )
    return {
        "employee_id": employee_id,
        "points_awarded": awarded,
        "new_total": new_total,
        "new_level": lvl,
    }


async def deduct_points(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str,
    rule_code: str,
    note: str = "",
) -> dict[str, Any]:
    """扣减积分（用于负分规则）。"""
    if rule_code not in POINT_RULES:
        raise ValueError(f"未知规则编码: {rule_code}")
    base = int(POINT_RULES[rule_code]["points"])
    if base >= 0:
        raise ValueError("该规则不是负分规则，请使用 award_points")
    tid = _parse_uuid(tenant_id, "tenant_id")
    eid = _parse_uuid(employee_id, "employee_id")
    await _set_tenant(db, tenant_id)
    log_id = uuid.uuid4()
    await db.execute(
        text(
            f"""
            INSERT INTO {POINT_LOGS_TABLE}
                (id, tenant_id, employee_id, rule_code, points, note, created_at)
            VALUES
                (:id, :tid, :eid, :rcode, :pts, :note, NOW())
            """
        ),
        {
            "id": log_id,
            "tid": tid,
            "eid": eid,
            "rcode": rule_code,
            "pts": base,
            "note": note or None,
        },
    )
    await db.flush()
    new_total = await _sum_employee_points(db, tid, eid)
    lvl = compute_level(new_total)
    logger.info(
        "employee_points.deduct",
        tenant_id=tenant_id,
        employee_id=employee_id,
        rule_code=rule_code,
        points_deducted=abs(base),
        new_total=new_total,
    )
    return {
        "employee_id": employee_id,
        "points_deducted": abs(base),
        "new_total": new_total,
        "new_level": lvl,
    }


async def get_leaderboard(
    db: AsyncSession,
    tenant_id: str,
    store_id: str | None = None,
    period: PeriodLiteral = "monthly",
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """获取积分排行榜。"""
    if page < 1:
        raise ValueError("page 须 >= 1")
    if size < 1 or size > 200:
        raise ValueError("size 须在 1–200 之间")
    tid = _parse_uuid(tenant_id, "tenant_id")
    sid: uuid.UUID | None = None
    if store_id is not None:
        sid = _parse_uuid(store_id, "store_id")
    p_start, p_end = _period_bounds(period)
    await _set_tenant(db, tenant_id)
    period_filter = "TRUE"
    params: dict[str, Any] = {"tid": tid, "sid": sid}
    if p_start is not None and p_end is not None:
        period_filter = "l.created_at >= :pstart AND l.created_at < :pend"
        params["pstart"] = p_start
        params["pend"] = p_end
    store_clause = "TRUE" if sid is None else "e.store_id = :sid"
    count_sql = text(
        f"""
        SELECT COUNT(*) AS c
        FROM {EMPLOYEES_TABLE} e
        WHERE e.tenant_id = :tid AND e.is_deleted = FALSE AND ({store_clause})
        """
    )
    cr = await db.execute(count_sql, params)
    total = int(cr.scalar_one() or 0)
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset
    lr = await db.execute(
        text(
            f"""
            WITH agg AS (
                SELECT
                    e.id AS employee_id,
                    e.emp_name,
                    COALESCE(SUM(l.points), 0) AS total_points,
                    COALESCE(SUM(l.points) FILTER (WHERE {period_filter}), 0) AS monthly_points
                FROM {EMPLOYEES_TABLE} e
                LEFT JOIN {POINT_LOGS_TABLE} l
                    ON l.employee_id = e.id AND l.tenant_id = e.tenant_id
                WHERE e.tenant_id = :tid AND e.is_deleted = FALSE AND ({store_clause})
                GROUP BY e.id, e.emp_name
            ),
            ranked AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (ORDER BY monthly_points DESC, total_points DESC) AS rank
                FROM agg
            )
            SELECT * FROM ranked
            ORDER BY rank
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )
    rows = lr.mappings().all()
    eids = [uuid.UUID(str(r["employee_id"])) for r in rows]
    recent_map = await _fetch_recent_actions(db, tid, eids, 5)
    items: list[dict[str, Any]] = []
    for r in rows:
        eid_str = str(r["employee_id"])
        tp = int(r["total_points"])
        items.append(
            {
                "employee_id": eid_str,
                "emp_name": r["emp_name"],
                "total_points": tp,
                "monthly_points": int(r["monthly_points"]),
                "rank": int(r["rank"]),
                "level": compute_level(tp),
                "recent_actions": recent_map.get(eid_str, []),
            },
        )
    logger.info(
        "employee_points.leaderboard",
        tenant_id=tenant_id,
        store_id=store_id,
        period=period,
        page=page,
        size=size,
        total=total,
    )
    return {"items": items, "total": total}


async def get_employee_points_detail(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str,
) -> dict[str, Any]:
    """获取员工积分明细。"""
    tid = _parse_uuid(tenant_id, "tenant_id")
    eid = _parse_uuid(employee_id, "employee_id")
    await _set_tenant(db, tenant_id)
    total = await _sum_employee_points(db, tid, eid)
    lvl = compute_level(total)
    next_name, to_next = _next_level_info(total)
    hr = await db.execute(
        text(
            f"""
            SELECT rule_code, points, note, created_at
            FROM {POINT_LOGS_TABLE}
            WHERE tenant_id = :tid AND employee_id = :eid
            ORDER BY created_at DESC
            """
        ),
        {"tid": tid, "eid": eid},
    )
    history: list[dict[str, Any]] = []
    for row in hr.mappings().all():
        rc = str(row["rule_code"])
        ca = row["created_at"]
        if hasattr(ca, "isoformat"):
            ds = ca.isoformat()
        else:
            ds = str(ca)
        history.append(
            {
                "rule_code": rc,
                "rule_name": _rule_name(rc) if rc in POINT_RULES else rc,
                "points": int(row["points"]),
                "note": row["note"] or "",
                "date": ds,
            },
        )
    return {
        "total_points": total,
        "level": lvl,
        "next_level": next_name,
        "points_to_next": to_next,
        "history": history,
    }


async def get_horse_race_ranking(
    db: AsyncSession,
    tenant_id: str,
    store_ids: list[str],
    period: PeriodLiteral = "monthly",
) -> list[dict[str, Any]]:
    """门店间赛马排名。"""
    if not store_ids:
        return []
    tid = _parse_uuid(tenant_id, "tenant_id")
    suuids = [_parse_uuid(s, "store_id") for s in store_ids]
    p_start, p_end = _period_bounds(period)
    await _set_tenant(db, tenant_id)
    period_filter = "TRUE"
    params: dict[str, Any] = {"tid": tid, "sids": suuids}
    if p_start is not None and p_end is not None:
        period_filter = "l.created_at >= :pstart AND l.created_at < :pend"
        params["pstart"] = p_start
        params["pend"] = p_end
    r = await db.execute(
        text(
            f"""
            WITH per_store AS (
                SELECT
                    s.id AS store_id,
                    s.store_name,
                    COUNT(DISTINCT e.id) FILTER (WHERE e.is_deleted = FALSE) AS employee_count,
                    COALESCE(SUM(l.points) FILTER (WHERE {period_filter}), 0) AS total_points
                FROM {STORES_TABLE} s
                LEFT JOIN {EMPLOYEES_TABLE} e
                    ON e.store_id = s.id AND e.tenant_id = s.tenant_id
                LEFT JOIN {POINT_LOGS_TABLE} l
                    ON l.employee_id = e.id AND l.tenant_id = e.tenant_id
                WHERE s.tenant_id = :tid AND s.id = ANY(:sids) AND s.is_deleted = FALSE
                GROUP BY s.id, s.store_name
            ),
            scored AS (
                SELECT
                    store_id,
                    store_name,
                    total_points,
                    employee_count,
                    CASE WHEN employee_count > 0
                        THEN ROUND(total_points::numeric / employee_count, 2)
                        ELSE 0
                    END AS avg_points_per_employee
                FROM per_store
            ),
            ranked AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        ORDER BY total_points DESC, avg_points_per_employee DESC
                    ) AS rank
                FROM scored
            )
            SELECT * FROM ranked ORDER BY rank
            """
        ),
        params,
    )
    out: list[dict[str, Any]] = []
    for row in r.mappings().all():
        out.append(
            {
                "store_id": str(row["store_id"]),
                "store_name": row["store_name"],
                "total_points": int(row["total_points"]),
                "avg_points_per_employee": float(row["avg_points_per_employee"]),
                "employee_count": int(row["employee_count"]),
                "rank": int(row["rank"]),
            },
        )
    logger.info(
        "employee_points.horse_race",
        tenant_id=tenant_id,
        store_count=len(store_ids),
        period=period,
    )
    return out
