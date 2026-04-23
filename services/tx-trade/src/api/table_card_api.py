"""
TunxiangOS Smart Table Card - API Router
Module: services/tx-trade/src/api/table_card_api.py

FastAPI router for smart table card endpoints.
Provides real DB queries against the `tables` and `orders` tables (v002).
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/tables", tags=["table-card"])

# ============================================================================
# Valid status values
# ============================================================================

VALID_STATUSES = {"free", "occupied", "reserved", "dirty", "pending_checkout"}

# ============================================================================
# Request / Response Models
# ============================================================================


class TableCardFieldResponse(BaseModel):
    """Resolved field for table card."""

    key: str
    label: str
    value: Any
    priority: int = Field(ge=0, le=100)
    alert: str  # normal, warning, critical
    render_hint: Optional[str] = None


class TableCardResponse(BaseModel):
    """Resolved table card response."""

    table_id: str
    table_no: str
    area: Optional[str] = None
    seats: int
    status: str
    guest_count: int = 0
    card_fields: List[TableCardFieldResponse]
    updated_at: Optional[str] = None


class TablesListResponse(BaseModel):
    """Response for list tables endpoint."""

    ok: bool = True
    data: Dict[str, Any]


class StatisticsResponse(BaseModel):
    """Table statistics response."""

    ok: bool = True
    data: Dict[str, Any]


class FieldRankingResponse(BaseModel):
    """Field ranking information."""

    field_key: str
    score: float = Field(ge=0, le=100)
    click_count: int
    last_clicked_at: Optional[str] = None


class UpdateStatusRequest(BaseModel):
    """Request body for status update."""

    status: str = Field(description="New status: free/occupied/reserved/dirty/pending_checkout")


# ============================================================================
# Helper: build summary from status counts
# ============================================================================


def _build_summary(rows) -> Dict[str, int]:
    summary: Dict[str, int] = dict.fromkeys(VALID_STATUSES, 0)
    for row in rows:
        status = row["status"]
        if status in summary:
            summary[status] += row["cnt"]
    return summary


def _detect_meal_period() -> str:
    hour = datetime.utcnow().hour + 8  # CST approximation
    hour = hour % 24
    if 6 <= hour < 11:
        return "breakfast"
    elif 11 <= hour < 14:
        return "lunch"
    elif 17 <= hour < 21:
        return "dinner"
    elif hour >= 21 or hour < 2:
        return "late_night"
    else:
        return "off_peak"


# ============================================================================
# GET /statistics  — must be registered BEFORE /{table_id}
# ============================================================================


@router.get(
    "/statistics",
    response_model=StatisticsResponse,
    summary="Get table statistics",
    description="Get aggregate statistics for tables in a store",
)
async def get_statistics(
    store_id: str = Query(..., description="Store ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID", description="Tenant ID"),
):
    """Aggregate table counts by status."""
    sql = text("""
        SELECT status, COUNT(*) AS cnt
        FROM tables
        WHERE store_id = :sid::uuid
          AND tenant_id = :tid::uuid
          AND is_deleted = FALSE
        GROUP BY status
    """)
    try:
        async for db in get_db_with_tenant(x_tenant_id):
            result = await db.execute(sql, {"sid": store_id, "tid": x_tenant_id})
            rows = [dict(r._mapping) for r in result.fetchall()]

        summary = _build_summary(rows)
        total_tables = sum(summary.values())
        occupied = summary.get("occupied", 0)
        free = summary.get("free", 0)

        return StatisticsResponse(
            ok=True,
            data={
                "free_count": free,
                "occupied_count": occupied,
                "reserved_count": summary.get("reserved", 0),
                "dirty_count": summary.get("dirty", 0),
                "pending_checkout_count": summary.get("pending_checkout", 0),
                "total_tables": total_tables,
                "total_occupied": occupied,
                "total_available": free,
                "summary": summary,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except SQLAlchemyError:
        logger.error("get_statistics_db_error", store_id=store_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Database error fetching statistics")


# ============================================================================
# GET /field-rankings
# ============================================================================


@router.get(
    "/field-rankings",
    summary="Get learned field rankings",
    description="Get field importance rankings based on staff click patterns",
)
async def get_field_rankings(
    store_id: str = Query(..., description="Store ID"),
    meal_period: Optional[str] = Query(None, description="Meal period filter"),
    limit: int = Query(10, le=50),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID", description="Tenant ID"),
):
    """
    Return field importance rankings.
    No field_ranking table yet — returns empty list.
    """
    return {"ok": True, "data": []}


# ============================================================================
# GET /  — list tables
# ============================================================================


@router.get(
    "/",
    summary="Get tables with smart card context",
    description="Fetch list of tables with optional area/status filters",
)
async def list_tables(
    store_id: str = Query(..., description="Store ID"),
    area: Optional[str] = Query(None, description="Filter by area"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID", description="Tenant ID"),
):
    """
    List tables with guest_count joined from active orders.
    """
    # Build dynamic WHERE clauses
    filters = [
        "t.store_id = :sid::uuid",
        "t.tenant_id = :tid::uuid",
        "t.is_deleted = FALSE",
    ]
    params: Dict[str, Any] = {"sid": store_id, "tid": x_tenant_id}

    if area:
        filters.append("t.area = :area")
        params["area"] = area
    if status:
        filters.append("t.status = :status")
        params["status"] = status

    where_clause = " AND ".join(filters)

    sql = text(f"""
        SELECT t.id::text AS table_id,
               t.table_no,
               t.area,
               t.seats,
               t.status,
               COALESCE(o.guest_count, 0) AS guest_count,
               t.updated_at
        FROM tables t
        LEFT JOIN LATERAL (
            SELECT guest_count FROM orders
            WHERE store_id = t.store_id
              AND table_number = t.table_no
              AND status = 'active'
            ORDER BY created_at DESC LIMIT 1
        ) o ON TRUE
        WHERE {where_clause}
        ORDER BY t.table_no
        LIMIT :lim OFFSET :off
    """)

    count_sql = text(f"""
        SELECT COUNT(*) FROM tables t
        WHERE {where_clause}
    """)

    stat_sql = text("""
        SELECT status, COUNT(*) AS cnt
        FROM tables
        WHERE store_id = :sid::uuid
          AND tenant_id = :tid::uuid
          AND is_deleted = FALSE
        GROUP BY status
    """)

    params_page = {**params, "lim": limit, "off": offset}

    try:
        async for db in get_db_with_tenant(x_tenant_id):
            rows_result = await db.execute(sql, params_page)
            rows = [dict(r._mapping) for r in rows_result.fetchall()]

            count_result = await db.execute(count_sql, params)
            total_count = count_result.scalar() or 0

            stat_result = await db.execute(stat_sql, {"sid": store_id, "tid": x_tenant_id})
            stat_rows = [dict(r._mapping) for r in stat_result.fetchall()]

        summary = _build_summary(stat_rows)
        meal_period = _detect_meal_period()

        tables = [
            {
                "table_id": r["table_id"],
                "table_no": r["table_no"],
                "area": r["area"],
                "seats": r["seats"],
                "status": r["status"],
                "guest_count": r["guest_count"],
                "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
                "card_fields": [],
            }
            for r in rows
        ]

        return {
            "ok": True,
            "data": {
                "tables": tables,
                "total_count": total_count,
                "summary": summary,
                "meal_period": meal_period,
            },
        }
    except SQLAlchemyError:
        logger.error("list_tables_db_error", store_id=store_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Database error listing tables")


# ============================================================================
# GET /{table_id}  — single table detail
# ============================================================================


@router.get(
    "/{table_id}",
    summary="Get single table detail",
    description="Fetch detailed information for a specific table",
)
async def get_table_detail(
    table_id: str,
    store_id: str = Query(..., description="Store ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID", description="Tenant ID"),
):
    """Return a single table with its current guest count."""
    sql = text("""
        SELECT t.id::text AS table_id,
               t.table_no,
               t.area,
               t.seats,
               t.status,
               COALESCE(o.guest_count, 0) AS guest_count,
               t.updated_at
        FROM tables t
        LEFT JOIN LATERAL (
            SELECT guest_count FROM orders
            WHERE store_id = t.store_id
              AND table_number = t.table_no
              AND status = 'active'
            ORDER BY created_at DESC LIMIT 1
        ) o ON TRUE
        WHERE t.id = :table_id::uuid
          AND t.store_id = :sid::uuid
          AND t.tenant_id = :tid::uuid
          AND t.is_deleted = FALSE
    """)
    try:
        async for db in get_db_with_tenant(x_tenant_id):
            result = await db.execute(sql, {"table_id": table_id, "sid": store_id, "tid": x_tenant_id})
            row = result.fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="Table not found")

        r = dict(row._mapping)
        return {
            "ok": True,
            "data": {
                "table_id": r["table_id"],
                "table_no": r["table_no"],
                "area": r["area"],
                "seats": r["seats"],
                "status": r["status"],
                "guest_count": r["guest_count"],
                "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
                "card_fields": [],
            },
        }
    except HTTPException:
        raise
    except SQLAlchemyError:
        logger.error("get_table_detail_db_error", table_id=table_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Database error fetching table detail")


# ============================================================================
# POST /{table_id}/click  — record field click
# ============================================================================


@router.post(
    "/{table_id}/click",
    status_code=201,
    summary="Record field click",
    description="Record when user clicks on a field (for future learning)",
)
async def record_click(
    table_id: str,
    store_id: str = Query(..., description="Store ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID", description="Tenant ID"),
):
    """Log a field click event. Learning engine integration is deferred."""
    logger.info(
        "field_click_recorded",
        table_id=table_id,
        store_id=store_id,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": {"recorded": True}}


# ============================================================================
# PUT /{table_id}/status  — update table status
# ============================================================================


@router.put(
    "/{table_id}/status",
    summary="Update table status",
    description="Update table status (free/occupied/reserved/dirty/pending_checkout)",
)
async def update_table_status(
    table_id: str,
    body: UpdateStatusRequest,
    store_id: str = Query(..., description="Store ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID", description="Tenant ID"),
):
    """Update table status with validation."""
    if body.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{body.status}'. Must be one of: {sorted(VALID_STATUSES)}",
        )

    sql = text("""
        UPDATE tables
        SET status = :status, updated_at = NOW()
        WHERE id = :table_id::uuid
          AND store_id = :sid::uuid
          AND tenant_id = :tid::uuid
          AND is_deleted = FALSE
        RETURNING id::text AS table_id, table_no, status, updated_at
    """)

    try:
        async for db in get_db_with_tenant(x_tenant_id):
            result = await db.execute(
                sql,
                {
                    "status": body.status,
                    "table_id": table_id,
                    "sid": store_id,
                    "tid": x_tenant_id,
                },
            )
            row = result.fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="Table not found")

        r = dict(row._mapping)
        return {
            "ok": True,
            "data": {
                "table_id": r["table_id"],
                "table_no": r["table_no"],
                "status": r["status"],
                "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
            },
        }
    except HTTPException:
        raise
    except SQLAlchemyError:
        logger.error("update_table_status_db_error", table_id=table_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Database error updating table status")
