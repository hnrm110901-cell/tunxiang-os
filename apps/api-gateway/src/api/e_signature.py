"""
电子签约 API
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..services.e_signature_service import ESignatureService

router = APIRouter(prefix="/api/v1/hr/e-signature", tags=["hr-e-signature"])


# ---------- Schemas ----------
class CreateTemplateRequest(BaseModel):
    code: str
    name: str
    category: str = "labor_contract"
    content_text: Optional[str] = None
    content_template_url: Optional[str] = None
    placeholders: Optional[List[Dict[str, Any]]] = None
    required_fields: Optional[List[str]] = None
    legal_entity_id: Optional[uuid.UUID] = None


class CreateEnvelopeRequest(BaseModel):
    template_id: Optional[uuid.UUID] = None
    signer_list: List[Dict[str, Any]]
    placeholder_values: Optional[Dict[str, Any]] = None
    subject: Optional[str] = None
    initiator_id: Optional[str] = None
    legal_entity_id: Optional[uuid.UUID] = None
    expires_in_days: int = 14
    related_contract_id: Optional[uuid.UUID] = None
    related_entity_type: Optional[str] = None


class SignRequest(BaseModel):
    signer_id: str
    signature_image_base64: Optional[str] = None
    signature_image_url: Optional[str] = None
    seal_id: Optional[uuid.UUID] = None
    device_info: Optional[str] = None


class RejectRequest(BaseModel):
    signer_id: str
    reason: Optional[str] = None


class CreateSealRequest(BaseModel):
    legal_entity_id: uuid.UUID
    seal_name: str
    seal_type: str = "contract"
    seal_image_url: Optional[str] = None
    authorized_users: Optional[List[str]] = None
    expires_at: Optional[datetime] = None


class SendEnvelopeRequest(BaseModel):
    actor_id: Optional[str] = None


# ---------- Templates ----------
@router.post("/templates", summary="新建模板")
async def create_template(req: CreateTemplateRequest, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    try:
        tpl = await ESignatureService.create_template(db, **req.dict())
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": str(tpl.id), "code": tpl.code}


# ---------- Envelopes ----------
@router.post("/envelopes", summary="创建信封")
async def create_envelope(req: CreateEnvelopeRequest, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    try:
        env = await ESignatureService.prepare_envelope(db, **req.dict())
        await db.commit()
    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    return {"id": str(env.id), "envelope_no": env.envelope_no, "status": env.envelope_status.value}


@router.post("/envelopes/{envelope_id}/send", summary="发送信封")
async def send_envelope(
    envelope_id: uuid.UUID,
    req: SendEnvelopeRequest,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        env = await ESignatureService.send_envelope(db, envelope_id, actor_id=req.actor_id)
        await db.commit()
    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    return {"id": str(env.id), "status": env.envelope_status.value}


@router.post("/envelopes/{envelope_id}/sign", summary="签署")
async def sign_envelope(
    envelope_id: uuid.UUID,
    req: SignRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    ip = request.client.host if request.client else None
    try:
        result = await ESignatureService.sign(
            db,
            envelope_id=envelope_id,
            signer_id=req.signer_id,
            signature_image_url=req.signature_image_url,
            signature_image_base64=req.signature_image_base64,
            seal_id=req.seal_id,
            ip_address=ip,
            device_info=req.device_info,
        )
        await db.commit()
    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    return result


@router.post("/envelopes/{envelope_id}/reject", summary="拒签")
async def reject_envelope(
    envelope_id: uuid.UUID,
    req: RejectRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    ip = request.client.host if request.client else None
    try:
        env = await ESignatureService.reject(
            db,
            envelope_id=envelope_id,
            signer_id=req.signer_id,
            reason=req.reason,
            ip_address=ip,
        )
        await db.commit()
    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    return {"id": str(env.id), "status": env.envelope_status.value}


@router.get("/envelopes/my", summary="我的信封")
async def my_envelopes(
    role: str = Query("signer", pattern="^(initiator|signer)$"),
    user_id: str = Query(...),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    rows = await ESignatureService.list_envelopes(db, role=role, user_id=user_id, status=status)
    return {"items": rows, "total": len(rows)}


@router.get("/envelopes/pending", summary="我的待签清单")
async def pending_envelopes(
    user_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    rows = await ESignatureService.list_pending_for_user(db, user_id=user_id)
    return {"items": rows, "total": len(rows)}


@router.get("/envelopes/{envelope_id}", summary="信封详情")
async def envelope_detail(envelope_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    try:
        return await ESignatureService.get_envelope_detail(db, envelope_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="信封不存在")


@router.get("/envelopes/{envelope_id}/audit-trail", summary="审计链")
async def audit_trail(envelope_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    rows = await ESignatureService.get_audit_trail(db, envelope_id)
    return {"items": rows, "total": len(rows)}


@router.get("/envelopes/{envelope_id}/pdf", summary="下载已签 PDF")
async def download_pdf(envelope_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    detail = await ESignatureService.get_envelope_detail(db, envelope_id)
    path = detail.get("signed_document_url")
    if not path or not os.path.exists(path):
        # 尝试按需重生成
        from ..services.e_signature_pdf_service import ESignaturePdfService

        path = await ESignaturePdfService.render_signed_pdf(db, envelope_id)
        await db.commit()
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="PDF 未生成")
    return FileResponse(path, filename=os.path.basename(path), media_type="application/pdf")


# ---------- Seals ----------
@router.post("/seals", summary="新建印章")
async def create_seal(req: CreateSealRequest, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    try:
        seal = await ESignatureService.create_seal(db, **req.dict())
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": str(seal.id), "seal_name": seal.seal_name}
