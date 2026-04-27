from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/civic/trace", tags=["civic-trace"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class InboundRecordCreate(BaseModel):
    store_id: str
    supplier_id: Optional[str] = None
    supplier_name: str
    product_name: str
    product_category: str
    batch_no: Optional[str] = None
    quantity: float
    unit: str
    production_date: Optional[date] = None
    expiry_date: Optional[date] = None
    origin_trace_code: Optional[str] = None
    storage_type: Optional[str] = None
    inspection_result: bool = True
    inspector_id: Optional[str] = None
    inspection_notes: Optional[str] = None


class SupplierCreate(BaseModel):
    supplier_name: str
    license_no: Optional[str] = None
    license_type: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    valid_until: Optional[date] = None


class ColdchainRecordCreate(BaseModel):
    store_id: str
    batch_id: Optional[str] = None
    device_id: Optional[str] = None
    checkpoint: str
    temperature_c: float
    humidity_pct: Optional[float] = None
    operator_id: Optional[str] = None
    notes: Optional[str] = None


class SubmitRequest(BaseModel):
    store_id: str
    date_from: date
    date_to: date


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/inbound")
async def create_inbound_record(
    body: InboundRecordCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """录入进货台账"""
    await _set_tenant(db, x_tenant_id)
    record_id = str(uuid4())
    batch_no = body.batch_no or f"B-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{record_id[:8]}"
    try:
        await db.execute(
            text("""
                INSERT INTO civic_inbound_records (
                    id, tenant_id, store_id, supplier_id, supplier_name,
                    product_name, product_category, batch_no, quantity, unit,
                    production_date, expiry_date, origin_trace_code, storage_type,
                    inspection_result, inspector_id, inspection_notes, created_at
                ) VALUES (
                    :id, :tenant_id, :store_id, :supplier_id, :supplier_name,
                    :product_name, :product_category, :batch_no, :quantity, :unit,
                    :production_date, :expiry_date, :origin_trace_code, :storage_type,
                    :inspection_result, :inspector_id, :inspection_notes, NOW()
                )
            """),
            {
                "id": record_id,
                "tenant_id": x_tenant_id,
                "store_id": body.store_id,
                "supplier_id": body.supplier_id,
                "supplier_name": body.supplier_name,
                "product_name": body.product_name,
                "product_category": body.product_category,
                "batch_no": batch_no,
                "quantity": body.quantity,
                "unit": body.unit,
                "production_date": body.production_date,
                "expiry_date": body.expiry_date,
                "origin_trace_code": body.origin_trace_code,
                "storage_type": body.storage_type,
                "inspection_result": body.inspection_result,
                "inspector_id": body.inspector_id,
                "inspection_notes": body.inspection_notes,
            },
        )
        await db.commit()
        log.info("inbound_record_created", record_id=record_id, store_id=body.store_id)
        return {"ok": True, "data": {"id": record_id, "batch_no": batch_no}}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("inbound_record_create_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/inbound")
async def list_inbound_records(
    store_id: str = Query(...),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """查询进货台账"""
    await _set_tenant(db, x_tenant_id)
    try:
        conditions = ["tenant_id = :tenant_id", "store_id = :store_id"]
        params: Dict[str, Any] = {"tenant_id": x_tenant_id, "store_id": store_id}

        if date_from:
            conditions.append("created_at >= :date_from")
            params["date_from"] = date_from
        if date_to:
            conditions.append("created_at < :date_to + INTERVAL '1 day'")
            params["date_to"] = date_to

        where = " AND ".join(conditions)
        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        count_result = await db.execute(text(f"SELECT COUNT(*) FROM civic_inbound_records WHERE {where}"), params)
        total = count_result.scalar() or 0

        rows = await db.execute(
            text(
                f"SELECT * FROM civic_inbound_records WHERE {where} "
                f"ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        items = [dict(r._mapping) for r in rows]
        log.info("inbound_records_listed", store_id=store_id, total=total)
        return {"ok": True, "data": {"items": items, "total": total}}
    except SQLAlchemyError as exc:
        log.error("inbound_records_list_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/batch/{batch_no}")
async def trace_batch(
    batch_no: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """批次追溯"""
    await _set_tenant(db, x_tenant_id)
    try:
        inbound = await db.execute(
            text("SELECT * FROM civic_inbound_records WHERE tenant_id = :tenant_id AND batch_no = :batch_no"),
            {"tenant_id": x_tenant_id, "batch_no": batch_no},
        )
        inbound_rows = [dict(r._mapping) for r in inbound]

        coldchain = await db.execute(
            text(
                "SELECT * FROM civic_coldchain_records "
                "WHERE tenant_id = :tenant_id AND batch_id = :batch_no "
                "ORDER BY created_at"
            ),
            {"tenant_id": x_tenant_id, "batch_no": batch_no},
        )
        coldchain_rows = [dict(r._mapping) for r in coldchain]

        if not inbound_rows:
            raise HTTPException(status_code=404, detail=f"Batch {batch_no} not found")

        log.info("batch_traced", batch_no=batch_no)
        return {
            "ok": True,
            "data": {
                "batch_no": batch_no,
                "inbound_records": inbound_rows,
                "coldchain_records": coldchain_rows,
            },
        }
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("batch_trace_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/suppliers")
async def create_supplier(
    body: SupplierCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """供应商资质登记"""
    await _set_tenant(db, x_tenant_id)
    supplier_id = str(uuid4())
    try:
        await db.execute(
            text("""
                INSERT INTO civic_suppliers (
                    id, tenant_id, supplier_name, license_no, license_type,
                    contact_name, contact_phone, address, valid_until, status, created_at
                ) VALUES (
                    :id, :tenant_id, :supplier_name, :license_no, :license_type,
                    :contact_name, :contact_phone, :address, :valid_until, 'active', NOW()
                )
            """),
            {
                "id": supplier_id,
                "tenant_id": x_tenant_id,
                "supplier_name": body.supplier_name,
                "license_no": body.license_no,
                "license_type": body.license_type,
                "contact_name": body.contact_name,
                "contact_phone": body.contact_phone,
                "address": body.address,
                "valid_until": body.valid_until,
            },
        )
        await db.commit()
        log.info("supplier_created", supplier_id=supplier_id)
        return {"ok": True, "data": {"id": supplier_id}}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("supplier_create_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/suppliers")
async def list_suppliers(
    status: Optional[str] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """供应商列表"""
    await _set_tenant(db, x_tenant_id)
    try:
        conditions = ["tenant_id = :tenant_id", "is_deleted = FALSE"]
        params: Dict[str, Any] = {"tenant_id": x_tenant_id}

        if status:
            conditions.append("status = :status")
            params["status"] = status

        where = " AND ".join(conditions)
        rows = await db.execute(
            text(f"SELECT * FROM civic_suppliers WHERE {where} ORDER BY created_at DESC"),
            params,
        )
        items = [dict(r._mapping) for r in rows]
        log.info("suppliers_listed", count=len(items))
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except SQLAlchemyError as exc:
        log.error("suppliers_list_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/coldchain")
async def create_coldchain_record(
    body: ColdchainRecordCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """冷链温控记录"""
    await _set_tenant(db, x_tenant_id)
    record_id = str(uuid4())
    try:
        await db.execute(
            text("""
                INSERT INTO civic_coldchain_records (
                    id, tenant_id, store_id, batch_id, device_id, checkpoint,
                    temperature_c, humidity_pct, operator_id, notes, created_at
                ) VALUES (
                    :id, :tenant_id, :store_id, :batch_id, :device_id, :checkpoint,
                    :temperature_c, :humidity_pct, :operator_id, :notes, NOW()
                )
            """),
            {
                "id": record_id,
                "tenant_id": x_tenant_id,
                "store_id": body.store_id,
                "batch_id": body.batch_id,
                "device_id": body.device_id,
                "checkpoint": body.checkpoint,
                "temperature_c": body.temperature_c,
                "humidity_pct": body.humidity_pct,
                "operator_id": body.operator_id,
                "notes": body.notes,
            },
        )
        await db.commit()
        log.info("coldchain_record_created", record_id=record_id, store_id=body.store_id)
        return {"ok": True, "data": {"id": record_id}}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("coldchain_record_create_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/completeness")
async def check_completeness(
    store_id: str = Query(...),
    date: date = Query(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """追溯完整性检查"""
    await _set_tenant(db, x_tenant_id)
    try:
        inbound_count = await db.execute(
            text(
                "SELECT COUNT(*) FROM civic_inbound_records "
                "WHERE tenant_id = :tid AND store_id = :sid "
                "AND created_at::date = :d"
            ),
            {"tid": x_tenant_id, "sid": store_id, "d": date},
        )
        total_inbound = inbound_count.scalar() or 0

        with_trace = await db.execute(
            text(
                "SELECT COUNT(*) FROM civic_inbound_records "
                "WHERE tenant_id = :tid AND store_id = :sid "
                "AND created_at::date = :d AND origin_trace_code IS NOT NULL"
            ),
            {"tid": x_tenant_id, "sid": store_id, "d": date},
        )
        traced = with_trace.scalar() or 0

        with_inspection = await db.execute(
            text(
                "SELECT COUNT(*) FROM civic_inbound_records "
                "WHERE tenant_id = :tid AND store_id = :sid "
                "AND created_at::date = :d AND inspection_result IS NOT NULL"
            ),
            {"tid": x_tenant_id, "sid": store_id, "d": date},
        )
        inspected = with_inspection.scalar() or 0

        completeness_pct = round((traced / total_inbound * 100) if total_inbound > 0 else 0, 2)
        inspection_pct = round((inspected / total_inbound * 100) if total_inbound > 0 else 0, 2)

        log.info("completeness_checked", store_id=store_id, date=str(date), pct=completeness_pct)
        return {
            "ok": True,
            "data": {
                "store_id": store_id,
                "date": str(date),
                "total_inbound": total_inbound,
                "traced_count": traced,
                "inspected_count": inspected,
                "trace_completeness_pct": completeness_pct,
                "inspection_completeness_pct": inspection_pct,
            },
        }
    except SQLAlchemyError as exc:
        log.error("completeness_check_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/submit")
async def submit_trace_data(
    body: SubmitRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """手动触发上报"""
    await _set_tenant(db, x_tenant_id)
    submission_id = str(uuid4())
    try:
        records = await db.execute(
            text(
                "SELECT COUNT(*) FROM civic_inbound_records "
                "WHERE tenant_id = :tid AND store_id = :sid "
                "AND created_at::date BETWEEN :df AND :dt"
            ),
            {
                "tid": x_tenant_id,
                "sid": body.store_id,
                "df": body.date_from,
                "dt": body.date_to,
            },
        )
        record_count = records.scalar() or 0

        await db.execute(
            text("""
                INSERT INTO civic_submissions (
                    id, tenant_id, store_id, domain, record_count,
                    date_from, date_to, status, created_at
                ) VALUES (
                    :id, :tid, :sid, 'traceability', :cnt,
                    :df, :dt, 'pending', NOW()
                )
            """),
            {
                "id": submission_id,
                "tid": x_tenant_id,
                "sid": body.store_id,
                "cnt": record_count,
                "df": body.date_from,
                "dt": body.date_to,
            },
        )
        await db.commit()
        log.info("trace_submit_triggered", submission_id=submission_id, record_count=record_count)
        return {
            "ok": True,
            "data": {
                "submission_id": submission_id,
                "record_count": record_count,
                "status": "pending",
            },
        }
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("trace_submit_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")
