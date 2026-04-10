"""人力成本毛利仪表盘路由

端点：
  GET /api/v1/labor-margin/realtime      实时毛利（含人力成本）
  GET /api/v1/labor-margin/hourly        按小时分解
  GET /api/v1/labor-margin/monthly       月度趋势
  GET /api/v1/labor-margin/comparison    多店对比
  GET /api/v1/labor-margin/loss-hours    亏损时段识别

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date
from typing import Any, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.labor_margin_service import LaborMarginService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/labor-margin", tags=["labor-margin"])

_svc = LaborMarginService()


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


# ── 端点 ──────────────────────────────────────────────────────────────────────


@router.get("/realtime")
async def realtime_margin(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    target_date: Optional[date] = Query(None, description="日期，默认今天"),
    db: AsyncSession = Depends(get_db),
):
    """实时毛利（含人力成本）"""
    tenant_id = _get_tenant_id(request)
    d = target_date or date.today()
    log.info("labor_margin.realtime", store_id=store_id, date=str(d))
    try:
        data = await _svc.get_realtime_margin(db, tenant_id, store_id, d)
        return _ok(data)
    except ValueError as exc:
        return _err(str(exc))


@router.get("/hourly")
async def hourly_breakdown(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    target_date: Optional[date] = Query(None, description="日期，默认今天"),
    db: AsyncSession = Depends(get_db),
):
    """按小时分解"""
    tenant_id = _get_tenant_id(request)
    d = target_date or date.today()
    log.info("labor_margin.hourly", store_id=store_id, date=str(d))
    try:
        data = await _svc.get_hourly_breakdown(db, tenant_id, store_id, d)
        return _ok(data)
    except ValueError as exc:
        return _err(str(exc))


@router.get("/monthly")
async def monthly_trend(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    month: str = Query(..., description="月份 YYYY-MM"),
    db: AsyncSession = Depends(get_db),
):
    """月度趋势"""
    tenant_id = _get_tenant_id(request)
    log.info("labor_margin.monthly", store_id=store_id, month=month)
    try:
        data = await _svc.get_monthly_trend(db, tenant_id, store_id, month)
        return _ok(data)
    except ValueError as exc:
        return _err(str(exc))


@router.get("/comparison")
async def store_comparison(
    request: Request,
    store_ids: str = Query(..., description="逗号分隔的门店ID列表"),
    month: str = Query(..., description="月份 YYYY-MM"),
    db: AsyncSession = Depends(get_db),
):
    """多店对比"""
    tenant_id = _get_tenant_id(request)
    ids = [s.strip() for s in store_ids.split(",") if s.strip()]
    if not ids:
        return _err("store_ids 不能为空")
    log.info("labor_margin.comparison", store_count=len(ids), month=month)
    try:
        data = await _svc.get_store_comparison(db, tenant_id, ids, month)
        return _ok(data)
    except ValueError as exc:
        return _err(str(exc))


@router.get("/loss-hours")
async def loss_hours(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    target_date: Optional[date] = Query(None, description="日期，默认今天"),
    db: AsyncSession = Depends(get_db),
):
    """亏损时段识别"""
    tenant_id = _get_tenant_id(request)
    d = target_date or date.today()
    log.info("labor_margin.loss_hours", store_id=store_id, date=str(d))
    try:
        data = await _svc.identify_loss_hours(db, tenant_id, store_id, d)
        return _ok(data)
    except ValueError as exc:
        return _err(str(exc))
