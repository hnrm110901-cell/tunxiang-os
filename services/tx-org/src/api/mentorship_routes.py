"""Mentorship Relations CRUD — Human Hub / mentorship_relations

端点列表：
  GET    /api/v1/mentorships                           带教列表（分页+筛选）
  POST   /api/v1/mentorships                           创建带教关系
  GET    /api/v1/mentorships/statistics                 带教统计看板
  GET    /api/v1/mentorships/leaderboard                带教排行榜
  GET    /api/v1/mentorships/{mentorship_id}            带教详情
  PUT    /api/v1/mentorships/{mentorship_id}            更新带教
  PUT    /api/v1/mentorships/{mentorship_id}/complete   完成带教
  PUT    /api/v1/mentorships/{mentorship_id}/terminate  终止带教
  DELETE /api/v1/mentorships/{mentorship_id}            软删除
"""

from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/mentorships", tags=["mentorships"])


# ── helpers ──────────────────────────────────────────────────────────
def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


def _row_to_dict(r) -> dict:
    """Convert a row mapping to a serialisable dict."""
    d = dict(r)
    for key in ("created_at", "updated_at"):
        if d.get(key) is not None:
            d[key] = d[key].isoformat() if hasattr(d[key], "isoformat") else str(d[key])
    for key in ("start_date", "end_date"):
        if d.get(key) is not None:
            d[key] = d[key].isoformat() if hasattr(d[key], "isoformat") else str(d[key])
    # Numeric fields: convert Decimal to float
    for key in ("mentor_score", "mentee_pass_rate"):
        if d.get(key) is not None:
            d[key] = float(d[key])
    return d


# ── column list (reused across queries) ──────────────────────────────
_SELECT_COLS = """
    id::text AS mentorship_id, tenant_id::text, mentor_id::text, mentee_id::text,
    store_id::text, start_date, end_date, status,
    mentor_score, mentee_pass_rate, notes,
    is_deleted, created_at, updated_at
"""


# ── request models ───────────────────────────────────────────────────
class CreateMentorshipReq(BaseModel):
    mentor_id: str = Field(..., min_length=1)
    mentee_id: str = Field(..., min_length=1)
    store_id: str = Field(..., min_length=1)
    start_date: date
    notes: Optional[str] = None


class UpdateMentorshipReq(BaseModel):
    notes: Optional[str] = None
    mentor_score: Optional[float] = Field(None, ge=0, le=10)
    mentee_pass_rate: Optional[float] = Field(None, ge=0, le=100)
    end_date: Optional[date] = None


class CompleteMentorshipReq(BaseModel):
    mentor_score: float = Field(..., ge=0, le=10)
    mentee_pass_rate: float = Field(..., ge=0, le=100)
    notes: Optional[str] = None


class TerminateMentorshipReq(BaseModel):
    notes: str = Field(..., min_length=1)


