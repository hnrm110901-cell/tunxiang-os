"""宴会现场订单 API"""

from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.banquet_live_order_service import BanquetLiveOrderService


def _tid(r: Request) -> str:
    t = getattr(r.state, "tenant_id", None) or r.headers.get("X-Tenant-ID", "")
    if not t:
        raise HTTPException(400, "X-Tenant-ID required")
    return t


async def _db(r: Request) -> AsyncGenerator[AsyncSession, None]:
    async for s in get_db_with_tenant(_tid(r)):
        yield s


def _ok(d):
    return {"ok": True, "data": d, "error": None}


def _err(m, c=400):
    raise HTTPException(c, {"ok": False, "data": None, "error": {"message": m}})


router = APIRouter(prefix="/api/v1/banquet/live-orders", tags=["banquet-live"])


class CreateReq(BaseModel):
    banquet_id: str
    order_type: str
    items_json: list = []
    amount_fen: int = 0
    quantity: int = 1
    requested_name: Optional[str] = None
    notes: Optional[str] = None


class RejectReq(BaseModel):
    reason: str


@router.post("/")
async def create(req: CreateReq, r: Request, db: AsyncSession = Depends(_db)):
    return _ok(
        await BanquetLiveOrderService(db, _tid(r)).create_live_order(
            req.banquet_id,
            req.order_type,
            req.items_json,
            req.amount_fen,
            req.quantity,
            notes=req.notes,
            requested_name=req.requested_name,
        )
    )


@router.get("/{banquet_id}")
async def list_orders(
    banquet_id: str, status: Optional[str] = None, r: Request = None, db: AsyncSession = Depends(_db)
):
    return _ok(await BanquetLiveOrderService(db, _tid(r)).list_by_banquet(banquet_id, status))


@router.post("/{live_order_id}/approve")
async def approve(live_order_id: str, r: Request, db: AsyncSession = Depends(_db)):
    try:
        return _ok(await BanquetLiveOrderService(db, _tid(r)).approve(live_order_id, _tid(r)))
    except ValueError as e:
        _err(str(e))


@router.post("/{live_order_id}/reject")
async def reject(live_order_id: str, req: RejectReq, r: Request, db: AsyncSession = Depends(_db)):
    try:
        return _ok(await BanquetLiveOrderService(db, _tid(r)).reject(live_order_id, req.reason))
    except ValueError as e:
        _err(str(e))


@router.post("/{live_order_id}/fulfill")
async def fulfill(live_order_id: str, r: Request, db: AsyncSession = Depends(_db)):
    return _ok(await BanquetLiveOrderService(db, _tid(r)).fulfill(live_order_id))


@router.get("/total/{banquet_id}")
async def get_total(banquet_id: str, r: Request = None, db: AsyncSession = Depends(_db)):
    return _ok(await BanquetLiveOrderService(db, _tid(r)).get_live_total(banquet_id))
