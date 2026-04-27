"""宴会订单管理 API (Phase 1) — 订单CRUD / 定金 / 时间线 / 日程 / 取消 / 仪表盘

注意：本文件为宴会模块Phase 1新建路由，前缀 /api/v1/banquet/orders，
与原 banquet_order_routes.py（前缀 /api/v1/trade/banquet）功能区分。
"""

from typing import AsyncGenerator, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.banquet_crm_service import BanquetCRMService

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/banquet/orders", tags=["banquet-order"])


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


class CreateBanquetOrderReq(BaseModel):
    store_id: str
    lead_id: Optional[str] = None
    quote_id: Optional[str] = None
    venue_id: str
    customer_name: str = Field(min_length=1)
    phone: str = Field(min_length=1)
    event_type: str
    event_date: str  # YYYY-MM-DD
    time_slot: str  # lunch / dinner / full_day
    table_count: int = Field(ge=1)
    guest_count: int = Field(ge=1)
    total_amount_fen: int = Field(ge=0)
    deposit_required_fen: int = Field(0, ge=0)
    menu_items: list[dict] = Field(default_factory=list)
    special_requests: Optional[str] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None


class UpdateBanquetStatusReq(BaseModel):
    status: str
    reason: Optional[str] = None
    operator_id: Optional[str] = None


class RecordDepositReq(BaseModel):
    amount_fen: int = Field(gt=0)
    payment_method: str  # wechat / alipay / cash / bank_transfer
    payment_ref: Optional[str] = None
    received_by: Optional[str] = None
    notes: Optional[str] = None


class CancelBanquetReq(BaseModel):
    reason: str = Field(min_length=1)
    cancelled_by: Optional[str] = None
    refund_deposit: bool = False
    refund_amount_fen: Optional[int] = Field(None, ge=0)


# ─── Endpoints ───


@router.post("/")
async def create_banquet_order(
    body: CreateBanquetOrderReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """创建宴会订单"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.create_banquet_order(body.model_dump())
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/")
async def list_banquet_orders(
    request: Request,
    store_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    event_date_from: Optional[str] = Query(None),
    event_date_to: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_db_session),
):
    """列表查询宴会订单"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.list_banquet_orders(
            store_id=store_id,
            status=status,
            event_date_from=event_date_from,
            event_date_to=event_date_to,
            event_type=event_type,
            page=page,
            size=size,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/dashboard/{store_id}")
async def get_dashboard(
    store_id: str,
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(_get_db_session),
):
    """获取宴会仪表盘汇总"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.get_banquet_dashboard(store_id=store_id, date_from=date_from, date_to=date_to)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/schedule/{store_id}/{date}")
async def get_day_schedule(
    store_id: str,
    date: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """获取指定日期的宴会日程"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.get_day_schedule(store_id=store_id, date=date)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/{banquet_id}")
async def get_banquet_order(
    banquet_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """获取宴会订单详情"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.get_banquet_order(banquet_id=banquet_id)
        if not result:
            _err("Banquet order not found", code=404)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.patch("/{banquet_id}/status")
async def update_banquet_status(
    banquet_id: str,
    body: UpdateBanquetStatusReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """更新宴会订单状态"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.update_banquet_status(
            banquet_id=banquet_id,
            status=body.status,
            reason=body.reason,
            operator_id=body.operator_id,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/{banquet_id}/deposit")
async def record_deposit(
    banquet_id: str,
    body: RecordDepositReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """记录定金收取"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.record_deposit(banquet_id=banquet_id, data=body.model_dump())
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/{banquet_id}/timeline")
async def get_timeline(
    banquet_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """获取宴会订单时间线"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.get_banquet_timeline(banquet_id=banquet_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/{banquet_id}/cancel")
async def cancel_banquet(
    banquet_id: str,
    body: CancelBanquetReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """取消宴会订单"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetCRMService(tenant_id=tenant_id, db=db)
    try:
        result = await svc.cancel_banquet(banquet_id=banquet_id, data=body.model_dump())
        return _ok(result)
    except ValueError as e:
        _err(str(e))
