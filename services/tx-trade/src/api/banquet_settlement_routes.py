"""宴会结算 API"""
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.banquet_settlement_service import BanquetSettlementService


def _tid(r: Request) -> str:
    t = getattr(r.state, "tenant_id", None) or r.headers.get("X-Tenant-ID", "")
    if not t: raise HTTPException(400, "X-Tenant-ID required")
    return t
async def _db(r: Request) -> AsyncGenerator[AsyncSession, None]:
    async for s in get_db_with_tenant(_tid(r)): yield s
def _ok(d): return {"ok": True, "data": d, "error": None}
def _err(m, c=400): raise HTTPException(c, {"ok": False, "data": None, "error": {"message": m}})

router = APIRouter(prefix="/api/v1/banquet/settlements", tags=["banquet-settlement"])

class GenerateReq(BaseModel):
    banquet_id: str
class FinalizeReq(BaseModel):
    payment_method: str
    payment_ref: Optional[str] = None

@router.post("/generate")
async def generate(req: GenerateReq, r: Request, db: AsyncSession = Depends(_db)):
    try: return _ok(await BanquetSettlementService(db, _tid(r)).generate_settlement(req.banquet_id))
    except ValueError as e: _err(str(e))

@router.get("/by-banquet/{banquet_id}")
async def get_by_banquet(banquet_id: str, r: Request, db: AsyncSession = Depends(_db)):
    return _ok(await BanquetSettlementService(db, _tid(r)).get_by_banquet(banquet_id))

@router.get("/{settlement_id}")
async def get_settlement(settlement_id: str, r: Request, db: AsyncSession = Depends(_db)):
    try: return _ok(await BanquetSettlementService(db, _tid(r)).get_settlement(settlement_id))
    except ValueError as e: _err(str(e), 404)

@router.post("/{settlement_id}/finalize")
async def finalize(settlement_id: str, req: FinalizeReq, r: Request, db: AsyncSession = Depends(_db)):
    return _ok(await BanquetSettlementService(db, _tid(r)).finalize(settlement_id, req.payment_method, req.payment_ref))

@router.post("/{settlement_id}/invoice")
async def request_invoice(settlement_id: str, r: Request, db: AsyncSession = Depends(_db)):
    return _ok(await BanquetSettlementService(db, _tid(r)).request_invoice(settlement_id))
