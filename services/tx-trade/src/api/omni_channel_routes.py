"""外卖聚合统一接单 API — 美团/饿了么/抖音 webhook + 接单面板

ROUTER REGISTRATION (在tx-trade/src/main.py中添加):
    from .api.omni_channel_routes import router as omni_channel_router
    app.include_router(omni_channel_router, prefix="/api/v1")
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import date, datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.omni_channel_service import (
    OmniChannelService,
    OmniChannelError,
    UnsupportedPlatformError,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/omni", tags=["omni-channel"])

# ─── 签名验证 secret（从环境变量读取，不硬编码） ────────────────────────────────

_PLATFORM_SECRETS: dict[str, str] = {
    "meituan": os.environ.get("MEITUAN_WEBHOOK_SECRET", ""),
    "eleme": os.environ.get("ELEME_WEBHOOK_SECRET", ""),
    "douyin": os.environ.get("DOUYIN_WEBHOOK_SECRET", ""),
}


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _verify_meituan_signature(body: bytes, signature: str, secret: str) -> bool:
    """美团签名验证：MD5(body + secret)"""
    if not secret:
        logger.warning("omni_channel.webhook.no_secret", platform="meituan")
        return True  # 无secret时放行（开发模式），生产应返回False
    expected = hashlib.md5(body + secret.encode()).hexdigest().lower()
    return hmac.compare_digest(expected, signature.lower())


def _verify_eleme_signature(body: bytes, signature: str, secret: str) -> bool:
    """饿了么签名验证：HMAC-SHA256"""
    if not secret:
        logger.warning("omni_channel.webhook.no_secret", platform="eleme")
        return True
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def _verify_douyin_signature(body: bytes, signature: str, secret: str) -> bool:
    """抖音签名验证：HMAC-SHA256"""
    if not secret:
        logger.warning("omni_channel.webhook.no_secret", platform="douyin")
        return True
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


_SIGNATURE_VERIFIERS = {
    "meituan": _verify_meituan_signature,
    "eleme": _verify_eleme_signature,
    "douyin": _verify_douyin_signature,
}


def _verify_platform_signature(platform: str, body: bytes, request: Request) -> bool:
    """统一签名验证入口"""
    secret = _PLATFORM_SECRETS.get(platform, "")
    verifier = _SIGNATURE_VERIFIERS.get(platform)
    if verifier is None:
        return False

    # 各平台签名header名称
    sig_header_map = {
        "meituan": "X-Meituan-Signature",
        "eleme": "X-Eleme-Signature",
        "douyin": "X-Douyin-Signature",
    }
    signature = request.headers.get(sig_header_map.get(platform, "X-Signature"), "")
    if not signature:
        logger.warning("omni_channel.webhook.missing_signature", platform=platform)
        return not secret  # 无secret时允许无签名请求（开发模式）

    return verifier(body, signature, secret)


# ─── 请求/响应模型 ────────────────────────────────────────────────────────────


class AcceptOrderReq(BaseModel):
    estimated_minutes: int = 20


class RejectOrderReq(BaseModel):
    reason_code: int = 1


# ─── 路由 ─────────────────────────────────────────────────────────────────────


@router.post("/webhook/{platform}", summary="平台推单回调（美团/饿了么/抖音）")
async def webhook_receive_order(
    platform: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """接收各平台外卖推单回调。

    - 验证平台签名（secret从环境变量读取）
    - 标准化为内部Order格式写库
    - 自动推送到KDS
    - 平台回调失败只记录日志，不影响内部流程
    """
    if platform not in OmniChannelService.PLATFORMS:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")

    body = await request.body()
    log = logger.bind(platform=platform)

    # 签名验证
    if not _verify_platform_signature(platform, body, request):
        log.warning("omni_channel.webhook.signature_invalid")
        raise HTTPException(status_code=401, detail="签名验证失败")

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        log.error("omni_channel.webhook.invalid_json", error=str(exc))
        raise HTTPException(status_code=400, detail="无效的JSON payload") from exc

    tenant_id = _get_tenant_id(request)
    store_id = payload.get("store_id") or request.headers.get("X-Store-ID", "")
    if not store_id:
        raise HTTPException(status_code=400, detail="store_id required in payload or X-Store-ID header")

    try:
        svc = OmniChannelService()
        order = await svc.receive_order(
            platform=platform,
            raw_payload=payload,
            store_id=store_id,
            tenant_id=tenant_id,
            db=db,
        )
        await db.commit()
        log.info("omni_channel.webhook.ok", platform_order_id=order.platform_order_id)
        return {"ok": True, "data": {"order_id": order.internal_order_id, "platform": platform}, "error": None}
    except UnsupportedPlatformError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OmniChannelError as exc:
        log.error("omni_channel.webhook.failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/orders/pending", summary="待接单列表（所有平台混合）")
async def get_pending_orders(
    store_id: str = Query(..., description="门店ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询当前所有平台待接单订单，按下单时间升序排列。"""
    tenant_id = _get_tenant_id(request)
    svc = OmniChannelService()
    orders = await svc.get_pending_orders(store_id=store_id, tenant_id=tenant_id, db=db)

    return {
        "ok": True,
        "data": [
            {
                "order_id": o.internal_order_id,
                "platform": o.platform,
                "platform_order_id": o.platform_order_id,
                "status": o.status,
                "total_fen": o.total_fen,
                "notes": o.notes,
                "customer_phone": o.customer_phone,
                "delivery_address": o.delivery_address,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "items": [
                    {
                        "name": item.name,
                        "quantity": item.quantity,
                        "price_fen": item.price_fen,
                        "notes": item.notes,
                    }
                    for item in o.items
                ],
            }
            for o in orders
        ],
        "error": None,
    }


