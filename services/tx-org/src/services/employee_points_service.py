"""tx-org 员工积分与赛马排名服务。

扩展版：支持 v253 新表（point_transactions / point_rewards / horse_race_seasons / point_redemptions）
保留与旧表 employee_point_logs 的向后兼容。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Literal

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Employee, Store

logger = structlog.get_logger(__name__)

EMPLOYEES_TABLE = Employee.__tablename__
STORES_TABLE = Store.__tablename__
POINT_LOGS_TABLE = "employee_point_logs"

# ── v253 新表 ──────────────────────────────────────────────────────────────────
POINT_TX_TABLE = "point_transactions"
POINT_REWARDS_TABLE = "point_rewards"
HORSE_RACE_TABLE = "horse_race_seasons"
POINT_REDEMPTIONS_TABLE = "point_redemptions"

POINT_RULES: dict[str, dict[str, str | int]] = {
    "manual_adjust": {"name": "人工调整", "points": 0, "period": "per_action"},
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
              AND is_deleted = FALSE
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
              AND is_deleted = FALSE
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


async def apply_manual_points_delta(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str,
    delta: int,
    note: str = "",
) -> dict[str, Any]:
    """人工加减任意积分（正/负），rule_code 固定为 manual_adjust。"""
    if delta == 0:
        raise ValueError("调整积分不能为 0")
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
                (:id, :tid, :eid, 'manual_adjust', :pts, :note, NOW())
            """
        ),
        {
            "id": log_id,
            "tid": tid,
            "eid": eid,
            "pts": int(delta),
            "note": note or None,
        },
    )
    await db.flush()
    new_total = await _sum_employee_points(db, tid, eid)
    lvl = compute_level(new_total)
    logger.info(
        "employee_points.manual_adjust",
        tenant_id=tenant_id,
        employee_id=employee_id,
        delta=delta,
        new_total=new_total,
    )
    return {
        "employee_id": employee_id,
        "points_awarded": int(delta),
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
                    ON l.employee_id = e.id
                    AND l.tenant_id = e.tenant_id
                    AND l.is_deleted = FALSE
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
            SELECT id, rule_code, points, note, created_at
            FROM {POINT_LOGS_TABLE}
            WHERE tenant_id = :tid AND employee_id = :eid AND is_deleted = FALSE
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
                "id": str(row["id"]),
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
                    ON l.employee_id = e.id
                    AND l.tenant_id = e.tenant_id
                    AND l.is_deleted = FALSE
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


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  v253 扩展：基于 point_transactions 新表的 DB 持久化积分服务                     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


async def _get_pt_balance(
    db: AsyncSession,
    tenant_uuid: uuid.UUID,
    employee_uuid: uuid.UUID,
) -> int:
    """从 point_transactions 表计算员工积分余额。"""
    r = await db.execute(
        text(f"""
            SELECT COALESCE(SUM(points), 0) AS bal
            FROM {POINT_TX_TABLE}
            WHERE tenant_id = :tid AND employee_id = :eid AND is_deleted = FALSE
        """),
        {"tid": tenant_uuid, "eid": employee_uuid},
    )
    return int(r.scalar_one() or 0)


async def award_points_v2(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str,
    rule_code: str,
    reason: str = "",
    operator_id: str | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    """v253 发放积分（写入 point_transactions 表）。"""
    if rule_code not in POINT_RULES:
        raise ValueError(f"未知规则编码: {rule_code}")
    base = int(POINT_RULES[rule_code]["points"])
    if base <= 0:
        raise ValueError("该规则不是正分规则，请使用 deduct_points_v2")

    tid = _parse_uuid(tenant_id, "tenant_id")
    eid = _parse_uuid(employee_id, "employee_id")
    oid = _parse_uuid(operator_id, "operator_id") if operator_id else None
    await _set_tenant(db, tenant_id)

    balance = await _get_pt_balance(db, tid, eid)
    new_balance = balance + base

    tx_id = uuid.uuid4()
    await db.execute(
        text(f"""
            INSERT INTO {POINT_TX_TABLE}
                (id, tenant_id, employee_id, rule_code, points, balance_after, reason, source, operator_id, created_at)
            VALUES
                (:id, :tid, :eid, :rcode, :pts, :bal, :reason, :src, :oid, NOW())
        """),
        {
            "id": tx_id,
            "tid": tid,
            "eid": eid,
            "rcode": rule_code,
            "pts": base,
            "bal": new_balance,
            "reason": reason or None,
            "src": source,
            "oid": oid,
        },
    )
    await db.flush()

    lvl = compute_level(new_balance)
    logger.info(
        "employee_points_v2.award",
        tenant_id=tenant_id,
        employee_id=employee_id,
        rule_code=rule_code,
        points=base,
        balance=new_balance,
    )
    return {
        "transaction_id": str(tx_id),
        "employee_id": employee_id,
        "points_awarded": base,
        "balance": new_balance,
        "level": lvl,
    }


async def deduct_points_v2(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str,
    rule_code: str,
    reason: str = "",
    operator_id: str | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    """v253 扣减积分（写入 point_transactions 表）。"""
    if rule_code not in POINT_RULES:
        raise ValueError(f"未知规则编码: {rule_code}")
    base = int(POINT_RULES[rule_code]["points"])
    if base >= 0:
        raise ValueError("该规则不是负分规则，请使用 award_points_v2")

    tid = _parse_uuid(tenant_id, "tenant_id")
    eid = _parse_uuid(employee_id, "employee_id")
    oid = _parse_uuid(operator_id, "operator_id") if operator_id else None
    await _set_tenant(db, tenant_id)

    balance = await _get_pt_balance(db, tid, eid)
    new_balance = balance + base  # base is negative

    tx_id = uuid.uuid4()
    await db.execute(
        text(f"""
            INSERT INTO {POINT_TX_TABLE}
                (id, tenant_id, employee_id, rule_code, points, balance_after, reason, source, operator_id, created_at)
            VALUES
                (:id, :tid, :eid, :rcode, :pts, :bal, :reason, :src, :oid, NOW())
        """),
        {
            "id": tx_id,
            "tid": tid,
            "eid": eid,
            "rcode": rule_code,
            "pts": base,
            "bal": new_balance,
            "reason": reason or None,
            "src": source,
            "oid": oid,
        },
    )
    await db.flush()

    lvl = compute_level(new_balance)
    logger.info(
        "employee_points_v2.deduct",
        tenant_id=tenant_id,
        employee_id=employee_id,
        rule_code=rule_code,
        points=base,
        balance=new_balance,
    )
    return {
        "transaction_id": str(tx_id),
        "employee_id": employee_id,
        "points_deducted": abs(base),
        "balance": new_balance,
        "level": lvl,
    }


async def get_employee_balance_v2(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str,
) -> int:
    """查询员工积分余额（point_transactions 表）。"""
    tid = _parse_uuid(tenant_id, "tenant_id")
    eid = _parse_uuid(employee_id, "employee_id")
    await _set_tenant(db, tenant_id)
    return await _get_pt_balance(db, tid, eid)


async def get_points_history_v2(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """查询员工积分流水（分页）。"""
    if page < 1:
        raise ValueError("page >= 1")
    if size < 1 or size > 200:
        raise ValueError("size 须在 1–200")
    tid = _parse_uuid(tenant_id, "tenant_id")
    eid = _parse_uuid(employee_id, "employee_id")
    await _set_tenant(db, tenant_id)

    cr = await db.execute(
        text(f"""
            SELECT COUNT(*) FROM {POINT_TX_TABLE}
            WHERE tenant_id = :tid AND employee_id = :eid AND is_deleted = FALSE
        """),
        {"tid": tid, "eid": eid},
    )
    total = int(cr.scalar_one() or 0)

    offset = (page - 1) * size
    r = await db.execute(
        text(f"""
            SELECT id, rule_code, points, balance_after, reason, source, operator_id, created_at
            FROM {POINT_TX_TABLE}
            WHERE tenant_id = :tid AND employee_id = :eid AND is_deleted = FALSE
            ORDER BY created_at DESC
            LIMIT :lim OFFSET :off
        """),
        {"tid": tid, "eid": eid, "lim": size, "off": offset},
    )
    items: list[dict[str, Any]] = []
    for row in r.mappings().all():
        rc = str(row["rule_code"])
        ca = row["created_at"]
        items.append(
            {
                "id": str(row["id"]),
                "rule_code": rc,
                "rule_name": _rule_name(rc) if rc in POINT_RULES else rc,
                "points": int(row["points"]),
                "balance_after": int(row["balance_after"]),
                "reason": row["reason"] or "",
                "source": row["source"] or "manual",
                "date": ca.isoformat() if hasattr(ca, "isoformat") else str(ca),
            }
        )
    return {"items": items, "total": total}


async def get_leaderboard_v2(
    db: AsyncSession,
    tenant_id: str,
    scope_type: str = "store",
    scope_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """积分排行榜（从 point_transactions 表聚合）。"""
    if limit < 1 or limit > 100:
        raise ValueError("limit 须在 1–100")
    tid = _parse_uuid(tenant_id, "tenant_id")
    sid: uuid.UUID | None = None
    if scope_id:
        sid = _parse_uuid(scope_id, "scope_id")
    await _set_tenant(db, tenant_id)

    store_clause = "TRUE" if sid is None else "e.store_id = :sid"
    r = await db.execute(
        text(f"""
            WITH agg AS (
                SELECT
                    pt.employee_id,
                    e.emp_name,
                    e.store_id,
                    COALESCE(SUM(pt.points), 0) AS total_points,
                    COALESCE(SUM(pt.points) FILTER (WHERE pt.points > 0), 0) AS earned,
                    COALESCE(SUM(pt.points) FILTER (WHERE pt.points < 0), 0) AS consumed
                FROM {POINT_TX_TABLE} pt
                JOIN {EMPLOYEES_TABLE} e
                    ON e.id = pt.employee_id AND e.tenant_id = pt.tenant_id
                WHERE pt.tenant_id = :tid AND pt.is_deleted = FALSE
                  AND e.is_deleted = FALSE AND ({store_clause})
                GROUP BY pt.employee_id, e.emp_name, e.store_id
            )
            SELECT *, ROW_NUMBER() OVER (ORDER BY total_points DESC) AS rank
            FROM agg
            ORDER BY rank
            LIMIT :lim
        """),
        {"tid": tid, "sid": sid, "lim": limit},
    )
    items: list[dict[str, Any]] = []
    for row in r.mappings().all():
        tp = int(row["total_points"])
        items.append(
            {
                "employee_id": str(row["employee_id"]),
                "emp_name": row["emp_name"],
                "store_id": str(row["store_id"]) if row["store_id"] else None,
                "total_points": tp,
                "earned": int(row["earned"]),
                "consumed": int(row["consumed"]),
                "rank": int(row["rank"]),
                "level": compute_level(tp),
            }
        )
    return items


async def redeem_reward(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str,
    reward_id: str,
) -> dict[str, Any]:
    """员工兑换积分商品。"""
    tid = _parse_uuid(tenant_id, "tenant_id")
    eid = _parse_uuid(employee_id, "employee_id")
    rid = _parse_uuid(reward_id, "reward_id")
    await _set_tenant(db, tenant_id)

    # 查询商品（FOR UPDATE 锁定行，防止并发兑换竞态）
    rr = await db.execute(
        text(f"""
            SELECT id, reward_name, reward_type, points_cost, stock, is_active
            FROM {POINT_REWARDS_TABLE}
            WHERE tenant_id = :tid AND id = :rid AND is_deleted = FALSE
            FOR UPDATE
        """),
        {"tid": tid, "rid": rid},
    )
    reward = rr.mappings().first()
    if not reward:
        raise ValueError("兑换商品不存在")
    if not reward["is_active"]:
        raise ValueError("该商品已下架")
    cost = int(reward["points_cost"])
    stock = int(reward["stock"])

    # 检查库存
    if stock == 0:
        raise ValueError("商品库存不足")

    # 检查余额（锁定员工积分流水行，防止并发扣减）
    bal_r = await db.execute(
        text(f"""
            SELECT COALESCE(SUM(points), 0) AS bal
            FROM {POINT_TX_TABLE}
            WHERE tenant_id = :tid AND employee_id = :eid AND is_deleted = FALSE
            FOR UPDATE
        """),
        {"tid": tid, "eid": eid},
    )
    balance = int(bal_r.scalar_one() or 0)
    if balance < cost:
        raise ValueError(f"积分不足，当前余额 {balance}，需要 {cost}")

    # 扣减库存（stock > 0 时）
    if stock > 0:
        await db.execute(
            text(f"""
                UPDATE {POINT_REWARDS_TABLE}
                SET stock = stock - 1, updated_at = NOW()
                WHERE id = :rid AND tenant_id = :tid AND stock > 0
            """),
            {"rid": rid, "tid": tid},
        )

    # 写入扣分流水
    new_balance = balance - cost
    tx_id = uuid.uuid4()
    await db.execute(
        text(f"""
            INSERT INTO {POINT_TX_TABLE}
                (id, tenant_id, employee_id, rule_code, points, balance_after, reason, source, created_at)
            VALUES
                (:id, :tid, :eid, 'redeem', :pts, :bal, :reason, 'auto', NOW())
        """),
        {
            "id": tx_id,
            "tid": tid,
            "eid": eid,
            "pts": -cost,
            "bal": new_balance,
            "reason": f"兑换: {reward['reward_name']}",
        },
    )

    # 写入兑换记录
    redemption_id = uuid.uuid4()
    await db.execute(
        text(f"""
            INSERT INTO {POINT_REDEMPTIONS_TABLE}
                (id, tenant_id, employee_id, reward_id, points_spent, status, created_at)
            VALUES
                (:id, :tid, :eid, :rid, :cost, 'pending', NOW())
        """),
        {"id": redemption_id, "tid": tid, "eid": eid, "rid": rid, "cost": cost},
    )
    await db.flush()

    logger.info(
        "employee_points_v2.redeem",
        tenant_id=tenant_id,
        employee_id=employee_id,
        reward_id=reward_id,
        cost=cost,
        balance=new_balance,
    )
    return {
        "redemption_id": str(redemption_id),
        "reward_name": reward["reward_name"],
        "points_spent": cost,
        "balance": new_balance,
        "status": "pending",
    }


# ── 兑换商品 CRUD ─────────────────────────────────────────────────────────────


async def list_rewards(
    db: AsyncSession,
    tenant_id: str,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    """查询兑换商品列表。"""
    tid = _parse_uuid(tenant_id, "tenant_id")
    await _set_tenant(db, tenant_id)
    active_clause = "AND is_active = TRUE" if active_only else ""
    r = await db.execute(
        text(f"""
            SELECT id, reward_name, reward_type, points_cost, stock, description, is_active, created_at
            FROM {POINT_REWARDS_TABLE}
            WHERE tenant_id = :tid AND is_deleted = FALSE {active_clause}
            ORDER BY points_cost ASC
        """),
        {"tid": tid},
    )
    items: list[dict[str, Any]] = []
    for row in r.mappings().all():
        ca = row["created_at"]
        items.append(
            {
                "id": str(row["id"]),
                "reward_name": row["reward_name"],
                "reward_type": row["reward_type"],
                "points_cost": int(row["points_cost"]),
                "stock": int(row["stock"]),
                "description": row["description"] or "",
                "is_active": bool(row["is_active"]),
                "created_at": ca.isoformat() if hasattr(ca, "isoformat") else str(ca),
            }
        )
    return items


async def create_reward(
    db: AsyncSession,
    tenant_id: str,
    reward_name: str,
    reward_type: str,
    points_cost: int,
    stock: int = -1,
    description: str = "",
) -> dict[str, Any]:
    """创建兑换商品。"""
    tid = _parse_uuid(tenant_id, "tenant_id")
    await _set_tenant(db, tenant_id)
    rid = uuid.uuid4()
    await db.execute(
        text(f"""
            INSERT INTO {POINT_REWARDS_TABLE}
                (id, tenant_id, reward_name, reward_type, points_cost, stock, description, created_at, updated_at)
            VALUES
                (:id, :tid, :name, :rtype, :cost, :stock, :desc, NOW(), NOW())
        """),
        {
            "id": rid,
            "tid": tid,
            "name": reward_name,
            "rtype": reward_type,
            "cost": points_cost,
            "stock": stock,
            "desc": description or None,
        },
    )
    await db.flush()
    return {"id": str(rid), "reward_name": reward_name, "points_cost": points_cost}


async def toggle_reward(
    db: AsyncSession,
    tenant_id: str,
    reward_id: str,
) -> dict[str, Any]:
    """切换商品上下架状态。"""
    tid = _parse_uuid(tenant_id, "tenant_id")
    rid = _parse_uuid(reward_id, "reward_id")
    await _set_tenant(db, tenant_id)
    r = await db.execute(
        text(f"""
            UPDATE {POINT_REWARDS_TABLE}
            SET is_active = NOT is_active, updated_at = NOW()
            WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE
            RETURNING id, is_active
        """),
        {"rid": rid, "tid": tid},
    )
    row = r.mappings().first()
    if not row:
        raise ValueError("商品不存在")
    await db.flush()
    return {"id": str(row["id"]), "is_active": bool(row["is_active"])}


# ── 赛马赛季 CRUD ─────────────────────────────────────────────────────────────


async def create_horse_race_season(
    db: AsyncSession,
    tenant_id: str,
    season_name: str,
    start_date: date,
    end_date: date,
    scope_type: str = "store",
    scope_id: str | None = None,
    ranking_dimension: str = "points",
    prizes: list[dict[str, Any]] | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """创建赛马赛季。"""
    tid = _parse_uuid(tenant_id, "tenant_id")
    sid: uuid.UUID | None = None
    if scope_id:
        sid = _parse_uuid(scope_id, "scope_id")
    await _set_tenant(db, tenant_id)

    import json

    season_id = uuid.uuid4()
    await db.execute(
        text(f"""
            INSERT INTO {HORSE_RACE_TABLE}
                (id, tenant_id, season_name, scope_type, scope_id, start_date, end_date,
                 ranking_dimension, prizes, rules, status, created_at, updated_at)
            VALUES
                (:id, :tid, :name, :stype, :sid, :sd, :ed, :dim, :prizes::jsonb, :rules::jsonb, 'upcoming', NOW(), NOW())
        """),
        {
            "id": season_id,
            "tid": tid,
            "name": season_name,
            "stype": scope_type,
            "sid": sid,
            "sd": start_date,
            "ed": end_date,
            "dim": ranking_dimension,
            "prizes": json.dumps(prizes or []),
            "rules": json.dumps(rules or {}),
        },
    )
    await db.flush()
    logger.info("horse_race.create", tenant_id=tenant_id, season_id=str(season_id))
    return {"id": str(season_id), "season_name": season_name, "status": "upcoming"}


async def list_horse_race_seasons(
    db: AsyncSession,
    tenant_id: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """查询赛马赛季列表。"""
    tid = _parse_uuid(tenant_id, "tenant_id")
    await _set_tenant(db, tenant_id)
    status_clause = "AND status = :status" if status else ""
    params: dict[str, Any] = {"tid": tid}
    if status:
        params["status"] = status
    r = await db.execute(
        text(f"""
            SELECT id, season_name, scope_type, scope_id, start_date, end_date,
                   ranking_dimension, status, prizes, rules, created_at
            FROM {HORSE_RACE_TABLE}
            WHERE tenant_id = :tid AND is_deleted = FALSE {status_clause}
            ORDER BY start_date DESC
        """),
        params,
    )
    items: list[dict[str, Any]] = []
    for row in r.mappings().all():
        items.append(
            {
                "id": str(row["id"]),
                "season_name": row["season_name"],
                "scope_type": row["scope_type"],
                "scope_id": str(row["scope_id"]) if row["scope_id"] else None,
                "start_date": row["start_date"].isoformat()
                if hasattr(row["start_date"], "isoformat")
                else str(row["start_date"]),
                "end_date": row["end_date"].isoformat()
                if hasattr(row["end_date"], "isoformat")
                else str(row["end_date"]),
                "ranking_dimension": row["ranking_dimension"],
                "status": row["status"],
                "prizes": row["prizes"] or [],
                "rules": row["rules"] or {},
            }
        )
    return items


async def get_horse_race_season_ranking(
    db: AsyncSession,
    tenant_id: str,
    season_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    """获取赛季排名（基于积分维度）。"""
    tid = _parse_uuid(tenant_id, "tenant_id")
    ssid = _parse_uuid(season_id, "season_id")
    await _set_tenant(db, tenant_id)

    # 先查赛季信息
    sr = await db.execute(
        text(f"""
            SELECT id, season_name, scope_type, scope_id, start_date, end_date, ranking_dimension, status
            FROM {HORSE_RACE_TABLE}
            WHERE tenant_id = :tid AND id = :ssid AND is_deleted = FALSE
        """),
        {"tid": tid, "ssid": ssid},
    )
    season = sr.mappings().first()
    if not season:
        raise ValueError("赛季不存在")

    # 基于积分排名：统计赛季日期区间内的积分总和
    sd = season["start_date"]
    ed = season["end_date"]
    scope_clause = ""
    params: dict[str, Any] = {"tid": tid, "sd": sd, "ed": ed, "lim": limit}
    if season["scope_type"] == "store" and season["scope_id"]:
        scope_clause = "AND e.store_id = :scope_id"
        params["scope_id"] = season["scope_id"]

    r = await db.execute(
        text(f"""
            WITH agg AS (
                SELECT
                    pt.employee_id,
                    e.emp_name,
                    e.store_id,
                    COALESCE(SUM(pt.points), 0) AS season_points
                FROM {POINT_TX_TABLE} pt
                JOIN {EMPLOYEES_TABLE} e ON e.id = pt.employee_id AND e.tenant_id = pt.tenant_id
                WHERE pt.tenant_id = :tid AND pt.is_deleted = FALSE
                  AND e.is_deleted = FALSE
                  AND pt.created_at >= :sd AND pt.created_at < :ed + INTERVAL '1 day'
                  {scope_clause}
                GROUP BY pt.employee_id, e.emp_name, e.store_id
            )
            SELECT *, ROW_NUMBER() OVER (ORDER BY season_points DESC) AS rank
            FROM agg
            ORDER BY rank
            LIMIT :lim
        """),
        params,
    )
    items: list[dict[str, Any]] = []
    for row in r.mappings().all():
        items.append(
            {
                "employee_id": str(row["employee_id"]),
                "emp_name": row["emp_name"],
                "store_id": str(row["store_id"]) if row["store_id"] else None,
                "season_points": int(row["season_points"]),
                "rank": int(row["rank"]),
            }
        )
    return {
        "season": {
            "id": str(season["id"]),
            "season_name": season["season_name"],
            "status": season["status"],
            "start_date": season["start_date"].isoformat()
            if hasattr(season["start_date"], "isoformat")
            else str(season["start_date"]),
            "end_date": season["end_date"].isoformat()
            if hasattr(season["end_date"], "isoformat")
            else str(season["end_date"]),
        },
        "ranking": items,
    }


async def update_horse_race_status(
    db: AsyncSession,
    tenant_id: str,
    season_id: str,
    new_status: str,
) -> dict[str, Any]:
    """更新赛季状态（upcoming/active/completed）。"""
    valid_statuses = ("upcoming", "active", "completed")
    if new_status not in valid_statuses:
        raise ValueError(f"状态须为 {valid_statuses}")
    tid = _parse_uuid(tenant_id, "tenant_id")
    ssid = _parse_uuid(season_id, "season_id")
    await _set_tenant(db, tenant_id)
    r = await db.execute(
        text(f"""
            UPDATE {HORSE_RACE_TABLE}
            SET status = :status, updated_at = NOW()
            WHERE id = :ssid AND tenant_id = :tid AND is_deleted = FALSE
            RETURNING id, season_name, status
        """),
        {"ssid": ssid, "tid": tid, "status": new_status},
    )
    row = r.mappings().first()
    if not row:
        raise ValueError("赛季不存在")
    await db.flush()
    return {"id": str(row["id"]), "season_name": row["season_name"], "status": row["status"]}


# ── 积分统计概览 ───────────────────────────────────────────────────────────────


async def get_points_stats(
    db: AsyncSession,
    tenant_id: str,
    store_id: str | None = None,
) -> dict[str, Any]:
    """积分统计概览。"""
    tid = _parse_uuid(tenant_id, "tenant_id")
    sid: uuid.UUID | None = None
    if store_id:
        sid = _parse_uuid(store_id, "store_id")
    await _set_tenant(db, tenant_id)

    store_clause = "TRUE" if sid is None else "e.store_id = :sid"
    r = await db.execute(
        text(f"""
            SELECT
                COUNT(DISTINCT pt.employee_id) AS active_employees,
                COALESCE(SUM(pt.points) FILTER (WHERE pt.points > 0), 0) AS total_earned,
                COALESCE(SUM(pt.points) FILTER (WHERE pt.points < 0), 0) AS total_consumed,
                COALESCE(SUM(pt.points), 0) AS net_balance
            FROM {POINT_TX_TABLE} pt
            JOIN {EMPLOYEES_TABLE} e ON e.id = pt.employee_id AND e.tenant_id = pt.tenant_id
            WHERE pt.tenant_id = :tid AND pt.is_deleted = FALSE
              AND e.is_deleted = FALSE AND ({store_clause})
        """),
        {"tid": tid, "sid": sid},
    )
    row = r.mappings().one()

    # 兑换统计
    rr = await db.execute(
        text(f"""
            SELECT COUNT(*) AS total_redemptions, COALESCE(SUM(points_spent), 0) AS total_redeemed
            FROM {POINT_REDEMPTIONS_TABLE}
            WHERE tenant_id = :tid AND is_deleted = FALSE
        """),
        {"tid": tid},
    )
    rrow = rr.mappings().one()

    return {
        "active_employees": int(row["active_employees"]),
        "total_earned": int(row["total_earned"]),
        "total_consumed": abs(int(row["total_consumed"])),
        "net_balance": int(row["net_balance"]),
        "total_redemptions": int(rrow["total_redemptions"]),
        "total_redeemed_points": int(rrow["total_redeemed"]),
    }
