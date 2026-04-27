"""日计划 API"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/agent/plans", tags=["planner"])


@router.post("/generate")
async def generate_plan(store_id: str):
    from ..agents.planner import DailyPlannerAgent

    agent = DailyPlannerAgent(tenant_id="default", store_id=store_id)
    plan = await agent.generate_daily_plan()
    return {"ok": True, "data": plan}


@router.get("/{store_id}")
async def get_plan(store_id: str, date: str = "today"):
    return {"ok": True, "data": {"store_id": store_id, "date": date, "status": "pending_approval"}}


@router.post("/{plan_id}/approve")
async def approve_plan(plan_id: str, approved_items: list = [], rejected_items: list = [], notes: str = ""):
    return {"ok": True, "data": {"plan_id": plan_id, "status": "approved"}}


@router.get("/{plan_id}/status")
async def plan_status(plan_id: str):
    return {"ok": True, "data": {"plan_id": plan_id, "status": "executing"}}


@router.get("/history/")
async def plan_history(store_id: str, limit: int = 30):
    return {"ok": True, "data": {"items": [], "total": 0}}
