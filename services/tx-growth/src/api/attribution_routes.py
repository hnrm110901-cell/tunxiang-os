"""ROI 归因 API 路由

端点列表：
  GET  /api/v1/growth/attribution/dashboard            营销总览仪表盘
  GET  /api/v1/growth/attribution/campaigns/{id}/roi   单活动 ROI
  GET  /api/v1/growth/attribution/journeys/{id}/roi    旅程 ROI
  GET  /api/v1/growth/attribution/funnel/{source_id}   转化漏斗
  POST /api/v1/growth/attribution/touch                记录营销触达（内部调用）
  POST /api/v1/growth/attribution/order                订单归因（内部调用）
  GET  /api/v1/growth/attribution/top-performers       ROI 最高活动排名

认证：所有请求需携带 X-Tenant-ID header（RLS 租户隔离）。
响应格式：{"ok": bool, "data": {}, "error": {}}
"""

import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, field_validator
from services.roi_attribution import ROIAttributionService

from shared.ontology.src.database import async_session_factory

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/attribution", tags=["attribution"])

_roi_service = ROIAttributionService()


# ---------------------------------------------------------------------------
# 通用响应辅助
# ---------------------------------------------------------------------------


def ok(data: Any) -> dict:
    return {"ok": True, "data": data}


def err(msg: str) -> dict:
    return {"ok": False, "error": {"message": msg}}


def _parse_tenant(x_tenant_id: str) -> uuid.UUID:
    """解析 X-Tenant-ID header，失败时抛 422。"""
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"X-Tenant-ID 格式无效: {x_tenant_id}") from exc


# ---------------------------------------------------------------------------
# Pydantic 请求模型
# ---------------------------------------------------------------------------


class RecordTouchRequest(BaseModel):
    """记录营销触达请求体"""

    customer_id: str
    touch_type: str  # campaign | journey | referral | manual
    source_id: str
    source_name: str = ""
    channel: str  # wecom | sms | miniapp | pos_receipt
    message_title: Optional[str] = None
    offer_id: Optional[str] = None
    touched_at: Optional[str] = None  # ISO 8601，为 None 则使用服务器时间

    @field_validator("touch_type")
    @classmethod
    def validate_touch_type(cls, v: str) -> str:
        allowed = {"campaign", "journey", "referral", "manual"}
        if v not in allowed:
            raise ValueError(f"touch_type 必须是 {allowed} 之一，收到: {v!r}")
        return v

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        allowed = {"wecom", "sms", "miniapp", "pos_receipt"}
        if v not in allowed:
            raise ValueError(f"channel 必须是 {allowed} 之一，收到: {v!r}")
        return v


class AttributeOrderRequest(BaseModel):
    """订单归因请求体"""

    order_id: str
    customer_id: str
    order_amount_fen: int
    order_time: Optional[str] = None  # ISO 8601，为 None 则使用服务器时间
    model: str = "last_touch"  # last_touch | first_touch | linear

    @field_validator("order_amount_fen")
    @classmethod
    def validate_amount(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"order_amount_fen 不能为负数，收到: {v}")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        allowed = {"last_touch", "first_touch", "linear"}
        if v not in allowed:
            raise ValueError(f"model 必须是 {allowed} 之一，收到: {v!r}")
        return v


# ---------------------------------------------------------------------------
# GET /dashboard — 营销总览仪表盘
# ---------------------------------------------------------------------------


