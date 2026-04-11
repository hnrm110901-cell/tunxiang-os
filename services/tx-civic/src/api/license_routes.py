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

router = APIRouter(prefix="/api/v1/civic/licenses", tags=["civic-licenses"])
log = structlog.get_logger(__name__)

# Secondary router for health-certs under the same module
health_router = APIRouter(prefix="/api/v1/civic/health-certs", tags=["civic-health-certs"])


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class LicenseCreate(BaseModel):
    store_id: str
    license_type: str
    license_no: str
    license_name: str
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    issuing_authority: Optional[str] = None
    document_urls: List[str] = Field(default_factory=list)
    scope_desc: Optional[str] = None
    auto_alert_days: int = 30


class HealthCertCreate(BaseModel):
    store_id: str
    employee_id: str
    employee_name: str
    cert_no: str
    issue_date: date
    expiry_date: date
    issuing_authority: Optional[str] = None
    document_url: Optional[str] = None


class RenewalUpdate(BaseModel):
    renewal_status: str


# ---------------------------------------------------------------------------
# License Endpoints
# ---------------------------------------------------------------------------

@router.post("")
async def create_license(
    body: LicenseCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """登记证照"""
    await _set_tenant(db, x_tenant_id)
    license_id = str(uuid4())
    try:
        await db.execute(
            text("""
                INSERT INTO civic_licenses (
                    id, tenant_id, store_id, license_type, license_no,
                    license_name, issue_date, expiry_date, issuing_authority,
                    document_urls, scope_desc, auto_alert_days, status, created_at
                ) VALUES (
                    :id, :tid, :sid, :ltype, :lno,
                    :lname, :idate, :edate, :auth,
                    :docs, :scope, :alert_days, 'active', NOW()
                )
            """),
            {
                "id": license_id,
                "tid": x_tenant_id,
                "sid": body.store_id,
                "ltype": body.license_type,
                "lno": body.license_no,
                "lname": body.license_name,
                "idate": body.issue_date,
                "edate": body.expiry_date,
                "auth": body.issuing_authority,
                "docs": body.document_urls,
                "scope": body.scope_desc,
                "alert_days": body.auto_alert_days,
            },
        )
        await db.commit()
        log.info("license_created", license_id=license_id, store_id=body.store_id)
        return {"ok": True, "data": {"id": license_id}}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("license_create_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("")
async def list_licenses(
    store_id: Optional[str] = Query(None),
    license_type: Optional[str] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """证照列表"""
    await _set_tenant(db, x_tenant_id)
    try:
        conditions = ["tenant_id = :tid", "is_deleted = FALSE"]
        params: Dict[str, Any] = {"tid": x_tenant_id}

        if store_id:
            conditions.append("store_id = :sid")
            params["sid"] = store_id
        if license_type:
            conditions.append("license_type = :ltype")
            params["ltype"] = license_type

        where = " AND ".join(conditions)
        rows = await db.execute(
            text(f"SELECT * FROM civic_licenses WHERE {where} ORDER BY expiry_date ASC"),
            params,
        )
        items = [dict(r._mapping) for r in rows]
        log.info("licenses_listed", count=len(items))
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except SQLAlchemyError as exc:
        log.error("licenses_list_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/expiring")
async def list_expiring_licenses(
    days: int = Query(30, ge=1),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """即将到期清单"""
    await _set_tenant(db, x_tenant_id)
    try:
        rows = await db.execute(
            text("""
                SELECT * FROM civic_licenses
                WHERE tenant_id = :tid AND is_deleted = FALSE
                    AND expiry_date IS NOT NULL
                    AND expiry_date <= CURRENT_DATE + :days * INTERVAL '1 day'
                    AND expiry_date >= CURRENT_DATE
                ORDER BY expiry_date ASC
            """),
            {"tid": x_tenant_id, "days": days},
        )
        items = [dict(r._mapping) for r in rows]
        log.info("expiring_licenses_listed", days=days, count=len(items))
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except SQLAlchemyError as exc:
        log.error("expiring_licenses_list_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/{license_id}/renew")
async def mark_renewal(
    license_id: str,
    body: RenewalUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """标记续办中"""
    await _set_tenant(db, x_tenant_id)
    try:
        result = await db.execute(
            text(
                "UPDATE civic_licenses SET "
                "status = :status, updated_at = NOW() "
                "WHERE id = :id AND tenant_id = :tid"
            ),
            {"id": license_id, "tid": x_tenant_id, "status": body.renewal_status},
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"License {license_id} not found")

        await db.commit()
        log.info("license_renewal_marked", license_id=license_id, status=body.renewal_status)
        return {"ok": True, "data": {"id": license_id, "status": body.renewal_status}}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("license_renewal_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Health Certificate Endpoints
# ---------------------------------------------------------------------------

@health_router.post("")
async def create_health_cert(
    body: HealthCertCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """员工健康证登记"""
    await _set_tenant(db, x_tenant_id)
    cert_id = str(uuid4())
    try:
        await db.execute(
            text("""
                INSERT INTO civic_health_certs (
                    id, tenant_id, store_id, employee_id, employee_name,
                    cert_no, issue_date, expiry_date, issuing_authority,
                    document_url, status, created_at
                ) VALUES (
                    :id, :tid, :sid, :eid, :ename,
                    :cno, :idate, :edate, :auth,
                    :doc_url, 'active', NOW()
                )
            """),
            {
                "id": cert_id,
                "tid": x_tenant_id,
                "sid": body.store_id,
                "eid": body.employee_id,
                "ename": body.employee_name,
                "cno": body.cert_no,
                "idate": body.issue_date,
                "edate": body.expiry_date,
                "auth": body.issuing_authority,
                "doc_url": body.document_url,
            },
        )
        await db.commit()
        log.info("health_cert_created", cert_id=cert_id, employee_id=body.employee_id)
        return {"ok": True, "data": {"id": cert_id}}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("health_cert_create_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@health_router.get("/expiring")
async def list_expiring_health_certs(
    days: int = Query(30, ge=1),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """健康证到期清单"""
    await _set_tenant(db, x_tenant_id)
    try:
        rows = await db.execute(
            text("""
                SELECT * FROM civic_health_certs
                WHERE tenant_id = :tid AND is_deleted = FALSE
                    AND expiry_date <= CURRENT_DATE + :days * INTERVAL '1 day'
                    AND expiry_date >= CURRENT_DATE
                ORDER BY expiry_date ASC
            """),
            {"tid": x_tenant_id, "days": days},
        )
        items = [dict(r._mapping) for r in rows]
        log.info("expiring_health_certs_listed", days=days, count=len(items))
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except SQLAlchemyError as exc:
        log.error("expiring_health_certs_list_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="Internal server error")
