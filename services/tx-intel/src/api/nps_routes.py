"""
NPS调查管理 API

POST /api/v1/intel/nps/send-survey  — 发送NPS调查
POST /api/v1/intel/nps/respond       — 记录调查回复
GET  /api/v1/intel/nps/dashboard     — NPS仪表盘
GET  /api/v1/intel/nps/by-store      — 按门店NPS分解
GET  /api/v1/intel/nps/detractors    — 贬损者跟进列表
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from services.nps_service import NPSService
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/intel/nps", tags=["nps"])

_nps_svc = NPSService()


# ─── 请求模型 ────────────────────────────────────────────────────────


class SendSurveyRequest(BaseModel):
    customer_id: str = Field(description="客户UUID")
    store_id: str = Field(description="门店UUID")
    order_id: str | None = Field(default=None, description="可选关联订单UUID")
    channel: str = Field(default="wechat", description="发送渠道: wechat/sms/app")


class RecordResponseRequest(BaseModel):
    survey_id: str = Field(description="调查UUID")
    nps_score: int = Field(ge=0, le=10, description="NPS评分 0-10")
    feedback_text: str | None = Field(default=None, description="可选反馈文本")


# ─── 路由 ─────────────────────────────────────────────────────────────


@router.post("/send-survey")
async def send_survey(
    body: SendSurveyRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """发送NPS调查给客户"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await _nps_svc.send_survey(
            tenant_id=uuid.UUID(x_tenant_id),
            customer_id=uuid.UUID(body.customer_id),
            store_id=uuid.UUID(body.store_id),
            order_id=uuid.UUID(body.order_id) if body.order_id else None,
            db=db,
            channel=body.channel,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        return {"ok": False, "error": {"message": str(exc), "code": "INVALID_INPUT"}}
    except SQLAlchemyError as exc:
        logger.error("nps.send_survey_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.post("/respond")
async def record_response(
    body: RecordResponseRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """记录NPS调查回复"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await _nps_svc.record_response(
            tenant_id=uuid.UUID(x_tenant_id),
            survey_id=uuid.UUID(body.survey_id),
            nps_score=body.nps_score,
            feedback_text=body.feedback_text,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        return {"ok": False, "error": {"message": str(exc), "code": "INVALID_INPUT"}}
    except SQLAlchemyError as exc:
        logger.error("nps.record_response_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.get("/dashboard")
async def get_nps_dashboard(
    store_id: str | None = Query(None, description="门店UUID，空=全部"),
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """NPS仪表盘：得分+趋势+回复率"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await _nps_svc.get_nps_dashboard(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            store_id=uuid.UUID(store_id) if store_id else None,
            days=days,
        )
        return {"ok": True, "data": result}
    except SQLAlchemyError as exc:
        logger.warning("nps.dashboard_failed", error=str(exc))
        return {
            "ok": True,
            "data": {
                "nps_score": 0.0,
                "total_sent": 0,
                "total_responded": 0,
                "response_rate": 0.0,
                "promoters": 0,
                "passives": 0,
                "detractors": 0,
                "avg_score": 0.0,
                "avg_response_time_sec": 0,
                "period_days": days,
                "trend": [],
            },
        }


@router.get("/by-store")
async def get_nps_by_store(
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """按门店NPS分解"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await _nps_svc.get_nps_by_store(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            days=days,
        )
        return {"ok": True, "data": {"stores": result}}
    except SQLAlchemyError as exc:
        logger.warning("nps.by_store_failed", error=str(exc))
        return {"ok": True, "data": {"stores": []}}


@router.get("/detractors")
async def get_detractors(
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """贬损者列表（用于跟进）"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await _nps_svc.get_detractor_list(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            days=days,
        )
        return {"ok": True, "data": {"detractors": result, "total": len(result)}}
    except SQLAlchemyError as exc:
        logger.warning("nps.detractors_failed", error=str(exc))
        return {"ok": True, "data": {"detractors": [], "total": 0}}