@router.get("/dashboard")
async def get_attribution_dashboard(
    start: str = Query(default="", description="开始日期 YYYY-MM-DD，默认本月初"),
    end: str = Query(default="", description="结束日期 YYYY-MM-DD，默认今日"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """营销总览仪表盘。

    返回总触达数、总转化数、总归因收入、平均ROI、渠道对比和近期每日趋势。
    """
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        try:
            data = await _roi_service.get_attribution_dashboard(
                tenant_id=tenant_id,
                date_range={"start": start, "end": end},
                db=db,
            )
            return ok(data)
        except (ValueError, KeyError) as exc:
            log.warning("attribution_dashboard_error", error=str(exc), tenant_id=str(tenant_id))
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET /campaigns/{id}/roi — 单活动 ROI
# ---------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/roi")
async def get_campaign_roi(
    campaign_id: str,
    start: str = Query(default="", description="开始日期 YYYY-MM-DD"),
    end: str = Query(default="", description="结束日期 YYYY-MM-DD"),
    model: str = Query(default="last_touch", description="归因模型"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """计算指定活动在日期范围内的 ROI。"""
    tenant_id = _parse_tenant(x_tenant_id)

    today = datetime.now(timezone.utc).date()
    try:
        start_date = date.fromisoformat(start) if start else date(today.year, today.month, 1)
        end_date = date.fromisoformat(end) if end else today
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"日期格式无效（YYYY-MM-DD）: {exc}") from exc

    async with async_session_factory() as db:
        try:
            data = await _roi_service.calculate_campaign_roi(
                campaign_id=campaign_id,
                start_date=start_date,
                end_date=end_date,
                tenant_id=tenant_id,
                db=db,
                model=model,
            )
            return ok(data)
        except (ValueError, KeyError) as exc:
            log.warning(
                "campaign_roi_error",
                campaign_id=campaign_id,
                error=str(exc),
                tenant_id=str(tenant_id),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET /journeys/{id}/roi — 旅程 ROI
# ---------------------------------------------------------------------------


@router.get("/journeys/{journey_id}/roi")
async def get_journey_roi(
    journey_id: str,
    model: str = Query(default="last_touch", description="归因模型"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """计算指定旅程的 ROI，含各渠道漏斗分析。"""
    tenant_id = _parse_tenant(x_tenant_id)

    async with async_session_factory() as db:
        try:
            data = await _roi_service.calculate_journey_roi(
                journey_id=journey_id,
                tenant_id=tenant_id,
                db=db,
                model=model,
            )
            return ok(data)
        except (ValueError, KeyError) as exc:
            log.warning(
                "journey_roi_error",
                journey_id=journey_id,
                error=str(exc),
                tenant_id=str(tenant_id),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET /funnel/{source_id} — 转化漏斗
# ---------------------------------------------------------------------------


@router.get("/funnel/{source_id}")
async def get_conversion_funnel(
    source_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取指定活动/旅程的逐步转化漏斗。"""
    tenant_id = _parse_tenant(x_tenant_id)

    async with async_session_factory() as db:
        try:
            data = await _roi_service.get_conversion_funnel(
                source_id=source_id,
                tenant_id=tenant_id,
                db=db,
            )
            return ok(data)
        except (ValueError, KeyError) as exc:
            log.warning(
                "funnel_error",
                source_id=source_id,
                error=str(exc),
                tenant_id=str(tenant_id),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# POST /touch — 记录营销触达（内部调用）
# ---------------------------------------------------------------------------


@router.post("/touch")
async def record_touch(
    req: RecordTouchRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """记录一次营销触达事件。

    由旅程执行器（journey_executor）和活动引擎在推送消息后内部调用。
    """
    tenant_id = _parse_tenant(x_tenant_id)

    touch_data: dict = req.model_dump()
    if req.touched_at:
        try:
            touch_data["touched_at"] = datetime.fromisoformat(req.touched_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"touched_at 格式无效（ISO 8601）: {exc}",
            ) from exc

    async with async_session_factory() as db:
        try:
            touch = await _roi_service.record_touch(
                touch_data=touch_data,
                tenant_id=tenant_id,
                db=db,
            )
            await db.commit()
            return ok(
                {
                    "touch_id": str(touch.id),
                    "customer_id": str(touch.customer_id),
                    "source_id": touch.source_id,
                    "channel": touch.channel,
                    "touched_at": touch.touched_at.isoformat(),
                }
            )
        except (ValueError, KeyError) as exc:
            await db.rollback()
            log.warning(
                "record_touch_error",
                error=str(exc),
                tenant_id=str(tenant_id),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# POST /order — 订单归因（内部调用）
# ---------------------------------------------------------------------------


@router.post("/order")
async def attribute_order(
    req: AttributeOrderRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """将一笔订单归因到最近的营销触点。

    由 tx-trade 订单完成事件或旅程 condition 节点 process_first_order 触发。
    """
    tenant_id = _parse_tenant(x_tenant_id)

    try:
        order_uuid = uuid.UUID(req.order_id)
        customer_uuid = uuid.UUID(req.customer_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"UUID 格式无效: {exc}") from exc

    order_time: datetime
    if req.order_time:
        try:
            order_time = datetime.fromisoformat(req.order_time.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"order_time 格式无效（ISO 8601）: {exc}",
            ) from exc
    else:
        order_time = datetime.now(timezone.utc)

    async with async_session_factory() as db:
        try:
            result = await _roi_service.attribute_order(
                order_id=order_uuid,
                customer_id=customer_uuid,
                order_amount_fen=req.order_amount_fen,
                order_time=order_time,
                tenant_id=tenant_id,
                db=db,
                model=req.model,
            )
            await db.commit()
            return ok(result)
        except (ValueError, KeyError) as exc:
            await db.rollback()
            log.warning(
                "attribute_order_error",
                order_id=req.order_id,
                error=str(exc),
                tenant_id=str(tenant_id),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET /top-performers — ROI 最高活动排名
# ---------------------------------------------------------------------------


@router.get("/top-performers")
async def get_top_performers(
    limit: int = Query(default=10, ge=1, le=50, description="返回条数，默认10"),
    days: int = Query(default=30, ge=1, le=365, description="统计近多少天，默认30"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取 ROI 最高的营销活动/旅程排名。"""
    tenant_id = _parse_tenant(x_tenant_id)

    async with async_session_factory() as db:
        try:
            data = await _roi_service.get_top_performers(
                tenant_id=tenant_id,
                db=db,
                limit=limit,
                days=days,
            )
            return ok({"items": data, "total": len(data)})
        except (ValueError, KeyError) as exc:
            log.warning(
                "top_performers_error",
                error=str(exc),
                tenant_id=str(tenant_id),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
