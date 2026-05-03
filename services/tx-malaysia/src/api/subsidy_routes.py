"""马来西亚政府补贴计费 API 端点 — MDEC / SME Corp

端点：
  - GET  /api/v1/subsidy/programs           列出可用补贴方案
  - POST /api/v1/subsidy/check-eligibility   校验商户资格
  - POST /api/v1/subsidy/apply               申请补贴
  - GET  /api/v1/subsidy/status              查询当前补贴状态
  - GET  /api/v1/subsidy/bill                计算当前周期账单
"""

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.subsidy_service import SubsidyService

router = APIRouter(prefix="/api/v1/subsidy", tags=["subsidy"])


# ── DI ──────────────────────────────────────────────────────────


async def get_subsidy_service(
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> SubsidyService:
    return SubsidyService(db=db, tenant_id=x_tenant_id)


# ── 请求/响应模型 ─────────────────────────────────────────────


class SubsidyProgram(BaseModel):
    """补贴方案信息"""

    id: str
    name: str
    subsidy_rate: float
    max_subsidy_fen: int
    max_subsidy_rm: float
    monthly_fee_fen: int
    monthly_fee_rm: float
    description: str
    eligibility_criteria: list[str]


class SubsidyProgramsResponse(BaseModel):
    """可用补贴方案列表"""

    programs: list[SubsidyProgram]


class CheckEligibilityRequest(BaseModel):
    """资格校验请求"""

    program: str = Field(..., description="补贴方案 ID，如 mdec_digital_grant")


class CheckEligibilityResponse(BaseModel):
    """资格校验结果"""

    eligible: bool
    status: str
    program: str
    reasons: list[str]
    subsidy_rate: float
    max_subsidy_fen: int
    monthly_fee_fen: int


class ApplySubsidyRequest(BaseModel):
    """补贴申请请求"""

    program: str = Field(..., description="补贴方案 ID，如 mdec_digital_grant")


class ApplySubsidyResponse(BaseModel):
    """补贴申请结果"""

    applied: bool
    subsidy_id: str
    program: str
    status: str
    subsidy_rate: float
    monthly_fee_fen: int
    subsidy_amount_fen: int
    payable_fen: int
    applied_at: str
    expires_at: str


class ActiveSubsidyInfo(BaseModel):
    """活跃补贴信息"""

    subsidy_id: str
    program: str
    subsidy_rate: float
    monthly_fee_fen: int
    subsidy_amount_fen: int
    applied_at: Optional[str] = None
    expires_at: Optional[str] = None
    status: str


class CurrentBillInfo(BaseModel):
    """当前账单信息"""

    bill_id: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    base_fee_fen: int
    subsidy_fen: int
    payable_fen: int
    status: Optional[str] = None


class SubsidyStatusResponse(BaseModel):
    """补贴状态查询结果"""

    has_active_subsidy: bool
    active_subsidies: list[ActiveSubsidyInfo]
    current_bill: Optional[CurrentBillInfo] = None
    total_saved_fen: int


class BillResponse(BaseModel):
    """账单计算结果"""

    period_start: str
    period_end: str
    base_fee_fen: int
    subsidy_fen: int
    payable_fen: int
    active_subsidies: list[ActiveSubsidyInfo]


class GenerateInvoiceRequest(BaseModel):
    """生成账单请求"""

    period: str = Field(..., description="账单周期，格式 YYYY-MM，如 2026-05")


class GenerateInvoiceResponse(BaseModel):
    """生成账单结果"""

    bill_id: Optional[str] = None
    tenant_id: str
    period: str
    base_fee_fen: int
    subsidy_fen: int
    payable_fen: int
    status: str


# ── 端点 ──────────────────────────────────────────────────────


@router.get("/programs", response_model=SubsidyProgramsResponse)
async def list_programs():
    """列出所有可用的马来西亚政府补贴方案

    当前支持的方案：
      - MDEC Digitalisation Grant（补贴 50%，最高 RM3,500）
      - SME Corp Automasuk（补贴 40%，最高 RM2,000）
    """
    return SubsidyProgramsResponse(**SubsidyService.list_programs())


@router.post("/check-eligibility", response_model=CheckEligibilityResponse)
async def check_eligibility(
    req: CheckEligibilityRequest,
    service: SubsidyService = Depends(get_subsidy_service),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """校验商户在指定补贴方案中的资格

    检查 SSM 验证状态、企业规模（SME 标准）、方案特有条件。
    """
    try:
        result = await service.check_eligibility(
            tenant_id=x_tenant_id,
            program=req.program,
        )
        return CheckEligibilityResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/apply", response_model=ApplySubsidyResponse)
async def apply_subsidy(
    req: ApplySubsidyRequest,
    service: SubsidyService = Depends(get_subsidy_service),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """申请政府补贴套餐

    自动校验资格，通过后创建补贴记录。
    补贴金额 = min(月费 × 补贴率, 最高补贴额)
    """
    try:
        result = await service.apply_subsidy(
            tenant_id=x_tenant_id,
            program=req.program,
        )
        return ApplySubsidyResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/status", response_model=SubsidyStatusResponse)
async def get_subsidy_status(
    service: SubsidyService = Depends(get_subsidy_service),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """查询商户当前补贴状态

    包括活跃补贴、当前待缴账单、累计节省金额。
    """
    try:
        result = await service.get_subsidy_status(tenant_id=x_tenant_id)
        return SubsidyStatusResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/bill", response_model=BillResponse)
async def get_current_bill(
    period_start: date = Query(..., description="账单周期起始日（YYYY-MM-DD）"),
    period_end: date = Query(..., description="账单周期结束日（YYYY-MM-DD）"),
    service: SubsidyService = Depends(get_subsidy_service),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """计算当前周期补贴后账单

    公式: payable_fen = base_fee_fen - subsidy_fen
    """
    try:
        result = await service.calculate_bill(
            tenant_id=x_tenant_id,
            period_start=period_start,
            period_end=period_end,
        )
        return BillResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/generate-invoice", response_model=GenerateInvoiceResponse)
async def generate_invoice(
    req: GenerateInvoiceRequest,
    service: SubsidyService = Depends(get_subsidy_service),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """生成补贴账单记录

    将当前周期费用写入 subsidy_bills 表，状态为 pending。
    """
    try:
        result = await service.generate_invoice(
            tenant_id=x_tenant_id,
            period=req.period,
        )
        return GenerateInvoiceResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
