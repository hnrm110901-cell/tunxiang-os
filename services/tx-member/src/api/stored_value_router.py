"""储值卡 API 路由（新版 member 维度）

端点列表：
  POST   /api/v1/members/{member_id}/sv/charge           充值（含赠送规则匹配）
  POST   /api/v1/members/{member_id}/sv/consume          消费核销
  POST   /api/v1/sv/transactions/{tx_id}/refund          退款（按原始流水）
  GET    /api/v1/members/{member_id}/sv/balance          查余额
  GET    /api/v1/members/{member_id}/sv/transactions     交易流水
  GET    /api/v1/sv/charge-rules                         充值赠送规则列表
  POST   /api/v1/sv/charge-rules                         创建充值赠送规则
  POST   /api/v1/members/{member_id}/sv/exchange-points  积分兑换余额

注：本路由使用 stored_value_service.StoredValueService，
    充值赠送规则查询 sv_charge_rules（v057 迁移新增表）。
"""
from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from services.stored_value_service import (
    CardNotActiveError,
    CardNotFoundError,
    InsufficientBalanceError,
    StoredValueService,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["stored-value-v2"])
_svc = StoredValueService()


# ──────────────────────────────────────────────────────────────────
# 依赖
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

class ChargeReq(BaseModel):
    amount_fen: int = Field(..., gt=0, description="充值金额（分）")
    operator_id: uuid.UUID | None = None
    remark: str | None = None


class ConsumeReq(BaseModel):
    card_id: uuid.UUID = Field(..., description="储值卡 ID")
    order_id: uuid.UUID | None = None
    amount_fen: int = Field(..., gt=0, description="消费金额（分）")
    operator_id: uuid.UUID | None = None


class RefundReq(BaseModel):
    operator_id: uuid.UUID | None = None
    remark: str | None = None


class ExchangePointsReq(BaseModel):
    points: int = Field(..., gt=0, description="兑换积分数")
    points_to_fen_ratio: int = Field(
        default=100, gt=0, description="每多少积分兑换 1 分钱（默认 100:1）"
    )


class CreateChargeRuleReq(BaseModel):
    store_id: uuid.UUID | None = Field(default=None, description="适用门店，NULL=全租户")
    charge_amount: int = Field(..., gt=0, description="触发充值金额（分）")
    bonus_amount: int = Field(..., ge=0, description="赠送金额（分）")
    description: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


# ──────────────────────────────────────────────────────────────────
# 充值
# ──────────────────────────────────────────────────────────────────

