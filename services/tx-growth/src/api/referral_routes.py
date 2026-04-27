"""裂变拉新 API — 邀请有礼（老带新）

端点：
  POST  /api/v1/growth/referrals/campaigns              创建裂变活动
  GET   /api/v1/growth/referrals/campaigns              活动列表
  GET   /api/v1/growth/referrals/campaigns/{id}/stats   活动统计
  POST  /api/v1/growth/referrals/invite/generate        生成邀请链接（小程序端调用）
  POST  /api/v1/growth/referrals/invite/register        新用户通过邀请码注册
  POST  /api/v1/growth/referrals/invite/first-order     首单触发奖励
  GET   /api/v1/growth/referrals/my-invites             我的邀请记录
"""

import uuid
from datetime import datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, field_validator
from services.referral_service import ReferralError, ReferralService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/referrals", tags=["referrals"])

_svc = ReferralService()


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str, code: str = "ERROR") -> dict:
    return {"ok": False, "error": {"code": code, "message": msg}}


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------


class CreateCampaignRequest(BaseModel):
    name: str
    referrer_reward_type: str  # coupon|points|stored_value
    referrer_reward_value: int
    referrer_reward_condition: str  # new_register|first_order
    invitee_reward_type: str
    invitee_reward_value: int
    max_referrals_per_user: int = 0
    min_order_amount_fen: int = 0
    valid_days: int = 30
    anti_fraud_same_device: bool = True
    anti_fraud_same_ip: bool = False
    anti_fraud_same_phone_prefix: bool = True
    valid_from: datetime
    valid_until: Optional[datetime] = None

    @field_validator("referrer_reward_type", "invitee_reward_type")
    @classmethod
    def validate_reward_type(cls, v: str) -> str:
        allowed = {"coupon", "points", "stored_value"}
        if v not in allowed:
            raise ValueError(f"reward_type 必须是 {allowed} 之一")
        return v

    @field_validator("referrer_reward_condition")
    @classmethod
    def validate_reward_condition(cls, v: str) -> str:
        allowed = {"new_register", "first_order"}
        if v not in allowed:
            raise ValueError(f"referrer_reward_condition 必须是 {allowed} 之一")
        return v

    @field_validator("referrer_reward_value", "invitee_reward_value")
    @classmethod
    def validate_reward_value(cls, v: int) -> int:
        if v < 0:
            raise ValueError("奖励值不能为负数")
        return v

    @field_validator("min_order_amount_fen")
    @classmethod
    def validate_min_order(cls, v: int) -> int:
        if v < 0:
            raise ValueError("最低订单金额不能为负数")
        return v


class GenerateInviteLinkRequest(BaseModel):
    campaign_id: uuid.UUID
    referrer_customer_id: uuid.UUID


class RegisterViaInviteRequest(BaseModel):
    invite_code: str
    new_customer_id: uuid.UUID
    device_id: Optional[str] = None
    phone: Optional[str] = None


