"""超级年卡 API — 6个端点

1. 年卡方案列表
2. 购买年卡
3. 权益清单
4. 权益使用情况
5. 续费
6. 赠送年卡
"""
from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/member/premium", tags=["premium-card"])


# ── 请求模型 ──────────────────────────────────────────────────

class PurchaseCardReq(BaseModel):
    customer_id: str
    plan_id: str  # silver / gold / diamond
    payment_id: str


class GiftCardReq(BaseModel):
    sender_id: str
    receiver_phone: str = Field(min_length=11, max_length=11)
    plan_id: str


# ── 1. 年卡方案列表 ──────────────────────────────────────────

@router.get("/plans")
async def list_annual_plans(
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """年卡方案列表 — 银卡698/金卡1298/钻石2998（元/年）"""
    from services.premium_card import ANNUAL_PLANS

    plans = [
        {"plan_id": k, **v}
        for k, v in ANNUAL_PLANS.items()
    ]
    return {
        "ok": True,
        "data": {"plans": plans},
    }


# ── 2. 购买年卡 ──────────────────────────────────────────────

@router.post("/purchase")
async def purchase_annual_card(
    body: PurchaseCardReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """购买超级年卡"""
    # TODO: 注入真实 DB session 后调用 premium_card.purchase_annual_card
    return {
        "ok": True,
        "data": {
            "card_id": "placeholder",
            "customer_id": body.customer_id,
            "plan_id": body.plan_id,
            "status": "active",
        },
    }


# ── 3. 权益清单 ──────────────────────────────────────────────

@router.get("/cards/{card_id}/benefits")
async def get_card_benefits(
    card_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """权益清单 — 折扣/免费菜/优先预订/专属客服"""
    # TODO: 注入真实 DB session 后调用 premium_card.get_card_benefits
    return {
        "ok": True,
        "data": {
            "card_id": card_id,
            "benefits": [],
            "status": "active",
            "days_remaining": 0,
        },
    }


# ── 4. 权益使用情况 ──────────────────────────────────────────

@router.get("/cards/{card_id}/usage")
async def check_benefit_usage(
    card_id: str,
    benefit_type: str = Query(..., description="权益类型key: free_dish_monthly/birthday_gift等"),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """权益使用情况 — 已用/剩余次数"""
    # TODO: 注入真实 DB session 后调用 premium_card.check_benefit_usage
    return {
        "ok": True,
        "data": {
            "card_id": card_id,
            "benefit_type": benefit_type,
            "total_quota": 0,
            "used": 0,
            "remaining": 0,
            "period": "monthly",
        },
    }


# ── 5. 续费 ──────────────────────────────────────────────────

@router.post("/cards/{card_id}/renew")
async def renew_card(
    card_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """续费年卡 — 在到期日基础上延长一年"""
    # TODO: 注入真实 DB session 后调用 premium_card.renew_card
    return {
        "ok": True,
        "data": {
            "card_id": card_id,
            "renewed": True,
        },
    }


# ── 6. 赠送年卡 ──────────────────────────────────────────────

@router.post("/gift")
async def gift_card(
    body: GiftCardReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """赠送年卡 — 购买并赠送给指定手机号用户"""
    # TODO: 注入真实 DB session 后调用 premium_card.gift_card
    return {
        "ok": True,
        "data": {
            "gift_id": "placeholder",
            "sender_id": body.sender_id,
            "receiver_phone": body.receiver_phone,
            "plan_id": body.plan_id,
            "status": "pending",
        },
    }
