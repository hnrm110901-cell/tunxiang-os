"""营收驱动排班 API 路由

端点列表（prefix=/api/v1/revenue-schedule）：
  GET  /api/v1/revenue-schedule/analysis         时段营收分析
  GET  /api/v1/revenue-schedule/optimal-plan      最优排班方案
  POST /api/v1/revenue-schedule/apply-plan        将最优方案写入排班表(draft)
  GET  /api/v1/revenue-schedule/comparison        当前排班vs最优排班对比
  GET  /api/v1/revenue-schedule/savings-estimate  月度成本节约预估

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.revenue_schedule_service import RevenueScheduleService

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/revenue-schedule", tags=["revenue-schedule"])

# 单例
_service = RevenueScheduleService()


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": msg}}


def _set_tenant(db: AsyncSession, tenant_id: str):
    """RLS 设置当前租户（预留，由中间件统一处理）。"""
    pass


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class ApplyPlanRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    week_start: date = Field(..., description="周起始日期（周一）")
    operator_id: str = Field(..., description="操作人ID")


# ── 端点实现 ──────────────────────────────────────────────────────────────────


@router.get("/analysis")
async def revenue_analysis(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    weeks: int = Query(4, ge=1, le=12, description="回溯周数"),
    db: AsyncSession = Depends(get_db),
):
    """时段营收分析——返回各时段平均营收 + 人力需求推导。"""
    tenant_id = _get_tenant_id(request)
    log.info(
        "revenue_schedule.api.analysis",
        store_id=store_id,
        weeks=weeks,
    )
    try:
        data = await _service.analyze_revenue_pattern(
            db, tenant_id, store_id, weeks
        )
        return _ok(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/optimal-plan")
async def optimal_plan(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    week_start: Optional[date] = Query(
        None, description="周起始日（周一），默认下周一"
    ),
    db: AsyncSession = Depends(get_db),
):
    """最优排班方案——返回一整周7天×6时段的最优人力配置。"""
    tenant_id = _get_tenant_id(request)

    if week_start is None:
        today = date.today()
        days_to_monday = (7 - today.weekday()) % 7 or 7
        week_start = today + timedelta(days=days_to_monday)

    log.info(
        "revenue_schedule.api.optimal_plan",
        store_id=store_id,
        week_start=week_start.isoformat(),
    )
    try:
        data = await _service.generate_weekly_plan(
            db, tenant_id, store_id, week_start
        )
        return _ok(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/apply-plan")
async def apply_plan(
    request: Request,
    body: ApplyPlanRequest,
    db: AsyncSession = Depends(get_db),
):
    """将最优方案写入排班表（status=draft），30分钟回滚窗口。"""
    tenant_id = _get_tenant_id(request)
    log.info(
        "revenue_schedule.api.apply_plan",
        store_id=body.store_id,
        week_start=body.week_start.isoformat(),
        operator_id=body.operator_id,
    )
    try:
        data = await _service.apply_plan_as_draft(
            db,
            tenant_id,
            body.store_id,
            body.week_start,
            body.operator_id,
        )
        return _ok(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/comparison")
async def comparison(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    week_start: Optional[date] = Query(
        None, description="周起始日（周一），默认下周一"
    ),
    db: AsyncSession = Depends(get_db),
):
    """当前排班 vs 最优排班对比——按时段展示差异。"""
    tenant_id = _get_tenant_id(request)

    if week_start is None:
        today = date.today()
        days_to_monday = (7 - today.weekday()) % 7 or 7
        week_start = today + timedelta(days=days_to_monday)

    log.info(
        "revenue_schedule.api.comparison",
        store_id=store_id,
        week_start=week_start.isoformat(),
    )
    try:
        plan = await _service.generate_weekly_plan(
            db, tenant_id, store_id, week_start
        )

        # 汇总各时段差异
        slot_comparison: list[dict] = []
        for day_plan in plan["daily_plans"]:
            for slot in day_plan["slots"]:
                if slot.get("delta"):
                    slot_comparison.append({
                        "date": day_plan["date"],
                        "weekday_name": day_plan["weekday_name"],
                        "slot_name": slot["slot_name"],
                        "start_time": slot["start_time"],
                        "end_time": slot["end_time"],
                        "predicted_revenue_fen": slot["predicted_revenue_fen"],
                        "optimal_staff": slot["optimal_staff"],
                        "current_staff": slot["current_staff"],
                        "delta": slot["delta"],
                    })

        data = {
            "store_id": store_id,
            "week_start": week_start.isoformat(),
            "differences": slot_comparison,
            "total_differences": len(slot_comparison),
            "summary": plan["summary"],
        }
        return _ok(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/savings-estimate")
async def savings_estimate(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    month: str = Query(
        ...,
        description="月份 YYYY-MM",
        regex=r"^\d{4}-\d{2}$",
    ),
    db: AsyncSession = Depends(get_db),
):
    """月度成本节约预估——当前排班方案 vs 营收驱动方案的差额。"""
    tenant_id = _get_tenant_id(request)
    log.info(
        "revenue_schedule.api.savings_estimate",
        store_id=store_id,
        month=month,
    )
    try:
        data = await _service.estimate_monthly_savings(
            db, tenant_id, store_id, month
        )
        return _ok(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
