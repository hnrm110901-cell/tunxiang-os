"""付费会员订阅 API — 月卡/季卡/年卡

前缀: /api/v1/member/subscriptions

端点:
  POST /                   — 创建订阅（下单+生成微信支付参数）
  GET  /my                 — 查询当前用户的活跃订阅
  POST /{id}/cancel        — 取消自动续费
  GET  /plans              — 获取可用订阅方案列表
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/member/subscriptions", tags=["subscription"])


# ─── Models ────────────────────────────────────────────────────────────────────

class SubscriptionPlan(BaseModel):
    plan_id: str
    name: str
    price_fen: int
    period_days: int
    benefits: list[str]
    popular: bool = False


class CreateSubscriptionRequest(BaseModel):
    plan_id: str  # monthly | quarterly | yearly


class SubscriptionResponse(BaseModel):
    subscription_id: str
    plan_id: str
    plan_name: str
    status: str  # active | expired | cancelled
    started_at: str
    expires_at: str
    auto_renew: bool


# ─── Data ──────────────────────────────────────────────────────────────────────

PLANS: dict[str, SubscriptionPlan] = {
    "monthly": SubscriptionPlan(
        plan_id="monthly", name="月卡", price_fen=1990, period_days=30,
        benefits=["每单9折", "免配送费", "生日双倍积分", "专属会员价"],
    ),
    "quarterly": SubscriptionPlan(
        plan_id="quarterly", name="季卡", price_fen=4990, period_days=90, popular=True,
        benefits=["月卡全部权益", "每月满50减20券", "新品优先体验", "积分1.5倍"],
    ),
    "yearly": SubscriptionPlan(
        plan_id="yearly", name="年卡", price_fen=16800, period_days=365,
        benefits=["季卡全部权益", "专属客服", "优先排队", "生日免费菜品", "积分2倍", "跨品牌通用"],
    ),
}

# 内存存储（生产环境替换为DB）
_subscriptions: dict[str, SubscriptionResponse] = {}


def _require_tenant(tenant_id: Optional[str]) -> str:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID required")
    return tenant_id


# ─── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/plans")
async def list_plans(
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
):
    """获取可用订阅方案"""
    _require_tenant(x_tenant_id)
    return {"ok": True, "data": {"plans": [p.model_dump() for p in PLANS.values()]}}


@router.post("")
async def create_subscription(
    req: CreateSubscriptionRequest,
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
):
    """创建订阅 — 生成微信支付参数"""
    tid = _require_tenant(x_tenant_id)
    plan = PLANS.get(req.plan_id)
    if not plan:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {req.plan_id}")

    sub_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=plan.period_days)

    sub = SubscriptionResponse(
        subscription_id=sub_id,
        plan_id=plan.plan_id,
        plan_name=plan.name,
        status="active",
        started_at=now.isoformat(),
        expires_at=expires.isoformat(),
        auto_renew=True,
    )
    _subscriptions[f"{tid}:{sub_id}"] = sub

    # TODO: 调用微信支付统一下单API，返回真实支付参数
    # 当前返回mock支付参数供前端测试
    payment_params = {
        "timeStamp": str(int(now.timestamp())),
        "nonceStr": uuid.uuid4().hex[:16],
        "package": f"prepay_id=mock_{sub_id[:8]}",
        "signType": "RSA",
        "paySign": "mock_sign_" + sub_id[:8],
    }

    logger.info("subscription_created", tenant=tid, plan=plan.plan_id, sub_id=sub_id, price_fen=plan.price_fen)

    return {
        "ok": True,
        "data": {
            "subscription_id": sub_id,
            "payment_params": payment_params,
        },
    }


@router.get("/my")
async def get_my_subscription(
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
):
    """查询当前活跃订阅"""
    tid = _require_tenant(x_tenant_id)

    # 查找该租户的活跃订阅
    active = None
    for key, sub in _subscriptions.items():
        if key.startswith(f"{tid}:") and sub.status == "active":
            active = sub
            break

    if not active:
        return {"ok": True, "data": {"plan_id": None, "expires_at": None}}

    return {"ok": True, "data": active.model_dump()}


@router.post("/{subscription_id}/cancel")
async def cancel_subscription(
    subscription_id: str,
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
):
    """取消自动续费"""
    tid = _require_tenant(x_tenant_id)
    key = f"{tid}:{subscription_id}"

    sub = _subscriptions.get(key)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    sub.auto_renew = False
    logger.info("subscription_auto_renew_cancelled", tenant=tid, sub_id=subscription_id)

    return {"ok": True, "data": {"subscription_id": subscription_id, "auto_renew": False}}
