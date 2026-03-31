"""触达归因链路 API 路由 (v088)

端点列表：
  POST /api/v1/growth/attribution/track-click/{touch_id}
       记录点击（无需鉴权，防刷：同一 touch_id + IP 60s 内只记一次）

  GET  /api/v1/growth/attribution/touches
       触达事件列表（支持 channel / campaign_id / date_range 过滤）

  GET  /api/v1/growth/attribution/conversions
       转化记录列表

  GET  /api/v1/growth/attribution/campaigns/{id}/summary
       活动汇总看板数据

  GET  /api/v1/growth/attribution/performance/channels
       渠道效果对比

  GET  /api/v1/growth/attribution/performance/segments
       人群效果对比

  POST /api/v1/growth/attribution/touch-record
       记录一次营销触达（内部调用，需 X-Tenant-ID）

  POST /api/v1/growth/attribution/attribute-conversion
       触发归因检查（内部调用，需 X-Tenant-ID）

认证：track-click 无需鉴权，其余均需 X-Tenant-ID header。
防刷：track-click 使用 Redis 对 (touch_id, client_ip) 去重，TTL 60s。
响应格式：{"ok": bool, "data": {}, "error": {}}
"""
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, field_validator

from shared.ontology.src.database import async_session_factory
from services.touch_tracker import TouchTracker
from services.attribution_aggregator import AttributionAggregator

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/attribution", tags=["touch-attribution"])

_tracker = TouchTracker()
_aggregator = AttributionAggregator()

# Redis 客户端（防刷用）：懒加载，redis 不可用时降级为不防刷
_redis: Any = None


async def _get_redis() -> Optional[Any]:
    """懒加载 Redis 客户端，不可用时返回 None（降级不防刷）。"""
    global _redis
    if _redis is not None:
        return _redis
    try:
        import redis.asyncio as aioredis  # type: ignore
        import os
        _redis = aioredis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
            socket_connect_timeout=1,
        )
        await _redis.ping()
        return _redis
    except Exception:  # noqa: BLE001
        log.warning("redis_unavailable_click_dedup_disabled")
        return None


# ---------------------------------------------------------------------------
# 通用辅助
# ---------------------------------------------------------------------------


def ok(data: Any) -> dict:
    return {"ok": True, "data": data}


def err(msg: str) -> dict:
    return {"ok": False, "error": {"message": msg}}


def _parse_tenant(x_tenant_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"X-Tenant-ID 格式无效: {x_tenant_id}") from exc


