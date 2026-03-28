"""发票服务 API — 开票申请/税控提交/状态查询/二维码/台账

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from ..services.invoice_service import (
    create_invoice_request,
    submit_to_tax_platform,
    get_invoice_status,
    generate_qrcode_data,
    get_invoice_ledger,
)

router = APIRouter(prefix="/api/v1/invoices", tags=["invoices"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─── 请求模型 ───


class CreateInvoiceReq(BaseModel):
    order_id: str
    invoice_type: str = Field(..., description="electronic / paper / vat_special")
    buyer_info: dict = Field(..., description="购方信息")
    amount_fen: int = Field(default=0, ge=0)
    items: Optional[list[dict]] = None


class SubmitInvoiceReq(BaseModel):
    invoice_id: str


class QRCodeReq(BaseModel):
    order_id: str
    amount_fen: int = Field(default=0, ge=0)
    store_name: str = ""


class LedgerReq(BaseModel):
    store_id: str
    start_date: str = Field(..., description="起始日期 YYYY-MM-DD")
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD")


# ─── 路由 ───


@router.post("")
async def api_create_invoice(body: CreateInvoiceReq, request: Request):
    """创建开票申请"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await create_invoice_request(
            order_id=body.order_id,
            invoice_type=body.invoice_type,
            buyer_info=body.buyer_info,
            tenant_id=tenant_id,
            amount_fen=body.amount_fen,
            items=body.items,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _ok(result)


@router.post("/submit")
async def api_submit_invoice(body: SubmitInvoiceReq, request: Request):
    """提交到税控平台"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await submit_to_tax_platform(body.invoice_id, tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return _ok(result)


@router.get("/{invoice_id}")
async def api_get_invoice_status(invoice_id: str, request: Request):
    """查询发票状态"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await get_invoice_status(invoice_id, tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return _ok(result)


@router.post("/qrcode")
async def api_generate_qrcode(body: QRCodeReq, request: Request):
    """生成开票二维码数据"""
    tenant_id = _get_tenant_id(request)
    result = await generate_qrcode_data(
        order_id=body.order_id,
        tenant_id=tenant_id,
        amount_fen=body.amount_fen,
        store_name=body.store_name,
    )
    return _ok(result)


@router.post("/ledger")
async def api_get_ledger(body: LedgerReq, request: Request):
    """查询发票台账"""
    tenant_id = _get_tenant_id(request)
    result = await get_invoice_ledger(
        store_id=body.store_id,
        date_range=(body.start_date, body.end_date),
        tenant_id=tenant_id,
    )
    return _ok(result)
