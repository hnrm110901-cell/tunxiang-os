"""宴会AI + KPI看板 API"""
from typing import AsyncGenerator, Optional
from datetime import date as date_cls
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db_with_tenant

def _tid(r: Request) -> str:
    t = getattr(r.state, "tenant_id", None) or r.headers.get("X-Tenant-ID", "")
    if not t: raise HTTPException(400, "X-Tenant-ID required")
    return t
async def _db(r: Request) -> AsyncGenerator[AsyncSession, None]:
    async for s in get_db_with_tenant(_tid(r)): yield s
def _ok(d): return {"ok": True, "data": d, "error": None}
def _err(m, c=400): raise HTTPException(c, {"ok": False, "data": None, "error": {"message": m}})

router = APIRouter(prefix="/api/v1/banquet/ai", tags=["banquet-ai"])


class PriceSuggestReq(BaseModel):
    store_id: str
    event_type: str
    table_count: int
    guest_count: int
    event_month: Optional[int] = None

class MenuSuggestReq(BaseModel):
    event_type: str
    tier: str = "standard"
    budget_per_table_fen: int

class PreCheckReq(BaseModel):
    banquet_id: str

class ForecastReq(BaseModel):
    store_id: str
    target_month: str

class SnapshotReq(BaseModel):
    store_id: str
    period: str = "monthly"
    date: str


@router.post("/pricing/suggest")
async def suggest_price(req: PriceSuggestReq, r: Request, db: AsyncSession = Depends(_db)):
    from ..agents.skills.banquet_pricing_agent import BanquetPricingAgent
    agent = BanquetPricingAgent(db, _tid(r))
    return _ok(await agent.suggest_price(req.store_id, req.event_type, req.table_count, req.guest_count, req.event_month))

@router.post("/pricing/menu")
async def suggest_menu(req: MenuSuggestReq, r: Request, db: AsyncSession = Depends(_db)):
    from ..agents.skills.banquet_pricing_agent import BanquetPricingAgent
    agent = BanquetPricingAgent(db, _tid(r))
    return _ok(await agent.suggest_menu(req.event_type, req.tier, req.budget_per_table_fen))

@router.post("/operations/pre-check")
async def pre_event_check(req: PreCheckReq, r: Request, db: AsyncSession = Depends(_db)):
    from ..agents.skills.banquet_operations_agent import BanquetOperationsAgent
    agent = BanquetOperationsAgent(db, _tid(r))
    return _ok(await agent.pre_event_check(req.banquet_id))

@router.get("/operations/optimize/{store_id}")
async def optimize_schedule(store_id: str, date: str = Query(...), r: Request = None, db: AsyncSession = Depends(_db)):
    from ..agents.skills.banquet_operations_agent import BanquetOperationsAgent
    agent = BanquetOperationsAgent(db, _tid(r))
    return _ok(await agent.optimize_daily_schedule(store_id, date_cls.fromisoformat(date)))

@router.post("/growth/forecast")
async def forecast_demand(req: ForecastReq, r: Request, db: AsyncSession = Depends(_db)):
    from ..agents.skills.banquet_growth_agent import BanquetGrowthAgent
    agent = BanquetGrowthAgent(db, _tid(r))
    return _ok(await agent.forecast_demand(req.store_id, req.target_month))

@router.get("/growth/reorder/{store_id}")
async def reorder_opportunities(store_id: str, r: Request = None, db: AsyncSession = Depends(_db)):
    from ..agents.skills.banquet_growth_agent import BanquetGrowthAgent
    agent = BanquetGrowthAgent(db, _tid(r))
    return _ok(await agent.find_reorder_opportunities(store_id))

@router.get("/growth/churn/{store_id}")
async def churn_risk(store_id: str, days: int = 90, r: Request = None, db: AsyncSession = Depends(_db)):
    from ..agents.skills.banquet_growth_agent import BanquetGrowthAgent
    agent = BanquetGrowthAgent(db, _tid(r))
    return _ok(await agent.detect_churn_risk(store_id, days))

@router.post("/dashboard/snapshot")
async def generate_snapshot(req: SnapshotReq, r: Request, db: AsyncSession = Depends(_db)):
    from ..services.banquet_kpi_service import BanquetKPIService
    svc = BanquetKPIService(db, _tid(r))
    return _ok(await svc.generate_snapshot(req.store_id, req.period, date_cls.fromisoformat(req.date)))

@router.get("/dashboard/{store_id}")
async def get_dashboard(store_id: str, period: str = "monthly", r: Request = None, db: AsyncSession = Depends(_db)):
    from ..services.banquet_kpi_service import BanquetKPIService
    svc = BanquetKPIService(db, _tid(r))
    return _ok(await svc.get_dashboard(store_id, period))

@router.get("/dashboard/benchmarks/{store_id}")
async def get_benchmarks(store_id: str, date: str = Query(...), r: Request = None, db: AsyncSession = Depends(_db)):
    from ..services.banquet_kpi_service import BanquetKPIService
    svc = BanquetKPIService(db, _tid(r))
    return _ok(await svc.generate_benchmarks(store_id, date_cls.fromisoformat(date)))
