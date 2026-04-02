"""加盟管理 API — 完整实现

端点清单：
  GET    /api/v1/franchise/franchisees                   加盟商列表
  POST   /api/v1/franchise/franchisees                   新建加盟商
  GET    /api/v1/franchise/franchisees/{id}              加盟商详情
  PUT    /api/v1/franchise/franchisees/{id}              更新加盟商信息
  GET    /api/v1/franchise/franchisees/{id}/stores       旗下门店列表
  GET    /api/v1/franchise/franchisees/{id}/dashboard    经营看板

  GET    /api/v1/franchise/royalty/bills                 账单列表
  POST   /api/v1/franchise/royalty/generate-batch        批量生成月度账单
  POST   /api/v1/franchise/royalty/bills/{id}/pay        标记已付款
  GET    /api/v1/franchise/royalty/report                月度汇总报表
  POST   /api/v1/franchise/royalty/check-overdue         检查并标记逾期账单

  GET    /api/v1/franchise/audits                        巡店审计列表
  POST   /api/v1/franchise/audits                        新建审计记录
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.franchise_service import FranchiseService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/franchise", tags=["franchise"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _parse_tenant_uuid(x_tenant_id: Optional[str]) -> UUID:
    """解析 X-Tenant-ID header 为 UUID，缺失或格式错误时抛出 400。"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="缺少必要 Header：X-Tenant-ID")
    try:
        return UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式无效：{x_tenant_id}")


def _parse_uuid(value: str, field_name: str) -> UUID:
    """解析路径参数为 UUID，格式错误时抛出 400。"""
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_name} 格式无效：{value}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型（Pydantic V2）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class RoyaltyTierReq(BaseModel):
    min_revenue: float = Field(..., ge=0, description="触发阶梯的最低月营业额（元）")
    rate: float = Field(..., gt=0, lt=1, description="该阶梯分润率")


class CreateFranchiseeReq(BaseModel):
    franchisee_name: str = Field(..., max_length=100, description="加盟商名称")
    contact_name: Optional[str] = Field(None, max_length=50)
    contact_phone: Optional[str] = Field(None, max_length=20)
    contact_email: Optional[str] = Field(None, max_length=100)
    region: Optional[str] = Field(None, max_length=50)
    contract_start: Optional[str] = Field(None, description="合同开始日期 YYYY-MM-DD")
    contract_end: Optional[str] = Field(None, description="合同结束日期 YYYY-MM-DD")
    royalty_rate: float = Field(default=0.05, gt=0, lt=1, description="基础分润率")
    royalty_tiers: List[RoyaltyTierReq] = Field(default_factory=list)
    management_fee_fen: int = Field(default=0, ge=0, description="月度管理费（分）")
    brand_usage_fee_fen: int = Field(default=0, ge=0, description="品牌使用费（分）")


class UpdateFranchiseeReq(BaseModel):
    franchisee_name: Optional[str] = Field(None, max_length=100)
    contact_name: Optional[str] = Field(None, max_length=50)
    contact_phone: Optional[str] = Field(None, max_length=20)
    contact_email: Optional[str] = Field(None, max_length=100)
    region: Optional[str] = Field(None, max_length=50)
    contract_start: Optional[str] = None
    contract_end: Optional[str] = None
    royalty_rate: Optional[float] = Field(None, gt=0, lt=1)
    management_fee_fen: Optional[int] = Field(None, ge=0)
    brand_usage_fee_fen: Optional[int] = Field(None, ge=0)
    status: Optional[str] = Field(None, description="active / suspended / terminated")


class GenerateBatchReq(BaseModel):
    year: int = Field(..., ge=2020, le=2099, description="账单年份")
    month: int = Field(..., ge=1, le=12, description="账单月份")


class CreateAuditReq(BaseModel):
    franchisee_id: str = Field(..., description="加盟商 UUID")
    store_id: str = Field(..., description="门店 UUID")
    audit_date: Optional[str] = Field(None, description="审计日期 YYYY-MM-DD，默认今天")
    score: Optional[float] = Field(None, ge=0, le=100, description="审计分数")
    findings: Optional[Dict[str, Any]] = Field(default_factory=dict, description="审计发现项 JSONB")
    auditor_id: Optional[str] = Field(None, description="审计人 UUID")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  加盟商管理端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/franchisees")
