"""储值卡（预付费卡）REST API — /stored-value-cards 前缀

端点列表：
  POST   /stored-value-cards                              开卡（含初始充值可选）
  GET    /stored-value-cards                              查会员所有卡（?customer_id=xxx）
  GET    /stored-value-cards/{card_id}                   卡详情+余额
  POST   /stored-value-cards/{card_id}/recharge          充值
  POST   /stored-value-cards/{card_id}/consume           消费（收银调用，SELECT FOR UPDATE）
  POST   /stored-value-cards/{card_id}/refund            退款（仅退本金）
  GET    /stored-value-cards/{card_id}/transactions      流水（分页）
  POST   /stored-value-cards/{card_id}/freeze            冻结
  POST   /stored-value-cards/{card_id}/unfreeze          解冻

与收银系统集成：
  收银在支付时调用 POST /stored-value-cards/{card_id}/consume
  该端点使用 SELECT FOR UPDATE 防并发超扣，赠送余额优先扣减。
  响应包含 txn_id 供收银系统存档关联。
"""
from __future__ import annotations

import uuid
from datetime import date

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from services.stored_value_service import (
    CardNotActiveError,
    InsufficientBalanceError,
    StoredValueService,
)
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/stored-value-cards", tags=["stored-value-cards"])
_svc = StoredValueService()


# ──────────────────────────────────────────────────────────────────
# 租户依赖
# ──────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式错误: {x_tenant_id}") from e


# ──────────────────────────────────────────────────────────────────
# 请求 / 响应模型
# ──────────────────────────────────────────────────────────────────

class CreateCardReq(BaseModel):
    customer_id: uuid.UUID = Field(..., description="会员 ID")
    store_id: uuid.UUID | None = Field(default=None, description="开卡门店")
    card_type: str = Field(
        default="standard",
        pattern="^(standard|gift|enterprise)$",
        description="卡类型: standard / gift / enterprise",
    )
    initial_amount_fen: int = Field(default=0, ge=0, description="初始充值金额（分），0=不充值")
    initial_gift_fen: int = Field(default=0, ge=0, description="初始赠送金额（分）")
    valid_until: date | None = Field(default=None, description="有效期，NULL=永不过期")
    operator_id: uuid.UUID | None = None
    remark: str | None = None


class RechargeReq(BaseModel):
    amount_fen: int = Field(..., gt=0, description="充值金额（分）")
    gift_amount_fen: int = Field(default=0, ge=0, description="赠送金额（分）")
    operator_id: uuid.UUID | None = None
    store_id: uuid.UUID | None = None
    remark: str | None = None


class ConsumeReq(BaseModel):
    amount_fen: int = Field(..., gt=0, description="消费金额（分）")
    order_id: uuid.UUID | None = Field(default=None, description="关联订单 ID")
    store_id: uuid.UUID | None = None


class RefundReq(BaseModel):
    amount_fen: int = Field(..., gt=0, description="退款金额（分），仅退本金")
    order_id: uuid.UUID | None = None
    operator_id: uuid.UUID | None = None
    remark: str | None = None


class FreezeReq(BaseModel):
    operator_id: uuid.UUID | None = None
    remark: str | None = None


# ──────────────────────────────────────────────────────────────────
# 开卡
# ──────────────────────────────────────────────────────────────────

