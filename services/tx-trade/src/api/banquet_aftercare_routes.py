"""宴会售后 API"""

from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.banquet_aftercare_service import BanquetAftercareService


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


router = APIRouter(prefix="/api/v1/banquet/aftercare", tags=["banquet-aftercare"])


class FeedbackReq(BaseModel):
    banquet_id: str
    overall_score: int = Field(ge=1, le=5)
    food_score: int = 0
    service_score: int = 0
    venue_score: int = 0
    value_score: int = 0
    comments: Optional[str] = None
    improvement_suggestions: Optional[str] = None
    would_recommend: bool = True
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None


class ReplyReq(BaseModel):
    reply_content: str
    replied_by: str


class ReferralReq(BaseModel):
    referrer_banquet_id: str
    referred_name: str
    referred_phone: str
    referrer_name: Optional[str] = None
    referrer_phone: Optional[str] = None
    reward_type: str = "coupon"
    reward_value_fen: int = 0


class ConvertReq(BaseModel):
    lead_id: str


@router.post("/feedbacks")
async def submit_feedback(req: FeedbackReq, r: Request, db: AsyncSession = Depends(_db)):
    try:
        return _ok(await BanquetAftercareService(db, _tid(r)).submit_feedback(**req.model_dump()))
    except ValueError as e:
        _err(str(e))


@router.get("/feedbacks")
async def list_feedbacks(
    banquet_id: Optional[str] = None,
    min_score: Optional[int] = None,
    page: int = 1,
    size: int = 20,
    r: Request = None,
    db: AsyncSession = Depends(_db),
):
    return _ok(
        await BanquetAftercareService(db, _tid(r)).list_feedbacks(
            banquet_id=banquet_id, min_score=min_score, page=page, size=size
        )
    )


@router.post("/feedbacks/{feedback_id}/reply")
async def reply_feedback(feedback_id: str, req: ReplyReq, r: Request, db: AsyncSession = Depends(_db)):
    return _ok(
        await BanquetAftercareService(db, _tid(r)).reply_feedback(feedback_id, req.reply_content, req.replied_by)
    )


@router.get("/satisfaction")
async def satisfaction_stats(r: Request = None, db: AsyncSession = Depends(_db)):
    return _ok(await BanquetAftercareService(db, _tid(r)).get_satisfaction_stats())


@router.post("/referrals")
async def create_referral(req: ReferralReq, r: Request, db: AsyncSession = Depends(_db)):
    return _ok(await BanquetAftercareService(db, _tid(r)).create_referral(**req.model_dump()))


@router.post("/referrals/{referral_id}/convert")
async def convert_referral(referral_id: str, req: ConvertReq, r: Request, db: AsyncSession = Depends(_db)):
    return _ok(await BanquetAftercareService(db, _tid(r)).convert_referral(referral_id, req.lead_id))


@router.get("/referrals")
async def list_referrals(
    banquet_id: Optional[str] = None, status: Optional[str] = None, r: Request = None, db: AsyncSession = Depends(_db)
):
    return _ok(await BanquetAftercareService(db, _tid(r)).list_referrals(banquet_id, status))
