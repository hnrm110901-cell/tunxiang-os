"""储值卡 + 礼品卡 — 小程序端 API 路由

面向消费者小程序 (miniapp-customer) 的端点，与管理端/POS端分离。

# ROUTER REGISTRATION (在 tx-member/src/main.py 中添加):
# from .api.stored_value_miniapp_routes import router as stored_value_miniapp_router
# app.include_router(stored_value_miniapp_router)

端点列表:
  GET  /api/v1/member/miniapp/stored-value/balance       余额查询（按 member_id）
  GET  /api/v1/member/miniapp/stored-value/plans         充值方案列表
  POST /api/v1/member/miniapp/stored-value/recharge      发起充值（返回微信支付参数）
  GET  /api/v1/member/miniapp/stored-value/transactions  流水明细（分页）
  POST /api/v1/member/miniapp/gift-card/purchase         购买礼品卡
  GET  /api/v1/member/miniapp/gift-card/list             我的礼品卡列表
"""
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/member/miniapp",
    tags=["miniapp-stored-value"],
)


# ──────────────────────────────────────────────────────────────────
# 请求/响应模型
# ──────────────────────────────────────────────────────────────────


class RechargeReq(BaseModel):
    member_id: str
    plan_id: str | None = None
    amount_fen: int = Field(..., gt=0, description="充值金额（分）")


class GiftCardPurchaseReq(BaseModel):
    member_id: str
    amount_fen: int = Field(..., gt=0, description="面值（分）")
    theme: str = Field(default="birthday", description="卡面主题")
    bless_msg: str = Field(default="", max_length=50, description="祝福语")
    recipient_phone: str = Field(..., min_length=11, max_length=11, description="收礼人手机号")


# ──────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ──────────────────────────────────────────────────────────────────
# 端点
# ──────────────────────────────────────────────────────────────────


