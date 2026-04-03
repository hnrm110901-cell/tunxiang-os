"""加盟管理 API

# ROUTER REGISTRATION:
# from .api.franchise_routes import router as franchise_router
# app.include_router(franchise_router, prefix="/api/v1/franchise")

端点清单：
  POST   /franchise/franchisees              - 创建加盟商
  GET    /franchise/franchisees              - 加盟商列表（总部视角）
  POST   /franchise/{id}/assign-store        - 分配门店
  GET    /franchise/{id}/dashboard           - 加盟商仪表盘
  POST   /franchise/bills/generate           - 生成月度账单
  GET    /franchise/bills                    - 账单列表（?franchisee_id=）
  POST   /franchise/bills/{id}/confirm       - 确认账单
  POST   /franchise/bills/{id}/pay           - 标记已付款
  GET    /franchise/overdue-alerts           - 欠款预警
"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..services.franchise_service import FranchiseService
from ..services.royalty_calculator import RoyaltyCalculator

router = APIRouter(prefix="/api/v1/franchise", tags=["franchise"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _get_tenant(x_tenant_id: Optional[str]) -> str:
    """从 Header 提取 tenant_id，缺失时使用默认值。"""
    return x_tenant_id or "default_tenant"


def _parse_tenant_uuid(x_tenant_id: Optional[str]) -> UUID:
    """解析 tenant_id 为 UUID，格式错误时抛出 400。"""
    raw = _get_tenant(x_tenant_id)
    try:
        return UUID(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式无效：{raw}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class RoyaltyTierReq(BaseModel):
    min_revenue: float = Field(..., ge=0)
    rate: float = Field(..., gt=0, lt=1)


class CreateFranchiseeReq(BaseModel):
    franchisee_name: str = Field(..., max_length=100)
    contact_name: Optional[str] = Field(None, max_length=50)
    contact_phone: Optional[str] = Field(None, max_length=20)
    contract_start: Optional[str] = None  # "YYYY-MM-DD"
    contract_end: Optional[str] = None
    royalty_rate: float = Field(default=0.05, gt=0, lt=1)
    royalty_tiers: List[RoyaltyTierReq] = Field(default_factory=list)


class AssignStoreReq(BaseModel):
    store_id: str


class GenerateBillsReq(BaseModel):
    bill_month: str = Field(..., pattern=r"^\d{4}-\d{2}$", description="格式 YYYY-MM")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  加盟商管理端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/franchisees")
async def create_franchisee(
    req: CreateFranchiseeReq,
    x_tenant_id: Optional[str] = Header(None),
):
    """创建加盟商（总部操作）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    try:
        franchisee = await FranchiseService.create_franchisee(
            data=req.model_dump(),
            tenant_id=tenant_id,
            db=None,
        )
        return {"ok": True, "data": franchisee.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/franchisees")
async def list_franchisees(
    status: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    x_tenant_id: Optional[str] = Header(None),
):
    """加盟商列表（总部视角，支持状态过滤和分页）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    result = await FranchiseService.list_franchisees(
        tenant_id=tenant_id,
        db=None,
        status=status,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


@router.post("/franchisees/{franchisee_id}/assign-store")
async def assign_store(
    franchisee_id: str,
    req: AssignStoreReq,
    x_tenant_id: Optional[str] = Header(None),
):
    """分配门店给加盟商。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    try:
        link = await FranchiseService.assign_store(
            franchisee_id=UUID(franchisee_id),
            store_id=UUID(req.store_id),
            tenant_id=tenant_id,
            db=None,
        )
        return {"ok": True, "data": link.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/franchisees/{franchisee_id}/dashboard")
async def get_franchisee_dashboard(
    franchisee_id: str,
    x_tenant_id: Optional[str] = Header(None),
):
    """加盟商仪表盘：本月营业额、本月分润、累计欠款。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    try:
        dashboard = await FranchiseService.get_franchisee_dashboard(
            franchisee_id=UUID(franchisee_id),
            tenant_id=tenant_id,
            db=None,
        )
        return {"ok": True, "data": dashboard}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  账单管理端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/bills/generate")
async def generate_bills(
    req: GenerateBillsReq,
    x_tenant_id: Optional[str] = Header(None),
):
    """生成指定月份的月度分润账单（批处理）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    try:
        bills = await RoyaltyCalculator.generate_monthly_bills(
            tenant_id=tenant_id,
            bill_month=req.bill_month,
            db=None,
        )
        return {
            "ok": True,
            "data": {
                "bill_month": req.bill_month,
                "generated": len(bills),
                "bills": [b.to_dict() for b in bills],
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/bills")
async def list_bills(
    franchisee_id: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    x_tenant_id: Optional[str] = Header(None),
):
    """账单列表（支持按加盟商过滤）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    fid: Optional[UUID] = None
    if franchisee_id:
        try:
            fid = UUID(franchisee_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="franchisee_id 格式无效")

    result = await FranchiseService.list_bills(
        tenant_id=tenant_id,
        db=None,
        franchisee_id=fid,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


@router.post("/bills/{bill_id}/confirm")
async def confirm_bill(
    bill_id: str,
    x_tenant_id: Optional[str] = Header(None),
):
    """总部确认账单（pending → confirmed）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    try:
        bill = await FranchiseService.confirm_bill(
            bill_id=UUID(bill_id),
            tenant_id=tenant_id,
            db=None,
        )
        return {"ok": True, "data": bill.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/bills/{bill_id}/pay")
async def mark_bill_paid(
    bill_id: str,
    x_tenant_id: Optional[str] = Header(None),
):
    """标记账单已付款（confirmed/overdue → paid）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    try:
        bill = await FranchiseService.mark_bill_paid(
            bill_id=UUID(bill_id),
            tenant_id=tenant_id,
            db=None,
        )
        return {"ok": True, "data": bill.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  欠款预警端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/overdue-alerts")
async def get_overdue_alerts(
    threshold: float = 50000.0,
    x_tenant_id: Optional[str] = Header(None),
):
    """欠款预警：累计欠款超阈值的加盟商列表。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    alerts = await FranchiseService.check_overdue_alerts(
        tenant_id=tenant_id,
        db=None,
        threshold=threshold,
    )
    return {"ok": True, "data": {"alerts": alerts, "count": len(alerts)}}