@router.post("/orders/{order_id}/accept", summary="接单")
async def accept_order(
    order_id: str,
    req: AcceptOrderReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """接单：更新状态为confirmed，并回调平台接单接口。

    平台回调失败只记录structlog日志，不影响接单结果。
    """
    tenant_id = _get_tenant_id(request)
    svc = OmniChannelService()
    try:
        result = await svc.accept_order(
            order_id=order_id,
            estimated_minutes=req.estimated_minutes,
            tenant_id=tenant_id,
            db=db,
        )
        await db.commit()
        return {"ok": True, "data": result, "error": None}
    except OmniChannelError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/orders/{order_id}/reject", summary="拒单")
async def reject_order(
    order_id: str,
    req: RejectOrderReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """拒单：更新状态为rejected，并回调平台拒单接口。

    平台回调失败只记录structlog日志，不影响拒单结果。
    """
    tenant_id = _get_tenant_id(request)
    svc = OmniChannelService()
    try:
        result = await svc.reject_order(
            order_id=order_id,
            reason_code=req.reason_code,
            tenant_id=tenant_id,
            db=db,
        )
        await db.commit()
        return {"ok": True, "data": result, "error": None}
    except OmniChannelError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/orders", summary="历史订单（含渠道）")
async def get_orders(
    store_id: str = Query(..., description="门店ID"),
    order_date: Optional[date] = Query(None, alias="date", description="查询日期（YYYY-MM-DD），不传则今日"),
    platform: Optional[str] = Query(None, description="平台筛选: meituan/eleme/douyin"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询门店历史外卖订单（含渠道信息），支持按平台筛选，分页返回。"""
    import uuid as _uuid
    from shared.ontology.src.entities import Order as OrderModel
    from sqlalchemy import select, and_, func

    tenant_id = _get_tenant_id(request)
    tid = _uuid.UUID(tenant_id)
    sid = _uuid.UUID(store_id)

    target_date = order_date or datetime.now().date()
    day_start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=datetime.now().astimezone().tzinfo)
    day_end = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=datetime.now().astimezone().tzinfo)

    conditions = [
        OrderModel.tenant_id == tid,
        OrderModel.store_id == sid,
        OrderModel.source_channel.in_(OmniChannelService.PLATFORMS),
        OrderModel.created_at >= day_start,
        OrderModel.created_at <= day_end,
        OrderModel.is_deleted == False,  # noqa: E712
    ]
    if platform and platform in OmniChannelService.PLATFORMS:
        conditions.append(OrderModel.source_channel == platform)

    total_stmt = select(func.count()).select_from(OrderModel).where(and_(*conditions))
    total_result = await db.execute(total_stmt)
    total = total_result.scalar() or 0

    stmt = (
        select(OrderModel)
        .where(and_(*conditions))
        .order_by(OrderModel.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    items = [
        {
            "order_id": str(row.id),
            "platform": row.source_channel,
            "platform_order_id": getattr(row, "platform_order_id", row.order_no),
            "status": row.status,
            "total_fen": getattr(row, "total_amount_fen", 0),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]

    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}, "error": None}


@router.get("/stats", summary="渠道统计（GMV/单量/接单率）")
async def get_channel_stats(
    store_id: str = Query(..., description="门店ID"),
    stat_date: Optional[date] = Query(None, alias="date", description="统计日期，不传则今日"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """按平台统计当日GMV、订单量、接单率。"""
    import uuid as _uuid
    from shared.ontology.src.entities import Order as OrderModel
    from sqlalchemy import select, and_, func, case

    tenant_id = _get_tenant_id(request)
    tid = _uuid.UUID(tenant_id)
    sid = _uuid.UUID(store_id)

    target_date = stat_date or datetime.now().date()
    day_start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0)
    day_end = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59)

    stats_by_platform = {}
    for platform in OmniChannelService.PLATFORMS:
        stmt = select(
            func.count().label("total_orders"),
            func.sum(
                case(
                    (OrderModel.status.in_(["confirmed", "completed"]), 1),
                    else_=0,
                )
            ).label("accepted_orders"),
            func.sum(
                case(
                    (OrderModel.status == "completed", getattr(OrderModel, "total_amount_fen", 0)),
                    else_=0,
                )
            ).label("gmv_fen"),
        ).where(
            and_(
                OrderModel.tenant_id == tid,
                OrderModel.store_id == sid,
                OrderModel.source_channel == platform,
                OrderModel.created_at >= day_start,
                OrderModel.created_at <= day_end,
                OrderModel.is_deleted == False,  # noqa: E712
            )
        )
        result = await db.execute(stmt)
        row = result.one_or_none()
        total = int(row[0] or 0) if row else 0
        accepted = int(row[1] or 0) if row else 0
        gmv_fen = int(row[2] or 0) if row else 0
        accept_rate = round(accepted / total, 4) if total > 0 else 0.0

        stats_by_platform[platform] = {
            "platform": platform,
            "total_orders": total,
            "accepted_orders": accepted,
            "gmv_fen": gmv_fen,
            "accept_rate": accept_rate,
        }

    return {"ok": True, "data": {"date": str(target_date), "platforms": stats_by_platform}, "error": None}


@router.post("/auto-reject/run", summary="触发超时自动拒单")
async def run_auto_reject(
    store_id: str = Query(..., description="门店ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动触发或定时调用：对超时未接单的外卖订单执行自动拒单。

    超时时限从 OmniChannelService.auto_reject_minutes 读取（默认3分钟）。
    生产环境应通过定时任务（cron / Celery beat）自动调用此接口。
    """
    tenant_id = _get_tenant_id(request)
    svc = OmniChannelService()
    result = await svc.auto_reject_overdue(
        store_id=store_id,
        tenant_id=tenant_id,
        db=db,
    )
    if result["rejected_count"] > 0:
        await db.commit()

    return {"ok": True, "data": result, "error": None}
