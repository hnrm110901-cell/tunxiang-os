"""顾客体验链路监控 API 路由 — Sprint G4

端点:
  POST /api/v1/journey/events                        记录旅程事件打点
  GET  /api/v1/journey/{store_id}/active              当前活跃旅程(实时)
  GET  /api/v1/journey/{store_id}/violations          SLA违规列表
  GET  /api/v1/journey/{store_id}/stats               旅程统计
  POST /api/v1/journey/{store_id}/satisfaction         提交满意度评分
  GET  /api/v1/journey/{store_id}/satisfaction/dashboard  满意度仪表盘
  GET  /api/v1/journey/{store_id}/satisfaction/alerts  差评告警
  GET  /api/v1/journey/{store_id}/funnel               转化漏斗
  POST /api/v1/journey/{store_id}/funnel/compute       计算当日漏斗

统一响应: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.conversion_funnel_service import ConversionFunnelService
from ..services.customer_journey_timing_service import CustomerJourneyTimingService
from ..services.satisfaction_service import SatisfactionService

router = APIRouter(prefix="/api/v1/journey", tags=["customer-journey"])
log = structlog.get_logger(__name__)

# 服务实例
_journey_svc = CustomerJourneyTimingService()
_satisfaction_svc = SatisfactionService()
_funnel_svc = ConversionFunnelService()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Pydantic 请求/响应模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class JourneyEventRequest(BaseModel):
    """旅程事件打点请求。"""

    store_id: uuid.UUID
    order_id: Optional[uuid.UUID] = None
    table_id: Optional[uuid.UUID] = None
    event_type: str = Field(
        ...,
        description="事件类型: arrived|seated|ordered|first_served|paid|left",
    )
    timestamp: Optional[datetime] = None
    party_size: Optional[int] = Field(None, ge=1, le=100)
    is_delivery: bool = False


class SatisfactionRequest(BaseModel):
    """满意度评分请求。"""

    order_id: Optional[uuid.UUID] = None
    journey_id: Optional[uuid.UUID] = None
    overall_score: int = Field(..., ge=1, le=5)
    food_score: Optional[int] = Field(None, ge=1, le=5)
    service_score: Optional[int] = Field(None, ge=1, le=5)
    speed_score: Optional[int] = Field(None, ge=1, le=5)
    comment: Optional[str] = Field(None, max_length=2000)
    source: str = Field("miniapp", pattern=r"^(miniapp|pos|manual)$")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": {}}


def _err(code: str, message: str, status: int = 400) -> None:
    raise HTTPException(
        status_code=status,
        detail={"ok": False, "data": {}, "error": {"code": code, "message": message}},
    )


def _parse_tenant(x_tenant_id: Optional[str]) -> uuid.UUID:
    if not x_tenant_id:
        _err("MISSING_TENANT", "缺少 X-Tenant-ID 请求头", 401)
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        _err("INVALID_TENANT", "X-Tenant-ID 格式错误", 401)
    # unreachable, but keeps mypy happy
    raise HTTPException(status_code=401)  # pragma: no cover


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  旅程事件打点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/events")
async def record_journey_event(
    body: JourneyEventRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """记录旅程事件打点。"""
    tenant_id = _parse_tenant(x_tenant_id)
    ts = body.timestamp or datetime.now(timezone.utc)

    try:
        result = await _journey_svc.record_event(
            db=db,
            store_id=body.store_id,
            tenant_id=tenant_id,
            order_id=body.order_id,
            event_type=body.event_type,
            timestamp=ts,
            table_id=body.table_id,
            party_size=body.party_size,
            is_delivery=body.is_delivery,
        )
        return _ok(result)
    except ValueError as e:
        _err("INVALID_EVENT", str(e))
    except SQLAlchemyError as e:
        log.error("journey_event_db_error", error=str(e))
        _err("DB_ERROR", "数据库操作失败", 500)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  当前活跃旅程
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/{store_id}/active")
async def get_active_journeys(
    store_id: uuid.UUID,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """当前活跃旅程（实时看板）。"""
    tenant_id = _parse_tenant(x_tenant_id)

    try:
        journeys = await _journey_svc.get_active_journeys(
            db=db, store_id=store_id, tenant_id=tenant_id
        )
        return _ok({"journeys": journeys, "count": len(journeys)})
    except SQLAlchemyError as e:
        log.error("active_journeys_db_error", error=str(e))
        _err("DB_ERROR", "数据库操作失败", 500)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SLA 违规列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/{store_id}/violations")
async def get_sla_violations(
    store_id: uuid.UUID,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """SLA 违规列表。"""
    tenant_id = _parse_tenant(x_tenant_id)

    try:
        violations = await _journey_svc.check_sla_violations(
            db=db, store_id=store_id, tenant_id=tenant_id
        )
        return _ok({"violations": violations, "count": len(violations)})
    except SQLAlchemyError as e:
        log.error("sla_violations_db_error", error=str(e))
        _err("DB_ERROR", "数据库操作失败", 500)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  旅程统计
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/{store_id}/stats")
async def get_journey_stats(
    store_id: uuid.UUID,
    date_from: Optional[date] = Query(None, description="起始日期(含), 默认7天前"),
    date_to: Optional[date] = Query(None, description="结束日期(含), 默认今天"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """旅程统计。"""
    tenant_id = _parse_tenant(x_tenant_id)
    today = date.today()
    d_from = date_from or (today - timedelta(days=6))
    d_to = date_to or today

    try:
        stats = await _journey_svc.get_journey_stats(
            db=db,
            store_id=store_id,
            tenant_id=tenant_id,
            date_from=d_from,
            date_to=d_to,
        )
        return _ok(stats)
    except SQLAlchemyError as e:
        log.error("journey_stats_db_error", error=str(e))
        _err("DB_ERROR", "数据库操作失败", 500)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  满意度评分
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/{store_id}/satisfaction")
async def submit_satisfaction(
    store_id: uuid.UUID,
    body: SatisfactionRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """提交满意度评分。"""
    tenant_id = _parse_tenant(x_tenant_id)

    try:
        result = await _satisfaction_svc.submit_rating(
            db=db,
            store_id=store_id,
            tenant_id=tenant_id,
            order_id=body.order_id,
            overall_score=body.overall_score,
            food_score=body.food_score,
            service_score=body.service_score,
            speed_score=body.speed_score,
            comment=body.comment,
            source=body.source,
            journey_id=body.journey_id,
        )
        return _ok(result)
    except ValueError as e:
        _err("INVALID_RATING", str(e))
    except SQLAlchemyError as e:
        log.error("satisfaction_submit_db_error", error=str(e))
        _err("DB_ERROR", "数据库操作失败", 500)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  满意度仪表盘
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/{store_id}/satisfaction/dashboard")
async def get_satisfaction_dashboard(
    store_id: uuid.UUID,
    date_from: Optional[date] = Query(None, description="起始日期(含), 默认30天前"),
    date_to: Optional[date] = Query(None, description="结束日期(含), 默认今天"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """满意度仪表盘。"""
    tenant_id = _parse_tenant(x_tenant_id)
    today = date.today()
    d_from = date_from or (today - timedelta(days=29))
    d_to = date_to or today

    try:
        dashboard = await _satisfaction_svc.get_satisfaction_dashboard(
            db=db,
            store_id=store_id,
            tenant_id=tenant_id,
            date_from=d_from,
            date_to=d_to,
        )
        return _ok(dashboard)
    except SQLAlchemyError as e:
        log.error("satisfaction_dashboard_db_error", error=str(e))
        _err("DB_ERROR", "数据库操作失败", 500)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  差评告警
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/{store_id}/satisfaction/alerts")
async def get_negative_alerts(
    store_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """差评告警列表。"""
    tenant_id = _parse_tenant(x_tenant_id)

    try:
        alerts = await _satisfaction_svc.get_negative_alerts(
            db=db,
            store_id=store_id,
            tenant_id=tenant_id,
            limit=limit,
        )
        return _ok({"alerts": alerts, "count": len(alerts)})
    except SQLAlchemyError as e:
        log.error("negative_alerts_db_error", error=str(e))
        _err("DB_ERROR", "数据库操作失败", 500)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  转化漏斗
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/{store_id}/funnel")
async def get_funnel_analysis(
    store_id: uuid.UUID,
    date_from: Optional[date] = Query(None, description="起始日期(含), 默认30天前"),
    date_to: Optional[date] = Query(None, description="结束日期(含), 默认今天"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """转化漏斗分析。"""
    tenant_id = _parse_tenant(x_tenant_id)
    today = date.today()
    d_from = date_from or (today - timedelta(days=29))
    d_to = date_to or today

    try:
        analysis = await _funnel_svc.get_funnel_analysis(
            db=db,
            store_id=store_id,
            tenant_id=tenant_id,
            date_from=d_from,
            date_to=d_to,
        )
        return _ok(analysis)
    except SQLAlchemyError as e:
        log.error("funnel_analysis_db_error", error=str(e))
        _err("DB_ERROR", "数据库操作失败", 500)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  计算当日漏斗
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/{store_id}/funnel/compute")
async def compute_daily_funnel(
    store_id: uuid.UUID,
    target_date: Optional[date] = Query(None, description="目标日期, 默认今天"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """计算指定日期的转化漏斗。"""
    tenant_id = _parse_tenant(x_tenant_id)
    d = target_date or date.today()

    try:
        result = await _funnel_svc.compute_daily_funnel(
            db=db,
            store_id=store_id,
            tenant_id=tenant_id,
            target_date=d,
        )
        return _ok(result)
    except SQLAlchemyError as e:
        log.error("funnel_compute_db_error", error=str(e))
        _err("DB_ERROR", "数据库操作失败", 500)
