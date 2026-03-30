"""电子发票 API 路由

# ROUTER REGISTRATION (在 tx-finance/src/main.py 中添加):
# from .api.e_invoice_routes import router as invoice_router
# app.include_router(invoice_router, prefix="/api/v1/invoices")

端点清单：
  POST   /invoices/request                  申请发票（提交订单id+抬头信息）
  GET    /invoices/{invoice_id}/status      查询发票状态
  POST   /invoices/{invoice_id}/retry       重试失败申请
  POST   /invoices/{invoice_id}/reprint     重打发票
  GET    /invoices                           查询订单下的发票（?order_id=）
  POST   /invoices/{invoice_id}/cancel      红冲作废
"""
import uuid
from decimal import Decimal
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant
from services.invoice_service import (
    InvoiceAmountMismatchError,
    InvoiceNotFoundError,
    InvoiceService,
    InvoiceStatusError,
    _invoice_to_dict,
)
from models.invoice import Invoice
from sqlalchemy import select

logger = structlog.get_logger()
router = APIRouter(tags=["e-invoice"])

# 单例 service（NuonuoInvoiceClient 内部懒加载 adapter）
_invoice_service = InvoiceService()


# ── 依赖 ──────────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    """从 Header 提取 tenant_id，返回带 RLS 的 DB session。"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-ID 格式无效",
        )


# ── Pydantic 请求/响应 Schema ─────────────────────────────────────────────────

class InvoiceRequestBody(BaseModel):
    order_id: uuid.UUID
    invoice_type: str = Field(
        default="electronic",
        pattern="^(vat_special|vat_normal|electronic)$",
        description="发票类型：vat_special/vat_normal/electronic",
    )
    invoice_title: Optional[str] = Field(default=None, max_length=100, description="发票抬头")
    tax_number: Optional[str] = Field(default=None, max_length=50, description="购方税号")
    amount: Decimal = Field(gt=0, description="开票金额（元）")
    tax_amount: Optional[Decimal] = Field(default=None, ge=0, description="税额（元）")
    order_amount: Optional[Decimal] = Field(default=None, gt=0, description="订单实付金额，用于校验")
    buyer_address: Optional[str] = None
    buyer_phone: Optional[str] = None
    buyer_bank_name: Optional[str] = None
    buyer_bank_account: Optional[str] = None
    goods_list: Optional[list[dict[str, Any]]] = Field(default=None, description="商品明细，为空时自动生成单行")
    clerk: Optional[str] = Field(default="系统")
    remark: Optional[str] = None


class CancelInvoiceBody(BaseModel):
    reason: str = Field(default="顾客申请作废", max_length=200)


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _handle_service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, InvoiceNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, InvoiceAmountMismatchError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, InvoiceStatusError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


# ── 路由 ──────────────────────────────────────────────────────────────────────

@router.post("/request", status_code=status.HTTP_201_CREATED)
async def request_invoice(
    body: InvoiceRequestBody,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """申请电子发票。

    订单完成后由前端或其他服务调用，写入 invoices 表（pending 状态）并异步发起开票请求。
    """
    invoice_info = body.model_dump()
    order_amount = invoice_info.pop("order_amount", None)

    try:
        invoice = await _invoice_service.request_invoice(
            order_id=body.order_id,
            invoice_info=invoice_info,
            tenant_id=tenant_id,
            db=db,
            order_amount=order_amount,
        )
    except (InvoiceAmountMismatchError, InvoiceNotFoundError, InvoiceStatusError) as exc:
        raise _handle_service_error(exc) from exc

    return _ok(_invoice_to_dict(invoice))


@router.get("/{invoice_id}/status")
async def get_invoice_status(
    invoice_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """查询发票状态。若本地 pending 则实时查询诺诺。"""
    try:
        data = await _invoice_service.get_invoice_status(invoice_id, tenant_id, db)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return _ok(data)


@router.post("/{invoice_id}/retry")
async def retry_invoice(
    invoice_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """重试失败的发票申请（仅 failed 状态可操作）。"""
    try:
        invoice = await _invoice_service.retry_failed(invoice_id, tenant_id, db)
    except (InvoiceNotFoundError, InvoiceStatusError) as exc:
        raise _handle_service_error(exc) from exc

    return _ok(_invoice_to_dict(invoice))


@router.post("/{invoice_id}/reprint")
async def reprint_invoice(
    invoice_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """重打发票（重新获取 PDF 链接，仅 issued 状态可操作）。"""
    try:
        data = await _invoice_service.reprint(invoice_id, tenant_id, db)
    except (InvoiceNotFoundError, InvoiceStatusError) as exc:
        raise _handle_service_error(exc) from exc

    return _ok(data)


@router.get("")
async def list_invoices_by_order(
    order_id: uuid.UUID = Query(..., description="订单 ID"),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """查询订单下的所有发票。"""
    result = await db.execute(
        select(Invoice).where(
            Invoice.order_id == order_id,
            Invoice.tenant_id == tenant_id,
        )
    )
    invoices = result.scalars().all()
    return _ok([_invoice_to_dict(inv) for inv in invoices])


@router.post("/{invoice_id}/cancel")
async def cancel_invoice(
    invoice_id: uuid.UUID,
    body: CancelInvoiceBody,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """红冲作废发票（仅 issued 状态可操作）。"""
    try:
        invoice = await _invoice_service.cancel_invoice(
            invoice_id=invoice_id,
            tenant_id=tenant_id,
            db=db,
            reason=body.reason,
        )
    except (InvoiceNotFoundError, InvoiceStatusError) as exc:
        raise _handle_service_error(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return _ok(_invoice_to_dict(invoice))
