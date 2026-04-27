from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/civic/fire", tags=["civic-fire"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class FireEquipmentCreate(BaseModel):
    store_id: str
    equipment_type: str
    equipment_name: str
    location_desc: Optional[str] = None
    serial_no: Optional[str] = None
    manufacturer: Optional[str] = None
    install_date: Optional[date] = None
    inspection_cycle_days: int = 30


class InspectionCreate(BaseModel):
    store_id: str
    inspector_id: str
    inspector_name: str
    inspection_type: str
    checklist_results: List[Dict[str, Any]] = Field(default_factory=list)
    issues_found: List[Dict[str, Any]] = Field(default_factory=list)
    overall_result: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/equipment")
async def create_equipment(
    body: FireEquipmentCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """消防设备登记"""
    await _set_tenant(db, x_tenant_id)
    equipment_id = str(uuid4())
    try:
        await db.execute(
            text("""
                INSERT INTO civic_fire_equipment (
                    id, tenant_id, store_id, equipment_type, equipment_name,
                    location_desc, serial_no, manufacturer, install_date,
                    inspection_cycle_days, last_inspection_date, next_inspection_date,
                    status, created_at
                ) VALUES (
                    :id, :tid, :sid, :etype, :ename,
                    :loc, :sno, :mfr, :idate,
                    :cycle, NULL,
                    CASE WHEN :idate IS NOT NULL
                        THEN :idate + :cycle * INTERVAL '1 day'
                        ELSE CURRENT_DATE + :cycle * INTERVAL '1 day'
                    END,
                    'active', NOW()
                )
            """),
            {
                "id": equipment_id,
                "tid": x_tenant_id,
                "sid": body.store_id,
                "etype": body.equipment_type,
                "ename": body.equipment_name,
                "loc": body.location_desc,
                "sno": body.serial_no,
                "mfr": body.manufacturer,
                "idate": body.install_date,
                "cycle": body.inspection_cycle_days,
            },
        )
        await db.commit()
        log.info("fire_equipment_created", equipment_id=equipment_id, store_id=body.store_id)
        return {"ok": True, "data": {"id": equipment_id}}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("fire_equipment_create_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/inspections")
async def create_inspection(
    body: InspectionCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """巡检记录"""
    await _set_tenant(db, x_tenant_id)
    inspection_id = str(uuid4())
    try:
        await db.execute(
            text("""
                INSERT INTO civic_fire_inspections (
                    id, tenant_id, store_id, inspector_id, inspector_name,
                    inspection_type, checklist_results, issues_found,
                    overall_result, created_at
                ) VALUES (
                    :id, :tid, :sid, :iid, :iname,
                    :itype, :checklist, :issues,
                    :result, NOW()
                )
            """),
            {
                "id": inspection_id,
                "tid": x_tenant_id,
                "sid": body.store_id,
                "iid": body.inspector_id,
                "iname": body.inspector_name,
                "itype": body.inspection_type,
                "checklist": body.checklist_results,
                "issues": body.issues_found,
                "result": body.overall_result,
            },
        )
        await db.commit()
        log.info("fire_inspection_created", inspection_id=inspection_id, store_id=body.store_id)
        return {"ok": True, "data": {"id": inspection_id}}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("fire_inspection_create_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/inspections")
async def list_inspections(
    store_id: str = Query(...),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """巡检历史"""
    await _set_tenant(db, x_tenant_id)
    try:
        offset = (page - 1) * size

        count_result = await db.execute(
            text("SELECT COUNT(*) FROM civic_fire_inspections WHERE tenant_id = :tid AND store_id = :sid"),
            {"tid": x_tenant_id, "sid": store_id},
        )
        total = count_result.scalar() or 0

        rows = await db.execute(
            text(
                "SELECT * FROM civic_fire_inspections "
                "WHERE tenant_id = :tid AND store_id = :sid "
                "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            {"tid": x_tenant_id, "sid": store_id, "limit": size, "offset": offset},
        )
        items = [dict(r._mapping) for r in rows]
        log.info("fire_inspections_listed", store_id=store_id, total=total)
        return {"ok": True, "data": {"items": items, "total": total}}
    except SQLAlchemyError as exc:
        log.error("fire_inspections_list_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/equipment/due")
async def list_due_equipment(
    days: int = Query(7, ge=1),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """待检设备清单"""
    await _set_tenant(db, x_tenant_id)
    try:
        rows = await db.execute(
            text("""
                SELECT * FROM civic_fire_equipment
                WHERE tenant_id = :tid AND is_deleted = FALSE
                    AND status = 'active'
                    AND (
                        next_inspection_date IS NULL
                        OR next_inspection_date <= CURRENT_DATE + :days * INTERVAL '1 day'
                    )
                ORDER BY next_inspection_date ASC NULLS FIRST
            """),
            {"tid": x_tenant_id, "days": days},
        )
        items = [dict(r._mapping) for r in rows]
        log.info("due_equipment_listed", days=days, count=len(items))
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except SQLAlchemyError as exc:
        log.error("due_equipment_list_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")