# ── GET /statistics (before /{mentorship_id} to avoid route clash) ───
@router.get("/statistics")
async def mentorship_statistics(
    request: Request,
    store_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """带教统计看板 — 总数/活跃/完成/终止/平均分/平均通关率/按门店分组。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["tenant_id = :tid", "is_deleted = FALSE"]
    params: dict[str, Any] = {"tid": tenant_id}

    if store_id is not None:
        conditions.append("store_id = :store_id")
        params["store_id"] = store_id

    where = " AND ".join(conditions)

    # Overall stats
    overall_sql = text(f"""
        SELECT
            COUNT(*)::int                                              AS total,
            COUNT(*) FILTER (WHERE status = 'active')::int             AS active_count,
            COUNT(*) FILTER (WHERE status = 'completed')::int          AS completed_count,
            COUNT(*) FILTER (WHERE status = 'terminated')::int         AS terminated_count,
            COALESCE(AVG(mentor_score) FILTER (WHERE mentor_score IS NOT NULL), 0)  AS avg_mentor_score,
            COALESCE(AVG(mentee_pass_rate) FILTER (WHERE mentee_pass_rate IS NOT NULL), 0) AS avg_pass_rate
        FROM mentorship_relations
        WHERE {where}
    """)
    overall = (await db.execute(overall_sql, params)).mappings().first()

    # By store
    store_sql = text(f"""
        SELECT
            store_id::text,
            COUNT(*)::int                                              AS total,
            COUNT(*) FILTER (WHERE status = 'active')::int             AS active_count,
            COUNT(*) FILTER (WHERE status = 'completed')::int          AS completed_count,
            COALESCE(AVG(mentor_score) FILTER (WHERE mentor_score IS NOT NULL), 0) AS avg_mentor_score,
            COALESCE(AVG(mentee_pass_rate) FILTER (WHERE mentee_pass_rate IS NOT NULL), 0) AS avg_pass_rate
        FROM mentorship_relations
        WHERE {where}
        GROUP BY store_id
        ORDER BY total DESC
    """)
    store_rows = (await db.execute(store_sql, params)).mappings().all()

    return _ok(
        {
            "total": overall["total"],
            "active_count": overall["active_count"],
            "completed_count": overall["completed_count"],
            "terminated_count": overall["terminated_count"],
            "avg_mentor_score": round(float(overall["avg_mentor_score"]), 1),
            "avg_pass_rate": round(float(overall["avg_pass_rate"]), 2),
            "by_store": [
                {
                    "store_id": r["store_id"],
                    "total": r["total"],
                    "active_count": r["active_count"],
                    "completed_count": r["completed_count"],
                    "avg_mentor_score": round(float(r["avg_mentor_score"]), 1),
                    "avg_pass_rate": round(float(r["avg_pass_rate"]), 2),
                }
                for r in store_rows
            ],
        }
    )


# ── GET /leaderboard (before /{mentorship_id} to avoid route clash) ──
@router.get("/leaderboard")
async def mentorship_leaderboard(
    request: Request,
    sort_by: str = Query("mentor_score", regex="^(mentor_score|mentee_pass_rate)$"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """带教排行榜 — 按完成数+平均分排名，返回 top N。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # Sort metric
    metric_col = "avg_mentor_score" if sort_by == "mentor_score" else "avg_pass_rate"

    sql = text(f"""
        SELECT
            mentor_id::text,
            COUNT(*) FILTER (WHERE status = 'completed')::int AS completed_count,
            COUNT(*)::int AS total_count,
            COALESCE(AVG(mentor_score) FILTER (WHERE mentor_score IS NOT NULL), 0) AS avg_mentor_score,
            COALESCE(AVG(mentee_pass_rate) FILTER (WHERE mentee_pass_rate IS NOT NULL), 0) AS avg_pass_rate
        FROM mentorship_relations
        WHERE tenant_id = :tid AND is_deleted = FALSE
        GROUP BY mentor_id
        HAVING COUNT(*) FILTER (WHERE status = 'completed') > 0
        ORDER BY {metric_col} DESC, completed_count DESC
        LIMIT :lmt
    """)
    rows = (await db.execute(sql, {"tid": tenant_id, "lmt": limit})).mappings().all()

    items = [
        {
            "rank": idx + 1,
            "mentor_id": r["mentor_id"],
            "completed_count": r["completed_count"],
            "total_count": r["total_count"],
            "avg_mentor_score": round(float(r["avg_mentor_score"]), 1),
            "avg_pass_rate": round(float(r["avg_pass_rate"]), 2),
        }
        for idx, r in enumerate(rows)
    ]

    return _ok({"items": items, "sort_by": sort_by})


# ── GET / list ───────────────────────────────────────────────────────
@router.get("")
async def list_mentorships(
    request: Request,
    store_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    mentor_id: Optional[str] = Query(None),
    mentee_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """带教列表 — 分页 + 多条件筛选。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["tenant_id = :tid", "is_deleted = FALSE"]
    params: dict[str, Any] = {"tid": tenant_id}

    if store_id is not None:
        conditions.append("store_id = :store_id")
        params["store_id"] = store_id
    if status is not None:
        conditions.append("status = :status")
        params["status"] = status
    if mentor_id is not None:
        conditions.append("mentor_id = :mentor_id")
        params["mentor_id"] = mentor_id
    if mentee_id is not None:
        conditions.append("mentee_id = :mentee_id")
        params["mentee_id"] = mentee_id

    where = " AND ".join(conditions)

    count_sql = text(f"SELECT COUNT(*) FROM mentorship_relations WHERE {where}")
    total = (await db.execute(count_sql, params)).scalar() or 0

    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    data_sql = text(f"""
        SELECT {_SELECT_COLS}
        FROM mentorship_relations
        WHERE {where}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """)
    rows = (await db.execute(data_sql, params)).mappings().all()

    items = [_row_to_dict(r) for r in rows]

    return _ok({"items": items, "total": total, "page": page, "size": size})


# ── POST / create ────────────────────────────────────────────────────
@router.post("", status_code=201)
async def create_mentorship(
    body: CreateMentorshipReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """创建带教关系 — 校验自我带教 + 学员同时段唯一。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # Rule 1: cannot mentor yourself
    if body.mentor_id == body.mentee_id:
        raise HTTPException(status_code=400, detail="Mentor and mentee cannot be the same person")

    # Rule 2: mentee cannot have 2 active mentorships at the same time
    active_sql = text("""
        SELECT id FROM mentorship_relations
        WHERE tenant_id = :tid
          AND mentee_id = :mentee_id
          AND status = 'active'
          AND is_deleted = FALSE
    """)
    active = (
        await db.execute(
            active_sql,
            {
                "tid": tenant_id,
                "mentee_id": body.mentee_id,
            },
        )
    ).first()
    if active:
        raise HTTPException(
            status_code=409,
            detail="Mentee already has an active mentorship relation",
        )

    new_id = str(uuid4())
    now = datetime.now(timezone.utc)

    sql = text("""
        INSERT INTO mentorship_relations
            (id, tenant_id, mentor_id, mentee_id, store_id,
             start_date, end_date, status, mentor_score, mentee_pass_rate,
             notes, is_deleted, created_at, updated_at)
        VALUES
            (:id, :tid, :mentor_id, :mentee_id, :store_id,
             :start_date, NULL, 'active', NULL, NULL,
             :notes, FALSE, :now, :now)
        RETURNING id::text AS mentorship_id
    """)
    result = (
        (
            await db.execute(
                sql,
                {
                    "id": new_id,
                    "tid": tenant_id,
                    "mentor_id": body.mentor_id,
                    "mentee_id": body.mentee_id,
                    "store_id": body.store_id,
                    "start_date": body.start_date,
                    "notes": body.notes,
                    "now": now,
                },
            )
        )
        .mappings()
        .first()
    )

    await db.commit()

    log.info(
        "mentorship.created",
        mentorship_id=new_id,
        tenant_id=tenant_id,
        mentor_id=body.mentor_id,
        mentee_id=body.mentee_id,
    )

    return _ok({"mentorship_id": str(result["mentorship_id"])})


# ── GET /{mentorship_id} ──────────────────────────────────────────────
@router.get("/{mentorship_id}")
async def get_mentorship(
    mentorship_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """带教详情 — 返回单条记录或 404。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text(f"""
        SELECT {_SELECT_COLS}
        FROM mentorship_relations
        WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE
    """)
    row = (await db.execute(sql, {"id": mentorship_id, "tid": tenant_id})).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Mentorship not found")

    return _ok(_row_to_dict(row))


# ── PUT /{mentorship_id} ──────────────────────────────────────────────
@router.put("/{mentorship_id}")
async def update_mentorship(
    mentorship_id: str,
    body: UpdateMentorshipReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """更新带教 — 动态 SET 子句，仅更新传入字段。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    now = datetime.now(timezone.utc)
    fields["updated_at"] = now

    set_clauses = [f"{k} = :{k}" for k in fields]
    set_sql = ", ".join(set_clauses)

    sql = text(f"""
        UPDATE mentorship_relations
        SET {set_sql}
        WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE
        RETURNING id::text AS mentorship_id
    """)
    params = {**fields, "id": mentorship_id, "tid": tenant_id}
    result = (await db.execute(sql, params)).mappings().first()

    if not result:
        raise HTTPException(status_code=404, detail="Mentorship not found")

    await db.commit()

    log.info("mentorship.updated", mentorship_id=mentorship_id, tenant_id=tenant_id, updated_fields=list(fields.keys()))

    return _ok({"mentorship_id": mentorship_id})


# ── PUT /{mentorship_id}/complete ─────────────────────────────────────
@router.put("/{mentorship_id}/complete")
async def complete_mentorship(
    mentorship_id: str,
    body: CompleteMentorshipReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """完成带教 — 设 status=completed, end_date, mentor_score, mentee_pass_rate。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)
    today = date.today()

    sql = text("""
        UPDATE mentorship_relations
        SET status = 'completed',
            end_date = :end_date,
            mentor_score = :mentor_score,
            mentee_pass_rate = :mentee_pass_rate,
            notes = COALESCE(:notes, notes),
            updated_at = :now
        WHERE id = :id AND tenant_id = :tid AND status = 'active' AND is_deleted = FALSE
        RETURNING id::text AS mentorship_id
    """)
    result = (
        (
            await db.execute(
                sql,
                {
                    "id": mentorship_id,
                    "tid": tenant_id,
                    "end_date": today,
                    "mentor_score": body.mentor_score,
                    "mentee_pass_rate": body.mentee_pass_rate,
                    "notes": body.notes,
                    "now": now,
                },
            )
        )
        .mappings()
        .first()
    )

    if not result:
        raise HTTPException(status_code=404, detail="Active mentorship not found")

    await db.commit()

    log.info(
        "mentorship.completed",
        mentorship_id=mentorship_id,
        tenant_id=tenant_id,
        mentor_score=body.mentor_score,
        mentee_pass_rate=body.mentee_pass_rate,
    )

    return _ok({"mentorship_id": mentorship_id})


# ── PUT /{mentorship_id}/terminate ────────────────────────────────────
@router.put("/{mentorship_id}/terminate")
async def terminate_mentorship(
    mentorship_id: str,
    body: TerminateMentorshipReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """终止带教 — 设 status=terminated, end_date, 记录终止原因。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)
    today = date.today()

    sql = text("""
        UPDATE mentorship_relations
        SET status = 'terminated',
            end_date = :end_date,
            notes = :notes,
            updated_at = :now
        WHERE id = :id AND tenant_id = :tid AND status = 'active' AND is_deleted = FALSE
        RETURNING id::text AS mentorship_id
    """)
    result = (
        (
            await db.execute(
                sql,
                {
                    "id": mentorship_id,
                    "tid": tenant_id,
                    "end_date": today,
                    "notes": body.notes,
                    "now": now,
                },
            )
        )
        .mappings()
        .first()
    )

    if not result:
        raise HTTPException(status_code=404, detail="Active mentorship not found")

    await db.commit()

    log.info("mentorship.terminated", mentorship_id=mentorship_id, tenant_id=tenant_id)

    return _ok({"mentorship_id": mentorship_id})


# ── DELETE /{mentorship_id} (soft) ────────────────────────────────────
@router.delete("/{mentorship_id}")
async def delete_mentorship(
    mentorship_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """软删除 — 仅 active 状态可删除。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)
    sql = text("""
        UPDATE mentorship_relations
        SET is_deleted = TRUE, updated_at = :now
        WHERE id = :id AND tenant_id = :tid AND status = 'active' AND is_deleted = FALSE
        RETURNING id::text AS mentorship_id
    """)
    result = (await db.execute(sql, {"id": mentorship_id, "tid": tenant_id, "now": now})).mappings().first()

    if not result:
        raise HTTPException(status_code=404, detail="Active mentorship not found or already deleted")

    await db.commit()

    log.info("mentorship.deleted", mentorship_id=mentorship_id, tenant_id=tenant_id)

    return _ok({"mentorship_id": mentorship_id})
