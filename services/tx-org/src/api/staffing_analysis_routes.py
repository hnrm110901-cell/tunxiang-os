"""Staffing Analysis — Human Hub / staffing_snapshots + store_staffing_templates"""

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, List, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger()
router = APIRouter(tags=["staffing-analysis"])


# -- helpers ----------------------------------------------------------------
def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# -- request models ---------------------------------------------------------
class SnapshotReq(BaseModel):
    store_id: str = Field(..., min_length=1)
    snapshot_date: Optional[date] = None


class BatchSnapshotReq(BaseModel):
    store_ids: List[str] = Field(..., min_length=1)
    snapshot_date: Optional[date] = None


# -- internal: generate snapshot for one store ------------------------------
async def _generate_snapshot_for_store(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    snapshot_date: date,
) -> list[dict]:
    """Generate staffing snapshot records for a single store.

    For each position+shift combo in the store's staffing template
    (matched by store.store_type), count actual employees and compute gap.
    """
    # 1. Get store_type for this store
    store_row = (
        (
            await db.execute(
                text("SELECT store_type FROM stores WHERE id = :sid AND tenant_id = :tid AND is_deleted = FALSE"),
                {"sid": store_id, "tid": tenant_id},
            )
        )
        .mappings()
        .first()
    )
    if not store_row:
        raise HTTPException(status_code=404, detail=f"Store {store_id} not found")

    store_type = store_row["store_type"]

    # 2. Get all active template entries for this store_type
    templates = (
        (
            await db.execute(
                text("""
            SELECT id::text AS template_id, position, shift,
                   COALESCE(recommended_count, min_count, 0) AS required_count,
                   min_skill_level
            FROM store_staffing_templates
            WHERE tenant_id = :tid
              AND store_type = :stype
              AND is_active = TRUE
              AND is_deleted = FALSE
            ORDER BY position, shift
        """),
                {"tid": tenant_id, "stype": store_type},
            )
        )
        .mappings()
        .all()
    )

    if not templates:
        return []

    now = datetime.now(timezone.utc)
    snapshots: list[dict] = []

    for tpl in templates:
        position = tpl["position"]
        shift = tpl["shift"]
        required = int(tpl["required_count"])
        min_skill = tpl["min_skill_level"]

        # 3. Count actual employees with matching position in this store
        actual_row = (
            (
                await db.execute(
                    text("""
                SELECT COUNT(*)::int AS cnt
                FROM employees
                WHERE tenant_id = :tid
                  AND store_id = :sid
                  AND position = :pos
                  AND is_deleted = FALSE
            """),
                    {"tid": tenant_id, "sid": store_id, "pos": position},
                )
            )
            .mappings()
            .first()
        )
        actual = int(actual_row["cnt"]) if actual_row else 0

        gap = actual - required

        # 4. Build skill_gap_detail if min_skill_level is set
        skill_gap_detail = None
        if min_skill:
            qualified_row = (
                (
                    await db.execute(
                        text("""
                    SELECT COUNT(*)::int AS cnt
                    FROM employees
                    WHERE tenant_id = :tid
                      AND store_id = :sid
                      AND position = :pos
                      AND is_deleted = FALSE
                      AND COALESCE((meta->>'skill_level')::int, 0) >= :min_level
                """),
                        {"tid": tenant_id, "sid": store_id, "pos": position, "min_level": min_skill},
                    )
                )
                .mappings()
                .first()
            )
            qualified = int(qualified_row["cnt"]) if qualified_row else 0
            skill_gap_detail = json.dumps(
                {
                    "min_level": min_skill,
                    "qualified_count": qualified,
                    "unqualified_count": actual - qualified,
                }
            )

        # 5. Calculate impact_score: abs(gap) * 2, capped at 10
        impact_score = min(abs(gap) * 2, 10) if gap < 0 else 0

        # 6. Insert snapshot record
        snap_id = str(uuid4())
        await db.execute(
            text("""
                INSERT INTO staffing_snapshots
                    (id, tenant_id, store_id, template_id, position, shift,
                     snapshot_date, required_count, actual_count, gap,
                     skill_gap_detail, impact_score,
                     created_at, updated_at, is_deleted)
                VALUES
                    (:id, :tid, :sid, :tpl_id, :position, :shift,
                     :snap_date, :required, :actual, :gap,
                     :skill_detail, :impact,
                     :now, :now, FALSE)
            """),
            {
                "id": snap_id,
                "tid": tenant_id,
                "sid": store_id,
                "tpl_id": tpl["template_id"],
                "position": position,
                "shift": shift,
                "snap_date": snapshot_date,
                "required": required,
                "actual": actual,
                "gap": gap,
                "skill_detail": skill_gap_detail,
                "impact": impact_score,
                "now": now,
            },
        )

        snapshots.append(
            {
                "snapshot_id": snap_id,
                "store_id": store_id,
                "position": position,
                "shift": shift,
                "required": required,
                "actual": actual,
                "gap": gap,
                "impact_score": impact_score,
                "snapshot_date": str(snapshot_date),
            }
        )

    return snapshots


