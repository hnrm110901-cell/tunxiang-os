from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/civic/env", tags=["civic-env"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class EmissionRecordCreate(BaseModel):
    store_id: str
    device_id: Optional[str] = None
    pm25: Optional[float] = None
    pm10: Optional[float] = None
    nmhc: Optional[float] = None
    emission_concentration: Optional[float] = None
    purifier_efficiency: Optional[float] = None


class WasteDisposalCreate(BaseModel):
    store_id: str
    waste_type: str
    weight_kg: float
    collector_company: Optional[str] = None
    collector_license: Optional[str] = None
    vehicle_plate: Optional[str] = None
    disposal_cert_no: Optional[str] = None
    photos: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/emission")
async def create_emission_record(
    body: EmissionRecordCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """油烟排放记录"""
    await _set_tenant(db, x_tenant_id)
    record_id = str(uuid4())
    try:
        await db.execute(
            text("""
                INSERT INTO civic_emission_records (
                    id, tenant_id, store_id, device_id,
                    pm25, pm10, nmhc, emission_concentration,
                    purifier_efficiency, created_at
                ) VALUES (
                    :id, :tid, :sid, :did,
                    :pm25, :pm10, :nmhc, :ec,
                    :pe, NOW()
                )
            """),
            {
                "id": record_id,
                "tid": x_tenant_id,
                "sid": body.store_id,
                "did": body.device_id,
                "pm25": body.pm25,
                "pm10": body.pm10,
                "nmhc": body.nmhc,
                "ec": body.emission_concentration,
                "pe": body.purifier_efficiency,
            },
        )
        await db.commit()
        log.info("emission_record_created", record_id=record_id, store_id=body.store_id)
        return {"ok": True, "data": {"id": record_id}}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("emission_record_create_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/emission/trend")
async def get_emission_trend(
    store_id: str = Query(...),
    days: int = Query(30, ge=1, le=365),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """排放趋势"""
    await _set_tenant(db, x_tenant_id)
    try:
        rows = await db.execute(
            text("""
                SELECT
                    created_at::date AS record_date,
                    AVG(pm25) AS avg_pm25,
                    AVG(pm10) AS avg_pm10,
                    AVG(nmhc) AS avg_nmhc,
                    AVG(emission_concentration) AS avg_concentration,
                    AVG(purifier_efficiency) AS avg_efficiency,
                    COUNT(*) AS sample_count
                FROM civic_emission_records
                WHERE tenant_id = :tid AND store_id = :sid
                    AND created_at >= NOW() - :days * INTERVAL '1 day'
                GROUP BY created_at::date
                ORDER BY record_date
            """),
            {"tid": x_tenant_id, "sid": store_id, "days": days},
        )
        items = [dict(r._mapping) for r in rows]
        log.info("emission_trend_fetched", store_id=store_id, days=days, points=len(items))
        return {"ok": True, "data": {"store_id": store_id, "days": days, "trend": items}}
    except SQLAlchemyError as exc:
        log.error("emission_trend_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/waste-disposal")
async def create_waste_disposal(
    body: WasteDisposalCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """餐厨垃圾台账"""
    await _set_tenant(db, x_tenant_id)
    record_id = str(uuid4())
    try:
        await db.execute(
            text("""
                INSERT INTO civic_waste_disposals (
                    id, tenant_id, store_id, waste_type, weight_kg,
                    collector_company, collector_license, vehicle_plate,
                    disposal_cert_no, photos, notes, created_at
                ) VALUES (
                    :id, :tid, :sid, :wtype, :wkg,
                    :cc, :cl, :vp,
                    :dcn, :photos, :notes, NOW()
                )
            """),
            {
                "id": record_id,
                "tid": x_tenant_id,
                "sid": body.store_id,
                "wtype": body.waste_type,
                "wkg": body.weight_kg,
                "cc": body.collector_company,
                "cl": body.collector_license,
                "vp": body.vehicle_plate,
                "dcn": body.disposal_cert_no,
                "photos": body.photos,
                "notes": body.notes,
            },
        )
        await db.commit()
        log.info("waste_disposal_created", record_id=record_id, store_id=body.store_id)
        return {"ok": True, "data": {"id": record_id}}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("waste_disposal_create_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/waste-disposal/summary")
async def get_waste_disposal_summary(
    store_id: str = Query(...),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """垃圾处置汇总"""
    await _set_tenant(db, x_tenant_id)
    try:
        conditions = ["tenant_id = :tid", "store_id = :sid"]
        params: Dict[str, Any] = {"tid": x_tenant_id, "sid": store_id}

        if date_from:
            conditions.append("created_at >= :df")
            params["df"] = date_from
        if date_to:
            conditions.append("created_at < :dt + INTERVAL '1 day'")
            params["dt"] = date_to

        where = " AND ".join(conditions)

        rows = await db.execute(
            text(
                f"SELECT waste_type, COUNT(*) AS disposal_count, "
                f"SUM(weight_kg) AS total_weight_kg "
                f"FROM civic_waste_disposals WHERE {where} "
                f"GROUP BY waste_type ORDER BY total_weight_kg DESC"
            ),
            params,
        )
        items = [dict(r._mapping) for r in rows]

        total_weight = sum(item.get("total_weight_kg", 0) or 0 for item in items)
        total_count = sum(item.get("disposal_count", 0) or 0 for item in items)

        log.info("waste_disposal_summary", store_id=store_id, total_weight=total_weight)
        return {
            "ok": True,
            "data": {
                "store_id": store_id,
                "total_weight_kg": total_weight,
                "total_count": total_count,
                "by_type": items,
            },
        }
    except SQLAlchemyError as exc:
        log.error("waste_disposal_summary_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/compliance")
async def get_env_compliance(
    store_id: str = Query(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """环保达标率"""
    await _set_tenant(db, x_tenant_id)
    try:
        # Emission compliance: check records in last 30 days
        emission_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE emission_concentration <= 2.0) AS compliant
                FROM civic_emission_records
                WHERE tenant_id = :tid AND store_id = :sid
                    AND created_at >= NOW() - INTERVAL '30 days'
            """),
            {"tid": x_tenant_id, "sid": store_id},
        )
        emission_row = emission_result.fetchone()
        emission_total = emission_row.total if emission_row else 0
        emission_compliant = emission_row.compliant if emission_row else 0
        emission_rate = round(
            (emission_compliant / emission_total * 100) if emission_total > 0 else 0, 2
        )

        # Waste disposal compliance: check if disposal records exist for last 7 days
        waste_result = await db.execute(
            text("""
                SELECT COUNT(DISTINCT created_at::date) AS active_days
                FROM civic_waste_disposals
                WHERE tenant_id = :tid AND store_id = :sid
                    AND created_at >= NOW() - INTERVAL '7 days'
            """),
            {"tid": x_tenant_id, "sid": store_id},
        )
        waste_days = (waste_result.scalar() or 0)
        waste_rate = round(waste_days / 7 * 100, 2)

        overall = round((emission_rate + waste_rate) / 2, 2)

        log.info("env_compliance", store_id=store_id, overall=overall)
        return {
            "ok": True,
            "data": {
                "store_id": store_id,
                "emission_compliance_pct": emission_rate,
                "waste_disposal_compliance_pct": waste_rate,
                "overall_compliance_pct": overall,
                "emission_samples": emission_total,
                "waste_active_days": waste_days,
            },
        }
    except SQLAlchemyError as exc:
        log.error("env_compliance_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")
