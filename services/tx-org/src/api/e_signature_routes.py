"""电子签约 API 路由

端点列表：
  POST   /api/v1/e-signature/templates              创建合同模板
  GET    /api/v1/e-signature/templates              模板列表
  GET    /api/v1/e-signature/templates/{id}         模板详情
  PUT    /api/v1/e-signature/templates/{id}         更新模板
  POST   /api/v1/e-signature/signing/initiate       发起签署
  PUT    /api/v1/e-signature/signing/{id}/employee-sign   员工签署
  PUT    /api/v1/e-signature/signing/{id}/company-sign    企业盖章
  PUT    /api/v1/e-signature/signing/{id}/terminate       终止合同
  GET    /api/v1/e-signature/signing                签署记录列表
  GET    /api/v1/e-signature/signing/{id}           签署详情
  GET    /api/v1/e-signature/expiring               即将到期合同
  GET    /api/v1/e-signature/stats                  统计概览

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.e_signature_service import ESignatureService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/e-signature", tags=["e-signature"])


# ── 辅助函数 ──────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail={"error": "missing tenant_id"})
    return str(tid).strip()


def _ok(data: object) -> dict:
    return {"ok": True, "data": data}


def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(status_code=code, detail={"ok": False, "error": {"message": msg}})


# ── 请求模型 ──────────────────────────────────────────────


class CreateTemplateReq(BaseModel):
    template_name: str = Field(..., max_length=200)
    contract_type: str = Field(..., max_length=50)
    content_html: str = ""
    variables: list[dict[str, Any]] = []
    created_by: Optional[str] = None


class UpdateTemplateReq(BaseModel):
    template_name: Optional[str] = Field(None, max_length=200)
    contract_type: Optional[str] = Field(None, max_length=50)
    content_html: Optional[str] = None
    variables: Optional[list[dict[str, Any]]] = None
    is_active: Optional[bool] = None


class InitiateSigningReq(BaseModel):
    template_id: str
    employee_id: str
    start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    variables_filled: dict[str, Any] = {}
    store_id: Optional[str] = None


class CompanySignReq(BaseModel):
    signer_id: str


class TerminateReq(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


# ── 模板 API ─────────────────────────────────────────────


@router.post("/templates")
async def create_template(
    body: CreateTemplateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    try:
        svc = ESignatureService(db, tenant_id)
        result = await svc.create_template(
            name=body.template_name,
            contract_type=body.contract_type,
            content_html=body.content_html,
            variables=body.variables,
            created_by=body.created_by,
        )
        return _ok(result)
    except ValueError as exc:
        _err(str(exc))
    return {"ok": False}  # unreachable, keeps mypy happy


@router.get("/templates")
async def list_templates(
    request: Request,
    contract_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    try:
        svc = ESignatureService(db, tenant_id)
        result = await svc.list_templates(contract_type=contract_type, page=page, size=size)
        return _ok(result)
    except ValueError as exc:
        _err(str(exc))
    return {"ok": False}


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    try:
        svc = ESignatureService(db, tenant_id)
        result = await svc.get_template(template_id)
        return _ok(result)
    except ValueError as exc:
        _err(str(exc))
    return {"ok": False}


@router.put("/templates/{template_id}")
async def update_template(
    template_id: str,
    body: UpdateTemplateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    try:
        svc = ESignatureService(db, tenant_id)
        kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
        result = await svc.update_template(template_id, **kwargs)
        return _ok(result)
    except ValueError as exc:
        _err(str(exc))
    return {"ok": False}


# ── 签署 API ─────────────────────────────────────────────


@router.post("/signing/initiate")
async def initiate_signing(
    body: InitiateSigningReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    try:
        svc = ESignatureService(db, tenant_id)
        result = await svc.initiate_signing(
            template_id=body.template_id,
            employee_id=body.employee_id,
            start_date=body.start_date,
            end_date=body.end_date,
            variables_filled=body.variables_filled,
            store_id=body.store_id,
        )
        return _ok(result)
    except ValueError as exc:
        _err(str(exc))
    return {"ok": False}


@router.put("/signing/{record_id}/employee-sign")
async def employee_sign(
    record_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    try:
        svc = ESignatureService(db, tenant_id)
        result = await svc.employee_sign(record_id)
        return _ok(result)
    except ValueError as exc:
        _err(str(exc))
    return {"ok": False}


@router.put("/signing/{record_id}/company-sign")
async def company_sign(
    record_id: str,
    body: CompanySignReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    try:
        svc = ESignatureService(db, tenant_id)
        result = await svc.company_sign(record_id, body.signer_id)
        return _ok(result)
    except ValueError as exc:
        _err(str(exc))
    return {"ok": False}


@router.put("/signing/{record_id}/terminate")
async def terminate_contract(
    record_id: str,
    body: TerminateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    try:
        svc = ESignatureService(db, tenant_id)
        result = await svc.terminate_contract(record_id, body.reason)
        return _ok(result)
    except ValueError as exc:
        _err(str(exc))
    return {"ok": False}


@router.get("/signing")
async def list_signing_records(
    request: Request,
    employee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    contract_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    try:
        svc = ESignatureService(db, tenant_id)
        result = await svc.list_signing_records(
            employee_id=employee_id,
            status=status,
            contract_type=contract_type,
            page=page,
            size=size,
        )
        return _ok(result)
    except ValueError as exc:
        _err(str(exc))
    return {"ok": False}


@router.get("/signing/{record_id}")
async def get_signing_detail(
    record_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    try:
        svc = ESignatureService(db, tenant_id)
        result = await svc.get_signing_detail(record_id)
        return _ok(result)
    except ValueError as exc:
        _err(str(exc))
    return {"ok": False}


# ── 到期提醒 + 统计 ──────────────────────────────────────


@router.get("/expiring")
async def expiring_contracts(
    request: Request,
    days: int = Query(30, ge=0, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    try:
        svc = ESignatureService(db, tenant_id)
        items = await svc.scan_expiring_contracts(days_threshold=days)
        return _ok(items)
    except ValueError as exc:
        _err(str(exc))
    return {"ok": False}


@router.get("/stats")
async def contract_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    try:
        svc = ESignatureService(db, tenant_id)
        result = await svc.get_contract_stats()
        return _ok(result)
    except ValueError as exc:
        _err(str(exc))
    return {"ok": False}
