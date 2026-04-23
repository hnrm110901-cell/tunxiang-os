"""宴会全流程 API — 线索→报价→签约→定金→菜单→执行→结账→回访→套餐模板"""

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services import banquet_template_service as tpl_svc
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
async def collect_deposit(contract_id: str, body: CollectDepositReq, svc: BanquetIntegrationService = Depends(_svc)):
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
async def confirm_menu(contract_id: str, body: ConfirmMenuReq, svc: BanquetIntegrationService = Depends(_svc)):
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
async def settle_banquet(contract_id: str, body: SettleReq, svc: BanquetIntegrationService = Depends(_svc)):
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
async def complete_feedback(contract_id: str, body: FeedbackReq, svc: BanquetIntegrationService = Depends(_svc)):
    """回访（自动更新会员积分）"""
    try:
        result = await svc.complete_feedback(
            contract_id=contract_id,
            **body.model_dump(),
        )
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


# ─── 套餐模板引擎 Request Models ───────────────────────────────────────────


class TemplateItemReq(BaseModel):
    dish_name: str = Field(..., min_length=1)
    dish_category: str | None = None
    quantity: float = Field(1.0, gt=0)
    unit: str = "道"
    is_signature: bool = False
    is_optional: bool = False
    notes: str | None = None
    sort_order: int = 0


class CreateTemplateReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(..., pattern="^(wedding|business|birthday|festival|other)$")
    description: str | None = None
    guest_count_min: int = Field(1, ge=1)
    guest_count_max: int = Field(999, ge=1)
    price_per_table_fen: int = Field(..., gt=0, description="每桌价格（分）")
    price_per_person_fen: int | None = Field(None, gt=0, description="每位价格（分，可选）")
    min_table_count: int = Field(1, ge=1)
    deposit_rate: float = Field(0.3, gt=0, le=1.0)
    store_id: str | None = None
    items: list[TemplateItemReq] = []


class UpdateTemplateReq(BaseModel):
    name: str | None = Field(None, max_length=200)
    category: str | None = Field(None, pattern="^(wedding|business|birthday|festival|other)$")
    description: str | None = None
    guest_count_min: int | None = Field(None, ge=1)
    guest_count_max: int | None = Field(None, ge=1)
    price_per_table_fen: int | None = Field(None, gt=0)
    price_per_person_fen: int | None = Field(None, gt=0)
    min_table_count: int | None = Field(None, ge=1)
    deposit_rate: float | None = Field(None, gt=0, le=1.0)
    store_id: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None
    items: list[TemplateItemReq] | None = None


class BuildQuoteReq(BaseModel):
    guest_count: int = Field(..., ge=1)
    table_count: int = Field(..., ge=1)
    adjustments: dict = Field(
        default_factory=dict,
        description="价格调整：{discount_fen: int, extra_fen: int}",
    )


# ─── 套餐模板引擎 Endpoints ────────────────────────────────────────────────


def _tenant_id(request: Request) -> str:
    return getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")


@router.post("/templates")
async def create_template(
    body: CreateTemplateReq,
    request: Request,
    db: AsyncSession = Depends(_get_db),
):
    """创建宴席套餐模板"""
    tenant_id = _tenant_id(request)
    try:
        result = await tpl_svc.create_template(
            **body.model_dump(exclude={"items"}),
            items=[i.model_dump() for i in body.items],
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@router.get("/templates")
async def list_templates(
    request: Request,
    category: str | None = None,
    store_id: str | None = None,
    guest_count: int | None = None,
    db: AsyncSession = Depends(_get_db),
):
    """列出套餐模板（?category=wedding&guest_count=200&store_id=xxx）"""
    tenant_id = _tenant_id(request)
    result = await tpl_svc.list_templates(
        category=category,
        store_id=store_id,
        guest_count=guest_count,
        tenant_id=tenant_id,
        db=db,
    )
    return _ok(result)


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db),
):
    """套餐模板详情"""
    tenant_id = _tenant_id(request)
    try:
        result = await tpl_svc.get_template(
            template_id=template_id,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as e:
        return _err(str(e), "NOT_FOUND")


@router.put("/templates/{template_id}")
async def update_template(
    template_id: str,
    body: UpdateTemplateReq,
    request: Request,
    db: AsyncSession = Depends(_get_db),
):
    """更新套餐模板（支持部分更新，传 items 则整体替换菜品明细）"""
    tenant_id = _tenant_id(request)
    try:
        raw_updates = body.model_dump(exclude_none=True)
        # items 需要转为 dict 列表
        if "items" in raw_updates and body.items is not None:
            raw_updates["items"] = [i.model_dump() for i in body.items]
        result = await tpl_svc.update_template(
            template_id=template_id,
            updates=raw_updates,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as e:
        return _err(str(e))


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db),
):
    """删除套餐模板（软删除）"""
    tenant_id = _tenant_id(request)
    try:
        await tpl_svc.delete_template(
            template_id=template_id,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok({"template_id": template_id, "deleted": True})
    except ValueError as e:
        return _err(str(e), "NOT_FOUND")


@router.post("/templates/{template_id}/build-quote")
async def build_quote_from_template(
    template_id: str,
    body: BuildQuoteReq,
    request: Request,
    db: AsyncSession = Depends(_get_db),
):
    """从套餐模板生成宴席报价单"""
    tenant_id = _tenant_id(request)
    try:
        result = await tpl_svc.build_quotation_from_template(
            template_id=template_id,
            guest_count=body.guest_count,
            table_count=body.table_count,
            adjustments=body.adjustments,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as e:
        return _err(str(e))