async def list_franchisees(
    status: Optional[str] = Query(None, description="按状态过滤：active/suspended/terminated"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
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


@router.post("/franchisees", status_code=201)
async def create_franchisee(
    req: CreateFranchiseeReq,
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """新建加盟商档案（总部操作）。"""
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


@router.get("/franchisees/{franchisee_id}")
async def get_franchisee(
    franchisee_id: str,
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """加盟商详情。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    fid = _parse_uuid(franchisee_id, "franchisee_id")
    franchisee = await FranchiseService.get_franchisee(fid, tenant_id, db=None)
    if franchisee is None:
        raise HTTPException(status_code=404, detail=f"加盟商 {franchisee_id} 不存在")
    return {"ok": True, "data": franchisee.to_dict()}


@router.put("/franchisees/{franchisee_id}")
async def update_franchisee(
    franchisee_id: str,
    req: UpdateFranchiseeReq,
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """更新加盟商信息（包含状态变更）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    fid = _parse_uuid(franchisee_id, "franchisee_id")
    data = req.model_dump(exclude_none=True)

    try:
        # 若包含状态变更，走专用状态流转方法
        if "status" in data:
            franchisee = await FranchiseService.update_franchisee_status(
                franchisee_id=fid,
                tenant_id=tenant_id,
                new_status=data["status"],
                db=None,
            )
        else:
            franchisee = await FranchiseService.update_franchisee(
                franchisee_id=fid,
                tenant_id=tenant_id,
                data=data,
                db=None,
            )
        return {"ok": True, "data": franchisee.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/franchisees/{franchisee_id}/stores")
async def list_franchisee_stores(
    franchisee_id: str,
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """加盟商旗下门店列表（含运营数据）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    fid = _parse_uuid(franchisee_id, "franchisee_id")
    stores = await FranchiseService.list_franchisee_stores(
        tenant_id=tenant_id,
        franchisee_id=fid,
        db=None,
    )
    return {"ok": True, "data": {"franchisee_id": franchisee_id, "stores": stores}}


@router.get("/franchisees/{franchisee_id}/dashboard")
async def get_franchisee_dashboard(
    franchisee_id: str,
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """加盟商经营看板：营收/环比/同比/待缴费用/门店/审计分数。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    fid = _parse_uuid(franchisee_id, "franchisee_id")
    try:
        dashboard = await FranchiseService.get_franchisee_dashboard(
            franchisee_id=fid,
            tenant_id=tenant_id,
            db=None,
        )
        return {"ok": True, "data": dashboard}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  特许权费用账单端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/royalty/bills")
async def list_royalty_bills(
    franchisee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="pending/paid/overdue"),
    year: Optional[int] = Query(None, ge=2020, le=2099),
    month: Optional[int] = Query(None, ge=1, le=12),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """账单列表（支持按加盟商/状态/月份过滤）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    fid: Optional[UUID] = None
    if franchisee_id:
        fid = _parse_uuid(franchisee_id, "franchisee_id")

    result = await FranchiseService.list_bills(
        tenant_id=tenant_id,
        db=None,
        franchisee_id=fid,
        status=status,
        year=year,
        month=month,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


@router.post("/royalty/generate-batch", status_code=201)
async def generate_royalty_batch(
    req: GenerateBatchReq,
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """批量生成指定月份所有活跃加盟商的特许权费用账单。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    try:
        result = await FranchiseService.create_royalty_bill_batch(
            tenant_id=tenant_id,
            year=req.year,
            month=req.month,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/royalty/bills/{bill_id}/pay")
async def mark_royalty_bill_paid(
    bill_id: str,
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """标记账单已付款（pending/overdue → paid）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    bid = _parse_uuid(bill_id, "bill_id")
    try:
        bill = await FranchiseService.mark_bill_paid(
            bill_id=bid,
            tenant_id=tenant_id,
            db=None,
        )
        return {"ok": True, "data": bill.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/royalty/report")
async def get_royalty_report(
    year: int = Query(..., ge=2020, le=2099),
    month: int = Query(..., ge=1, le=12),
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """月度特许权费用汇总报表。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    report = await FranchiseService.get_royalty_report(
        tenant_id=tenant_id,
        year=year,
        month=month,
        db=None,
    )
    return {"ok": True, "data": report.to_dict()}


@router.post("/royalty/check-overdue")
async def check_overdue_bills(
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """检查所有账单，将逾期未付的账单标记为 overdue。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    marked_count = await FranchiseService.check_overdue_bills(
        tenant_id=tenant_id,
        db=None,
    )
    return {"ok": True, "data": {"marked_overdue": marked_count}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  巡店审计端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/audits")
async def list_audits(
    franchisee_id: Optional[str] = Query(None),
    store_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """巡店审计列表（支持按加盟商/门店过滤）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    fid: Optional[UUID] = None
    sid: Optional[UUID] = None
    if franchisee_id:
        fid = _parse_uuid(franchisee_id, "franchisee_id")
    if store_id:
        sid = _parse_uuid(store_id, "store_id")

    result = await FranchiseService.list_audits(
        tenant_id=tenant_id,
        db=None,
        franchisee_id=fid,
        store_id=sid,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


@router.post("/audits", status_code=201)
async def create_audit(
    req: CreateAuditReq,
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """新建巡店审计记录。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    try:
        record = await FranchiseService.create_audit(
            tenant_id=tenant_id,
            data=req.model_dump(),
            db=None,
        )
        return {"ok": True, "data": record}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
