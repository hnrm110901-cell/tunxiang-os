from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/civic/submissions", tags=["civic-submissions"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class BatchSubmitRequest(BaseModel):
    store_id: str
    domain: str
    record_ids: List[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_submissions(
    store_id: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """上报日志"""
    await _set_tenant(db, x_tenant_id)
    try:
        conditions = ["tenant_id = :tid"]
        params: Dict[str, Any] = {"tid": x_tenant_id}

        if store_id:
            conditions.append("store_id = :sid")
            params["sid"] = store_id
        if domain:
            conditions.append("domain = :domain")
            params["domain"] = domain
        if status:
            conditions.append("status = :status")
            params["status"] = status

        where = " AND ".join(conditions)
        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM civic_submissions WHERE {where}"), params
        )
        total = count_result.scalar() or 0

        rows = await db.execute(
            text(
                f"SELECT * FROM civic_submissions WHERE {where} "
                f"ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        items = [dict(r._mapping) for r in rows]
        log.info("submissions_listed", total=total)
        return {"ok": True, "data": {"items": items, "total": total}}
    except SQLAlchemyError as exc:
        log.error("submissions_list_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{submission_id}/retry")
async def retry_submission(
    submission_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """重试失败的上报"""
    await _set_tenant(db, x_tenant_id)
    try:
        # Verify the submission exists and is in failed state
        check = await db.execute(
            text(
                "SELECT id, status, retry_count FROM civic_submissions "
                "WHERE id = :id AND tenant_id = :tid"
            ),
            {"id": submission_id, "tid": x_tenant_id},
        )
        row = check.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Submission {submission_id} not found")
        if row.status not in ("failed", "error"):
            raise HTTPException(
                status_code=400,
                detail=f"Submission is in '{row.status}' state, only failed submissions can be retried",
            )

        new_retry = (row.retry_count or 0) + 1
        await db.execute(
            text(
                "UPDATE civic_submissions SET "
                "status = 'pending', retry_count = :cnt, updated_at = NOW() "
                "WHERE id = :id AND tenant_id = :tid"
            ),
            {"id": submission_id, "tid": x_tenant_id, "cnt": new_retry},
        )
        await db.commit()
        log.info("submission_retry", submission_id=submission_id, retry_count=new_retry)
        return {"ok": True, "data": {"id": submission_id, "status": "pending", "retry_count": new_retry}}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("submission_retry_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stats")
async def get_submission_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """上报统计"""
    await _set_tenant(db, x_tenant_id)
    try:
        rows = await db.execute(
            text("""
                SELECT
                    domain,
                    status,
                    COUNT(*) AS count
                FROM civic_submissions
                WHERE tenant_id = :tid
                GROUP BY domain, status
                ORDER BY domain, status
            """),
            {"tid": x_tenant_id},
        )
        raw = [dict(r._mapping) for r in rows]

        # Aggregate by domain
        by_domain: Dict[str, Dict[str, int]] = {}
        total_all = 0
        for item in raw:
            d = item["domain"]
            s = item["status"]
            c = item["count"]
            if d not in by_domain:
                by_domain[d] = {}
            by_domain[d][s] = c
            total_all += c

        # Recent 24h success rate
        recent = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'success') AS success
                FROM civic_submissions
                WHERE tenant_id = :tid
                    AND created_at >= NOW() - INTERVAL '24 hours'
            """),
            {"tid": x_tenant_id},
        )
        recent_row = recent.fetchone()
        recent_total = recent_row.total if recent_row else 0
        recent_success = recent_row.success if recent_row else 0
        success_rate = round(
            (recent_success / recent_total * 100) if recent_total > 0 else 0, 2
        )

        log.info("submission_stats", total=total_all)
        return {
            "ok": True,
            "data": {
                "total": total_all,
                "by_domain": by_domain,
                "recent_24h": {
                    "total": recent_total,
                    "success": recent_success,
                    "success_rate_pct": success_rate,
                },
            },
        }
    except SQLAlchemyError as exc:
        log.error("submission_stats_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/batch")
async def batch_submit(
    body: BatchSubmitRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """批量上报"""
    await _set_tenant(db, x_tenant_id)
    try:
        submission_ids = []
        for record_id in body.record_ids:
            sid = str(uuid4())
            await db.execute(
                text("""
                    INSERT INTO civic_submissions (
                        id, tenant_id, store_id, domain, record_id,
                        record_count, status, created_at
                    ) VALUES (
                        :id, :tid, :sid, :domain, :rid,
                        1, 'pending', NOW()
                    )
                """),
                {
                    "id": sid,
                    "tid": x_tenant_id,
                    "sid": body.store_id,
                    "domain": body.domain,
                    "rid": record_id,
                },
            )
            submission_ids.append(sid)

        await db.commit()
        log.info(
            "batch_submit_created",
            store_id=body.store_id,
            domain=body.domain,
            count=len(submission_ids),
        )
        return {
            "ok": True,
            "data": {
                "submission_ids": submission_ids,
                "count": len(submission_ids),
                "status": "pending",
            },
        }
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("batch_submit_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{submission_id}/detail")
async def get_submission_detail(
    submission_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """上报详情"""
    await _set_tenant(db, x_tenant_id)
    try:
        row = await db.execute(
            text(
                "SELECT * FROM civic_submissions "
                "WHERE id = :id AND tenant_id = :tid"
            ),
            {"id": submission_id, "tid": x_tenant_id},
        )
        result = row.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail=f"Submission {submission_id} not found")

        log.info("submission_detail_fetched", submission_id=submission_id)
        return {"ok": True, "data": dict(result._mapping)}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("submission_detail_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")