class FirstOrderRequest(BaseModel):
    order_id: str
    customer_id: uuid.UUID
    order_amount_fen: int

    @field_validator("order_amount_fen")
    @classmethod
    def validate_amount(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("订单金额必须大于0")
        return v


# ---------------------------------------------------------------------------
# 端点实现
# ---------------------------------------------------------------------------


@router.post("/campaigns")
async def create_campaign(
    req: CreateCampaignRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建裂变活动（初始状态为 draft，需手动启动）"""
    from models.referral import ReferralCampaign
    from sqlalchemy.ext.asyncio import AsyncSession

    tenant_id = uuid.UUID(x_tenant_id)
    db: AsyncSession = request.state.db  # 由中间件注入

    campaign = ReferralCampaign(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=req.name,
        status="draft",
        referrer_reward_type=req.referrer_reward_type,
        referrer_reward_value=req.referrer_reward_value,
        referrer_reward_condition=req.referrer_reward_condition,
        invitee_reward_type=req.invitee_reward_type,
        invitee_reward_value=req.invitee_reward_value,
        max_referrals_per_user=req.max_referrals_per_user,
        min_order_amount_fen=req.min_order_amount_fen,
        valid_days=req.valid_days,
        anti_fraud_same_device=req.anti_fraud_same_device,
        anti_fraud_same_ip=req.anti_fraud_same_ip,
        anti_fraud_same_phone_prefix=req.anti_fraud_same_phone_prefix,
        valid_from=req.valid_from,
        valid_until=req.valid_until,
    )
    db.add(campaign)
    await db.commit()

    log.info(
        "referral.campaign_created",
        campaign_id=str(campaign.id),
        name=campaign.name,
        tenant_id=x_tenant_id,
    )
    return ok_response(
        {
            "campaign_id": str(campaign.id),
            "name": campaign.name,
            "status": campaign.status,
        }
    )


@router.get("/campaigns")
async def list_campaigns(
    request: Request,
    status: Optional[str] = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取裂变活动列表（支持按 status 过滤）"""
    from models.referral import ReferralCampaign
    from sqlalchemy import select

    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    query = select(ReferralCampaign).where(
        ReferralCampaign.tenant_id == tenant_id,
        ReferralCampaign.is_deleted == False,  # noqa: E712
    )
    if status:
        query = query.where(ReferralCampaign.status == status)
    query = query.order_by(ReferralCampaign.created_at.desc())

    result = await db.execute(query)
    campaigns = result.scalars().all()

    return ok_response(
        {
            "items": [
                {
                    "campaign_id": str(c.id),
                    "name": c.name,
                    "status": c.status,
                    "valid_from": c.valid_from.isoformat() if c.valid_from else None,
                    "valid_until": c.valid_until.isoformat() if c.valid_until else None,
                    "referrer_reward_type": c.referrer_reward_type,
                    "invitee_reward_type": c.invitee_reward_type,
                }
                for c in campaigns
            ],
            "total": len(campaigns),
        }
    )


@router.get("/campaigns/{campaign_id}/stats")
async def get_campaign_stats(
    campaign_id: uuid.UUID,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取裂变活动效果统计"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        stats = await _svc.get_referral_stats(campaign_id, tenant_id, db)
    except ReferralError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc

    return ok_response(stats)


@router.post("/invite/generate")
async def generate_invite_link(
    req: GenerateInviteLinkRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """老会员生成专属邀请链接（小程序端调用）"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _svc.generate_invite_link(
            campaign_id=req.campaign_id,
            referrer_customer_id=req.referrer_customer_id,
            tenant_id=tenant_id,
            db=db,
        )
    except ReferralError as exc:
        status_code = 400 if exc.code != "CAMPAIGN_NOT_FOUND" else 404
        raise HTTPException(status_code=status_code, detail=exc.message) from exc

    return ok_response(result)


@router.post("/invite/register")
async def register_via_invite(
    req: RegisterViaInviteRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """新用户通过邀请码完成注册绑定

    客户端需传入：邀请码、新用户 customer_id、设备 ID（可选）、手机号（可选）。
    IP 地址由服务端从请求上下文自动读取。
    """
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    # 从请求上下文获取客户端 IP（防刷用）
    client_ip: Optional[str] = None
    if request.client:
        client_ip = request.client.host

    try:
        result = await _svc.register_via_invite(
            invite_code=req.invite_code,
            new_customer_id=req.new_customer_id,
            device_id=req.device_id,
            ip=client_ip,
            phone=req.phone,
            tenant_id=tenant_id,
            db=db,
        )
    except ReferralError as exc:
        fraud_codes = {
            "FRAUD_SELF_REFERRAL",
            "FRAUD_SAME_DEVICE",
            "FRAUD_SAME_PHONE_PREFIX",
            "FRAUD_SAME_IP",
        }
        status_code = 403 if exc.code in fraud_codes else 400
        if exc.code == "INVITE_CODE_NOT_FOUND":
            status_code = 404
        raise HTTPException(status_code=status_code, detail=exc.message) from exc

    return ok_response(result)


@router.post("/invite/first-order")
async def first_order_trigger(
    req: FirstOrderRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """新用户首单完成后触发邀请人奖励（由 tx-trade 或旅程节点调用）"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    result = await _svc.process_first_order(
        order_id=req.order_id,
        customer_id=req.customer_id,
        order_amount_fen=req.order_amount_fen,
        tenant_id=tenant_id,
        db=db,
    )
    return ok_response(result)


@router.get("/my-invites")
async def get_my_invites(
    request: Request,
    campaign_id: uuid.UUID,
    customer_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取我的邀请记录（小程序端个人中心展示）"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _svc.get_my_referrals(
            customer_id=customer_id,
            campaign_id=campaign_id,
            tenant_id=tenant_id,
            db=db,
        )
    except ReferralError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc

    return ok_response(result)
