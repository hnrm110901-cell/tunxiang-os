"""Store Readiness Scores — 门店就绪度评分 API"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, Optional, List
from uuid import uuid4
from datetime import datetime, date, timezone
from decimal import Decimal
import json
import structlog

from shared.ontology.src.database import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/store-readiness", tags=["store-readiness"])


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


def _row_to_dict(row) -> dict:
    """Convert a DB row mapping to a JSON-safe dict."""
    d = {}
    for k, v in row.items():
        if isinstance(v, date) and not isinstance(v, datetime):
            d[k] = str(v)
        elif isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, Decimal):
            d[k] = float(v)
        elif isinstance(v, str):
            # Try parsing JSONB strings
            if k in ("dimensions", "risk_positions", "action_items"):
                try:
                    d[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    d[k] = v
            else:
                d[k] = v
        else:
            d[k] = v
    return d


_FIELDS = """
    id::text, tenant_id::text, store_id::text, score_date, shift,
    overall_score, dimensions, risk_level, risk_positions, action_items,
    is_deleted, created_at, updated_at
"""


def _calc_score_and_risk(dimensions: dict) -> tuple[float, str, list]:
    """Calculate overall_score, risk_level, risk_positions from dimensions."""
    sc = float(dimensions.get("shift_coverage", 0))
    sk = float(dimensions.get("skill_coverage", 0))
    nr = float(dimensions.get("newbie_ratio", 0))
    tc = float(dimensions.get("training_completion", 0))

    overall = round(sc * 0.35 + sk * 0.25 + (100 - nr) * 0.20 + tc * 0.20, 2)

    if overall >= 80:
        risk = "green"
    elif overall >= 60:
        risk = "yellow"
    else:
        risk = "red"

    # Auto-extract risk positions from shift_coverage < 80
    risk_positions: list[dict] = []
    if sc < 80:
        risk_positions.append({
            "position": "shift",
            "gap": round(80 - sc, 2),
            "reason": "排班覆盖率不足",
        })

    return overall, risk, risk_positions


# -- request models ---------------------------------------------------------
class ReadinessCreateReq(BaseModel):
    store_id: str = Field(..., min_length=1)
    score_date: Optional[date] = None
    shift: str = Field(default="full_day", max_length=30)
    overall_score: Optional[float] = Field(None, ge=0, le=100)
    dimensions: Optional[dict] = None
    risk_level: Optional[str] = None
    risk_positions: Optional[list] = None
    action_items: Optional[list] = None


class ReadinessUpdateReq(BaseModel):
    overall_score: Optional[float] = Field(None, ge=0, le=100)
    dimensions: Optional[dict] = None
    risk_level: Optional[str] = None
    risk_positions: Optional[list] = None
    action_items: Optional[list] = None


class ActionItemsReq(BaseModel):
    items: List[dict] = Field(..., min_length=1)


# -- 1. GET / -- 就绪度列表（分页+筛选）-------------------------------------
@router.get("")
async def list_readiness(
    request: Request,
    store_id: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    score_date: Optional[date] = Query(None),
    shift: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["tenant_id = :tid", "is_deleted = FALSE"]
    params: dict[str, Any] = {"tid": tenant_id}

    if store_id:
        conditions.append("store_id = :store_id")
        params["store_id"] = store_id
    if risk_level:
        conditions.append("risk_level = :risk_level")
        params["risk_level"] = risk_level
    if score_date:
        conditions.append("score_date = :score_date")
        params["score_date"] = score_date
    if shift:
        conditions.append("shift = :shift")
        params["shift"] = shift

    where = " AND ".join(conditions)

    # count
    cnt_row = (await db.execute(
        text(f"SELECT COUNT(*)::int AS total FROM store_readiness_scores WHERE {where}"),
        params,
    )).mappings().first()
    total = cnt_row["total"] if cnt_row else 0

    # data
    offset = (page - 1) * size
    params["lim"] = size
    params["off"] = offset

    rows = (await db.execute(
        text(f"""
            SELECT {_FIELDS}
            FROM store_readiness_scores
            WHERE {where}
            ORDER BY score_date DESC, risk_level DESC
            LIMIT :lim OFFSET :off
        """),
        params,
    )).mappings().all()

    items = [_row_to_dict(r) for r in rows]
    return _ok({"items": items, "total": total, "page": page, "size": size})


# -- 2. POST / -- 创建/更新就绪度评分（UPSERT）------------------------------
@router.post("", status_code=201)
async def upsert_readiness(
    body: ReadinessCreateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    s_date = body.score_date or date.today()
    now = datetime.now(timezone.utc)
    rec_id = str(uuid4())

    # Auto-calculate if dimensions provided with all four keys
    dims = body.dimensions or {}
    if all(k in dims for k in ("shift_coverage", "skill_coverage", "newbie_ratio", "training_completion")):
        overall, risk, auto_risk_pos = _calc_score_and_risk(dims)
    else:
        overall = body.overall_score or 0
        risk = body.risk_level or "green"
        auto_risk_pos = []

    risk_positions = body.risk_positions if body.risk_positions is not None else auto_risk_pos
    action_items = body.action_items or []

    sql = text("""
        INSERT INTO store_readiness_scores
            (id, tenant_id, store_id, score_date, shift,
             overall_score, dimensions, risk_level, risk_positions, action_items,
             is_deleted, created_at, updated_at)
        VALUES
            (:id, :tid, :store_id, :score_date, :shift,
             :overall_score, :dimensions::jsonb, :risk_level, :risk_positions::jsonb, :action_items::jsonb,
             FALSE, :now, :now)
        ON CONFLICT ON CONSTRAINT uq_readiness_daily
        DO UPDATE SET
            overall_score   = EXCLUDED.overall_score,
            dimensions      = EXCLUDED.dimensions,
            risk_level      = EXCLUDED.risk_level,
            risk_positions  = EXCLUDED.risk_positions,
            action_items    = EXCLUDED.action_items,
            updated_at      = EXCLUDED.updated_at
        RETURNING id::text, overall_score, risk_level
    """)
    result = (await db.execute(sql, {
        "id": rec_id, "tid": tenant_id, "store_id": body.store_id,
        "score_date": s_date, "shift": body.shift,
        "overall_score": overall,
        "dimensions": json.dumps(dims),
        "risk_level": risk,
        "risk_positions": json.dumps(risk_positions),
        "action_items": json.dumps(action_items),
        "now": now,
    })).mappings().first()

    await db.commit()

    log.info("store_readiness.upserted",
             store_id=body.store_id, score_date=str(s_date), tenant_id=tenant_id)

    return _ok({
        "id": result["id"] if result else rec_id,
        "overall_score": float(result["overall_score"]) if result else overall,
        "risk_level": result["risk_level"] if result else risk,
    })


# -- 3. GET /dashboard -- 就绪度总览 ----------------------------------------
@router.get("/dashboard")
async def readiness_dashboard(
    request: Request,
    score_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    s_date = score_date or date.today()

    # Risk level counts + avg score
    summary_sql = text("""
        SELECT
            COUNT(*) FILTER (WHERE risk_level = 'green')::int  AS green_count,
            COUNT(*) FILTER (WHERE risk_level = 'yellow')::int AS yellow_count,
            COUNT(*) FILTER (WHERE risk_level = 'red')::int    AS red_count,
            COALESCE(ROUND(AVG(overall_score), 2), 0)          AS avg_score
        FROM store_readiness_scores
        WHERE tenant_id = :tid AND score_date = :sd AND is_deleted = FALSE
    """)
    summary = (await db.execute(summary_sql, {"tid": tenant_id, "sd": s_date})).mappings().first()

    # Worst stores top 5
    worst_sql = text("""
        SELECT store_id::text, overall_score, risk_level
        FROM store_readiness_scores
        WHERE tenant_id = :tid AND score_date = :sd AND is_deleted = FALSE
        ORDER BY overall_score ASC
        LIMIT 5
    """)
    worst_rows = (await db.execute(worst_sql, {"tid": tenant_id, "sd": s_date})).mappings().all()

    worst_stores = [{
        "store_id": r["store_id"],
        "overall_score": float(r["overall_score"]),
        "risk_level": r["risk_level"],
    } for r in worst_rows]

    # Dimension averages
    dim_sql = text("""
        SELECT
            COALESCE(ROUND(AVG((dimensions->>'shift_coverage')::numeric), 2), 0)       AS avg_shift_coverage,
            COALESCE(ROUND(AVG((dimensions->>'skill_coverage')::numeric), 2), 0)       AS avg_skill_coverage,
            COALESCE(ROUND(AVG((dimensions->>'newbie_ratio')::numeric), 2), 0)         AS avg_newbie_ratio,
            COALESCE(ROUND(AVG((dimensions->>'training_completion')::numeric), 2), 0)  AS avg_training_completion
        FROM store_readiness_scores
        WHERE tenant_id = :tid AND score_date = :sd AND is_deleted = FALSE
          AND dimensions IS NOT NULL AND dimensions != '{}'::jsonb
    """)
    dim_row = (await db.execute(dim_sql, {"tid": tenant_id, "sd": s_date})).mappings().first()

    return _ok({
        "green_count": summary["green_count"] if summary else 0,
        "yellow_count": summary["yellow_count"] if summary else 0,
        "red_count": summary["red_count"] if summary else 0,
        "avg_score": float(summary["avg_score"]) if summary else 0,
        "worst_stores": worst_stores,
        "dimension_averages": {
            "shift_coverage": float(dim_row["avg_shift_coverage"]) if dim_row else 0,
            "skill_coverage": float(dim_row["avg_skill_coverage"]) if dim_row else 0,
            "newbie_ratio": float(dim_row["avg_newbie_ratio"]) if dim_row else 0,
            "training_completion": float(dim_row["avg_training_completion"]) if dim_row else 0,
        },
    })


# -- 4. GET /today -- 今日全部门店就绪度概览 ----------------------------------
@router.get("/today")
async def readiness_today(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text(f"""
        SELECT {_FIELDS}
        FROM store_readiness_scores
        WHERE tenant_id = :tid AND score_date = CURRENT_DATE AND is_deleted = FALSE
        ORDER BY
            CASE risk_level
                WHEN 'red' THEN 1
                WHEN 'yellow' THEN 2
                WHEN 'green' THEN 3
                ELSE 4
            END ASC
    """)
    rows = (await db.execute(sql, {"tid": tenant_id})).mappings().all()

    items = [_row_to_dict(r) for r in rows]
    return _ok({"items": items, "total": len(items)})


# -- 5. GET /trend -- 门店就绪度趋势 -----------------------------------------
@router.get("/trend")
async def readiness_trend(
    request: Request,
    store_id: str = Query(...),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        SELECT score_date, overall_score, risk_level, shift
        FROM store_readiness_scores
        WHERE tenant_id = :tid
          AND store_id = :sid
          AND score_date >= CURRENT_DATE - :days
          AND is_deleted = FALSE
        ORDER BY score_date ASC
    """)
    rows = (await db.execute(sql, {
        "tid": tenant_id, "sid": store_id, "days": days,
    })).mappings().all()

    series = [{
        "score_date": str(r["score_date"]),
        "overall_score": float(r["overall_score"]),
        "risk_level": r["risk_level"],
        "shift": r["shift"],
    } for r in rows]

    return _ok({"store_id": store_id, "days": days, "series": series})


