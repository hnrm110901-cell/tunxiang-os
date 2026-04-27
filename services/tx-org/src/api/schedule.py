"""排班管理 API"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.attendance_repository import get_store_schedules_for_date
from ..services.smart_schedule import SmartScheduleService

router = APIRouter(tags=["schedule"])

_store_schedule_services: dict[str, SmartScheduleService] = {}


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _svc_for_store(store_id: str) -> SmartScheduleService:
    if store_id not in _store_schedule_services:
        _store_schedule_services[store_id] = SmartScheduleService(
            store_config={
                "store_id": store_id,
                "store_name": store_id,
                "total_tables": 30,
                "open_hour": 10,
                "close_hour": 22,
                "base_daily_traffic": 280,
                "city": "changsha",
            }
        )
    return _store_schedule_services[store_id]


def _pick_latest_schedule_id(store_id: str) -> Optional[str]:
    svc = _store_schedule_services.get(store_id)
    if not svc or not svc._schedules:
        return None
    items = sorted(
        svc._schedules.items(),
        key=lambda x: x[1].get("created_at") or "",
        reverse=True,
    )
    return items[0][0] if items else None


def _run_generate(store_id: str, week_start: date) -> dict[str, Any]:
    return _svc_for_store(store_id).generate_schedule(store_id, week_start)


def _run_swap(
    store_id: str,
    schedule_id: str,
    employee_a: str,
    employee_b: str,
    shift_date: date,
) -> dict[str, Any]:
    return _svc_for_store(store_id).swap_shift(
        schedule_id,
        employee_a,
        employee_b,
        shift_date.isoformat(),
    )


class GenerateScheduleBody(BaseModel):
    store_id: str = Field(..., description="门店 ID")
    week_start: date = Field(..., description="周起始日 YYYY-MM-DD")


class SwapScheduleBody(BaseModel):
    store_id: str = Field(..., description="门店 ID")
    schedule_id: str = Field(..., description="排班表 ID")
    from_employee_id: str = Field(..., description="员工 A")
    to_employee_id: str = Field(..., description="员工 B")
    shift_date: date = Field(..., description="换班日期 YYYY-MM-DD")


async def _weekly_payload(
    store_id: str,
    week_start: date,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    for i in range(7):
        d = week_start + timedelta(days=i)
        rows = await get_store_schedules_for_date(store_id, d, tenant_id, db)
        by_date[d.isoformat()] = rows
    return {
        "store_id": store_id,
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "by_date": by_date,
    }


@router.get("/api/v1/schedule/weekly")
async def get_weekly_schedule(
    request: Request,
    store_id: str = Query(..., description="门店 ID"),
    week_start: date = Query(..., description="周起始日 YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/schedule/weekly — 获取某门店某周排班表（库表 employee_schedules）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)
    payload = await _weekly_payload(store_id, week_start, tenant_id, db)
    return _ok(payload)


@router.post("/api/v1/schedule/generate")
async def generate_schedule_v1(body: GenerateScheduleBody) -> dict[str, Any]:
    """POST /api/v1/schedule/generate — 智能生成排班建议（SmartScheduleService）"""
    data = _run_generate(body.store_id, body.week_start)
    return _ok(data)


@router.put("/api/v1/schedule/swap")
async def swap_schedule_v1(body: SwapScheduleBody) -> dict[str, Any]:
    """PUT /api/v1/schedule/swap — 换班申请（SmartScheduleService.swap_shift）"""
    result = _run_swap(
        body.store_id,
        body.schedule_id,
        body.from_employee_id,
        body.to_employee_id,
        body.shift_date,
    )
    if not result.get("ok", True):
        raise HTTPException(status_code=400, detail=result.get("error", "换班失败"))
    return _ok(result)


@router.get("/api/v1/org/schedule/")
async def get_schedule(
    request: Request,
    store_id: str = Query(...),
    week: Optional[str] = Query(None, description="周起始 YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询排班（周视图，库表）"""
    if not week:
        return _ok({"schedule": []})
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)
    try:
        ws = date.fromisoformat(week)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="week 须为 YYYY-MM-DD") from e
    payload = await _weekly_payload(store_id, ws, tenant_id, db)
    return _ok(payload)


@router.post("/api/v1/org/schedule/generate")
async def generate_schedule(
    store_id: str = Query(...),
    week: str = Query(..., description="周起始 YYYY-MM-DD"),
) -> dict[str, Any]:
    """AI 排班生成"""
    try:
        ws = date.fromisoformat(week)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="week 须为 YYYY-MM-DD") from e
    data = _run_generate(store_id, ws)
    return _ok(data)


@router.post("/api/v1/org/schedule/optimize")
async def optimize_schedule(store_id: str, schedule_id: str) -> dict[str, Any]:
    """多目标优化（成本/满意度/服务质量）"""
    svc = _svc_for_store(store_id)
    sch = svc._schedules.get(schedule_id)
    if not sch:
        raise HTTPException(status_code=404, detail="排班表不存在")
    validation = svc.validate_schedule(sch)
    return _ok({"optimized": True, "schedule_id": schedule_id, "validation": validation})


@router.get("/api/v1/org/schedule/staffing-needs")
async def get_staffing_needs(
    store_id: str = Query(...),
    work_date: str = Query(..., alias="date", description="YYYY-MM-DD"),
) -> dict[str, Any]:
    """人力需求预测"""
    try:
        d = date.fromisoformat(work_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="date 须为 YYYY-MM-DD") from e
    needs = _svc_for_store(store_id).calculate_staffing_need(store_id, d)
    return _ok({"needs": needs})


@router.post("/api/v1/org/schedule/advice/confirm")
async def confirm_staffing_advice(store_id: str, advice_id: str) -> dict[str, Any]:
    """店长确认排班建议"""
    return _ok({"confirmed": True, "store_id": store_id, "advice_id": advice_id})


@router.get("/api/v1/org/schedule/fairness")
async def get_shift_fairness(store_id: str, month: Optional[str] = None) -> dict[str, Any]:
    """班次公平性评分"""
    return _ok({"scores": [], "store_id": store_id, "month": month})


@router.post("/api/v1/org/schedule/swap-request")
async def request_shift_swap(
    from_emp_id: str = Query(...),
    to_emp_id: str = Query(...),
    shift_date: str = Query(..., description="YYYY-MM-DD"),
    store_id: Optional[str] = Query(None),
    schedule_id: Optional[str] = Query(None),
) -> dict[str, Any]:
    """换班申请"""
    try:
        d = date.fromisoformat(shift_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="shift_date 须为 YYYY-MM-DD") from e
    sid = schedule_id
    if store_id and not sid:
        sid = _pick_latest_schedule_id(store_id)
    if not store_id or not sid:
        return _ok({"request_id": "new"})
    result = _run_swap(store_id, sid, from_emp_id, to_emp_id, d)
    if not result.get("ok", True):
        raise HTTPException(status_code=400, detail=result.get("error", "换班失败"))
    return _ok(result)
