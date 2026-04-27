"""
采购付款联动 API 路由

负责采购付款单的创建、查询、审批、付款标记、发票匹配、对账等操作。
共 8 个端点，覆盖采购付款全生命周期。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

try:
    from src.services.procurement_payment_service import ProcurementPaymentService

    _procurement_svc = ProcurementPaymentService()
except ImportError:
    _procurement_svc = None  # type: ignore[assignment]

router = APIRouter()
log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 依赖注入
# ---------------------------------------------------------------------------


async def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> UUID:
    try:
        return UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的租户ID格式")


async def get_current_user(x_user_id: str = Header(..., alias="X-User-ID")) -> UUID:
    try:
        return UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户ID格式")


def _get_svc() -> "ProcurementPaymentService":
    if _procurement_svc is None:
        raise HTTPException(status_code=503, detail="采购付款服务暂不可用，请稍后重试")
    return _procurement_svc


# ---------------------------------------------------------------------------
# Pydantic Schema
# ---------------------------------------------------------------------------


class PaymentItemCreate(BaseModel):
    order_item_id: Optional[UUID] = None
    product_name: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[int] = None  # 分
    amount: int = Field(..., description="金额，单位：分(fen)")


class ProcurementPaymentCreate(BaseModel):
    purchase_order_id: UUID = Field(..., description="tx-supply 采购订单ID")
    purchase_order_no: Optional[str] = Field(None, max_length=64)
    supplier_id: Optional[UUID] = None
    supplier_name: Optional[str] = Field(None, max_length=200)
    payment_type: str = Field("purchase", description="付款类型：purchase / deposit / final")
    total_amount: int = Field(..., description="总金额，单位：分(fen)")
    due_date: Optional[date] = None
    notes: Optional[str] = None
    items: Optional[List[PaymentItemCreate]] = None


class ProcurementPaymentUpdate(BaseModel):
    purchase_order_no: Optional[str] = Field(None, max_length=64)
    supplier_name: Optional[str] = Field(None, max_length=200)
    payment_type: Optional[str] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None


class MarkPaidRequest(BaseModel):
    paid_amount: int = Field(..., description="本次实付金额，单位：分(fen)", gt=0)


class MatchInvoiceRequest(BaseModel):
    invoice_id: UUID = Field(..., description="要匹配的发票ID")


class PaginatedResponse(BaseModel):
    data: List[Any]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# 端点实现
# ---------------------------------------------------------------------------


@router.post("/payments", status_code=status.HTTP_201_CREATED)
async def create_payment(
    body: ProcurementPaymentCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    手工创建采购付款单

    - total_amount 单位为分(fen)，例如 10000 = 100元
    - 同一 purchase_order_id 只允许一张付款单（幂等保护），重复创建返回已有记录
    """
    svc = _get_svc()
    try:
        order_data = body.model_dump()
        order_data["created_by"] = current_user_id
        if body.items:
            order_data["items"] = [item.model_dump() for item in body.items]

        result = await svc.create_from_purchase_order(
            db=db,
            tenant_id=tenant_id,
            order_data=order_data,
        )
        await db.commit()
        log.info(
            "procurement_payment_created_via_api",
            tenant_id=str(tenant_id),
            payment_id=str(result.id),
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        log.error(
            "procurement_payment_create_failed",
            error=str(exc),
            tenant_id=str(tenant_id),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="创建采购付款单失败，请稍后重试")


@router.get("/payments")
async def list_payments(
    payment_status: Optional[str] = Query(
        None, alias="status", description="状态过滤：pending/approved/paid/cancelled"
    ),
    supplier_id: Optional[UUID] = Query(None, description="供应商ID过滤"),
    payment_type: Optional[str] = Query(None, description="付款类型过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    """
    查询采购付款单列表

    支持按状态、供应商、付款类型过滤，支持分页。
    """
    svc = _get_svc()
    try:
        filters = {
            "status": payment_status,
            "supplier_id": supplier_id,
            "payment_type": payment_type,
            "page": page,
            "page_size": page_size,
        }
        items, total = await svc.list_payments(db=db, tenant_id=tenant_id, filters=filters)
        return PaginatedResponse(data=items, total=total, page=page, page_size=page_size)
    except Exception as exc:
        log.error(
            "procurement_payments_list_failed",
            error=str(exc),
            tenant_id=str(tenant_id),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="查询采购付款单列表失败，请稍后重试")


@router.get("/payments/{payment_id}")
async def get_payment(
    payment_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """获取采购付款单详情（含付款条目和对账记录）"""
    svc = _get_svc()
    try:
        result = await svc.get_payment(db=db, tenant_id=tenant_id, payment_id=payment_id)
        return {"ok": True, "data": result}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        log.error(
            "procurement_payment_get_failed",
            error=str(exc),
            payment_id=str(payment_id),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="获取采购付款单详情失败，请稍后重试")


@router.put("/payments/{payment_id}")
async def update_payment(
    payment_id: UUID,
    body: ProcurementPaymentUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    更新采购付款单

    只允许修改 pending 状态的付款单。
    """
    svc = _get_svc()
    try:
        update_data = {k: v for k, v in body.model_dump().items() if v is not None}
        result = await svc.update_payment(
            db=db,
            tenant_id=tenant_id,
            payment_id=payment_id,
            data=update_data,
        )
        await db.commit()
        log.info(
            "procurement_payment_updated_via_api",
            payment_id=str(payment_id),
            tenant_id=str(tenant_id),
        )
        return {"ok": True, "data": result}
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        log.error(
            "procurement_payment_update_failed",
            error=str(exc),
            payment_id=str(payment_id),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="更新采购付款单失败，请稍后重试")


@router.post("/payments/{payment_id}/approve")
async def approve_payment(
    payment_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    审批通过采购付款单（pending → approved）

    操作人为当前登录用户（X-User-ID header）。
    """
    svc = _get_svc()
    try:
        result = await svc.approve_payment(
            db=db,
            tenant_id=tenant_id,
            payment_id=payment_id,
            approved_by=current_user_id,
        )
        await db.commit()
        log.info(
            "procurement_payment_approved_via_api",
            payment_id=str(payment_id),
            approved_by=str(current_user_id),
        )
        return {"ok": True, "data": result, "message": "付款单审批通过"}
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        log.error(
            "procurement_payment_approve_failed",
            error=str(exc),
            payment_id=str(payment_id),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="审批付款单失败，请稍后重试")


@router.post("/payments/{payment_id}/mark-paid")
async def mark_paid(
    payment_id: UUID,
    body: MarkPaidRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    标记采购付款单已付（approved → paid）

    - paid_amount 为本次实付金额，单位：分(fen)
    - 只允许 approved 状态的付款单执行此操作
    """
    svc = _get_svc()
    try:
        result = await svc.mark_paid(
            db=db,
            tenant_id=tenant_id,
            payment_id=payment_id,
            paid_amount=body.paid_amount,
        )
        await db.commit()
        log.info(
            "procurement_payment_marked_paid_via_api",
            payment_id=str(payment_id),
            paid_amount=body.paid_amount,
        )
        return {"ok": True, "data": result, "message": "付款单已标记为已付"}
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        log.error(
            "procurement_payment_mark_paid_failed",
            error=str(exc),
            payment_id=str(payment_id),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="标记付款单失败，请稍后重试")


@router.post("/payments/{payment_id}/match-invoice")
async def match_invoice(
    payment_id: UUID,
    body: MatchInvoiceRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    将发票与付款条目匹配

    将指定发票ID关联到付款单下所有未匹配的付款条目（invoice_id 为空的条目）。
    返回本次匹配的条目数及已匹配的条目数。
    """
    svc = _get_svc()
    try:
        result = await svc.match_invoice(
            db=db,
            tenant_id=tenant_id,
            payment_id=payment_id,
            invoice_id=body.invoice_id,
        )
        await db.commit()
        log.info(
            "procurement_invoice_matched_via_api",
            payment_id=str(payment_id),
            invoice_id=str(body.invoice_id),
        )
        return {"ok": True, "data": result}
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        log.error(
            "procurement_match_invoice_failed",
            error=str(exc),
            payment_id=str(payment_id),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="发票匹配失败，请稍后重试")


@router.get("/payments/{payment_id}/reconcile")
async def reconcile_payment(
    payment_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    发起/查询采购付款对账

    比较付款单金额与已匹配发票条目总金额，生成对账记录。
    - 差异 = 0：reconciliation_status = matched
    - 差异 ≠ 0：reconciliation_status = discrepancy
    金额单位均为分(fen)。
    """
    svc = _get_svc()
    try:
        result = await svc.reconcile(
            db=db,
            tenant_id=tenant_id,
            payment_id=payment_id,
        )
        await db.commit()
        log.info(
            "procurement_reconciliation_created_via_api",
            payment_id=str(payment_id),
            reconciliation_id=str(result.id),
            status=result.reconciliation_status,
        )
        return {"ok": True, "data": result}
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        log.error(
            "procurement_reconcile_failed",
            error=str(exc),
            payment_id=str(payment_id),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="发起对账失败，请稍后重试")
