"""储值卡 API 路由

# ROUTER REGISTRATION (在 tx-member/src/main.py 中添加):
# from .api.stored_value_routes import router as stored_value_router
# app.include_router(stored_value_router)

端点列表（v2 账户维度）：
  POST   /api/v1/member/stored-value/accounts/{member_id}/recharge   充值（按会员ID）
  POST   /api/v1/member/stored-value/accounts/{card_id}/consume      消费核销
  POST   /api/v1/member/stored-value/accounts/{card_id}/refund       退款
  POST   /api/v1/member/stored-value/accounts/{card_id}/transfer     余额转赠
  GET    /api/v1/member/stored-value/accounts/{card_id}/balance      余额查询
  GET    /api/v1/member/stored-value/accounts/{card_id}/transactions 流水记录
  POST   /api/v1/member/stored-value/batch/process-expiry            触发过期批处理

端点列表（v2 卡维度，已有）：
  POST   /api/v1/member/stored-value/cards                  开卡
  GET    /api/v1/member/stored-value/cards/{card_id}        卡详情
  POST   /api/v1/member/stored-value/recharge-by-plan       充值（v2：按 card_id + plan_id）
  POST   /api/v1/member/stored-value/refund-by-transaction  退款（v2：按原始流水）
  GET    /api/v1/member/stored-value/balance/{card_id}      余额查询（按 card_id）
  GET    /api/v1/member/stored-value/transactions/{card_id} 流水分页（按 card_id）
  GET    /api/v1/member/stored-value/plans                  套餐列表
  POST   /api/v1/member/stored-value/plans                  创建套餐

端点列表（v1 兼容：按卡号）：
  POST   /api/v1/member/stored-value/recharge               充值
  POST   /api/v1/member/stored-value/consume                消费
  POST   /api/v1/member/stored-value/refund                 退款
  POST   /api/v1/member/stored-value/freeze                 冻结
  POST   /api/v1/member/stored-value/unfreeze               解冻
  GET    /api/v1/member/stored-value/{card_no}/balance      余额查询
  GET    /api/v1/member/stored-value/{card_no}/transactions 流水查询
"""
import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from ..services.stored_value_service import (
    CardNotActiveError,
    InsufficientBalanceError,
    PlanNotFoundError,
    StoredValueService,
    TransferNotAllowedError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import MemberEventType, SettlementEventType
from shared.ontology.src.database import get_db_with_tenant

router = APIRouter(prefix="/api/v1/member/stored-value", tags=["stored-value"])
svc = StoredValueService()


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
# Request / Response 模型
# ──────────────────────────────────────────────────────────────────

class CreateCardReq(BaseModel):
    customer_id: uuid.UUID
    store_id: uuid.UUID | None = None
    scope_type: str = Field(default="brand", pattern="^(store|brand|group)$")
    operator_id: uuid.UUID | None = None
    remark: str | None = None


class RechargeByPlanReq(BaseModel):
    card_id: uuid.UUID
    plan_id: uuid.UUID
    operator_id: uuid.UUID | None = None
    store_id: uuid.UUID | None = None


class ConsumeByIdReq(BaseModel):
    card_id: uuid.UUID
    amount_fen: int = Field(..., gt=0, description="消费金额（分）")
    order_id: uuid.UUID | None = None
    store_id: uuid.UUID | None = None


class RefundByTxnReq(BaseModel):
    transaction_id: uuid.UUID
    refund_amount_fen: int = Field(..., gt=0, description="退款金额（分）")
    operator_id: uuid.UUID | None = None


class CreatePlanReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    recharge_amount_fen: int = Field(..., gt=0, description="充值金额（分）")
    gift_amount_fen: int = Field(default=0, ge=0, description="赠送金额（分）")
    scope_type: str = Field(default="brand", pattern="^(store|brand|group)$")
    sort_order: int = Field(default=0, ge=0)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    remark: str | None = None


# v1 兼容请求体
class RechargeReq(BaseModel):
    card_no: str
    amount_fen: int
    operator_id: str | None = None
    store_id: str | None = None


class ConsumeReq(BaseModel):
    card_no: str
    amount_fen: int
    order_id: str | None = None
    operator_id: str | None = None
    store_id: str | None = None


class RefundReq(BaseModel):
    card_no: str
    amount_fen: int
    order_id: str | None = None
    operator_id: str | None = None


class FreezeReq(BaseModel):
    card_no: str
    operator_id: str | None = None


# v2 账户维度请求体
class AccountRechargeReq(BaseModel):
    amount_fen: int = Field(..., gt=0, description="充值金额（分）")
    gift_amount_fen: int = Field(default=0, ge=0, description="赠送金额（分）")
    operator_id: uuid.UUID | None = None
    store_id: uuid.UUID | None = None
    remark: str | None = None


class AccountConsumeReq(BaseModel):
    amount_fen: int = Field(..., gt=0, description="消费金额（分）")
    order_id: uuid.UUID | None = None
    store_id: uuid.UUID | None = None


class AccountRefundReq(BaseModel):
    amount_fen: int = Field(..., gt=0, description="退款金额（分）")
    order_id: uuid.UUID | None = None
    operator_id: uuid.UUID | None = None
    remark: str | None = None


class AccountTransferReq(BaseModel):
    to_card_id: uuid.UUID = Field(..., description="转入方 card_id")
    amount_fen: int = Field(..., gt=0, description="转赠金额（分）")
    operator_id: uuid.UUID | None = None
    remark: str | None = None


# ──────────────────────────────────────────────────────────────────
# 账户维度端点（v2 新增）
# ──────────────────────────────────────────────────────────────────

@router.post("/accounts/{card_id}/recharge", summary="充值（按 card_id，直接传金额）")
async def account_recharge(
    card_id: uuid.UUID,
    req: AccountRechargeReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """向储值账户充值，余额正确增加，生成充值流水记录。
    支持满赠逻辑：充 amount_fen，赠 gift_amount_fen（由调用方按业务规则计算后传入）。
    """
    try:
        result = await svc.recharge_direct(
            db=db,
            card_id=card_id,
            amount_fen=req.amount_fen,
            gift_amount_fen=req.gift_amount_fen,
            tenant_id=tenant_id,
            operator_id=req.operator_id,
            store_id=req.store_id,
            remark=req.remark,
        )
        # ─── Phase 1 平行事件写入：储值充值（负债事件） ───
        asyncio.create_task(emit_event(
            event_type=MemberEventType.RECHARGED,
            tenant_id=tenant_id,
            stream_id=str(card_id),
            payload={
                "amount_fen": req.amount_fen,
                "gift_amount_fen": req.gift_amount_fen or 0,
                "new_balance_fen": result.get("balance_fen", 0),
                "operator_id": str(req.operator_id) if req.operator_id else None,
                "remark": req.remark,
                "customer_id": result.get("customer_id"),
            },
            store_id=str(req.store_id) if req.store_id else None,
            source_service="tx-member",
            metadata={"card_id": str(card_id)},
        ))
        # 充值同时记录储值负债事件（收入确认视图用）
        asyncio.create_task(emit_event(
            event_type=SettlementEventType.STORED_VALUE_DEFERRED,
            tenant_id=tenant_id,
            stream_id=str(card_id),
            payload={
                "amount_fen": req.amount_fen,
                "gift_amount_fen": req.gift_amount_fen or 0,
                "card_id": str(card_id),
                "customer_id": result.get("customer_id"),
            },
            store_id=str(req.store_id) if req.store_id else None,
            source_service="tx-member",
        ))
        return {"ok": True, "data": result}
    except (CardNotActiveError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/accounts/{card_id}/consume", summary="消费核销（按 card_id）")
async def account_consume(
    card_id: uuid.UUID,
    req: AccountConsumeReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """消费核销（悲观锁 SELECT FOR UPDATE 防并发超扣）。
    先扣赠送余额，再扣本金；余额不足返回 400。
    """
    try:
        result = await svc.consume_by_id(
            db=db,
            card_id=card_id,
            amount_fen=req.amount_fen,
            tenant_id=tenant_id,
            order_id=req.order_id,
            store_id=req.store_id,
        )
        # ─── Phase 1 平行事件写入：储值消费（收入确认事件） ───
        asyncio.create_task(emit_event(
            event_type=MemberEventType.CONSUMED,
            tenant_id=tenant_id,
            stream_id=str(card_id),
            payload={
                "amount_fen": req.amount_fen,
                "remaining_balance_fen": result.get("balance_fen", 0),
                "order_id": str(req.order_id) if req.order_id else None,
                "customer_id": result.get("customer_id"),
            },
            store_id=str(req.store_id) if req.store_id else None,
            source_service="tx-member",
            metadata={"card_id": str(card_id)},
            causation_id=str(req.order_id) if req.order_id else None,
        ))
        # 储值消费同时触发收入确认
        asyncio.create_task(emit_event(
            event_type=SettlementEventType.ADVANCE_CONSUMED,
            tenant_id=tenant_id,
            stream_id=str(card_id),
            payload={
                "amount_fen": req.amount_fen,
                "card_id": str(card_id),
                "order_id": str(req.order_id) if req.order_id else None,
                "customer_id": result.get("customer_id"),
            },
            store_id=str(req.store_id) if req.store_id else None,
            source_service="tx-member",
        ))
        return {"ok": True, "data": result}
    except InsufficientBalanceError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except CardNotActiveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/accounts/{card_id}/refund", summary="退款（按 card_id）")
async def account_refund(
    card_id: uuid.UUID,
    req: AccountRefundReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """退款，余额恢复（仅退本金）。"""
    try:
        result = await svc.refund_direct(
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


@router.post("/accounts/{card_id}/transfer", summary="余额转赠（按 card_id）")
async def account_transfer(
    card_id: uuid.UUID,
    req: AccountTransferReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """余额转赠（同一租户内），仅转本金余额。"""
    try:
        result = await svc.transfer(
            db=db,
            from_card_id=card_id,
            to_card_id=req.to_card_id,
            amount_fen=req.amount_fen,
            tenant_id=tenant_id,
            operator_id=req.operator_id,
            remark=req.remark,
        )
        return {"ok": True, "data": result}
    except InsufficientBalanceError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (CardNotActiveError, TransferNotAllowedError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/accounts/{card_id}/balance", summary="余额查询（按 card_id）")
async def account_balance(
    card_id: uuid.UUID,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """查询账户余额（本金 + 赠送余额分项）。"""
    try:
        result = await svc.get_balance(db=db, card_id=card_id, tenant_id=tenant_id)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/accounts/{card_id}/transactions", summary="流水记录（按 card_id）")
async def account_transactions(
    card_id: uuid.UUID,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """分页查询账户流水记录，按时间倒序。"""
    result = await svc.get_transactions_by_id(
        db=db, card_id=card_id, tenant_id=tenant_id, page=page, size=size,
    )
    return {"ok": True, "data": result}


@router.post("/batch/process-expiry", summary="触发过期批处理")
async def batch_process_expiry(
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """批量处理到期账户（供夜批 cron job 调用）：冻结余额，写流水。"""
    result = await svc.process_expiry_batch(db=db, tenant_id=tenant_id)
    return {"ok": True, "data": result}


# ──────────────────────────────────────────────────────────────────
# v2 端点
# ──────────────────────────────────────────────────────────────────

@router.post("/cards", summary="开卡")
async def create_card(
    req: CreateCardReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """新建储值卡，返回卡信息"""
    result = await svc.create_card(
        db=db,
        customer_id=req.customer_id,
        tenant_id=tenant_id,
        store_id=req.store_id,
        scope_type=req.scope_type,
        operator_id=req.operator_id,
        remark=req.remark,
    )
    return {"ok": True, "data": result}


@router.get("/cards/{card_id}", summary="卡详情")
async def get_card_by_id(
    card_id: uuid.UUID,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """按 card_id 查询储值卡详情"""
    card = await svc.get_card_by_id(db=db, card_id=card_id, tenant_id=tenant_id)
    if not card:
        raise HTTPException(status_code=404, detail=f"储值卡不存在: {card_id}")
    return {"ok": True, "data": card}


@router.post("/recharge-by-plan", summary="按套餐充值")
async def recharge_by_plan(
    req: RechargeByPlanReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """按套餐ID充值，同一事务内更新余额并记录流水"""
    try:
        result = await svc.recharge_by_plan(
            db=db,
            card_id=req.card_id,
            plan_id=req.plan_id,
            tenant_id=tenant_id,
            operator_id=req.operator_id,
            store_id=req.store_id,
        )
        return {"ok": True, "data": result}
    except PlanNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except CardNotActiveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/consume", summary="消费扣款")
async def consume(req: ConsumeReq, db: AsyncSession = Depends(_get_tenant_db)):
    """消费扣款 — 先扣赠送金再扣本金"""
    try:
        result = await svc.consume(
            db, req.card_no, req.amount_fen, req.order_id, req.operator_id, req.store_id,
        )
        return {"ok": True, "data": result}
    except InsufficientBalanceError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except CardNotActiveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/refund-by-transaction", summary="按原始流水退款")
async def refund_by_transaction(
    req: RefundByTxnReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """按原始消费流水退款，退款不超过原始消费额，仅退本金"""
    try:
        result = await svc.refund_by_transaction(
            db=db,
            transaction_id=req.transaction_id,
            refund_amount_fen=req.refund_amount_fen,
            tenant_id=tenant_id,
            operator_id=req.operator_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/balance/{card_id}", summary="余额查询（按 card_id）")
async def get_balance(
    card_id: uuid.UUID,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """查询储值卡余额，返回本金/赠送余额分项"""
    try:
        result = await svc.get_balance(db=db, card_id=card_id, tenant_id=tenant_id)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/transactions/{card_id}", summary="流水分页查询（按 card_id）")
async def get_transactions_by_id(
    card_id: uuid.UUID,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """按 card_id 分页查询交易流水，按时间倒序"""
    result = await svc.get_transactions_by_id(
        db=db, card_id=card_id, tenant_id=tenant_id, page=page, size=size,
    )
    return {"ok": True, "data": result}


@router.get("/plans", summary="套餐列表")
async def list_recharge_plans(
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """查询当前有效充值套餐，按 sort_order 排序"""
    plans = await svc.list_recharge_plans(db=db, tenant_id=tenant_id)
    return {"ok": True, "data": plans}


@router.post("/plans", summary="创建充值套餐")
async def create_recharge_plan(
    req: CreatePlanReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """新建充值套餐"""
    try:
        result = await svc.create_recharge_plan(
            db=db,
            tenant_id=tenant_id,
            name=req.name,
            recharge_amount_fen=req.recharge_amount_fen,
            gift_amount_fen=req.gift_amount_fen,
            scope_type=req.scope_type,
            sort_order=req.sort_order,
            valid_from=req.valid_from,
            valid_until=req.valid_until,
            remark=req.remark,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ──────────────────────────────────────────────────────────────────
# v1 兼容端点（保留原有接口，平滑迁移）
# ──────────────────────────────────────────────────────────────────

@router.get("/{card_no}/balance", summary="余额查询（v1 兼容：按卡号）")
async def get_balance_by_card_no(card_no: str, db: AsyncSession = Depends(_get_tenant_db)):
    """查询储值卡余额（按卡号）"""
    card = await svc.get_card(db, card_no)
    if not card:
        raise HTTPException(status_code=404, detail=f"储值卡不存在: {card_no}")
    return {"ok": True, "data": card}


@router.post("/recharge", summary="充值（v1 兼容：按金额+规则匹配）")
async def recharge(req: RechargeReq, db: AsyncSession = Depends(_get_tenant_db)):
    """充值 — 自动匹配赠送规则"""
    try:
        result = await svc.recharge(db, req.card_no, req.amount_fen, req.operator_id, req.store_id)
        return {"ok": True, "data": result}
    except CardNotActiveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/refund", summary="退款（v1 兼容）")
async def refund(req: RefundReq, db: AsyncSession = Depends(_get_tenant_db)):
    """退款 — 仅退本金"""
    try:
        result = await svc.refund(db, req.card_no, req.amount_fen, req.order_id, req.operator_id)
        return {"ok": True, "data": result}
    except (CardNotActiveError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/freeze", summary="冻结储值卡")
async def freeze(req: FreezeReq, db: AsyncSession = Depends(_get_tenant_db)):
    """冻结储值卡"""
    try:
        result = await svc.freeze(db, req.card_no, req.operator_id)
        return {"ok": True, "data": result}
    except (CardNotActiveError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/unfreeze", summary="解冻储值卡")
async def unfreeze(req: FreezeReq, db: AsyncSession = Depends(_get_tenant_db)):
    """解冻储值卡"""
    try:
        result = await svc.unfreeze(db, req.card_no, req.operator_id)
        return {"ok": True, "data": result}
    except (CardNotActiveError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{card_no}/transactions", summary="流水查询（v1 兼容：按卡号）")
async def get_transactions(
    card_no: str,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(_get_tenant_db),
):
    """查询储值卡交易流水（按卡号）"""
    try:
        result = await svc.get_transactions(db, card_no, limit=size, offset=(page - 1) * size)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