@router.post(
    "/members/{member_id}/sv/charge",
    summary="储值充值（自动匹配 sv_charge_rules 赠送规则）",
)
async def charge(
    member_id: uuid.UUID,
    req: ChargeReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """充值流程：
    1. 查找或创建会员储值卡
    2. 查询 sv_charge_rules 匹配赠送规则
    3. 计算 bonus（无匹配规则则 bonus=0）
    4. 更新卡余额（本金 + bonus）
    5. 记录充值 + bonus 流水
    """
    # 查找或创建储值卡
    from models.stored_value import StoredValueCard

    card_result = await db.execute(
        select(StoredValueCard).where(
            StoredValueCard.customer_id == member_id,
            StoredValueCard.tenant_id == tenant_id,
            StoredValueCard.status == "active",
            StoredValueCard.is_deleted.is_(False),
        ).order_by(StoredValueCard.created_at.asc()).limit(1)
    )
    card = card_result.scalar_one_or_none()

    if not card:
        # 自动开卡
        card_data = await _svc.create_card(
            db=db,
            customer_id=member_id,
            tenant_id=tenant_id,
        )
        card_result2 = await db.execute(
            select(StoredValueCard).where(
                StoredValueCard.id == uuid.UUID(card_data["id"])
            )
        )
        card = card_result2.scalar_one()

    # 查询赠送规则
    bonus_fen = await _match_charge_bonus(db, tenant_id, req.amount_fen)

    try:
        result = await _svc.recharge_direct(
            db=db,
            card_id=card.id,
            amount_fen=req.amount_fen,
            tenant_id=tenant_id,
            gift_amount_fen=bonus_fen,
            operator_id=req.operator_id,
            remark=req.remark,
        )
        bonus_desc = f"，赠送 {bonus_fen / 100:.2f} 元" if bonus_fen else ""
        logger.info(
            "sv_charge",
            member_id=str(member_id),
            amount_fen=req.amount_fen,
            bonus_fen=bonus_fen,
        )
        return {
            "ok": True,
            "data": {
                **result,
                "bonus_fen": bonus_fen,
                "message": f"充值 {req.amount_fen / 100:.2f} 元成功{bonus_desc}",
            },
        }
    except CardNotActiveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ──────────────────────────────────────────────────────────────────
# 消费核销
# ──────────────────────────────────────────────────────────────────

@router.post(
    "/members/{member_id}/sv/consume",
    summary="消费核销（乐观锁防并发超扣）",
)
async def consume(
    member_id: uuid.UUID,
    req: ConsumeReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """消费核销：
    1. 检查余额是否充足
    2. 乐观锁 UPDATE WHERE balance >= amount_fen
    3. 记录消费流水
    """
    try:
        result = await _svc.consume_by_id(
            db=db,
            card_id=req.card_id,
            amount_fen=req.amount_fen,
            tenant_id=tenant_id,
            order_id=req.order_id,
            store_id=None,
        )
        return {"ok": True, "data": result}
    except InsufficientBalanceError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except CardNotActiveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ──────────────────────────────────────────────────────────────────
# 退款
# ──────────────────────────────────────────────────────────────────

@router.post(
    "/sv/transactions/{tx_id}/refund",
    summary="退款（按原始消费流水）",
)
async def refund(
    tx_id: uuid.UUID,
    req: RefundReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """找到原消费记录，回退余额（仅退本金）。"""
    # 查原始流水的消费金额
    from models.stored_value import StoredValueTransaction

    txn_result = await db.execute(
        select(StoredValueTransaction).where(
            StoredValueTransaction.id == tx_id,
            StoredValueTransaction.tenant_id == tenant_id,
            StoredValueTransaction.is_deleted.is_(False),
        )
    )
    orig_txn = txn_result.scalar_one_or_none()
    if not orig_txn:
        raise HTTPException(status_code=404, detail=f"流水不存在: {tx_id}")
    if orig_txn.txn_type != "consume":
        raise HTTPException(
            status_code=400,
            detail=f"只能对消费流水退款，当前流水类型: {orig_txn.txn_type}",
        )

    try:
        result = await _svc.refund_by_transaction(
            db=db,
            transaction_id=tx_id,
            refund_amount_fen=abs(orig_txn.amount_fen),
            tenant_id=tenant_id,
            operator_id=req.operator_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ──────────────────────────────────────────────────────────────────
# 余额查询
# ──────────────────────────────────────────────────────────────────

@router.get(
    "/members/{member_id}/sv/balance",
    summary="查询会员储值余额",
)
async def get_balance(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """查询会员储值卡余额（本金 + 赠送余额分项）。"""
    from models.stored_value import StoredValueCard

    card_result = await db.execute(
        select(StoredValueCard).where(
            StoredValueCard.customer_id == member_id,
            StoredValueCard.tenant_id == tenant_id,
            StoredValueCard.is_deleted.is_(False),
        ).order_by(StoredValueCard.created_at.asc()).limit(1)
    )
    card = card_result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail=f"会员 {member_id} 尚未开储值卡")

    try:
        result = await _svc.get_balance(db=db, card_id=card.id, tenant_id=tenant_id)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ──────────────────────────────────────────────────────────────────
# 交易流水
# ──────────────────────────────────────────────────────────────────

@router.get(
    "/members/{member_id}/sv/transactions",
    summary="查询会员储值流水",
)
async def get_transactions(
    member_id: uuid.UUID,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """分页查询会员储值流水，按时间倒序。"""
    from models.stored_value import StoredValueCard

    card_result = await db.execute(
        select(StoredValueCard).where(
            StoredValueCard.customer_id == member_id,
            StoredValueCard.tenant_id == tenant_id,
            StoredValueCard.is_deleted.is_(False),
        ).order_by(StoredValueCard.created_at.asc()).limit(1)
    )
    card = card_result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail=f"会员 {member_id} 尚未开储值卡")

    result = await _svc.get_transactions_by_id(
        db=db, card_id=card.id, tenant_id=tenant_id, page=page, size=size,
    )
    return {"ok": True, "data": result}


# ──────────────────────────────────────────────────────────────────
# 充值赠送规则
# ──────────────────────────────────────────────────────────────────

@router.get(
    "/sv/charge-rules",
    summary="充值赠送规则列表",
)
async def list_charge_rules(
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """查询当前有效的充值赠送规则（is_active=true，在有效期内）。"""
    now = datetime.utcnow()
    rows = await db.execute(
        text(
            "SELECT id, store_id, charge_amount, bonus_amount, description, "
            "       is_active, valid_from, valid_to, created_at "
            "FROM sv_charge_rules "
            "WHERE tenant_id = :tid AND is_active = true AND is_deleted = false "
            "  AND (valid_from IS NULL OR valid_from <= :now) "
            "  AND (valid_to   IS NULL OR valid_to   >= :now) "
            "ORDER BY charge_amount ASC"
        ),
        {"tid": tenant_id, "now": now},
    )
    rules = [dict(r._mapping) for r in rows.fetchall()]
    # 序列化 UUID / datetime
    for rule in rules:
        for k, v in rule.items():
            if isinstance(v, uuid.UUID):
                rule[k] = str(v)
            elif isinstance(v, datetime):
                rule[k] = v.isoformat()
    return {"ok": True, "data": rules}


@router.post(
    "/sv/charge-rules",
    summary="创建充值赠送规则",
    status_code=201,
)
async def create_charge_rule(
    req: CreateChargeRuleReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """新建充值赠送规则（插入 sv_charge_rules 表）。"""
    if req.bonus_amount == 0:
        raise HTTPException(status_code=400, detail="赠送金额必须大于 0")

    result = await db.execute(
        text(
            "INSERT INTO sv_charge_rules "
            "(tenant_id, store_id, charge_amount, bonus_amount, description, "
            " is_active, valid_from, valid_to) "
            "VALUES (:tid, :sid, :ca, :ba, :desc, true, :vf, :vt) "
            "RETURNING id, charge_amount, bonus_amount, description, valid_from, valid_to"
        ),
        {
            "tid": tenant_id,
            "sid": req.store_id,
            "ca": req.charge_amount,
            "ba": req.bonus_amount,
            "desc": req.description,
            "vf": req.valid_from,
            "vt": req.valid_to,
        },
    )
    row = result.fetchone()
    rule_id = str(row[0])

    logger.info(
        "sv_charge_rule_created",
        tenant_id=str(tenant_id),
        rule_id=rule_id,
        charge_amount=req.charge_amount,
        bonus_amount=req.bonus_amount,
    )
    return {
        "ok": True,
        "data": {
            "id": rule_id,
            "charge_amount": row[1],
            "bonus_amount": row[2],
            "description": row[3],
            "valid_from": row[4].isoformat() if row[4] else None,
            "valid_to": row[5].isoformat() if row[5] else None,
        },
    }


# ──────────────────────────────────────────────────────────────────
# 积分兑换余额
# ──────────────────────────────────────────────────────────────────

@router.post(
    "/members/{member_id}/sv/exchange-points",
    summary="积分兑换储值余额",
)
async def exchange_points(
    member_id: uuid.UUID,
    req: ExchangePointsReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
):
    """积分兑换余额：从 member_cards 扣积分，充入储值卡本金余额。"""
    try:
        result = await _svc.exchange_points_for_balance(
            db=db,
            tenant_id=tenant_id,
            member_id=member_id,
            points=req.points,
            points_to_fen_ratio=req.points_to_fen_ratio,
        )
        return {"ok": True, "data": result}
    except CardNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InsufficientBalanceError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ──────────────────────────────────────────────────────────────────
# 内部辅助
# ──────────────────────────────────────────────────────────────────

async def _match_charge_bonus(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    amount_fen: int,
) -> int:
    """从 sv_charge_rules 匹配最优赠送规则，返回赠送金额（分）。

    策略：取 charge_amount <= amount_fen 中赠送金额最大的规则。
    无匹配则返回 0。
    """
    now = datetime.utcnow()
    result = await db.execute(
        text(
            "SELECT bonus_amount FROM sv_charge_rules "
            "WHERE tenant_id = :tid AND is_active = true AND is_deleted = false "
            "  AND charge_amount <= :amt "
            "  AND (valid_from IS NULL OR valid_from <= :now) "
            "  AND (valid_to   IS NULL OR valid_to   >= :now) "
            "ORDER BY bonus_amount DESC "
            "LIMIT 1"
        ),
        {"tid": tenant_id, "amt": amount_fen, "now": now},
    )
    row = result.fetchone()
    return int(row[0]) if row else 0
