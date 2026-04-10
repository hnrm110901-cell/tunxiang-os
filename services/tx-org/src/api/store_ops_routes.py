"""门店人力作战台 BFF 聚合路由

端点列表：
  GET  /api/v1/store-ops/today            今日人力作战台首页数据
  GET  /api/v1/store-ops/positions        岗位在岗/离岗详情列表
  GET  /api/v1/store-ops/anomalies        今日考勤异常列表
  POST /api/v1/store-ops/quick-action     店长快速操作
  GET  /api/v1/store-ops/weekly-summary   本周人力概览
  GET  /api/v1/store-ops/fill-suggestions 缺岗补位建议
  POST /api/v1/store-ops/fill-gap         确认补位
  GET  /api/v1/store-ops/labor-metrics    月度人力指标

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.store_ops_service import (
    execute_fill_gap,
    execute_quick_action,
    get_anomalies,
    get_fill_suggestions,
    get_labor_metrics,
    get_position_detail,
    get_today_dashboard,
    get_weekly_summary,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["store-ops"])


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


# ── 请求/响应模型 ─────────────────────────────────────────────────────────────


class QuickActionRequest(BaseModel):
    action_type: str = Field(
        ...,
        description="acknowledge_late | mark_absent | approve_leave | assign_fill",
    )
    target_id: str = Field(..., description="对应记录ID")
    operator_id: str = Field(..., description="操作人ID")
    note: Optional[str] = Field(None, description="备注")


class FillGapRequest(BaseModel):
    gap_id: str = Field(..., description="缺口ID")
    employee_id: str = Field(..., description="补位员工ID")
    fill_type: str = Field(
        ...,
        description="internal_transfer | cross_store | overtime",
    )


# ── 端点实现 ──────────────────────────────────────────────────────────────────


@router.get("/api/v1/store-ops/today")
async def today_dashboard(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    target_date: Optional[date] = Query(None, description="目标日期，默认今天"),
    db: AsyncSession = Depends(get_db),
):
    """今日人力作战台首页数据。"""
    tenant_id = _get_tenant_id(request)
    log.info("store_ops.today", store_id=store_id, target_date=target_date)
    try:
        data = await get_today_dashboard(db, tenant_id, store_id, target_date)
        return _ok(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/v1/store-ops/positions")
async def position_detail(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    target_date: Optional[date] = Query(None, alias="date", description="日期"),
    db: AsyncSession = Depends(get_db),
):
    """岗位在岗/离岗详情列表。"""
    tenant_id = _get_tenant_id(request)
    log.info("store_ops.positions", store_id=store_id, target_date=target_date)
    data = await get_position_detail(db, tenant_id, store_id, target_date)
    return _ok(data)


@router.get("/api/v1/store-ops/anomalies")
async def anomalies_list(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    target_date: Optional[date] = Query(None, alias="date", description="日期"),
    db: AsyncSession = Depends(get_db),
):
    """今日考勤异常列表（迟到/未打卡/早退）。"""
    tenant_id = _get_tenant_id(request)
    log.info("store_ops.anomalies", store_id=store_id, target_date=target_date)
    data = await get_anomalies(db, tenant_id, store_id, target_date)
    return _ok(data)


@router.post("/api/v1/store-ops/quick-action")
async def quick_action(
    request: Request,
    body: QuickActionRequest,
    db: AsyncSession = Depends(get_db),
):
    """店长快速操作：确认迟到/标记旷工/审批请假/指派补位。"""
    tenant_id = _get_tenant_id(request)
    log.info(
        "store_ops.quick_action",
        action_type=body.action_type,
        target_id=body.target_id,
    )
    try:
        result = await execute_quick_action(
            db, tenant_id,
            body.action_type,
            body.target_id,
            body.operator_id,
            body.note,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/v1/store-ops/weekly-summary")
async def weekly_summary(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    db: AsyncSession = Depends(get_db),
):
    """本周人力概览（7天出勤率/工时/成本趋势）。"""
    tenant_id = _get_tenant_id(request)
    log.info("store_ops.weekly_summary", store_id=store_id)
    data = await get_weekly_summary(db, tenant_id, store_id)
    return _ok(data)


@router.get("/api/v1/store-ops/fill-suggestions")
async def fill_suggestions(
    request: Request,
    gap_id: str = Query(..., description="缺口ID"),
    db: AsyncSession = Depends(get_db),
):
    """缺岗补位建议候选人列表。"""
    tenant_id = _get_tenant_id(request)
    log.info("store_ops.fill_suggestions", gap_id=gap_id)
    data = await get_fill_suggestions(db, tenant_id, gap_id)
    return _ok(data)


@router.post("/api/v1/store-ops/fill-gap")
async def fill_gap(
    request: Request,
    body: FillGapRequest,
    db: AsyncSession = Depends(get_db),
):
    """确认补位：创建新排班 + 更新缺口状态 + 发事件。"""
    tenant_id = _get_tenant_id(request)
    log.info(
        "store_ops.fill_gap",
        gap_id=body.gap_id,
        employee_id=body.employee_id,
        fill_type=body.fill_type,
    )
    try:
        result = await execute_fill_gap(
            db, tenant_id,
            body.gap_id,
            body.employee_id,
            body.fill_type,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/v1/store-ops/labor-metrics")
async def labor_metrics(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    month: str = Query(..., description="月份 YYYY-MM", regex=r"^\d{4}-\d{2}$"),
    db: AsyncSession = Depends(get_db),
):
    """月度人力指标：出勤率/人均工时/人工成本率/加班率/缺勤率。"""
    tenant_id = _get_tenant_id(request)
    log.info("store_ops.labor_metrics", store_id=store_id, month=month)
    data = await get_labor_metrics(db, tenant_id, store_id, month)
    return _ok(data)
