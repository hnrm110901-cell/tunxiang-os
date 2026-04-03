"""宴会全流程 API — 线索→报价→签约→定金→菜单→执行→结账→回访"""
import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.banquet_integration import BanquetIntegrationService

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/banquets", tags=["banquet"])


# ─── 依赖注入 ───

async def _get_db(request: Request):
    tenant_id = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tenant_id:
        from fastapi import HTTPException
        raise HTTPException(400, "Missing X-Tenant-ID")
    async for session in get_db_with_tenant(tenant_id):
        yield session


def _svc(request: Request, db: AsyncSession = Depends(_get_db)) -> BanquetIntegrationService:
    tenant_id = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    store_id = request.headers.get("X-Store-ID", "")
    return BanquetIntegrationService(tenant_id=tenant_id, store_id=store_id, db=db)


def _ok(data: dict) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: str = "BAD_REQUEST") -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": msg}}


# ─── Request Models ───

class CreateLeadReq(BaseModel):
    customer_name: str = Field(..., min_length=1)
    company_name: str = ""
    phone: str = Field(..., min_length=1)
    event_type: str = "wedding"
    event_date: str = ""
    guest_count: int = Field(10, ge=1)
    estimated_budget_fen: int = 0
    source: str = "walk_in"
    notes: str = ""


class CreateQuotationReq(BaseModel):
    lead_id: str = Field(..., min_length=1)
    tier: str = "standard"
    adjustments: dict = {}


class CollectDepositReq(BaseModel):
    method: str = "wechat"
    amount_fen: int = Field(0, ge=0)


class ConfirmMenuReq(BaseModel):
    menu_items: list[dict] = []


class SettleReq(BaseModel):
    payments: list[dict] = []


class FeedbackReq(BaseModel):
    overall_score: int = Field(5, ge=1, le=5)
    food_score: int = Field(5, ge=1, le=5)
    service_score: int = Field(5, ge=1, le=5)
    comments: str = ""


# ─── Endpoints ───

@router.post("/leads")
async def create_lead(body: CreateLeadReq, svc: BanquetIntegrationService = Depends(_svc)):
    """创建宴会线索"""
    try:
        result = await svc.create_lead(**body.model_dump())
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@router.get("/leads")
async def list_leads(
    status: str = "",
    page: int = 1,
    size: int = 20,
    svc: BanquetIntegrationService = Depends(_svc),
):
    """线索列表"""
    result = svc.lifecycle.get_sales_funnel()
    return _ok(result)


@router.put("/leads/{lead_id}/stage")
async def advance_stage(lead_id: str, target_stage: str, svc: BanquetIntegrationService = Depends(_svc)):
    """推进线索阶段"""
    try:
        result = svc.lifecycle.advance_stage(lead_id=lead_id, target_stage=target_stage)
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@router.post("/quotations")
async def create_quotation(body: CreateQuotationReq, svc: BanquetIntegrationService = Depends(_svc)):
    """创建报价单（含毛利检查）"""
    try:
        result = await svc.create_quotation(**body.model_dump())
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@router.post("/contracts")
async def create_contract(lead_id: str, svc: BanquetIntegrationService = Depends(_svc)):
    """签约"""
    try:
        result = svc.lifecycle.create_contract(lead_id=lead_id)
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@router.get("/contracts/{contract_id}")
async def get_contract(contract_id: str, svc: BanquetIntegrationService = Depends(_svc)):
    """合同详情"""
    try:
        result = svc.lifecycle.get_contract_detail(contract_id=contract_id)
        return _ok(result)
    except ValueError as e:
        return _err(str(e), "NOT_FOUND")


@router.post("/contracts/{contract_id}/deposit")
async def collect_deposit(contract_id: str, body: CollectDepositReq,
                          svc: BanquetIntegrationService = Depends(_svc)):
    """收定金（自动创建支付记录）"""
    try:
        result = await svc.collect_deposit(
            contract_id=contract_id,
            method=body.method,
            amount_fen=body.amount_fen,
        )
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@router.put("/contracts/{contract_id}/confirm-menu")
async def confirm_menu(contract_id: str, body: ConfirmMenuReq,
                       svc: BanquetIntegrationService = Depends(_svc)):
    """确认菜单（自动BOM展开+采购单）"""
    try:
        result = await svc.confirm_menu(
            contract_id=contract_id,
            menu_items=body.menu_items,
        )
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@router.post("/contracts/{contract_id}/execute")
async def start_execution(contract_id: str, svc: BanquetIntegrationService = Depends(_svc)):
    """开始执行（创建订单+KDS分单）"""
    try:
        result = await svc.start_execution(contract_id=contract_id)
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@router.post("/contracts/{contract_id}/settle")
async def settle_banquet(contract_id: str, body: SettleReq,
                         svc: BanquetIntegrationService = Depends(_svc)):
    """结账（扣除定金，尾款支付）"""
    try:
        result = await svc.settle_banquet(
            contract_id=contract_id,
            payments=body.payments,
        )
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@router.post("/contracts/{contract_id}/feedback")
async def complete_feedback(contract_id: str, body: FeedbackReq,
                            svc: BanquetIntegrationService = Depends(_svc)):
    """回访（自动更新会员积分）"""
    try:
        result = await svc.complete_feedback(
            contract_id=contract_id,
            **body.model_dump(),
        )
        return _ok(result)
    except ValueError as e:
        return _err(str(e))
