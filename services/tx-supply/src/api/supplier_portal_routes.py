"""供应商门户 API

端点列表：
  POST   /api/v1/suppliers                        注册供应商
  GET    /api/v1/suppliers                        列出供应商（?category=&rating_min=）
  GET    /api/v1/suppliers/{supplier_id}          获取供应商详情（含交付统计）
  PUT    /api/v1/suppliers/{supplier_id}          更新供应商状态
  POST   /api/v1/suppliers/rfq                    发起询价
  POST   /api/v1/suppliers/rfq/{rfq_id}/quotes    供应商提交报价
  GET    /api/v1/suppliers/rfq/{rfq_id}/compare   比价分析
  POST   /api/v1/suppliers/rfq/{rfq_id}/accept    接受报价
  POST   /api/v1/suppliers/{supplier_id}/delivery 记录交付结果
  GET    /api/v1/suppliers/risk-assessment        供应链风险评估
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..services import supplier_portal_service as svc

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/suppliers", tags=["supplier-portal"])


# ──────────────────────────────────────────────────────────────────────────────
# 通用工具
# ──────────────────────────────────────────────────────────────────────────────


def _table_not_ready() -> dict:
    return {"ok": False, "error": {"code": "TABLE_NOT_READY", "message": "供应商门户表尚未就绪，请先执行数据库迁移"}}


def _not_found(msg: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"ok": False, "error": {"code": "NOT_FOUND", "message": msg}},
    )


def _bad_request(msg: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"ok": False, "error": {"code": "BAD_REQUEST", "message": msg}},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic 请求体
# ──────────────────────────────────────────────────────────────────────────────


class RegisterSupplierRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(
        description="seafood/meat/vegetable/seasoning/frozen/dry_goods/beverage/other"
    )
    contact: dict = Field(
        default_factory=dict,
        description='{"person":"张三","phone":"138xxx","address":"长沙市xxx"}',
    )
    certifications: list = Field(default_factory=list)
    payment_terms: str = Field(default="net30", description="net30/net60/cod")


class UpdateSupplierRequest(BaseModel):
    status: Optional[str] = Field(
        default=None,
        description="active/inactive/suspended/blacklisted",
    )
    overall_score: Optional[float] = Field(default=None, ge=0.0, le=100.0)


class RequestQuotesRequest(BaseModel):
    item_name: str = Field(min_length=1, max_length=200)
    quantity: float = Field(gt=0)
    delivery_date: Optional[date] = None
    supplier_ids: Optional[list[str]] = Field(
        default=None,
        description="指定供应商ID列表；为空则发给所有活跃供应商",
    )


class SubmitQuoteRequest(BaseModel):
    supplier_id: str
    unit_price_fen: int = Field(ge=0, description="报价单价，单位：分")
    delivery_days: int = Field(ge=0, description="承诺交货天数")
    notes: str = Field(default="")


class AcceptQuoteRequest(BaseModel):
    supplier_id: str


class RecordDeliveryRequest(BaseModel):
    on_time: bool
    quality_result: str = Field(description="pass/fail")


# ──────────────────────────────────────────────────────────────────────────────
# 供应商管理端点
# ──────────────────────────────────────────────────────────────────────────────


@router.post("")
async def register_supplier(
    body: RegisterSupplierRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """注册新供应商"""
    try:
        data = await svc.register_supplier(
            name=body.name,
            category=body.category,
            contact=body.contact,
            certifications=body.certifications,
            payment_terms=body.payment_terms,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": data}
    except ProgrammingError as exc:
        await db.rollback()
        if "does not exist" in str(exc).lower():
            return _table_not_ready()
        raise
    except ValueError as exc:
        await db.rollback()
        raise _bad_request(str(exc))


@router.get("")
async def list_suppliers(
    category: Optional[str] = Query(default=None),
    rating_min: Optional[float] = Query(default=None, ge=0.0, le=100.0),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """列出供应商（可按品类、最低评分过滤）"""
    try:
        items = await svc.list_suppliers(
            tenant_id=x_tenant_id,
            db=db,
            category=category,
            rating_min=rating_min,
        )
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except ProgrammingError as exc:
        if "does not exist" in str(exc).lower():
            return _table_not_ready()
        raise


@router.get("/risk-assessment")
async def get_risk_assessment(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """供应链风险评估（高风险供应商 / 单一货源品类 / 近期交付异常率）"""
    try:
        data = await svc.assess_risk(tenant_id=x_tenant_id, db=db)
        return {"ok": True, "data": data}
    except ProgrammingError as exc:
        if "does not exist" in str(exc).lower():
            return _table_not_ready()
        raise


@router.get("/{supplier_id}")
async def get_supplier(
    supplier_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """获取供应商完整档案（含交付统计、近期报价）"""
    try:
        data = await svc.get_supplier_profile(
            supplier_id=supplier_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": data}
    except ProgrammingError as exc:
        if "does not exist" in str(exc).lower():
            return _table_not_ready()
        raise
    except ValueError as exc:
        raise _not_found(str(exc))


@router.put("/{supplier_id}")
async def update_supplier(
    supplier_id: str,
    body: UpdateSupplierRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """更新供应商状态或评分"""
    try:
        data = await svc.update_supplier(
            supplier_id=supplier_id,
            tenant_id=x_tenant_id,
            db=db,
            status=body.status,
            overall_score=body.overall_score,
        )
        return {"ok": True, "data": data}
    except ProgrammingError as exc:
        await db.rollback()
        if "does not exist" in str(exc).lower():
            return _table_not_ready()
        raise
    except ValueError as exc:
        await db.rollback()
        raise _not_found(str(exc))


@router.post("/{supplier_id}/delivery")
async def record_delivery(
    supplier_id: str,
    body: RecordDeliveryRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """记录交付结果，自动更新供应商综合评分"""
    try:
        data = await svc.record_delivery(
            supplier_id=supplier_id,
            on_time=body.on_time,
            quality_result=body.quality_result,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": data}
    except ProgrammingError as exc:
        await db.rollback()
        if "does not exist" in str(exc).lower():
            return _table_not_ready()
        raise
    except ValueError as exc:
        await db.rollback()
        raise _not_found(str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# 询价管理端点
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/rfq")
async def request_quotes(
    body: RequestQuotesRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """发起询价（RFQ），向指定或全部活跃供应商发出询价单"""
    try:
        data = await svc.request_quotes(
            item_name=body.item_name,
            quantity=body.quantity,
            delivery_date=body.delivery_date,
            supplier_ids=body.supplier_ids,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": data}
    except ProgrammingError as exc:
        await db.rollback()
        if "does not exist" in str(exc).lower():
            return _table_not_ready()
        raise
    except ValueError as exc:
        await db.rollback()
        raise _bad_request(str(exc))


@router.post("/rfq/{rfq_id}/quotes")
async def submit_quote(
    rfq_id: str,
    body: SubmitQuoteRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """供应商提交报价"""
    try:
        await svc.submit_quote(
            rfq_id=rfq_id,
            supplier_id=body.supplier_id,
            unit_price_fen=body.unit_price_fen,
            delivery_days=body.delivery_days,
            notes=body.notes,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": {"rfq_id": rfq_id, "supplier_id": body.supplier_id}}
    except ProgrammingError as exc:
        await db.rollback()
        if "does not exist" in str(exc).lower():
            return _table_not_ready()
        raise
    except ValueError as exc:
        await db.rollback()
        raise _bad_request(str(exc))


@router.get("/rfq/{rfq_id}/compare")
async def compare_quotes(
    rfq_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """比价分析：计算并返回各供应商综合评分排名"""
    try:
        data = await svc.compare_quotes(rfq_id=rfq_id, tenant_id=x_tenant_id, db=db)
        return {"ok": True, "data": data}
    except ProgrammingError as exc:
        if "does not exist" in str(exc).lower():
            return _table_not_ready()
        raise
    except ValueError as exc:
        raise _bad_request(str(exc))


@router.post("/rfq/{rfq_id}/accept")
async def accept_quote(
    rfq_id: str,
    body: AcceptQuoteRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """接受报价，其余报价自动标记为已拒绝"""
    try:
        data = await svc.accept_quote(
            rfq_id=rfq_id,
            supplier_id=body.supplier_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": data}
    except ProgrammingError as exc:
        await db.rollback()
        if "does not exist" in str(exc).lower():
            return _table_not_ready()
        raise
    except ValueError as exc:
        await db.rollback()
        raise _bad_request(str(exc))
