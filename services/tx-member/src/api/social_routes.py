"""社交裂变 API -- 6端点

拼单/加入拼单/请客送礼/分享有礼/推荐追踪/社交统计
所有路由需要 X-Tenant-ID header。
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.social_engine import (
    create_group_order,
    create_share_link,
    get_social_stats,
    join_group_order,
    send_gift,
    track_referral,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/social", tags=["social"])


# ── 请求模型 ──────────────────────────────────────────────────

class CreateGroupOrderReq(BaseModel):
    initiator_id: str
    store_id: str
    table_id: Optional[str] = None


class JoinGroupOrderReq(BaseModel):
    customer_id: str


class SendGiftReq(BaseModel):
    sender_id: str
    receiver_phone: str
    gift_type: str  # dish | card | coupon
    gift_config: dict[str, Any] = Field(default_factory=dict)


class CreateShareLinkReq(BaseModel):
    customer_id: str
    campaign_type: str  # new_user | reactivation | group_buy


class TrackReferralReq(BaseModel):
    referrer_id: str
    new_customer_id: str


# ── 1. 创建拼单 ─────────────────────────────────────────────

@router.post("/group-orders")
async def api_create_group_order(
    body: CreateGroupOrderReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建拼单（多人各点各的）"""
    result = await create_group_order(
        initiator_id=body.initiator_id,
        store_id=body.store_id,
        table_id=body.table_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}


# ── 2. 加入拼单 ─────────────────────────────────────────────

@router.post("/group-orders/{group_id}/join")
async def api_join_group_order(
    group_id: str,
    body: JoinGroupOrderReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """加入拼单"""
    result = await join_group_order(
        group_id=group_id,
        customer_id=body.customer_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}


# ── 3. 请客/送礼 ───────────────────────────────────────────

@router.post("/gifts")
async def api_send_gift(
    body: SendGiftReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """请客/送菜品/送礼品卡"""
    result = await send_gift(
        sender_id=body.sender_id,
        receiver_phone=body.receiver_phone,
        gift_type=body.gift_type,
        gift_config=body.gift_config,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}


# ── 4. 分享有礼链接 ─────────────────────────────────────────

@router.post("/share-links")
async def api_create_share_link(
    body: CreateShareLinkReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """分享有礼链接"""
    result = await create_share_link(
        customer_id=body.customer_id,
        campaign_type=body.campaign_type,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}


# ── 5. 追踪推荐关系 ─────────────────────────────────────────

@router.post("/referrals")
async def api_track_referral(
    body: TrackReferralReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """追踪推荐关系+发放奖励"""
    result = await track_referral(
        referrer_id=body.referrer_id,
        new_customer_id=body.new_customer_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}


# ── 6. 社交统计 ─────────────────────────────────────────────

@router.get("/stats/{customer_id}")
async def api_social_stats(
    customer_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """社交统计（推荐人数/获得奖励/拼单次数）"""
    result = await get_social_stats(
        customer_id=customer_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result, "error": None}
