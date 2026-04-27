"""宴会报价管理 API — 模板CRUD / 报价生成 / 菜单定制 / 方案对比"""

from typing import AsyncGenerator, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.banquet_crm_service import BanquetCRMService

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/banquet/quotes", tags=["banquet-quote"])


# ─── 依赖注入 ───


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    tenant_id = _get_tenant_id(request)
    async for session in get_db_with_tenant(tenant_id):
        yield session


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


# ─── Request Models ───


class CreateTemplateReq(BaseModel):
    store_id: str
    name: str = Field(min_length=1)
    event_type: str
    tier: str = "standard"
    description: Optional[str] = None
    base_price_per_table_fen: int = Field(ge=0)
    min_tables: int = Field(1, ge=1)
    menu_items: list[dict] = Field(default_factory=list)
    included_services: list[str] = Field(default_factory=list)
    optional_addons: list[dict] = Field(default_factory=list)


class UpdateTemplateReq(BaseModel):
    name: Optional[str] = None
    event_type: Optional[str] = None
    tier: Optional[str] = None
    description: Optional[str] = None
    base_price_per_table_fen: Optional[int] = Field(None, ge=0)
    min_tables: Optional[int] = Field(None, ge=1)
    menu_items: Optional[list[dict]] = None
    included_services: Optional[list[str]] = None
    optional_addons: Optional[list[dict]] = None
    is_active: Optional[bool] = None


class GenerateQuoteReq(BaseModel):
    lead_id: str
    template_id: str
    table_count: int = Field(ge=1)
    adjustments: dict = Field(default_factory=dict)
    notes: Optional[str] = None


class UpdateQuoteStatusReq(BaseModel):
    status: str
    reason: Optional[str] = None


class CustomizeMenuReq(BaseModel):
    menu_items: list[dict] = Field(default_factory=list)
    special_requests: Optional[str] = None


class CompareQuotesReq(BaseModel):
    quote_ids: list[str] = Field(min_length=2, max_length=5)


# ─── Endpoints: Templates ───


@router.post("/templates")
async def create_template(
    body: CreateTemplateReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """创建报价模板"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.create_quote_template(body.model_dump())
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/templates")
async def list_templates(
    request: Request,
    store_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: AsyncSession = Depends(_get_db_session),
):
    """列表查询报价模板"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.list_quote_templates(
            store_id=store_id,
            event_type=event_type,
            tier=tier,
            is_active=is_active,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """获取报价模板详情"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.get_quote_template(template_id=template_id)
        if not result:
            _err("Template not found", code=404)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.put("/templates/{template_id}")
async def update_template(
    template_id: str,
    body: UpdateTemplateReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """更新报价模板"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        updates = body.model_dump(exclude_unset=True)
        result = await svc.update_quote_template(template_id=template_id, updates=updates)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── Endpoints: Quotes ───


@router.post("/")
async def generate_quote(
    body: GenerateQuoteReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """基于模板生成报价单"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.generate_quote(body.model_dump())
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/compare")
async def compare_quotes_get(
    request: Request,
    quote_ids: str = Query(..., description="Comma-separated quote IDs"),
    db: AsyncSession = Depends(_get_db_session),
):
    """对比多个报价方案（GET方式，逗号分隔ID）"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        ids = [qid.strip() for qid in quote_ids.split(",") if qid.strip()]
        if len(ids) < 2:
            _err("At least 2 quote IDs required for comparison")
        result = await svc.compare_quotes(quote_ids=ids)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/compare")
async def compare_quotes(
    body: CompareQuotesReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """对比多个报价方案"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.compare_quotes(quote_ids=body.quote_ids)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/by-lead/{lead_id}")
async def list_quotes_by_lead(
    lead_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """获取线索关联的所有报价"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.list_quotes_by_lead(lead_id=lead_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/{quote_id}")
async def get_quote(
    quote_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """获取报价详情"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.get_quote(quote_id=quote_id)
        if not result:
            _err("Quote not found", code=404)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.patch("/{quote_id}/status")
async def update_quote_status(
    quote_id: str,
    body: UpdateQuoteStatusReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """更新报价状态"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.update_quote_status(quote_id=quote_id, status=body.status, reason=body.reason)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.put("/{quote_id}/menu")
async def customize_menu(
    quote_id: str,
    body: CustomizeMenuReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """定制报价菜单"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.customize_quote_menu(
            quote_id=quote_id,
            menu_items=body.menu_items,
            special_requests=body.special_requests,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))