# -- 1. POST /snapshot -- generate staffing snapshot for one store ----------
@router.post("/api/v1/staffing-analysis/snapshot", status_code=201)
async def generate_snapshot(
    body: SnapshotReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    snapshot_date = body.snapshot_date or date.today()
    snapshots = await _generate_snapshot_for_store(db, tenant_id, body.store_id, snapshot_date)
    await db.commit()

    log.info("staffing_analysis.snapshot_generated", store_id=body.store_id, count=len(snapshots), tenant_id=tenant_id)

    return _ok({"snapshots": snapshots, "count": len(snapshots)})


# -- 2. POST /snapshot/batch -- batch generate snapshots --------------------
@router.post("/api/v1/staffing-analysis/snapshot/batch", status_code=201)
async def batch_generate_snapshots(
    body: BatchSnapshotReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    snapshot_date = body.snapshot_date or date.today()
    total_positions = 0
    total_gaps = 0

    for store_id in body.store_ids:
        snapshots = await _generate_snapshot_for_store(db, tenant_id, store_id, snapshot_date)
        total_positions += len(snapshots)
        total_gaps += sum(s["gap"] for s in snapshots if s["gap"] < 0)

    await db.commit()

    log.info(
        "staffing_analysis.batch_snapshot_generated",
        store_count=len(body.store_ids),
        total_positions=total_positions,
        tenant_id=tenant_id,
    )

    return _ok(
        {
            "total_stores": len(body.store_ids),
            "total_positions": total_positions,
            "total_gaps": total_gaps,
        }
    )


# -- 3. GET /compare -- staffing benchmark comparison ----------------------
@router.get("/api/v1/staffing-analysis/compare")
async def staffing_compare(
    request: Request,
    store_id: str = Query(...),
    snapshot_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    snap_date = snapshot_date or date.today()

    sql = text("""
        SELECT
            ss.position,
            ss.shift,
            ss.required_count   AS required,
            ss.actual_count     AS actual,
            ss.gap,
            ss.skill_gap_detail,
            ss.impact_score
        FROM staffing_snapshots ss
        WHERE ss.tenant_id = :tid
          AND ss.store_id  = :sid
          AND ss.snapshot_date = :snap_date
          AND ss.is_deleted = FALSE
        ORDER BY ss.position, ss.shift
    """)
    rows = (
        (
            await db.execute(
                sql,
                {
                    "tid": tenant_id,
                    "sid": store_id,
                    "snap_date": snap_date,
                },
            )
        )
        .mappings()
        .all()
    )

    items = []
    total_required = 0
    total_actual = 0
    total_gap = 0

    for r in rows:
        skill_detail = None
        if r["skill_gap_detail"]:
            try:
                skill_detail = (
                    json.loads(r["skill_gap_detail"])
                    if isinstance(r["skill_gap_detail"], str)
                    else r["skill_gap_detail"]
                )
            except (json.JSONDecodeError, TypeError):
                skill_detail = None

        items.append(
            {
                "position": r["position"],
                "shift": r["shift"],
                "required": r["required"],
                "actual": r["actual"],
                "gap": r["gap"],
                "skill_gap_detail": skill_detail,
                "impact_score": r["impact_score"],
            }
        )
        total_required += r["required"]
        total_actual += r["actual"]
        total_gap += r["gap"]

    gap_rate_pct = round((abs(total_gap) / total_required * 100), 2) if total_required > 0 else 0.0

    return _ok(
        {
            "items": items,
            "summary": {
                "total_required": total_required,
                "total_actual": total_actual,
                "total_gap": total_gap,
                "gap_rate_pct": gap_rate_pct,
            },
        }
    )


# -- 4. GET /gap-ranking -- gap ranking across stores ----------------------
@router.get("/api/v1/staffing-analysis/gap-ranking")
async def gap_ranking(
    request: Request,
    snapshot_date: Optional[date] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    snap_date = snapshot_date or date.today()

    sql = text("""
        SELECT
            ss.store_id::text,
            s.store_name,
            SUM(ss.required_count)::int AS total_required,
            SUM(ss.actual_count)::int   AS total_actual,
            SUM(ss.gap)::int            AS total_gap
        FROM staffing_snapshots ss
        JOIN stores s ON s.id = ss.store_id AND s.tenant_id = ss.tenant_id
        WHERE ss.tenant_id = :tid
          AND ss.snapshot_date = :snap_date
          AND ss.is_deleted = FALSE
        GROUP BY ss.store_id, s.store_name
        ORDER BY total_gap ASC
        LIMIT :lim
    """)
    rows = (
        (
            await db.execute(
                sql,
                {
                    "tid": tenant_id,
                    "snap_date": snap_date,
                    "lim": limit,
                },
            )
        )
        .mappings()
        .all()
    )

    ranked = []
    for idx, r in enumerate(rows, 1):
        total_req = r["total_required"]
        total_gap = r["total_gap"]
        gap_rate = round((abs(total_gap) / total_req * 100), 2) if total_req > 0 else 0.0
        ranked.append(
            {
                "rank": idx,
                "store_id": r["store_id"],
                "store_name": r["store_name"],
                "total_required": total_req,
                "total_actual": r["total_actual"],
                "total_gap": total_gap,
                "gap_rate_pct": gap_rate,
            }
        )

    return _ok({"items": ranked})


# -- 5. GET /trend -- staffing trend over time -----------------------------
@router.get("/api/v1/staffing-analysis/trend")
async def staffing_trend(
    request: Request,
    store_id: str = Query(...),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    ed = end_date or date.today()
    sd = start_date or (ed - timedelta(days=30))

    sql = text("""
        SELECT
            snapshot_date,
            SUM(required_count)::int AS total_required,
            SUM(actual_count)::int   AS total_actual,
            SUM(gap)::int            AS gap
        FROM staffing_snapshots
        WHERE tenant_id = :tid
          AND store_id  = :sid
          AND snapshot_date BETWEEN :sd AND :ed
          AND is_deleted = FALSE
        GROUP BY snapshot_date
        ORDER BY snapshot_date
    """)
    rows = (
        (
            await db.execute(
                sql,
                {
                    "tid": tenant_id,
                    "sid": store_id,
                    "sd": sd,
                    "ed": ed,
                },
            )
        )
        .mappings()
        .all()
    )

    series = []
    for r in rows:
        total_req = r["total_required"]
        gap_val = r["gap"]
        gap_rate = round((abs(gap_val) / total_req * 100), 2) if total_req > 0 else 0.0
        series.append(
            {
                "date": str(r["snapshot_date"]),
                "total_required": total_req,
                "total_actual": r["total_actual"],
                "gap": gap_val,
                "gap_rate_pct": gap_rate,
            }
        )

    return _ok({"series": series})


# -- 6. GET /skill-gaps -- skill gap analysis ------------------------------
@router.get("/api/v1/staffing-analysis/skill-gaps")
async def skill_gaps(
    request: Request,
    store_id: Optional[str] = Query(None),
    snapshot_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    snap_date = snapshot_date or date.today()

    conditions = [
        "tenant_id = :tid",
        "snapshot_date = :snap_date",
        "is_deleted = FALSE",
        "skill_gap_detail IS NOT NULL",
    ]
    params: dict[str, Any] = {"tid": tenant_id, "snap_date": snap_date}

    if store_id:
        conditions.append("store_id = :sid")
        params["sid"] = store_id

    where = " AND ".join(conditions)

    sql = text(f"""
        SELECT position, shift, skill_gap_detail
        FROM staffing_snapshots
        WHERE {where}
        ORDER BY position, shift
    """)
    rows = (await db.execute(sql, params)).mappings().all()

    # Aggregate by position
    position_map: dict[str, list] = {}
    for r in rows:
        pos = r["position"]
        raw = r["skill_gap_detail"]
        try:
            detail = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue

        if pos not in position_map:
            position_map[pos] = []

        position_map[pos].append(
            {
                "shift": r["shift"],
                "min_level": detail.get("min_level"),
                "qualified_count": detail.get("qualified_count", 0),
                "unqualified_count": detail.get("unqualified_count", 0),
                "gap": detail.get("unqualified_count", 0),
            }
        )

    items = [{"position": pos, "required_skills": skills} for pos, skills in position_map.items()]

    return _ok({"items": items})


# -- 7. GET /impact -- business impact analysis ----------------------------
@router.get("/api/v1/staffing-analysis/impact")
async def impact_analysis(
    request: Request,
    store_id: Optional[str] = Query(None),
    snapshot_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    snap_date = snapshot_date or date.today()

    conditions = [
        "ss.tenant_id = :tid",
        "ss.snapshot_date = :snap_date",
        "ss.is_deleted = FALSE",
        "ss.impact_score > 5",
    ]
    params: dict[str, Any] = {"tid": tenant_id, "snap_date": snap_date}

    if store_id:
        conditions.append("ss.store_id = :sid")
        params["sid"] = store_id

    where = " AND ".join(conditions)

    sql = text(f"""
        SELECT
            ss.store_id::text,
            s.store_name,
            ss.position,
            ss.shift,
            ss.gap,
            ss.impact_score
        FROM staffing_snapshots ss
        JOIN stores s ON s.id = ss.store_id AND s.tenant_id = ss.tenant_id
        WHERE {where}
        ORDER BY ss.impact_score DESC
    """)
    rows = (await db.execute(sql, params)).mappings().all()

    items = []
    for r in rows:
        score = r["impact_score"]
        if score >= 8:
            risk_level = "critical"
        elif score >= 5:
            risk_level = "warning"
        else:
            risk_level = "normal"

        items.append(
            {
                "store_id": r["store_id"],
                "store_name": r["store_name"],
                "position": r["position"],
                "shift": r["shift"],
                "gap": r["gap"],
                "impact_score": score,
                "risk_level": risk_level,
            }
        )

    return _ok({"items": items})
