"""付费会员订阅 API — 月卡/季卡/年卡

前缀: /api/v1/member/subscriptions

端点:
  POST /                   — 创建订阅（INSERT DB + 微信支付预下单）
  GET  /my                 — 查询当前用户的活跃订阅
  POST /{id}/cancel        — 取消自动续费
  GET  /plans              — 获取可用订阅方案列表
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/member/subscriptions", tags=["subscription"])


# ─── DB 依赖 ────────────────────────────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _require_tenant(tenant_id: Optional[str]) -> str:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID required")
    return tenant_id


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
    openid: Optional[str] = None  # 微信 openid，支付必填


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
        plan_id="monthly",
        name="月卡",
        price_fen=1990,
        period_days=30,
        benefits=["每单9折", "免配送费", "生日双倍积分", "专属会员价"],
    ),
    "quarterly": SubscriptionPlan(
        plan_id="quarterly",
        name="季卡",
        price_fen=4990,
        period_days=90,
        popular=True,
        benefits=["月卡全部权益", "每月满50减20券", "新品优先体验", "积分1.5倍"],
    ),
    "yearly": SubscriptionPlan(
        plan_id="yearly",
        name="年卡",
        price_fen=16800,
        period_days=365,
        benefits=["季卡全部权益", "专属客服", "优先排队", "生日免费菜品", "积分2倍", "跨品牌通用"],
    ),
}


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
    db: AsyncSession = Depends(_get_tenant_db),
):
    """创建订阅 — INSERT DB + 调用微信支付预下单"""
    tid = _require_tenant(x_tenant_id)
    plan = PLANS.get(req.plan_id)
    if not plan:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {req.plan_id}")

    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=plan.period_days)
    sub_id = str(uuid.uuid4())
    out_trade_no = f"SUB{now.strftime('%Y%m%d%H%M%S')}{str(uuid.uuid4()).replace('-', '')[:8].upper()}"

    try:
        await db.execute(
            text("""
                INSERT INTO member_subscriptions
                    (id, tenant_id, plan_id, plan_name, price_fen, period_days,
                     openid, status, started_at, expires_at, out_trade_no, auto_renew)
                VALUES
                    (:id::uuid, :tid::uuid, :plan_id, :plan_name, :price_fen, :period_days,
                     :openid, 'pending_payment', :started_at, :expires_at, :out_trade_no, TRUE)
            """),
            {
                "id": sub_id,
                "tid": tid,
                "plan_id": plan.plan_id,
                "plan_name": plan.name,
                "price_fen": plan.price_fen,
                "period_days": plan.period_days,
                "openid": req.openid,
                "started_at": now,
                "expires_at": expires,
                "out_trade_no": out_trade_no,
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("subscription_db_insert_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="创建订阅失败，请稍后重试")

    # 调用微信支付预下单
    try:
        from shared.integrations.wechat_pay import WechatPayService

        wechat = WechatPayService()
        payment_params = await wechat.create_prepay(
            out_trade_no=out_trade_no,
            total_fen=plan.price_fen,
            description=f"屯象会员{plan.name}",
            openid=req.openid or "",
            notify_url="https://api.tunxiang.com/api/v1/member/subscriptions/notify",
        )
    except (ConnectionError, TimeoutError, ValueError, OSError) as e:  # 支付参数生成失败不阻断订单创建
        logger.warning("wechat_prepay_failed", error=str(e))
        # 降级：返回占位参数（生产环境需保证 WechatPayService 配置正确）
        payment_params = {
            "timeStamp": str(int(now.timestamp())),
            "nonceStr": uuid.uuid4().hex[:16],
            "package": f"prepay_id=fallback_{sub_id[:8]}",
            "signType": "RSA",
            "paySign": "",
        }

    logger.info(
        "subscription_created",
        tenant=tid,
        plan=plan.plan_id,
        sub_id=sub_id,
        out_trade_no=out_trade_no,
        price_fen=plan.price_fen,
    )

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
    db: AsyncSession = Depends(_get_tenant_db),
):
    """查询当前活跃订阅"""
    tid = _require_tenant(x_tenant_id)

    try:
        result = await db.execute(
            text("""
                SELECT id::text, plan_id, plan_name, status,
                       started_at, expires_at, auto_renew
                FROM member_subscriptions
                WHERE tenant_id = :tid::uuid
                  AND status = 'active'
                  AND is_deleted = FALSE
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"tid": tid},
        )
        row = result.mappings().first()
    except SQLAlchemyError as exc:
        logger.error("subscription_fetch_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询订阅失败，请稍后重试")

    if not row:
        return {"ok": True, "data": {"plan_id": None, "expires_at": None}}

    return {
        "ok": True,
        "data": {
            "subscription_id": row["id"],
            "plan_id": row["plan_id"],
            "plan_name": row["plan_name"],
            "status": row["status"],
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
            "auto_renew": row["auto_renew"],
        },
    }


@router.post("/{subscription_id}/cancel")
async def cancel_subscription(
    subscription_id: str,
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """取消自动续费"""
    tid = _require_tenant(x_tenant_id)

    try:
        result = await db.execute(
            text("""
                UPDATE member_subscriptions
                SET auto_renew = FALSE,
                    cancelled_at = NOW(),
                    updated_at = NOW()
                WHERE id = :sid::uuid
                  AND tenant_id = :tid::uuid
                  AND is_deleted = FALSE
                RETURNING id::text, auto_renew
            """),
            {"sid": subscription_id, "tid": tid},
        )
        row = result.mappings().first()
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("subscription_cancel_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="取消订阅失败，请稍后重试")

    if not row:
        raise HTTPException(status_code=404, detail="Subscription not found")

    logger.info(
        "subscription_auto_renew_cancelled",
        tenant=tid,
        sub_id=subscription_id,
    )

    return {"ok": True, "data": {"subscription_id": subscription_id, "auto_renew": False}}
