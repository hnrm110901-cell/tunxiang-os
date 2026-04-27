"""宴会线索管理 API — 线索CRUD / 分配 / 跟进 / 转让 / 漏斗"""

from typing import AsyncGenerator, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.banquet_crm_service import BanquetCRMService

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/banquet/leads", tags=["banquet-crm"])


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


# ─── Request / Response Models ───


class CreateLeadReq(BaseModel):
    store_id: str
    customer_name: str = Field(min_length=1)
    phone: str = Field(min_length=1)
    event_type: str
    company: Optional[str] = None
    event_date: Optional[str] = None  # YYYY-MM-DD
    guest_count_est: Optional[int] = Field(None, ge=1)
    table_count_est: Optional[int] = Field(None, ge=1)
    budget_per_table_fen: int = 0
    source_channel: str = "walk_in"
    notes: Optional[str] = None


class UpdateLeadReq(BaseModel):
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    event_type: Optional[str] = None
    company: Optional[str] = None
    event_date: Optional[str] = None
    guest_count_est: Optional[int] = Field(None, ge=1)
    table_count_est: Optional[int] = Field(None, ge=1)
    budget_per_table_fen: Optional[int] = None
    source_channel: Optional[str] = None
    notes: Optional[str] = None


class AssignSalesReq(BaseModel):
    sales_id: str


class AddFollowUpReq(BaseModel):
    sales_id: str
    follow_type: str
    content: str = Field(min_length=1)
    next_action: Optional[str] = None
    next_follow_at: Optional[str] = None


class TransferLeadReq(BaseModel):
    from_employee_id: str
    to_employee_id: str
    reason: Optional[str] = None


class UpdateStatusReq(BaseModel):
    status: str
    reason: Optional[str] = None


# ─── Endpoints ───


@router.post("/")
async def create_lead(
    body: CreateLeadReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """创建宴会线索"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.create_lead(body.model_dump())
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/")
async def list_leads(
    request: Request,
    store_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    assigned_sales_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_db_session),
):
    """列表查询线索（支持多维过滤）"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.list_leads(
            store_id=store_id,
            status=status,
            event_type=event_type,
            date_from=date_from,
            date_to=date_to,
            assigned_sales_id=assigned_sales_id,
            page=page,
            size=size,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/funnel/{store_id}")
async def get_conversion_funnel(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """获取线索转化漏斗"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.get_conversion_funnel(store_id=store_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/due/{store_id}")
async def get_leads_due_followup(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """获取待跟进线索列表"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.get_leads_due_followup(store_id=store_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/{lead_id}")
async def get_lead(
    lead_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """获取线索详情"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.get_lead(lead_id=lead_id)
        if not result:
            _err("Lead not found", code=404)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.patch("/{lead_id}")
async def update_lead(
    lead_id: str,
    body: UpdateLeadReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """更新线索信息"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        updates = body.model_dump(exclude_unset=True)
        result = await svc.update_lead(lead_id=lead_id, updates=updates)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/{lead_id}/assign")
async def assign_sales(
    lead_id: str,
    body: AssignSalesReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """分配销售"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.assign_sales(lead_id=lead_id, sales_id=body.sales_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/{lead_id}/follow-up")
async def add_follow_up(
    lead_id: str,
    body: AddFollowUpReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """新增跟进记录"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.add_follow_up(lead_id=lead_id, data=body.model_dump())
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/{lead_id}/follow-ups")
async def list_follow_ups(
    lead_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """获取线索跟进记录列表"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.list_follow_ups(lead_id=lead_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/{lead_id}/transfer")
async def transfer_lead(
    lead_id: str,
    body: TransferLeadReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """转让线索"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.transfer_lead(
            lead_id=lead_id,
            from_employee_id=body.from_employee_id,
            to_employee_id=body.to_employee_id,
            reason=body.reason,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.patch("/{lead_id}/status")
async def update_lead_status(
    lead_id: str,
    body: UpdateStatusReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """更新线索状态"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.update_status(lead_id=lead_id, status=body.status, reason=body.reason)
        return _ok(result)
    except ValueError as e:
        _err(str(e))
