"""LHDN MyInvois e-Invoice API 路由"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.e_invoice_service import EinvoiceService, get_current_phase

router = APIRouter(prefix="/api/v1/einvoice", tags=["e-invoice"])


# ── DI ──────────────────────────────────────────────────────────


async def get_einvoice_service() -> EinvoiceService:
    return EinvoiceService()


# ── 请求/响应模型 ─────────────────────────────────────────────


class SubmitRequest(BaseModel):
    order_id: str = Field(..., description="订单ID")
    id_type: str = Field(default="BRN", description="BRN/NRIC/PASSPORT")
    id_value: str = Field(..., description="纳税人识别号")
    document_format: str = Field(default="JSON", description="JSON/XML/PDF")


class SubmitResponse(BaseModel):
    submission_uuid: str
    accepted_count: int
    rejected_count: int


class StatusResponse(BaseModel):
    document_uuid: str
    status: str
    lhdn_reference_no: Optional[str] = None
    error_message: Optional[str] = None


# ── 端点 ──────────────────────────────────────────────────────────


@router.get("/phase")
async def current_phase_endpoint():
    """查询当前 LHDN 合规 Phase"""
    phase = get_current_phase()
    return {"ok": True, "data": {"phase": phase}}


@router.post("/submit", response_model=SubmitResponse)
async def submit_einvoice(
    req: SubmitRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_store_id: str = Header("", alias="X-Store-ID"),
    service: EinvoiceService = Depends(get_einvoice_service),
):
    """提交 e-Invoice 到 LHDN MyInvois"""
    invoice_data = {
        "order_id": req.order_id,
        "id_type": req.id_type,
        "id_value": req.id_value,
    }
    try:
        result = await service.submit_invoice(
            invoice_data=invoice_data,
            tenant_id=x_tenant_id,
            store_id=x_store_id,
            document_format=req.document_format,
        )
        return SubmitResponse(
            submission_uuid=result["submission_uuid"],
            accepted_count=result["accepted_count"],
            rejected_count=result["rejected_count"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/status/{document_uuid}", response_model=StatusResponse)
async def get_einvoice_status(
    document_uuid: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    service: EinvoiceService = Depends(get_einvoice_service),
):
    """查询 e-Invoice 处理状态"""
    try:
        result = await service.query_invoice_status(
            document_uuid=document_uuid,
            tenant_id=x_tenant_id,
        )
        return StatusResponse(
            document_uuid=result["document_uuid"],
            status=result["status"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{document_uuid}/cancel")
async def cancel_einvoice(
    document_uuid: str,
    reason: Optional[str] = "",
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    service: EinvoiceService = Depends(get_einvoice_service),
):
    """取消/作废 e-Invoice"""
    try:
        result = await service.cancel_invoice(
            document_uuid=document_uuid,
            tenant_id=x_tenant_id,
            reason=reason,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/documents")
async def search_documents(
    date_from: str = Query(""),
    date_to: str = Query(""),
    status: str = Query(""),
    page_size: int = Query(100, ge=1, le=500),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    service: EinvoiceService = Depends(get_einvoice_service),
):
    """搜索e-Invoice列表"""
    try:
        result = await service.search_invoices(
            tenant_id=x_tenant_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
            page_size=page_size,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/submissions/recent")
async def get_recent_submissions(
    page_size: int = Query(10, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    service: EinvoiceService = Depends(get_einvoice_service),
):
    """查询最近提交记录"""
    try:
        result = await service.get_recent_submissions(
            tenant_id=x_tenant_id,
            page_size=page_size,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/health")
async def health_check(
    service: EinvoiceService = Depends(get_einvoice_service),
):
    """检查 MyInvois API 连通性"""
    ok = await service.health_check()
    return {"ok": ok, "data": {"reachable": ok}}
