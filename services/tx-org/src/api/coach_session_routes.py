"""Coach Sessions — 店长教练Agent API"""

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/coach-sessions", tags=["coach-sessions"])


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
            if k in ("suggestions", "actions_taken", "focus_employees"):
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
    id::text, tenant_id::text, store_id::text, manager_id::text,
    session_date, session_type, suggestions, actions_taken, focus_employees,
    readiness_before, readiness_after, notes,
    is_deleted, created_at, updated_at
"""

_VALID_SESSION_TYPES = {"daily", "weekly", "monthly", "incident"}
_VALID_CATEGORIES = {"staffing", "training", "scheduling", "performance", "retention"}
_VALID_PRIORITIES = {"high", "medium", "low"}


# -- request models ---------------------------------------------------------
class SuggestionItem(BaseModel):
    category: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    priority: str = Field(default="medium")
    accepted: bool = Field(default=False)


class FocusEmployeeItem(BaseModel):
    employee_id: str = Field(..., min_length=1)
    reason: Optional[str] = None
    action: Optional[str] = None


class CoachSessionCreateReq(BaseModel):
    store_id: str = Field(..., min_length=1)
    manager_id: str = Field(..., min_length=1)
    session_date: Optional[date] = None
    session_type: str = Field(default="daily", max_length=30)
    suggestions: Optional[List[dict]] = None
    focus_employees: Optional[List[dict]] = None
    readiness_before: Optional[float] = Field(None, ge=0, le=100)
    readiness_after: Optional[float] = Field(None, ge=0, le=100)
    notes: Optional[str] = None


class CoachSessionUpdateReq(BaseModel):
    notes: Optional[str] = None
    readiness_before: Optional[float] = Field(None, ge=0, le=100)
    readiness_after: Optional[float] = Field(None, ge=0, le=100)


class ActionAppendReq(BaseModel):
    action: str = Field(..., min_length=1)
    result: Optional[str] = None


class ActionCompleteReq(BaseModel):
    result: str = Field(..., min_length=1)


# -- 1. GET / -- 教练记录列表（分页+筛选）--------------------------------------
@router.get("")
async def list_coach_sessions(
    request: Request,
    store_id: Optional[str] = Query(None),
    manager_id: Optional[str] = Query(None),
    session_type: Optional[str] = Query(None),
    session_date: Optional[date] = Query(None),
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
    if manager_id:
        conditions.append("manager_id = :manager_id")
        params["manager_id"] = manager_id
    if session_type:
        conditions.append("session_type = :session_type")
        params["session_type"] = session_type
    if session_date:
        conditions.append("session_date = :session_date")
        params["session_date"] = session_date

    where = " AND ".join(conditions)

    cnt_row = (
        (
            await db.execute(
                text(f"SELECT COUNT(*)::int AS total FROM coach_sessions WHERE {where}"),
                params,
            )
        )
        .mappings()
        .first()
    )
    total = cnt_row["total"] if cnt_row else 0

    offset = (page - 1) * size
    params["lim"] = size
    params["off"] = offset

    rows = (
        (
            await db.execute(
                text(f"""
            SELECT {_FIELDS}
            FROM coach_sessions
            WHERE {where}
            ORDER BY session_date DESC, created_at DESC
            LIMIT :lim OFFSET :off
        """),
                params,
            )
        )
        .mappings()
        .all()
    )

    items = [_row_to_dict(r) for r in rows]
    return _ok({"items": items, "total": total, "page": page, "size": size})


# -- 2. POST / -- 创建教练会话 ------------------------------------------------
@router.post("", status_code=201)
async def create_coach_session(
    body: CoachSessionCreateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    if body.session_type not in _VALID_SESSION_TYPES:
        raise HTTPException(status_code=400, detail=f"session_type must be one of {_VALID_SESSION_TYPES}")

    s_date = body.session_date or date.today()
    now = datetime.now(timezone.utc)
    rec_id = str(uuid4())

    suggestions = body.suggestions or []
    focus_employees = body.focus_employees or []

    sql = text("""
        INSERT INTO coach_sessions
            (id, tenant_id, store_id, manager_id, session_date, session_type,
             suggestions, actions_taken, focus_employees,
             readiness_before, readiness_after, notes,
             is_deleted, created_at, updated_at)
        VALUES
            (:id, :tid, :store_id, :manager_id, :session_date, :session_type,
             :suggestions::jsonb, '[]'::jsonb, :focus_employees::jsonb,
             :readiness_before, :readiness_after, :notes,
             FALSE, :now, :now)
        RETURNING id::text
    """)
    result = (
        (
            await db.execute(
                sql,
                {
                    "id": rec_id,
                    "tid": tenant_id,
                    "store_id": body.store_id,
                    "manager_id": body.manager_id,
                    "session_date": s_date,
                    "session_type": body.session_type,
                    "suggestions": json.dumps(suggestions),
                    "focus_employees": json.dumps(focus_employees),
                    "readiness_before": body.readiness_before,
                    "readiness_after": body.readiness_after,
                    "notes": body.notes,
                    "now": now,
                },
            )
        )
        .mappings()
        .first()
    )

    await db.commit()

    log.info("coach_session.created", session_id=rec_id, manager_id=body.manager_id, tenant_id=tenant_id)

    return _ok({"id": result["id"] if result else rec_id})


# -- 3. GET /dashboard -- 教练总览 --------------------------------------------
@router.get("/dashboard")
async def coach_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # This week / this month counts
    counts_sql = text("""
        SELECT
            COUNT(*) FILTER (WHERE session_date >= date_trunc('week', CURRENT_DATE))::int AS this_week_count,
            COUNT(*) FILTER (WHERE session_date >= date_trunc('month', CURRENT_DATE))::int AS this_month_count
        FROM coach_sessions
        WHERE tenant_id = :tid AND is_deleted = FALSE
    """)
    counts = (await db.execute(counts_sql, {"tid": tenant_id})).mappings().first()

    # Acceptance rate (accepted / total suggestions)
    accept_sql = text("""
        SELECT
            COALESCE(SUM(jsonb_array_length(suggestions)), 0)::int AS total_suggestions,
            COALESCE(SUM((
                SELECT COUNT(*) FROM jsonb_array_elements(suggestions) s
                WHERE (s->>'accepted')::boolean = true
            )), 0)::int AS accepted_suggestions
        FROM coach_sessions
        WHERE tenant_id = :tid AND is_deleted = FALSE
          AND suggestions IS NOT NULL AND jsonb_array_length(suggestions) > 0
    """)
    accept = (await db.execute(accept_sql, {"tid": tenant_id})).mappings().first()

    total_sug = accept["total_suggestions"] if accept else 0
    accepted_sug = accept["accepted_suggestions"] if accept else 0
    acceptance_rate = round(accepted_sug / total_sug * 100, 2) if total_sug > 0 else 0

    # Average readiness lift
    lift_sql = text("""
        SELECT COALESCE(ROUND(AVG(readiness_after - readiness_before), 2), 0) AS avg_readiness_lift
        FROM coach_sessions
        WHERE tenant_id = :tid AND is_deleted = FALSE
          AND readiness_before IS NOT NULL AND readiness_after IS NOT NULL
    """)
    lift = (await db.execute(lift_sql, {"tid": tenant_id})).mappings().first()

    # By session type distribution
    type_sql = text("""
        SELECT session_type, COUNT(*)::int AS count
        FROM coach_sessions
        WHERE tenant_id = :tid AND is_deleted = FALSE
        GROUP BY session_type
        ORDER BY count DESC
    """)
    type_rows = (await db.execute(type_sql, {"tid": tenant_id})).mappings().all()
    by_session_type = {r["session_type"]: r["count"] for r in type_rows}

    # Top 5 active managers
    top_sql = text("""
        SELECT manager_id::text, COUNT(*)::int AS session_count
        FROM coach_sessions
        WHERE tenant_id = :tid AND is_deleted = FALSE
        GROUP BY manager_id
        ORDER BY session_count DESC
        LIMIT 5
    """)
    top_rows = (await db.execute(top_sql, {"tid": tenant_id})).mappings().all()
    top_managers = [{"manager_id": r["manager_id"], "session_count": r["session_count"]} for r in top_rows]

    return _ok(
        {
            "this_week_count": counts["this_week_count"] if counts else 0,
            "this_month_count": counts["this_month_count"] if counts else 0,
            "acceptance_rate": acceptance_rate,
            "avg_readiness_lift": float(lift["avg_readiness_lift"]) if lift else 0,
            "by_session_type": by_session_type,
            "top_managers": top_managers,
        }
    )


# -- 4. GET /manager-summary -- 店长教练汇总 -----------------------------------
@router.get("/manager-summary")
async def manager_summary(
    request: Request,
    manager_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # Total sessions + avg readiness lift
    stats_sql = text("""
        SELECT
            COUNT(*)::int AS total_sessions,
            COALESCE(ROUND(AVG(readiness_after - readiness_before), 2), 0) AS avg_readiness_lift
        FROM coach_sessions
        WHERE tenant_id = :tid AND manager_id = :mid AND is_deleted = FALSE
          AND readiness_before IS NOT NULL AND readiness_after IS NOT NULL
    """)
    stats = (await db.execute(stats_sql, {"tid": tenant_id, "mid": manager_id})).mappings().first()

    # Total session count (including those without readiness)
    total_sql = text("""
        SELECT COUNT(*)::int AS total_sessions
        FROM coach_sessions
        WHERE tenant_id = :tid AND manager_id = :mid AND is_deleted = FALSE
    """)
    total_row = (await db.execute(total_sql, {"tid": tenant_id, "mid": manager_id})).mappings().first()

    # Acceptance rate for this manager
    accept_sql = text("""
        SELECT
            COALESCE(SUM(jsonb_array_length(suggestions)), 0)::int AS total_suggestions,
            COALESCE(SUM((
                SELECT COUNT(*) FROM jsonb_array_elements(suggestions) s
                WHERE (s->>'accepted')::boolean = true
            )), 0)::int AS accepted_suggestions
        FROM coach_sessions
        WHERE tenant_id = :tid AND manager_id = :mid AND is_deleted = FALSE
          AND suggestions IS NOT NULL AND jsonb_array_length(suggestions) > 0
    """)
    accept = (await db.execute(accept_sql, {"tid": tenant_id, "mid": manager_id})).mappings().first()

    total_sug = accept["total_suggestions"] if accept else 0
    accepted_sug = accept["accepted_suggestions"] if accept else 0
    acceptance_rate = round(accepted_sug / total_sug * 100, 2) if total_sug > 0 else 0

    # Recent 5 sessions
    recent_sql = text(f"""
        SELECT {_FIELDS}
        FROM coach_sessions
        WHERE tenant_id = :tid AND manager_id = :mid AND is_deleted = FALSE
        ORDER BY session_date DESC, created_at DESC
        LIMIT 5
    """)
    recent_rows = (await db.execute(recent_sql, {"tid": tenant_id, "mid": manager_id})).mappings().all()
    recent_sessions = [_row_to_dict(r) for r in recent_rows]

    return _ok(
        {
            "manager_id": manager_id,
            "total_sessions": total_row["total_sessions"] if total_row else 0,
            "acceptance_rate": acceptance_rate,
            "avg_readiness_lift": float(stats["avg_readiness_lift"]) if stats else 0,
            "recent_sessions": recent_sessions,
        }
    )


# -- 5. GET /effectiveness -- 教练有效性分析 ------------------------------------
@router.get("/effectiveness")
async def coach_effectiveness(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        SELECT
            session_type,
            COUNT(*)::int AS session_count,
            COALESCE(ROUND(AVG(readiness_after - readiness_before), 2), 0) AS avg_lift
        FROM coach_sessions
        WHERE tenant_id = :tid AND is_deleted = FALSE
          AND readiness_before IS NOT NULL AND readiness_after IS NOT NULL
        GROUP BY session_type
        ORDER BY avg_lift DESC
    """)
    rows = (await db.execute(sql, {"tid": tenant_id})).mappings().all()

    by_type = [
        {
            "session_type": r["session_type"],
            "session_count": r["session_count"],
            "avg_readiness_lift": float(r["avg_lift"]),
        }
        for r in rows
    ]

    # Overall average
    overall_sql = text("""
        SELECT COALESCE(ROUND(AVG(readiness_after - readiness_before), 2), 0) AS avg_lift
        FROM coach_sessions
        WHERE tenant_id = :tid AND is_deleted = FALSE
          AND readiness_before IS NOT NULL AND readiness_after IS NOT NULL
    """)
    overall = (await db.execute(overall_sql, {"tid": tenant_id})).mappings().first()

    return _ok(
        {
            "overall_avg_lift": float(overall["avg_lift"]) if overall else 0,
            "by_session_type": by_type,
        }
    )


