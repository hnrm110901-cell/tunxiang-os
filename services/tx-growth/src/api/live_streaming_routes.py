"""直播管理 API — 活动CRUD + 开播/结束 + 优惠券 + 仪表盘

端点（8个）：
  POST /api/v1/growth/live/events               创建直播活动
  GET  /api/v1/growth/live/events               列表查询（分页+筛选）
  GET  /api/v1/growth/live/events/{id}          活动详情（含优惠券统计）
  PUT  /api/v1/growth/live/events/{id}/start    开播
  PUT  /api/v1/growth/live/events/{id}/end      结束直播
  POST /api/v1/growth/live/events/{id}/coupons          添加优惠券批次
  POST /api/v1/growth/live/events/{id}/coupons/claim    顾客领取优惠券
  GET  /api/v1/growth/live/dashboard            直播经营仪表盘
"""

import uuid
from datetime import datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, field_validator
from services.live_coupon_engine import LiveCouponEngine, LiveCouponError
from services.live_streaming_service import LiveStreamingError, LiveStreamingService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/live", tags=["live-streaming"])

_live_svc = LiveStreamingService()
_coupon_engine = LiveCouponEngine()


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str, code: str = "ERROR") -> dict:
    return {"ok": False, "error": {"code": code, "message": msg}}


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class CreateEventRequest(BaseModel):
    store_id: uuid.UUID
    title: str
    platform: str
    scheduled_at: datetime
    description: Optional[str] = None
    cover_image_url: Optional[str] = None
    host_employee_id: Optional[uuid.UUID] = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("直播标题不能为空")
        return v.strip()

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        valid = {"wechat_video", "douyin", "kuaishou", "xiaohongshu"}
        if v not in valid:
            raise ValueError(f"平台必须是 {', '.join(sorted(valid))} 之一")
        return v


class CreateCouponBatchRequest(BaseModel):
    coupon_name: str
    discount_desc: str = ""
    total_quantity: int
    expires_at: datetime
    coupon_batch_id: Optional[uuid.UUID] = None

    @field_validator("coupon_name")
    @classmethod
    def validate_coupon_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("优惠券名称不能为空")
        return v.strip()

    @field_validator("total_quantity")
    @classmethod
    def validate_quantity(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("优惠券数量必须大于0")
        return v


class ClaimCouponRequest(BaseModel):
    customer_id: uuid.UUID


# ---------------------------------------------------------------------------
# POST /events — 创建直播活动
# ---------------------------------------------------------------------------


@router.post("/events")
async def create_event(
    body: CreateEventRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建直播活动"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _live_svc.create_event(
            tenant_id=tenant_id,
            store_id=body.store_id,
            title=body.title,
            platform=body.platform,
            scheduled_at=body.scheduled_at,
            db=db,
            description=body.description,
            cover_image_url=body.cover_image_url,
            host_employee_id=body.host_employee_id,
        )
        return ok_response(result)
    except LiveStreamingError as exc:
        raise HTTPException(status_code=400, detail=error_response(exc.message, exc.code))


# ---------------------------------------------------------------------------
# GET /events — 列表查询
# ---------------------------------------------------------------------------


@router.get("/events")
async def list_events(
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    status: Optional[str] = None,
    platform: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """分页查询直播活动列表"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _live_svc.list_events(
            tenant_id=tenant_id,
            db=db,
            status=status,
            platform=platform,
            page=page,
            size=size,
        )
        return ok_response(result)
    except LiveStreamingError as exc:
        raise HTTPException(status_code=400, detail=error_response(exc.message, exc.code))


# ---------------------------------------------------------------------------
# GET /events/{event_id} — 活动详情（含优惠券统计）
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}")
async def get_event_detail(
    event_id: uuid.UUID,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取直播活动详情，包含优惠券汇总统计"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        event = await _live_svc.get_event(
            tenant_id=tenant_id,
            event_id=event_id,
            db=db,
        )
        coupon_stats = await _coupon_engine.get_coupon_stats(
            tenant_id=tenant_id,
            event_id=event_id,
            db=db,
        )
        event["coupon_stats"] = coupon_stats
        return ok_response(event)
    except LiveStreamingError as exc:
        raise HTTPException(status_code=404, detail=error_response(exc.message, exc.code))


# ---------------------------------------------------------------------------
# PUT /events/{event_id}/start — 开播
# ---------------------------------------------------------------------------


@router.put("/events/{event_id}/start")
async def start_event(
    event_id: uuid.UUID,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """开始直播"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _live_svc.start_event(
            tenant_id=tenant_id,
            event_id=event_id,
            db=db,
        )
        return ok_response(result)
    except LiveStreamingError as exc:
        raise HTTPException(status_code=400, detail=error_response(exc.message, exc.code))


# ---------------------------------------------------------------------------
# PUT /events/{event_id}/end — 结束直播
# ---------------------------------------------------------------------------


@router.put("/events/{event_id}/end")
async def end_event(
    event_id: uuid.UUID,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """结束直播"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _live_svc.end_event(
            tenant_id=tenant_id,
            event_id=event_id,
            db=db,
        )
        return ok_response(result)
    except LiveStreamingError as exc:
        raise HTTPException(status_code=400, detail=error_response(exc.message, exc.code))


# ---------------------------------------------------------------------------
# POST /events/{event_id}/coupons — 添加优惠券批次
# ---------------------------------------------------------------------------


@router.post("/events/{event_id}/coupons")
async def create_coupon_batch(
    event_id: uuid.UUID,
    body: CreateCouponBatchRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """为直播活动添加一批优惠券"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _coupon_engine.create_coupon_batch(
            tenant_id=tenant_id,
            event_id=event_id,
            coupon_name=body.coupon_name,
            discount_desc=body.discount_desc,
            total_quantity=body.total_quantity,
            expires_at=body.expires_at,
            db=db,
            coupon_batch_id=body.coupon_batch_id,
        )
        return ok_response(result)
    except LiveCouponError as exc:
        raise HTTPException(status_code=400, detail=error_response(exc.message, exc.code))


# ---------------------------------------------------------------------------
# POST /events/{event_id}/coupons/claim — 顾客领取优惠券
# ---------------------------------------------------------------------------


@router.post("/events/{event_id}/coupons/claim")
async def claim_coupon(
    event_id: uuid.UUID,
    body: ClaimCouponRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """顾客从直播间领取一张优惠券"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _coupon_engine.claim_coupon(
            tenant_id=tenant_id,
            event_id=event_id,
            customer_id=body.customer_id,
            db=db,
        )
        return ok_response(result)
    except LiveCouponError as exc:
        raise HTTPException(status_code=400, detail=error_response(exc.message, exc.code))


# ---------------------------------------------------------------------------
# GET /dashboard — 直播经营仪表盘
# ---------------------------------------------------------------------------


@router.get("/dashboard")
async def live_dashboard(
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    days: int = 30,
) -> dict:
    """直播经营仪表盘（默认最近30天）"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    result = await _live_svc.get_live_dashboard(
        tenant_id=tenant_id,
        db=db,
        days=days,
    )
    return ok_response(result)