@router.get("/stored-value/balance/{member_id}")
async def get_balance(
    member_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询储值余额（从 stored_value_accounts 表）"""
    logger.info("miniapp_stored_value_balance", member_id=member_id, tenant_id=x_tenant_id)
    await _set_rls(db, x_tenant_id)
    try:
        result = await db.execute(
            text("""
                SELECT
                    ROUND(balance * 100)::BIGINT        AS balance_fen,
                    ROUND(gift_balance * 100)::BIGINT   AS gift_balance_fen,
                    ROUND(bonus_balance * 100)::BIGINT  AS bonus_balance_fen,
                    id::TEXT                            AS card_id,
                    status
                FROM stored_value_accounts
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                  AND customer_id = :customer_id
                LIMIT 1
            """),
            {"customer_id": member_id},
        )
        row = result.mappings().first()
        if row:
            return {
                "ok": True,
                "data": {
                    "balance_fen": row["balance_fen"] or 0,
                    "gift_balance_fen": row["gift_balance_fen"] or 0,
                    "bonus_balance_fen": row["bonus_balance_fen"] or 0,
                    "card_id": row["card_id"],
                    "status": row["status"],
                },
            }
        return {"ok": True, "data": {"balance_fen": 0, "gift_balance_fen": 0, "bonus_balance_fen": 0, "card_id": None, "status": "none"}}
    except SQLAlchemyError as exc:
        logger.error("miniapp_stored_value_balance_db_error", error=str(exc))
        return {"ok": True, "data": {"balance_fen": 0, "gift_balance_fen": 0, "bonus_balance_fen": 0, "card_id": None, "status": "none"}}


@router.get("/stored-value/plans")
async def get_plans(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取充值方案列表（从 stored_value_recharge_plans 表）"""
    logger.info("miniapp_stored_value_plans", tenant_id=x_tenant_id)
    await _set_rls(db, x_tenant_id)
    try:
        result = await db.execute(
            text("""
                SELECT
                    id::TEXT        AS id,
                    name,
                    recharge_amount_fen AS amount_fen,
                    gift_amount_fen     AS bonus_fen,
                    sort_order
                FROM stored_value_recharge_plans
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                  AND is_active = true
                  AND is_deleted = false
                ORDER BY sort_order ASC, recharge_amount_fen ASC
            """),
        )
        items = [dict(r) for r in result.mappings()]
        return {"ok": True, "data": {"items": items}}
    except SQLAlchemyError as exc:
        logger.error("miniapp_stored_value_plans_db_error", error=str(exc))
        return {"ok": True, "data": {"items": []}}


@router.post("/stored-value/recharge")
async def recharge(
    req: RechargeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """发起充值（Mock 返回空支付参数，前端降级为模拟成功）"""
    logger.info(
        "miniapp_stored_value_recharge",
        member_id=req.member_id,
        plan_id=req.plan_id,
        amount_fen=req.amount_fen,
        tenant_id=x_tenant_id,
    )
    # TODO: 接入 StoredValueService + 微信支付下单
    order_id = str(uuid.uuid4())
    return {
        "ok": True,
        "data": {
            "order_id": order_id,
            "amount_fen": req.amount_fen,
            # 微信支付参数（待接入微信支付后填充）
            "timeStamp": None,
            "nonceStr": None,
            "package": None,
            "signType": None,
            "paySign": None,
        },
    }


@router.get("/stored-value/transactions/{member_id}")
async def get_transactions(
    member_id: str,
    type: str = Query(default="", description="筛选类型：recharge/consume/refund/空=全部"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询储值流水明细（从 stored_value_transactions 表）"""
    logger.info(
        "miniapp_stored_value_transactions",
        member_id=member_id,
        type=type,
        page=page,
        size=size,
        tenant_id=x_tenant_id,
    )
    await _set_rls(db, x_tenant_id)
    try:
        # 先查 account_id（stored_value_transactions 通过 account_id 关联会员）
        acct_result = await db.execute(
            text("""
                SELECT id FROM stored_value_accounts
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                  AND customer_id = :customer_id
                LIMIT 1
            """),
            {"customer_id": member_id},
        )
        acct_row = acct_result.mappings().first()
        if not acct_row:
            return {"ok": True, "data": {"items": [], "total": 0}}

        account_id = acct_row["id"]

        type_filter = "AND txn_type = :txn_type" if type else ""
        count_result = await db.execute(
            text(f"""
                SELECT COUNT(*) AS total
                FROM stored_value_transactions
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                  AND account_id = :account_id
                  {type_filter}
            """),
            {"account_id": account_id, "txn_type": type} if type else {"account_id": account_id},
        )
        total = count_result.scalar() or 0

        rows_result = await db.execute(
            text(f"""
                SELECT
                    id::TEXT                                AS id,
                    txn_type                                AS type,
                    COALESCE(note, txn_type)               AS description,
                    ROUND(amount * 100)::BIGINT            AS amount_fen,
                    created_at
                FROM stored_value_transactions
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                  AND account_id = :account_id
                  {type_filter}
                ORDER BY created_at DESC
                LIMIT :size OFFSET :offset
            """),
            {
                "account_id": account_id,
                **({"txn_type": type} if type else {}),
                "size": size,
                "offset": (page - 1) * size,
            },
        )
        items = []
        for r in rows_result.mappings():
            item = dict(r)
            if item.get("created_at"):
                item["created_at"] = item["created_at"].isoformat()
            items.append(item)
        return {"ok": True, "data": {"items": items, "total": total}}
    except SQLAlchemyError as exc:
        logger.error("miniapp_stored_value_transactions_db_error", error=str(exc))
        return {"ok": True, "data": {"items": [], "total": 0}}


@router.post("/gift-card/purchase")
async def purchase_gift_card(
    req: GiftCardPurchaseReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """购买礼品卡（Mock 返回空支付参数）"""
    logger.info(
        "miniapp_gift_card_purchase",
        member_id=req.member_id,
        amount_fen=req.amount_fen,
        theme=req.theme,
        recipient_phone=req.recipient_phone,
        tenant_id=x_tenant_id,
    )
    # TODO: 接入 GiftCardService + 微信支付下单
    order_id = str(uuid.uuid4())
    return {
        "ok": True,
        "data": {
            "order_id": order_id,
            "card_id": str(uuid.uuid4()),
            "amount_fen": req.amount_fen,
            "timeStamp": None,
            "nonceStr": None,
            "package": None,
            "signType": None,
            "paySign": None,
        },
    }


@router.get("/gift-card/list")
async def list_gift_cards(
    member_id: str = Query(..., description="会员ID"),
    direction: str = Query(default="received", description="received=已收到 / sent=已发出"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """我的礼品卡列表（graceful：表不存在时返回空列表）"""
    logger.info(
        "miniapp_gift_card_list",
        member_id=member_id,
        direction=direction,
        tenant_id=x_tenant_id,
    )
    await _set_rls(db, x_tenant_id)
    try:
        if direction == "received":
            result = await db.execute(
                text("""
                    SELECT
                        id::TEXT        AS id,
                        amount_fen,
                        theme,
                        bless_msg,
                        status,
                        sender_phone,
                        sender_name,
                        created_at
                    FROM gift_cards
                    WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                      AND recipient_customer_id = :member_id
                      AND is_deleted = false
                    ORDER BY created_at DESC
                """),
                {"member_id": member_id},
            )
        else:
            result = await db.execute(
                text("""
                    SELECT
                        id::TEXT        AS id,
                        amount_fen,
                        theme,
                        bless_msg,
                        status,
                        recipient_phone,
                        created_at
                    FROM gift_cards
                    WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                      AND sender_customer_id = :member_id
                      AND is_deleted = false
                    ORDER BY created_at DESC
                """),
                {"member_id": member_id},
            )
        items = []
        for r in result.mappings():
            item = dict(r)
            if item.get("created_at"):
                item["created_at"] = item["created_at"].isoformat()
            items.append(item)
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except SQLAlchemyError as exc:
        logger.warning("miniapp_gift_card_list_db_error", error=str(exc))
        return {"ok": True, "data": {"items": [], "total": 0}}