# -- 6. GET /{session_id} -- 会话详情 -----------------------------------------
@router.get("/{session_id}")
async def get_coach_session(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text(f"""
        SELECT {_FIELDS}
        FROM coach_sessions
        WHERE id = :sid AND tenant_id = :tid AND is_deleted = FALSE
    """)
    row = (await db.execute(sql, {"sid": session_id, "tid": tenant_id})).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Coach session not found")

    return _ok(_row_to_dict(row))


# -- 7. PUT /{session_id} -- 更新会话 -----------------------------------------
@router.put("/{session_id}")
async def update_coach_session(
    session_id: str,
    body: CoachSessionUpdateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)

    sets = ["updated_at = :now"]
    params: dict[str, Any] = {"sid": session_id, "tid": tenant_id, "now": now}

    if body.notes is not None:
        sets.append("notes = :notes")
        params["notes"] = body.notes
    if body.readiness_before is not None:
        sets.append("readiness_before = :readiness_before")
        params["readiness_before"] = body.readiness_before
    if body.readiness_after is not None:
        sets.append("readiness_after = :readiness_after")
        params["readiness_after"] = body.readiness_after

    set_clause = ", ".join(sets)

    result = await db.execute(
        text(f"""
            UPDATE coach_sessions
            SET {set_clause}
            WHERE id = :sid AND tenant_id = :tid AND is_deleted = FALSE
            RETURNING id::text
        """),
        params,
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Coach session not found")

    await db.commit()

    log.info("coach_session.updated", session_id=session_id, tenant_id=tenant_id)
    return _ok({"id": row["id"]})


# -- 8. PUT /{session_id}/accept/{sug_idx} -- 采纳建议 -------------------------
@router.put("/{session_id}/accept/{sug_idx}")
async def accept_suggestion(
    session_id: str,
    sug_idx: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)

    # Verify index is valid
    check_sql = text("""
        SELECT jsonb_array_length(suggestions) AS sug_len
        FROM coach_sessions
        WHERE id = :sid AND tenant_id = :tid AND is_deleted = FALSE
    """)
    check = (await db.execute(check_sql, {"sid": session_id, "tid": tenant_id})).mappings().first()
    if not check:
        raise HTTPException(status_code=404, detail="Coach session not found")
    if sug_idx < 0 or sug_idx >= check["sug_len"]:
        raise HTTPException(
            status_code=400, detail=f"Suggestion index {sug_idx} out of range (0-{check['sug_len'] - 1})"
        )

    # Use jsonb_set to update accepted flag
    sql = text("""
        UPDATE coach_sessions
        SET suggestions = jsonb_set(suggestions, :path, 'true'::jsonb),
            updated_at = :now
        WHERE id = :sid AND tenant_id = :tid AND is_deleted = FALSE
        RETURNING id::text, suggestions
    """)
    result = (
        (
            await db.execute(
                sql,
                {
                    "sid": session_id,
                    "tid": tenant_id,
                    "path": f"{{{sug_idx},accepted}}",
                    "now": now,
                },
            )
        )
        .mappings()
        .first()
    )

    if not result:
        raise HTTPException(status_code=404, detail="Coach session not found")

    await db.commit()

    log.info("coach_session.suggestion_accepted", session_id=session_id, sug_idx=sug_idx, tenant_id=tenant_id)

    suggestions = result["suggestions"]
    if isinstance(suggestions, str):
        try:
            suggestions = json.loads(suggestions)
        except (json.JSONDecodeError, TypeError):
            pass

    return _ok({"id": result["id"], "suggestions": suggestions})


# -- 9. POST /{session_id}/actions -- 追加行动记录 -----------------------------
@router.post("/{session_id}/actions", status_code=201)
async def append_action(
    session_id: str,
    body: ActionAppendReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)

    new_action = {
        "action": body.action,
        "result": body.result,
        "completed_at": None,
    }

    sql = text("""
        UPDATE coach_sessions
        SET actions_taken = COALESCE(actions_taken, '[]'::jsonb) || :new_action::jsonb,
            updated_at = :now
        WHERE id = :sid AND tenant_id = :tid AND is_deleted = FALSE
        RETURNING id::text, actions_taken
    """)
    result = (
        (
            await db.execute(
                sql,
                {
                    "sid": session_id,
                    "tid": tenant_id,
                    "new_action": json.dumps([new_action]),
                    "now": now,
                },
            )
        )
        .mappings()
        .first()
    )

    if not result:
        raise HTTPException(status_code=404, detail="Coach session not found")

    await db.commit()

    log.info("coach_session.action_appended", session_id=session_id, tenant_id=tenant_id)

    actions_taken = result["actions_taken"]
    if isinstance(actions_taken, str):
        try:
            actions_taken = json.loads(actions_taken)
        except (json.JSONDecodeError, TypeError):
            pass

    return _ok({"id": result["id"], "actions_taken": actions_taken})


# -- 10. PUT /{session_id}/actions/{act_idx}/complete -- 完成行动 ---------------
@router.put("/{session_id}/actions/{act_idx}/complete")
async def complete_action(
    session_id: str,
    act_idx: int,
    body: ActionCompleteReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)

    # Verify index is valid
    check_sql = text("""
        SELECT jsonb_array_length(actions_taken) AS act_len
        FROM coach_sessions
        WHERE id = :sid AND tenant_id = :tid AND is_deleted = FALSE
    """)
    check = (await db.execute(check_sql, {"sid": session_id, "tid": tenant_id})).mappings().first()
    if not check:
        raise HTTPException(status_code=404, detail="Coach session not found")
    if act_idx < 0 or act_idx >= check["act_len"]:
        raise HTTPException(status_code=400, detail=f"Action index {act_idx} out of range (0-{check['act_len'] - 1})")

    # Use jsonb_set to update result and completed_at
    sql = text("""
        UPDATE coach_sessions
        SET actions_taken = jsonb_set(
                jsonb_set(actions_taken, :result_path, :result_val::jsonb),
                :completed_path, :completed_val::jsonb
            ),
            updated_at = :now
        WHERE id = :sid AND tenant_id = :tid AND is_deleted = FALSE
        RETURNING id::text, actions_taken
    """)
    result = (
        (
            await db.execute(
                sql,
                {
                    "sid": session_id,
                    "tid": tenant_id,
                    "result_path": f"{{{act_idx},result}}",
                    "result_val": json.dumps(body.result),
                    "completed_path": f"{{{act_idx},completed_at}}",
                    "completed_val": json.dumps(now.isoformat()),
                    "now": now,
                },
            )
        )
        .mappings()
        .first()
    )

    if not result:
        raise HTTPException(status_code=404, detail="Coach session not found")

    await db.commit()

    log.info("coach_session.action_completed", session_id=session_id, act_idx=act_idx, tenant_id=tenant_id)

    actions_taken = result["actions_taken"]
    if isinstance(actions_taken, str):
        try:
            actions_taken = json.loads(actions_taken)
        except (json.JSONDecodeError, TypeError):
            pass

    return _ok({"id": result["id"], "actions_taken": actions_taken})


# -- 11. DELETE /{session_id} -- 软删除 ----------------------------------------
@router.delete("/{session_id}")
async def delete_coach_session(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)

    result = await db.execute(
        text("""
            UPDATE coach_sessions
            SET is_deleted = TRUE, updated_at = :now
            WHERE id = :sid AND tenant_id = :tid AND is_deleted = FALSE
            RETURNING id::text
        """),
        {"sid": session_id, "tid": tenant_id, "now": now},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Coach session not found")

    await db.commit()

    log.info("coach_session.deleted", session_id=session_id, tenant_id=tenant_id)
    return _ok({"id": row["id"], "deleted": True})
