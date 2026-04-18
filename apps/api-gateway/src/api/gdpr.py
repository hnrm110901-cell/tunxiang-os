"""
GDPR API 路由 — 同意管理 + SAR 流程
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.models.gdpr import DataAccessRequest
from src.services.gdpr_service import GDPRService

router = APIRouter(prefix="/api/v1/gdpr", tags=["gdpr"])


class ConsentIn(BaseModel):
    employee_id: str
    consent_type: str  # data_processing / marketing / third_party_share / ai_training
    granted: bool
    legal_basis: str = "consent"
    reason: Optional[str] = None


class AccessRequestIn(BaseModel):
    employee_id: str
    request_type: str  # access / export / delete / correct


@router.post("/consents")
async def upsert_consent(payload: ConsentIn, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    svc = GDPRService(db)
    if payload.granted:
        r = await svc.grant_consent(
            payload.employee_id, payload.consent_type, payload.legal_basis
        )
    else:
        r = await svc.revoke_consent(payload.employee_id, payload.consent_type, payload.reason)
    await db.commit()
    return {"id": str(r.id), "granted": r.granted}


@router.get("/consents/my")
async def my_consents(employee_id: str, db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    svc = GDPRService(db)
    records = await svc.get_my_consents(employee_id)
    return [
        {
            "id": str(r.id),
            "consent_type": r.consent_type,
            "granted": r.granted,
            "legal_basis": r.legal_basis,
            "granted_at": r.granted_at.isoformat() + "Z" if r.granted_at else None,
            "revoked_at": r.revoked_at.isoformat() + "Z" if r.revoked_at else None,
        }
        for r in records
    ]


@router.post("/access-requests")
async def create_request(
    payload: AccessRequestIn, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    svc = GDPRService(db)
    try:
        req = await svc.create_access_request(payload.employee_id, payload.request_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return {"id": str(req.id), "status": req.status, "request_type": req.request_type}


@router.get("/access-requests/my")
async def my_requests(employee_id: str, db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    stmt = (
        select(DataAccessRequest)
        .where(DataAccessRequest.employee_id == employee_id)
        .order_by(DataAccessRequest.created_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "request_type": r.request_type,
            "status": r.status,
            "requested_at": r.requested_at.isoformat() + "Z" if r.requested_at else None,
            "completed_at": r.completed_at.isoformat() + "Z" if r.completed_at else None,
        }
        for r in rows
    ]


@router.get("/access-requests/{req_id}/download")
async def download_export(req_id: str, db: AsyncSession = Depends(get_db)):
    """导出员工个人数据 ZIP 流式下载"""
    req = await db.get(DataAccessRequest, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="request not found")
    if req.request_type not in {"access", "export"}:
        raise HTTPException(status_code=400, detail="only access/export requests can download")

    svc = GDPRService(db)
    zip_bytes = await svc.export_personal_data(req.employee_id)
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=gdpr_export_{req.employee_id}.zip"},
    )
