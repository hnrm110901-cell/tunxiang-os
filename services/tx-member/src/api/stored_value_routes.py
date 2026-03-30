"""储值卡 API 路由"""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant
from services.stored_value_service import StoredValueService, InsufficientBalanceError, CardNotActiveError

router = APIRouter(prefix="/api/v1/member/stored-value", tags=["stored-value"])
svc = StoredValueService()


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


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


@router.get("/{card_no}/balance")
async def get_balance(card_no: str, db: AsyncSession = Depends(_get_tenant_db)):
    """查询储值卡余额"""
    card = await svc.get_card(db, card_no)
    if not card:
        raise HTTPException(status_code=404, detail=f"储值卡不存在: {card_no}")
    return {"ok": True, "data": card}


@router.post("/recharge")
async def recharge(req: RechargeReq, db: AsyncSession = Depends(_get_tenant_db)):
    """储值卡充值"""
    try:
        result = await svc.recharge(db, req.card_no, req.amount_fen, req.operator_id, req.store_id)
        return {"ok": True, "data": result}
    except CardNotActiveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/consume")
async def consume(req: ConsumeReq, db: AsyncSession = Depends(_get_tenant_db)):
    """储值卡消费"""
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


@router.post("/refund")
async def refund(req: RefundReq, db: AsyncSession = Depends(_get_tenant_db)):
    """储值卡退款"""
    try:
        result = await svc.refund(db, req.card_no, req.amount_fen, req.order_id, req.operator_id)
        return {"ok": True, "data": result}
    except (CardNotActiveError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/freeze")
async def freeze(req: FreezeReq, db: AsyncSession = Depends(_get_tenant_db)):
    """冻结储值卡"""
    try:
        result = await svc.freeze(db, req.card_no, req.operator_id)
        return {"ok": True, "data": result}
    except (CardNotActiveError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/unfreeze")
async def unfreeze(req: FreezeReq, db: AsyncSession = Depends(_get_tenant_db)):
    """解冻储值卡"""
    try:
        result = await svc.unfreeze(db, req.card_no, req.operator_id)
        return {"ok": True, "data": result}
    except (CardNotActiveError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{card_no}/transactions")
async def get_transactions(
    card_no: str,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(_get_tenant_db),
):
    """查询储值卡交易流水"""
    try:
        result = await svc.get_transactions(db, card_no, limit=size, offset=(page - 1) * size)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