# -- 6. GET /heatmap -- 就绪度热力图数据 -------------------------------------
@router.get("/heatmap")
async def readiness_heatmap(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        SELECT DISTINCT ON (store_id)
            store_id::text, overall_score, risk_level, score_date, shift
        FROM store_readiness_scores
        WHERE tenant_id = :tid AND is_deleted = FALSE
        ORDER BY store_id, score_date DESC
    """)
    rows = (await db.execute(sql, {"tid": tenant_id})).mappings().all()

    items = [{
        "store_id": r["store_id"],
        "overall_score": float(r["overall_score"]),
        "risk_level": r["risk_level"],
        "score_date": str(r["score_date"]),
        "shift": r["shift"],
    } for r in rows]

    return _ok({"items": items, "total": len(items)})


# -- 7. GET /{record_id} -- 就绪度详情 ---------------------------------------
@router.get("/{record_id}")
async def get_readiness(
    record_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text(f"""
        SELECT {_FIELDS}
        FROM store_readiness_scores
        WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE
    """)
    row = (await db.execute(sql, {"rid": record_id, "tid": tenant_id})).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Readiness record not found")

    return _ok(_row_to_dict(row))


# -- 8. PUT /{record_id} -- 更新就绪度 ---------------------------------------
@router.put("/{record_id}")
async def update_readiness(
    record_id: str,
    body: ReadinessUpdateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)

    sets = ["updated_at = :now"]
    params: dict[str, Any] = {"rid": record_id, "tid": tenant_id, "now": now}

    # If dimensions with all four keys, auto-calculate
    if body.dimensions and all(
        k in body.dimensions for k in ("shift_coverage", "skill_coverage", "newbie_ratio", "training_completion")
    ):
        overall, risk, auto_risk_pos = _calc_score_and_risk(body.dimensions)
        sets.append("dimensions = :dimensions::jsonb")
        sets.append("overall_score = :overall_score")
        sets.append("risk_level = :risk_level")
        params["dimensions"] = json.dumps(body.dimensions)
        params["overall_score"] = overall
        params["risk_level"] = risk
        if body.risk_positions is not None:
            sets.append("risk_positions = :risk_positions::jsonb")
            params["risk_positions"] = json.dumps(body.risk_positions)
        else:
            sets.append("risk_positions = :risk_positions::jsonb")
            params["risk_positions"] = json.dumps(auto_risk_pos)
    else:
        if body.dimensions is not None:
            sets.append("dimensions = :dimensions::jsonb")
            params["dimensions"] = json.dumps(body.dimensions)
        if body.overall_score is not None:
            sets.append("overall_score = :overall_score")
            params["overall_score"] = body.overall_score
        if body.risk_level is not None:
            sets.append("risk_level = :risk_level")
            params["risk_level"] = body.risk_level
        if body.risk_positions is not None:
            sets.append("risk_positions = :risk_positions::jsonb")
            params["risk_positions"] = json.dumps(body.risk_positions)

    if body.action_items is not None:
        sets.append("action_items = :action_items::jsonb")
        params["action_items"] = json.dumps(body.action_items)

    set_clause = ", ".join(sets)

    result = await db.execute(
        text(f"""
            UPDATE store_readiness_scores
            SET {set_clause}
            WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE
            RETURNING id::text
        """),
        params,
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Readiness record not found")

    await db.commit()

    log.info("store_readiness.updated", record_id=record_id, tenant_id=tenant_id)
    return _ok({"id": row["id"]})


# -- 9. PUT /{record_id}/actions -- 追加行动项 --------------------------------
@router.put("/{record_id}/actions")
async def append_action_items(
    record_id: str,
    body: ActionItemsReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)

    sql = text("""
        UPDATE store_readiness_scores
        SET action_items = COALESCE(action_items, '[]'::jsonb) || :new_items::jsonb,
            updated_at = :now
        WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE
        RETURNING id::text, action_items
    """)
    result = (await db.execute(sql, {
        "rid": record_id,
        "tid": tenant_id,
        "new_items": json.dumps(body.items),
        "now": now,
    })).mappings().first()

    if not result:
        raise HTTPException(status_code=404, detail="Readiness record not found")

    await db.commit()

    log.info("store_readiness.actions_appended",
             record_id=record_id, count=len(body.items), tenant_id=tenant_id)

    action_items = result["action_items"]
    if isinstance(action_items, str):
        try:
            action_items = json.loads(action_items)
        except (json.JSONDecodeError, TypeError):
            pass

    return _ok({"id": result["id"], "action_items": action_items})


# -- 10. DELETE /{record_id} -- 软删除 ----------------------------------------
@router.delete("/{record_id}")
async def delete_readiness(
    record_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)

    result = await db.execute(
        text("""
            UPDATE store_readiness_scores
            SET is_deleted = TRUE, updated_at = :now
            WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE
            RETURNING id::text
        """),
        {"rid": record_id, "tid": tenant_id, "now": now},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Readiness record not found")

    await db.commit()

    log.info("store_readiness.deleted", record_id=record_id, tenant_id=tenant_id)
    return _ok({"id": row["id"], "deleted": True})