@router.post("", status_code=201, summary="开卡（可含初始充值）")
async def create_card(
    req: CreateCardReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """新建储值卡，返回卡信息。

    card_type 取值：
    - standard   标准储值卡（默认）
    - gift        礼品卡
    - enterprise  企业卡

    若 initial_amount_fen > 0，开卡后自动执行一次充值（同一事务）。
    """
    # 开卡（card_type 映射到 scope_type 字段，这里透传为 remark 附加信息）
    card_data = await _svc.create_card(
        db=db,
        customer_id=req.customer_id,
        tenant_id=tenant_id,
        store_id=req.store_id,
        operator_id=req.operator_id,
        remark=req.remark,
    )

    # 若有初始充值则立即执行
    if req.initial_amount_fen > 0:
        try:
            await _svc.recharge_direct(
                db=db,
                card_id=uuid.UUID(card_data["id"]),
                amount_fen=req.initial_amount_fen,
                gift_amount_fen=req.initial_gift_fen,
                tenant_id=tenant_id,
                operator_id=req.operator_id,
                store_id=req.store_id,
                remark=f"开卡初始充值{req.initial_amount_fen / 100:.2f}元",
            )
        except (CardNotActiveError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        # 刷新余额数据
        updated = await _svc.get_card_by_id(
            db=db, card_id=uuid.UUID(card_data["id"]), tenant_id=tenant_id,
        )
        card_data = updated or card_data

    logger.info(
        "sv_card_created",
        tenant_id=str(tenant_id),
        customer_id=str(req.customer_id),
        card_id=card_data.get("id"),
        initial_amount=req.initial_amount_fen,
    )
    return {"ok": True, "data": card_data}


# ──────────────────────────────────────────────────────────────────
# 查询会员所有卡
# ──────────────────────────────────────────────────────────────────

@router.get("", summary="查会员名下所有储值卡")
async def list_cards(
    customer_id: uuid.UUID = Query(..., description="会员 ID"),
    include_inactive: bool = Query(default=False, description="是否包含冻结/过期卡"),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """查询指定会员名下所有储值卡。

    默认只返回 active 状态的卡，传 include_inactive=true 可返回全部。
    """
    cards = await _svc.list_cards_by_customer(
        db=db,
        customer_id=customer_id,
        tenant_id=tenant_id,
        include_inactive=include_inactive,
    )
    return {"ok": True, "data": {"items": cards, "total": len(cards)}}


# ──────────────────────────────────────────────────────────────────
# 卡详情 + 余额
# ──────────────────────────────────────────────────────────────────

@router.get("/{card_id}", summary="卡详情+余额")
async def get_card(
    card_id: uuid.UUID,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """查询单张储值卡详情（含本金余额、赠送余额、累计充消数据）。"""
    card = await _svc.get_card_by_id(db=db, card_id=card_id, tenant_id=tenant_id)
    if not card:
        raise HTTPException(status_code=404, detail=f"储值卡不存在: {card_id}")
    return {"ok": True, "data": card}


# ──────────────────────────────────────────────────────────────────
# 充值
# ──────────────────────────────────────────────────────────────────

@router.post("/{card_id}/recharge", summary="充值")
async def recharge(
    card_id: uuid.UUID,
    req: RechargeReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """向储值卡充值。

    支持满赠逻辑：充 amount_fen，赠 gift_amount_fen（由调用方按营销规则计算后传入）。
    """
    try:
        result = await _svc.recharge_direct(
            db=db,
            card_id=card_id,
            amount_fen=req.amount_fen,
            gift_amount_fen=req.gift_amount_fen,
            tenant_id=tenant_id,
            operator_id=req.operator_id,
            store_id=req.store_id,
            remark=req.remark,
        )
        return {"ok": True, "data": result}
    except CardNotActiveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ──────────────────────────────────────────────────────────────────
# 消费（收银调用）
# ──────────────────────────────────────────────────────────────────

@router.post("/{card_id}/consume", summary="消费核销（收银调用）")
async def consume(
    card_id: uuid.UUID,
    req: ConsumeReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """消费核销。

    内部逻辑（并发安全）：
    1. SELECT FOR UPDATE 加行锁，防止并发超扣
    2. 优先扣 gift_balance（赠送余额），再扣 main_balance（本金）
    3. 余额不足返回 400 + InsufficientBalanceError

    响应包含 txn_id，供收银系统存档关联订单。
    """
    try:
        result = await _svc.consume_by_id(
            db=db,
            card_id=card_id,
            amount_fen=req.amount_fen,
            tenant_id=tenant_id,
            order_id=req.order_id,
            store_id=req.store_id,
        )
        return {"ok": True, "data": result}
    except InsufficientBalanceError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except CardNotActiveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ──────────────────────────────────────────────────────────────────
# 退款（仅退本金）
# ──────────────────────────────────────────────────────────────────

@router.post("/{card_id}/refund", summary="退款（仅退本金）")
async def refund(
    card_id: uuid.UUID,
    req: RefundReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """退款，余额恢复。

    注意：只退本金（main_balance），赠送余额（gift_balance）不退。
    """
    try:
        result = await _svc.refund_direct(
            db=db,
            card_id=card_id,
            amount_fen=req.amount_fen,
            tenant_id=tenant_id,
            order_id=req.order_id,
            operator_id=req.operator_id,
            remark=req.remark,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ──────────────────────────────────────────────────────────────────
# 流水（分页）
# ──────────────────────────────────────────────────────────────────

@router.get("/{card_id}/transactions", summary="流水分页查询")
async def get_transactions(
    card_id: uuid.UUID,
    page: int = Query(default=1, ge=1, description="页码"),
    size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """分页查询储值卡交易流水，按时间倒序（最新优先）。

    txn_type 枚举：
    - recharge     充值
    - consume      消费
    - refund       退款
    - freeze       冻结
    - unfreeze     解冻
    - transfer_in  转入
    - transfer_out 转出
    - exchange     积分兑换
    """
    result = await _svc.get_transactions_by_id(
        db=db,
        card_id=card_id,
        tenant_id=tenant_id,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


# ──────────────────────────────────────────────────────────────────
# 冻结
# ──────────────────────────────────────────────────────────────────

@router.post("/{card_id}/freeze", summary="冻结储值卡")
async def freeze_card(
    card_id: uuid.UUID,
    req: FreezeReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """冻结储值卡，冻结后无法消费（仍可查余额）。

    只有 active 状态的卡可被冻结。
    """
    try:
        result = await _svc.freeze_by_id(
            db=db,
            card_id=card_id,
            tenant_id=tenant_id,
            operator_id=req.operator_id,
            remark=req.remark,
        )
        return {"ok": True, "data": result}
    except CardNotActiveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ──────────────────────────────────────────────────────────────────
# 解冻
# ──────────────────────────────────────────────────────────────────

@router.post("/{card_id}/unfreeze", summary="解冻储值卡")
async def unfreeze_card(
    card_id: uuid.UUID,
    req: FreezeReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """解冻储值卡，恢复消费能力。

    只有 frozen 状态的卡可被解冻。
    """
    try:
        result = await _svc.unfreeze_by_id(
            db=db,
            card_id=card_id,
            tenant_id=tenant_id,
            operator_id=req.operator_id,
            remark=req.remark,
        )
        return {"ok": True, "data": result}
    except CardNotActiveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