def _parse_date(s: str, field_name: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"{field_name} 日期格式无效（YYYY-MM-DD）: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Pydantic 请求体
# ---------------------------------------------------------------------------


class RecordTouchRequest(BaseModel):
    """记录营销触达请求体"""
    channel: str
    customer_id: str
    content_type: str
    content: dict = {}
    campaign_id: Optional[str] = None
    enrollment_id: Optional[str] = None
    phone: Optional[str] = None
    sent_at: Optional[str] = None

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        allowed = {"wecom", "sms", "miniapp_push", "poster_qr"}
        if v not in allowed:
            raise ValueError(f"channel 必须是 {allowed} 之一，收到: {v!r}")
        return v

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        allowed = {"coupon", "invitation", "product_recommend", "recall"}
        if v not in allowed:
            raise ValueError(f"content_type 必须是 {allowed} 之一，收到: {v!r}")
        return v


class AttributeConversionRequest(BaseModel):
    """触发归因检查请求体"""
    customer_id: str
    conversion_type: str
    conversion_id: str
    conversion_value: float
    converted_at: Optional[str] = None
    attribution_window_hours: int = 72
    model: str = "last_touch"

    @field_validator("conversion_type")
    @classmethod
    def validate_conversion_type(cls, v: str) -> str:
        allowed = {"reservation", "order", "repurchase", "referral"}
        if v not in allowed:
            raise ValueError(f"conversion_type 必须是 {allowed} 之一，收到: {v!r}")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        allowed = {"last_touch", "first_touch"}
        if v not in allowed:
            raise ValueError(f"model 必须是 {allowed} 之一，收到: {v!r}")
        return v

    @field_validator("conversion_value")
    @classmethod
    def validate_value(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"conversion_value 不能为负数，收到: {v}")
        return v


# ---------------------------------------------------------------------------
# POST /track-click/{touch_id} — 记录点击（无需鉴权）
# ---------------------------------------------------------------------------


@router.post("/track-click/{touch_id}", include_in_schema=True)
async def track_click(
    touch_id: str,
    request: Request,
) -> dict:
    """记录追踪链接点击事件。

    无需用户鉴权，供追踪链接回调使用。
    防刷：同一 (touch_id, client_ip) 60 秒内只计一次有效点击。
    """
    client_ip = request.client.host if request.client else "unknown"
    dedup_key = f"tx_click:{touch_id}:{client_ip}"

    redis_client = await _get_redis()
    if redis_client is not None:
        try:
            is_new = await redis_client.set(dedup_key, "1", ex=60, nx=True)
            if not is_new:
                log.debug("click_dedup_skipped", touch_id=touch_id, ip=client_ip)
                return ok({"touch_id": touch_id, "counted": False, "reason": "dedup"})
        except Exception:  # noqa: BLE001
            # Redis 故障时不阻断主流程，降级放行
            log.warning("redis_error_click_dedup_bypassed", touch_id=touch_id)

    async with async_session_factory() as db:
        try:
            event = await _tracker.record_click(touch_id=touch_id, db=db)
            await db.commit()
            if event is None:
                return ok({"touch_id": touch_id, "counted": False, "reason": "not_found"})
            return ok({
                "touch_id": event.touch_id,
                "click_count": event.click_count,
                "clicked_at": event.clicked_at.isoformat() if event.clicked_at else None,
                "counted": True,
            })
        except (ValueError, KeyError) as exc:
            await db.rollback()
            log.warning("track_click_error", touch_id=touch_id, error=str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET /touches — 触达事件列表
# ---------------------------------------------------------------------------


@router.get("/touches")
async def list_touches(
    channel: Optional[str] = Query(default=None, description="渠道过滤"),
    campaign_id: Optional[str] = Query(default=None, description="活动 UUID 过滤"),
    customer_id: Optional[str] = Query(default=None, description="客户 UUID 过滤"),
    start: str = Query(default="", description="开始日期 YYYY-MM-DD"),
    end: str = Query(default="", description="结束日期 YYYY-MM-DD"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """查询触达事件列表，支持多维度过滤。"""
    tenant_id = _parse_tenant(x_tenant_id)

    today = datetime.now(timezone.utc).date()
    start_date = _parse_date(start, "start") if start else date(today.year, today.month, 1)
    end_date = _parse_date(end, "end") if end else today

    filters = [
        "tenant_id = :tenant_id",
        "sent_at::date >= :start_date",
        "sent_at::date <= :end_date",
    ]
    bind: dict = {
        "tenant_id": tenant_id,
        "start_date": start_date,
        "end_date": end_date,
    }

    if channel:
        filters.append("channel = :channel")
        bind["channel"] = channel
    if campaign_id:
        try:
            bind["campaign_id"] = uuid.UUID(campaign_id)
            filters.append("campaign_id = :campaign_id")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"campaign_id UUID 格式无效: {exc}") from exc
    if customer_id:
        try:
            bind["customer_id"] = uuid.UUID(customer_id)
            filters.append("customer_id = :customer_id")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"customer_id UUID 格式无效: {exc}") from exc

    where = " AND ".join(filters)
    offset = (page - 1) * size
    bind["limit"] = size
    bind["offset"] = offset

    async with async_session_factory() as db:
        try:
            count_row = await db.execute(
                f"SELECT COUNT(*) AS cnt FROM touch_events WHERE {where}", bind
            )
            total = int((count_row.fetchone() or [0])[0])

            rows = await db.execute(
                f"""
                SELECT id, touch_id, channel, campaign_id, journey_enrollment_id,
                       customer_id, phone, content_type,
                       sent_at, delivered_at, clicked_at, click_count, created_at
                FROM touch_events
                WHERE {where}
                ORDER BY sent_at DESC
                LIMIT :limit OFFSET :offset
                """,
                bind,
            )

            items = [
                {
                    "id": str(row.id),
                    "touch_id": row.touch_id,
                    "channel": row.channel,
                    "campaign_id": str(row.campaign_id) if row.campaign_id else None,
                    "customer_id": str(row.customer_id),
                    "phone": row.phone,
                    "content_type": row.content_type,
                    "sent_at": row.sent_at.isoformat() if row.sent_at else None,
                    "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
                    "clicked_at": row.clicked_at.isoformat() if row.clicked_at else None,
                    "click_count": row.click_count,
                }
                for row in rows.fetchall()
            ]

            return ok({"items": items, "total": total, "page": page, "size": size})
        except (ValueError, KeyError) as exc:
            log.warning("list_touches_error", error=str(exc), tenant_id=str(tenant_id))
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET /conversions — 转化记录列表
# ---------------------------------------------------------------------------


@router.get("/conversions")
async def list_conversions(
    conversion_type: Optional[str] = Query(default=None),
    customer_id: Optional[str] = Query(default=None),
    start: str = Query(default=""),
    end: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """查询转化记录列表。"""
    tenant_id = _parse_tenant(x_tenant_id)

    today = datetime.now(timezone.utc).date()
    start_date = _parse_date(start, "start") if start else date(today.year, today.month, 1)
    end_date = _parse_date(end, "end") if end else today

    filters = [
        "tenant_id = :tenant_id",
        "converted_at::date >= :start_date",
        "converted_at::date <= :end_date",
    ]
    bind: dict = {
        "tenant_id": tenant_id,
        "start_date": start_date,
        "end_date": end_date,
    }

    if conversion_type:
        filters.append("conversion_type = :conversion_type")
        bind["conversion_type"] = conversion_type
    if customer_id:
        try:
            bind["customer_id"] = uuid.UUID(customer_id)
            filters.append("customer_id = :customer_id")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"customer_id UUID 格式无效: {exc}") from exc

    where = " AND ".join(filters)
    offset = (page - 1) * size
    bind["limit"] = size
    bind["offset"] = offset

    async with async_session_factory() as db:
        try:
            count_row = await db.execute(
                f"SELECT COUNT(*) AS cnt FROM attribution_conversions WHERE {where}", bind
            )
            total = int((count_row.fetchone() or [0])[0])

            rows = await db.execute(
                f"""
                SELECT id, touch_id, customer_id, conversion_type, conversion_id,
                       conversion_value, converted_at, attribution_window_hours,
                       is_first_conversion, created_at
                FROM attribution_conversions
                WHERE {where}
                ORDER BY converted_at DESC
                LIMIT :limit OFFSET :offset
                """,
                bind,
            )

            items = [
                {
                    "id": str(row.id),
                    "touch_id": row.touch_id,
                    "customer_id": str(row.customer_id),
                    "conversion_type": row.conversion_type,
                    "conversion_id": str(row.conversion_id),
                    "conversion_value": float(row.conversion_value),
                    "converted_at": row.converted_at.isoformat() if row.converted_at else None,
                    "attribution_window_hours": row.attribution_window_hours,
                    "is_first_conversion": row.is_first_conversion,
                }
                for row in rows.fetchall()
            ]

            return ok({"items": items, "total": total, "page": page, "size": size})
        except (ValueError, KeyError) as exc:
            log.warning("list_conversions_error", error=str(exc), tenant_id=str(tenant_id))
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET /campaigns/{id}/summary — 活动汇总看板
# ---------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/summary")
async def get_campaign_summary(
    campaign_id: str,
    start: str = Query(default="", description="开始日期 YYYY-MM-DD"),
    end: str = Query(default="", description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取活动汇总看板数据（先查 campaign_summaries 缓存，无则实时计算）。"""
    tenant_id = _parse_tenant(x_tenant_id)

    try:
        campaign_uuid = uuid.UUID(campaign_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"campaign_id UUID 格式无效: {exc}") from exc

    today = datetime.now(timezone.utc).date()
    start_date = _parse_date(start, "start") if start else date(today.year, today.month, 1)
    end_date = _parse_date(end, "end") if end else today

    async with async_session_factory() as db:
        try:
            # 先查预聚合缓存
            cache_row = await db.execute(
                """
                SELECT campaign_name, total_touches, delivered_count, clicked_count,
                       reservations_attributed, orders_attributed, revenue_attributed,
                       cac, roi, top_segments, updated_at
                FROM campaign_summaries
                WHERE tenant_id    = :tenant_id
                  AND campaign_id  = :campaign_id
                  AND period_start = :period_start
                  AND period_end   = :period_end
                LIMIT 1
                """,
                {
                    "tenant_id": tenant_id,
                    "campaign_id": campaign_uuid,
                    "period_start": start_date,
                    "period_end": end_date,
                },
            )
            cached = cache_row.fetchone()

            if cached:
                return ok({
                    "source": "cache",
                    "campaign_id": campaign_id,
                    "campaign_name": cached.campaign_name,
                    "period": {"start": str(start_date), "end": str(end_date)},
                    "funnel": {
                        "total_touches": cached.total_touches,
                        "delivered_count": cached.delivered_count,
                        "clicked_count": cached.clicked_count,
                    },
                    "conversions": {
                        "reservations": cached.reservations_attributed,
                        "orders": cached.orders_attributed,
                        "revenue": float(cached.revenue_attributed),
                    },
                    "metrics": {
                        "cac": float(cached.cac),
                        "roi": float(cached.roi),
                        "click_rate": round(
                            cached.clicked_count / max(1, cached.delivered_count), 4
                        ),
                    },
                    "top_segments": cached.top_segments or [],
                    "updated_at": cached.updated_at.isoformat() if cached.updated_at else None,
                })

            # 无缓存：实时计算
            summary = await _aggregator.compute_campaign_summary(
                tenant_id=tenant_id,
                period_start=start_date,
                period_end=end_date,
                db=db,
                campaign_id=campaign_uuid,
            )

            return ok({
                "source": "realtime",
                "campaign_id": campaign_id,
                "campaign_name": summary.campaign_name,
                "period": {"start": str(start_date), "end": str(end_date)},
                "funnel": {
                    "total_touches": summary.total_touches,
                    "delivered_count": summary.delivered_count,
                    "clicked_count": summary.clicked_count,
                    "click_rate": summary.click_rate,
                    "delivery_rate": summary.delivery_rate,
                },
                "conversions": {
                    "reservations": summary.reservations_attributed,
                    "orders": summary.orders_attributed,
                    "revenue": summary.revenue_attributed,
                },
                "metrics": {
                    "cac": summary.cac,
                    "roi": summary.roi,
                },
                "top_segments": summary.top_segments,
            })
        except (ValueError, KeyError) as exc:
            log.warning(
                "campaign_summary_error",
                campaign_id=campaign_id,
                error=str(exc),
                tenant_id=str(tenant_id),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET /performance/channels — 渠道效果对比
# ---------------------------------------------------------------------------


@router.get("/performance/channels")
async def get_channel_performance(
    start: str = Query(default=""),
    end: str = Query(default=""),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """各渠道效果对比：wecom / sms / miniapp_push / poster_qr。"""
    tenant_id = _parse_tenant(x_tenant_id)
    today = datetime.now(timezone.utc).date()
    start_date = _parse_date(start, "start") if start else date(today.year, today.month, 1)
    end_date = _parse_date(end, "end") if end else today

    async with async_session_factory() as db:
        try:
            results = await _aggregator.compute_channel_performance(
                tenant_id=tenant_id,
                period_start=start_date,
                period_end=end_date,
                db=db,
            )
            return ok({
                "items": [
                    {
                        "channel": r.channel,
                        "total_touches": r.total_touches,
                        "delivered_count": r.delivered_count,
                        "clicked_count": r.clicked_count,
                        "click_rate": r.click_rate,
                        "click_rate_pct": round(r.click_rate * 100, 1),
                        "conversions": r.conversions,
                        "revenue": r.revenue,
                        "conversion_rate": r.conversion_rate,
                        "conversion_rate_pct": round(r.conversion_rate * 100, 1),
                    }
                    for r in results
                ],
                "total": len(results),
                "period": {"start": str(start_date), "end": str(end_date)},
            })
        except (ValueError, KeyError) as exc:
            log.warning("channel_performance_error", error=str(exc), tenant_id=str(tenant_id))
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET /performance/segments — 人群效果对比
# ---------------------------------------------------------------------------


@router.get("/performance/segments")
async def get_segment_performance(
    start: str = Query(default=""),
    end: str = Query(default=""),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """各人群效果对比（以 content_type 作为人群代理维度）。"""
    tenant_id = _parse_tenant(x_tenant_id)
    today = datetime.now(timezone.utc).date()
    start_date = _parse_date(start, "start") if start else date(today.year, today.month, 1)
    end_date = _parse_date(end, "end") if end else today

    async with async_session_factory() as db:
        try:
            results = await _aggregator.compute_segment_performance(
                tenant_id=tenant_id,
                period_start=start_date,
                period_end=end_date,
                db=db,
            )
            return ok({
                "items": [
                    {
                        "segment_name": r.segment_name,
                        "total_touches": r.total_touches,
                        "conversions": r.conversions,
                        "revenue": r.revenue,
                        "conversion_rate": r.conversion_rate,
                        "conversion_rate_pct": round(r.conversion_rate * 100, 1),
                        "avg_order_value": r.avg_order_value,
                    }
                    for r in results
                ],
                "total": len(results),
                "period": {"start": str(start_date), "end": str(end_date)},
            })
        except (ValueError, KeyError) as exc:
            log.warning("segment_performance_error", error=str(exc), tenant_id=str(tenant_id))
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# POST /touch-record — 记录营销触达（内部调用）
# ---------------------------------------------------------------------------


@router.post("/touch-record")
async def record_touch(
    req: RecordTouchRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """记录一次营销触达，返回 touch_id 追踪短码。

    由旅程执行器、活动引擎、短信/企微发送服务调用。
    """
    tenant_id = _parse_tenant(x_tenant_id)

    try:
        customer_uuid = uuid.UUID(req.customer_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"customer_id UUID 格式无效: {exc}") from exc

    campaign_uuid: Optional[uuid.UUID] = None
    if req.campaign_id:
        try:
            campaign_uuid = uuid.UUID(req.campaign_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"campaign_id UUID 格式无效: {exc}") from exc

    enrollment_uuid: Optional[uuid.UUID] = None
    if req.enrollment_id:
        try:
            enrollment_uuid = uuid.UUID(req.enrollment_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"enrollment_id UUID 格式无效: {exc}") from exc

    sent_at: Optional[datetime] = None
    if req.sent_at:
        try:
            sent_at = datetime.fromisoformat(req.sent_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"sent_at 格式无效（ISO 8601）: {exc}"
            ) from exc

    async with async_session_factory() as db:
        try:
            event = await _tracker.record_touch(
                tenant_id=tenant_id,
                channel=req.channel,
                customer_id=customer_uuid,
                content_type=req.content_type,
                content=req.content,
                campaign_id=campaign_uuid,
                enrollment_id=enrollment_uuid,
                phone=req.phone,
                sent_at=sent_at,
                db=db,
            )
            await db.commit()
            return ok({
                "touch_id": event.touch_id,
                "customer_id": str(event.customer_id),
                "channel": event.channel,
                "sent_at": event.sent_at.isoformat(),
                "tracked_url_example": TouchTracker.generate_tracked_url(
                    event.touch_id, req.content.get("landing_url", "https://example.com")
                ),
            })
        except (ValueError, KeyError) as exc:
            await db.rollback()
            log.warning("record_touch_error", error=str(exc), tenant_id=str(tenant_id))
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# POST /attribute-conversion — 触发归因检查（内部调用）
# ---------------------------------------------------------------------------


@router.post("/attribute-conversion")
async def attribute_conversion(
    req: AttributeConversionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """触发归因检查，将订单/预订归因到营销触达。

    由 tx-trade 的订单完成事件或预订确认事件调用（直接 HTTP 或 Redis 事件消费）。
    幂等：同一 (touch_id, conversion_id) 不会重复写入。
    """
    tenant_id = _parse_tenant(x_tenant_id)

    try:
        customer_uuid = uuid.UUID(req.customer_id)
        conversion_uuid = uuid.UUID(req.conversion_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"UUID 格式无效: {exc}") from exc

    converted_at: Optional[datetime] = None
    if req.converted_at:
        try:
            converted_at = datetime.fromisoformat(req.converted_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"converted_at 格式无效（ISO 8601）: {exc}"
            ) from exc

    async with async_session_factory() as db:
        try:
            result = await _tracker.check_and_attribute(
                tenant_id=tenant_id,
                customer_id=customer_uuid,
                conversion_type=req.conversion_type,
                conversion_id=conversion_uuid,
                conversion_value=req.conversion_value,
                db=db,
                converted_at=converted_at,
                attribution_window_hours=req.attribution_window_hours,
                model=req.model,
            )
            await db.commit()

            if result is None:
                return ok({
                    "attributed": False,
                    "reason": "no_touch_in_window",
                    "conversion_id": req.conversion_id,
                })

            return ok({
                "attributed": True,
                "touch_id": result.touch_id,
                "conversion_type": result.conversion_type,
                "conversion_value": result.conversion_value,
                "is_first_conversion": result.is_first_conversion,
                "attributed_at": result.created_at.isoformat(),
            })
        except (ValueError, KeyError) as exc:
            await db.rollback()
            log.warning(
                "attribute_conversion_error",
                error=str(exc),
                tenant_id=str(tenant_id),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
