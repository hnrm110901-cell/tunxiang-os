"""跨品牌联盟忠诚度 API -- 8端点

合作伙伴管理/积分兑换/交易查询/联盟仪表盘
所有路由需要 X-Tenant-ID header。
"""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.alliance_service import AllianceService, AllianceServiceError

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/member/alliance", tags=["alliance"])

_svc = AllianceService()


# ── 请求模型 ──────────────────────────────────────────────────


class CreatePartnerReq(BaseModel):
    partner_name: str = Field(..., max_length=200)
    partner_type: str = Field(..., pattern="^(restaurant|retail|entertainment|fitness|hotel|other)$")
    partner_brand_logo: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    api_endpoint: Optional[str] = None
    api_key_encrypted: Optional[str] = None
    exchange_rate_out: float = 1.0
    exchange_rate_in: float = 1.0
    daily_exchange_limit: int = 1000
    contract_start: Optional[str] = None
    contract_end: Optional[str] = None
    terms_summary: Optional[str] = None


class UpdatePartnerReq(BaseModel):
    partner_name: Optional[str] = None
    partner_type: Optional[str] = None
    partner_brand_logo: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    api_endpoint: Optional[str] = None
    api_key_encrypted: Optional[str] = None
    exchange_rate_out: Optional[float] = None
    exchange_rate_in: Optional[float] = None
    daily_exchange_limit: Optional[int] = None
    contract_start: Optional[str] = None
    contract_end: Optional[str] = None
    terms_summary: Optional[str] = None


class ExchangePointsReq(BaseModel):
    customer_id: str
    partner_id: str
    direction: str = Field(..., pattern="^(inbound|outbound)$")
    points_amount: int = Field(..., gt=0)


# ── 1. 创建合作伙伴 ──────────────────────────────────────────


@router.post("/partners")
async def api_create_partner(
    body: CreatePartnerReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建联盟合作伙伴"""
    try:
        result = await _svc.create_partner(
            tenant_id=x_tenant_id,
            partner_data=body.model_dump(exclude_none=True),
            db=db,
        )
        return {"ok": True, "data": result, "error": None}
    except AllianceServiceError as e:
        return {"ok": False, "data": None, "error": {"code": e.code, "message": e.message}}


# ── 2. 获取合作伙伴列表 ──────────────────────────────────────


@router.get("/partners")
async def api_list_partners(
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    status: Optional[str] = Query(None),
    partner_type: Optional[str] = Query(None, alias="type"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取合作伙伴列表（分页，可按 status/type 筛选）"""
    result = await _svc.get_partner_list(
        tenant_id=x_tenant_id,
        db=db,
        status=status,
        partner_type=partner_type,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result, "error": None}


# ── 3. 更新合作伙伴 ──────────────────────────────────────────


@router.put("/partners/{partner_id}")
async def api_update_partner(
    partner_id: str,
    body: UpdatePartnerReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """更新联盟合作伙伴信息"""
    try:
        result = await _svc.update_partner(
            tenant_id=x_tenant_id,
            partner_id=partner_id,
            update_data=body.model_dump(exclude_none=True),
            db=db,
        )
        return {"ok": True, "data": result, "error": None}
    except AllianceServiceError as e:
        return {"ok": False, "data": None, "error": {"code": e.code, "message": e.message}}


# ── 4. 激活合作伙伴 ──────────────────────────────────────────


@router.put("/partners/{partner_id}/activate")
async def api_activate_partner(
    partner_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """激活合作伙伴"""
    try:
        result = await _svc.activate_partner(
            tenant_id=x_tenant_id,
            partner_id=partner_id,
            db=db,
        )
        return {"ok": True, "data": result, "error": None}
    except AllianceServiceError as e:
        return {"ok": False, "data": None, "error": {"code": e.code, "message": e.message}}


# ── 5. 暂停合作伙伴 ──────────────────────────────────────────


@router.put("/partners/{partner_id}/suspend")
async def api_suspend_partner(
    partner_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """暂停合作伙伴"""
    try:
        result = await _svc.suspend_partner(
            tenant_id=x_tenant_id,
            partner_id=partner_id,
            db=db,
        )
        return {"ok": True, "data": result, "error": None}
    except AllianceServiceError as e:
        return {"ok": False, "data": None, "error": {"code": e.code, "message": e.message}}


# ── 6. 积分兑换 ──────────────────────────────────────────────


@router.post("/exchange")
async def api_exchange_points(
    body: ExchangePointsReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """积分兑换（支持 inbound/outbound）"""
    try:
        if body.direction == "outbound":
            result = await _svc.exchange_points_out(
                tenant_id=x_tenant_id,
                customer_id=body.customer_id,
                partner_id=body.partner_id,
                points_amount=body.points_amount,
                db=db,
            )
        else:
            result = await _svc.exchange_points_in(
                tenant_id=x_tenant_id,
                customer_id=body.customer_id,
                partner_id=body.partner_id,
                external_points=body.points_amount,
                db=db,
            )
        return {"ok": True, "data": result, "error": None}
    except AllianceServiceError as e:
        return {"ok": False, "data": None, "error": {"code": e.code, "message": e.message}}


# ── 7. 交易列表 ──────────────────────────────────────────────


@router.get("/transactions")
async def api_list_transactions(
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    customer_id: Optional[str] = Query(None),
    partner_id: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取兑换交易列表（分页，可按 customer/partner/direction 筛选）"""
    if not customer_id:
        return {"ok": False, "data": None, "error": {"code": "missing_customer_id", "message": "customer_id 必填"}}

    result = await _svc.get_customer_transactions(
        tenant_id=x_tenant_id,
        customer_id=customer_id,
        db=db,
        partner_id=partner_id,
        direction=direction,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result, "error": None}


# ── 8. 联盟仪表盘 ────────────────────────────────────────────


@router.get("/dashboard")
async def api_alliance_dashboard(
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """联盟仪表盘统计"""
    result = await _svc.get_alliance_dashboard(
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}
