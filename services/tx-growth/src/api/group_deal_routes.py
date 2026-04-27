"""拼团 + 双向奖励 API — Social Viral S4W14-15

端点：
  POST  /api/v1/growth/group-deals              创建拼团
  GET   /api/v1/growth/group-deals              拼团列表（分页/筛选）
  GET   /api/v1/growth/group-deals/stats        拼团统计
  GET   /api/v1/growth/group-deals/leaderboard  推荐排行榜（from dual_rewards）
  GET   /api/v1/growth/group-deals/{id}         拼团详情+参与者
  POST  /api/v1/growth/group-deals/{id}/join    参团
  POST  /api/v1/growth/group-deals/{id}/leave   退团
  POST  /api/v1/growth/group-deals/{id}/pay     记录参团者支付
"""

import uuid
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, field_validator

from services.dual_reward_service import DualRewardError, DualRewardService
from services.group_deal_service import GroupDealError, GroupDealService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/group-deals", tags=["group-deals"])

_deal_svc = GroupDealService()
_reward_svc = DualRewardService()


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok_response(data: object) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str, code: str = "ERROR") -> dict:
    return {"ok": False, "error": {"code": code, "message": msg}}


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class CreateDealRequest(BaseModel):
    store_id: uuid.UUID
    name: str
    min_participants: int
    original_price_fen: int
    deal_price_fen: int
    expires_at: datetime
    initiator_customer_id: uuid.UUID
    dish_id: Optional[uuid.UUID] = None
    description: Optional[str] = None
    max_participants: int = 10

    @field_validator("min_participants")
    @classmethod
    def validate_min(cls, v: int) -> int:
        if v < 2:
            raise ValueError("最少参团人数不能小于2")
        return v

    @field_validator("original_price_fen", "deal_price_fen")
    @classmethod
    def validate_price(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("价格必须大于0")
        return v


class JoinDealRequest(BaseModel):
    customer_id: uuid.UUID


class LeaveDealRequest(BaseModel):
    customer_id: uuid.UUID


class PayDealRequest(BaseModel):
    customer_id: uuid.UUID
    order_id: uuid.UUID


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@router.post("")
async def create_deal(
    req: CreateDealRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建拼团活动"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _deal_svc.create_deal(
            tenant_id=tenant_id,
            store_id=req.store_id,
            name=req.name,
            min_participants=req.min_participants,
            original_price_fen=req.original_price_fen,
            deal_price_fen=req.deal_price_fen,
            expires_at=req.expires_at,
            initiator_customer_id=req.initiator_customer_id,
            db=db,
            dish_id=req.dish_id,
            description=req.description,
            max_participants=req.max_participants,
        )
        return ok_response(result)
    except GroupDealError as e:
        raise HTTPException(status_code=400, detail=error_response(e.message, e.code))


@router.get("")
async def list_deals(
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """拼团列表（分页/筛选）"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    result = await _deal_svc.list_deals(
        tenant_id=tenant_id,
        db=db,
        store_id=uuid.UUID(store_id) if store_id else None,
        status=status,
        page=page,
        size=size,
    )
    return ok_response(result)


@router.get("/stats")
async def get_stats(
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    days: int = 30,
) -> dict:
    """拼团统计"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    result = await _deal_svc.get_deal_stats(
        tenant_id=tenant_id, db=db, days=days
    )
    return ok_response(result)


@router.get("/leaderboard")
async def get_leaderboard(
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    limit: int = 20,
) -> dict:
    """推荐排行榜（from dual_rewards）"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    result = await _reward_svc.get_referral_leaderboard(
        tenant_id=tenant_id, db=db, limit=limit
    )
    return ok_response(result)


@router.get("/{deal_id}")
async def get_deal(
    deal_id: uuid.UUID,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """拼团详情+参与者"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _deal_svc.get_deal(
            tenant_id=tenant_id, deal_id=deal_id, db=db
        )
        return ok_response(result)
    except GroupDealError as e:
        raise HTTPException(status_code=404, detail=error_response(e.message, e.code))


@router.post("/{deal_id}/join")
async def join_deal(
    deal_id: uuid.UUID,
    req: JoinDealRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """参团"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _deal_svc.join_deal(
            tenant_id=tenant_id,
            deal_id=deal_id,
            customer_id=req.customer_id,
            db=db,
        )
        return ok_response(result)
    except GroupDealError as e:
        status = 400
        if e.code == "DEAL_NOT_FOUND":
            status = 404
        elif e.code in ("DEAL_FULL", "DEAL_NOT_OPEN", "DEAL_EXPIRED", "ALREADY_JOINED"):
            status = 409
        raise HTTPException(status_code=status, detail=error_response(e.message, e.code))


@router.post("/{deal_id}/leave")
async def leave_deal(
    deal_id: uuid.UUID,
    req: LeaveDealRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """退团"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _deal_svc.leave_deal(
            tenant_id=tenant_id,
            deal_id=deal_id,
            customer_id=req.customer_id,
            db=db,
        )
        return ok_response(result)
    except GroupDealError as e:
        status = 400
        if e.code == "NOT_IN_DEAL":
            status = 404
        elif e.code in ("ALREADY_PAID", "INITIATOR_CANNOT_LEAVE"):
            status = 409
        raise HTTPException(status_code=status, detail=error_response(e.message, e.code))


@router.post("/{deal_id}/pay")
async def pay_deal(
    deal_id: uuid.UUID,
    req: PayDealRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """记录参团者支付"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _deal_svc.record_payment(
            tenant_id=tenant_id,
            deal_id=deal_id,
            customer_id=req.customer_id,
            order_id=req.order_id,
            db=db,
        )
        return ok_response(result)
    except GroupDealError as e:
        status = 400
        if e.code == "NOT_IN_DEAL":
            status = 404
        elif e.code == "ALREADY_PAID":
            status = 409
        raise HTTPException(status_code=status, detail=error_response(e.message, e.code))
