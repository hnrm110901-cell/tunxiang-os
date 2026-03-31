"""外卖运营 API — 配置管理 / Busy Mode / 差评管理 / 健康度看板

ROUTER REGISTRATION (在 tx-trade/src/main.py 中添加):
    from .api.delivery_ops_routes import router as delivery_ops_router
    app.include_router(delivery_ops_router)
"""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.delivery_ops_service import (
    DeliveryOpsService,
    DeliveryOpsError,
    ConfigNotFoundError,
    ReviewNotFoundError,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/delivery", tags=["delivery-ops"])

_VALID_PLATFORMS = {"meituan", "eleme", "douyin"}


# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _validate_platform(platform: str) -> None:
    if platform not in _VALID_PLATFORMS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的平台: {platform}，有效值: {sorted(_VALID_PLATFORMS)}",
        )


# ─── 请求体模型 ────────────────────────────────────────────────────────────────


class UpdateConfigReq(BaseModel):
    auto_accept: Optional[bool] = None
    auto_accept_max_per_hour: Optional[int] = None
    busy_mode_prep_time_min: Optional[int] = None
    normal_prep_time_min: Optional[int] = None
    max_delivery_distance_km: Optional[float] = None
    is_active: Optional[bool] = None


class EnableBusyModeReq(BaseModel):
    duration_minutes: int = 120


class ReplyReviewReq(BaseModel):
    content: str


# ─── 运营配置 ──────────────────────────────────────────────────────────────────


@router.get(
    "/config/{store_id}",
    summary="获取门店所有平台外卖配置",
)
async def get_all_configs(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回该门店所有平台（美团/饿了么/抖音）的运营配置列表。
    不存在的平台配置自动以默认值创建。
    """
    tenant_id = _get_tenant_id(request)
    svc = DeliveryOpsService()
    try:
        configs = await svc.get_all_store_configs(
            store_id=store_id, tenant_id=tenant_id, db=db
        )
        await db.commit()
        return {
            "ok": True,
            "data": [c.model_dump(mode="json") for c in configs],
            "error": None,
        }
    except DeliveryOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/config/{store_id}/{platform}",
    summary="获取门店指定平台外卖配置",
)
async def get_config(
    store_id: str,
    platform: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取门店指定平台（meituan/eleme/douyin）的运营配置。"""
    _validate_platform(platform)
    tenant_id = _get_tenant_id(request)
    svc = DeliveryOpsService()
    try:
        config = await svc.get_store_config(
            store_id=store_id, platform=platform, tenant_id=tenant_id, db=db
        )
        await db.commit()
        return {"ok": True, "data": config.model_dump(mode="json"), "error": None}
    except DeliveryOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put(
    "/config/{store_id}/{platform}",
    summary="更新门店指定平台外卖配置",
)
async def update_config(
    store_id: str,
    platform: str,
    req: UpdateConfigReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新配置字段（自动接单开关、出餐时间、配送范围等）。
    只更新请求体中提供的字段（非 None 字段）。
    """
    _validate_platform(platform)
    tenant_id = _get_tenant_id(request)
    svc = DeliveryOpsService()
    try:
        update_data = {k: v for k, v in req.model_dump().items() if v is not None}
        config = await svc.update_store_config(
            store_id=store_id,
            platform=platform,
            config_update=update_data,
            tenant_id=tenant_id,
            db=db,
        )
        await db.commit()
        return {"ok": True, "data": config.model_dump(mode="json"), "error": None}
    except DeliveryOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─── Busy Mode ─────────────────────────────────────────────────────────────────


@router.post(
    "/busy-mode/{store_id}/{platform}",
    summary="开启忙碌模式",
)
async def enable_busy_mode(
    store_id: str,
    platform: str,
    req: EnableBusyModeReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """开启指定平台忙碌模式。
    忙碌模式期间出餐时间切换为 busy_mode_prep_time_min。
    duration_minutes 后自动逻辑过期（不写库关闭，由下次读取时判断）。
    """
    _validate_platform(platform)
    tenant_id = _get_tenant_id(request)
    svc = DeliveryOpsService()
    try:
        config = await svc.enable_busy_mode(
            store_id=store_id,
            platform=platform,
            tenant_id=tenant_id,
            db=db,
            duration_minutes=req.duration_minutes,
        )
        await db.commit()
        return {"ok": True, "data": config.model_dump(mode="json"), "error": None}
    except DeliveryOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/busy-mode/{store_id}/{platform}",
    summary="关闭忙碌模式",
)
async def disable_busy_mode(
    store_id: str,
    platform: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动关闭指定平台忙碌模式，出餐时间恢复正常值。"""
    _validate_platform(platform)
    tenant_id = _get_tenant_id(request)
    svc = DeliveryOpsService()
    try:
        config = await svc.disable_busy_mode(
            store_id=store_id, platform=platform, tenant_id=tenant_id, db=db
        )
        await db.commit()
        return {"ok": True, "data": config.model_dump(mode="json"), "error": None}
    except ConfigNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DeliveryOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/busy-mode/status/{store_id}",
    summary="查询门店所有平台忙碌状态",
)
async def get_busy_mode_status(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回该门店三个平台的忙碌模式开关、当前出餐时间及自动关闭时间。"""
    tenant_id = _get_tenant_id(request)
    svc = DeliveryOpsService()
    try:
        configs = await svc.get_all_store_configs(
            store_id=store_id, tenant_id=tenant_id, db=db
        )
        await db.commit()
        status_list = [
            {
                "platform": c.platform,
                "busy_mode": c.busy_mode,
                "current_prep_time_min": c.current_prep_time_min,
                "busy_mode_auto_off_at": (
                    c.busy_mode_auto_off_at.isoformat()
                    if c.busy_mode_auto_off_at
                    else None
                ),
            }
            for c in configs
        ]
        return {"ok": True, "data": status_list, "error": None}
    except DeliveryOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─── 差评管理 ──────────────────────────────────────────────────────────────────


@router.get(
    "/reviews/{store_id}",
    summary="差评列表（支持平台/天数/评分过滤）",
)
async def get_negative_reviews(
    store_id: str,
    request: Request,
    platform: Optional[str] = Query(None, description="平台筛选: meituan/eleme/douyin"),
    days: int = Query(7, ge=1, le=90, description="最近N天"),
    rating_max: int = Query(3, ge=1, le=5, description="评分上限（含）"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询门店差评列表，默认近7天≤3星。支持分页。"""
    if platform:
        _validate_platform(platform)
    tenant_id = _get_tenant_id(request)
    svc = DeliveryOpsService()
    try:
        items, total = await svc.get_negative_reviews(
            store_id=store_id,
            tenant_id=tenant_id,
            db=db,
            platform=platform,
            days=days,
            rating_max=rating_max,
            page=page,
            size=size,
        )
        return {
            "ok": True,
            "data": {
                "items": [r.model_dump(mode="json") for r in items],
                "total": total,
                "page": page,
                "size": size,
            },
            "error": None,
        }
    except DeliveryOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/reviews/{review_id}/reply",
    summary="回复差评",
)
async def reply_review(
    review_id: str,
    req: ReplyReviewReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """写入差评回复内容（reply_content + replied_at）。"""
    tenant_id = _get_tenant_id(request)
    svc = DeliveryOpsService()
    try:
        review = await svc.reply_review(
            review_id=review_id,
            content=req.content,
            tenant_id=tenant_id,
            db=db,
        )
        await db.commit()
        return {"ok": True, "data": review.model_dump(mode="json"), "error": None}
    except ReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DeliveryOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/reviews/alert-count/{store_id}",
    summary="未处理差评预警数（badge 用）",
)
async def get_alert_count(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回未发送预警（alert_sent=False）的差评数量，供前端 badge 显示。"""
    tenant_id = _get_tenant_id(request)
    svc = DeliveryOpsService()
    try:
        count = await svc.get_unhandled_alert_count(
            store_id=store_id, tenant_id=tenant_id, db=db
        )
        return {"ok": True, "data": {"count": count}, "error": None}
    except DeliveryOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─── 健康度看板 ────────────────────────────────────────────────────────────────


@router.get(
    "/health-dashboard/{store_id}",
    summary="各平台健康度汇总看板",
)
async def get_health_dashboard(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回门店各平台健康度（综合评分/DSR/月售/好评率/近7天差评数/状态）。

    status 字段说明：
      - healthy  — 评分≥4.5 且近7天差评<5
      - warning  — 评分4.0~4.5 或近7天差评≥5
      - critical — 评分<4.0 或近7天差评≥10
    """
    tenant_id = _get_tenant_id(request)
    svc = DeliveryOpsService()
    try:
        dashboard = await svc.get_health_dashboard(
            store_id=store_id, tenant_id=tenant_id, db=db
        )
        return {"ok": True, "data": dashboard.model_dump(mode="json"), "error": None}
    except DeliveryOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/health-dashboard/{store_id}/trend",
    summary="健康度趋势（近30天）",
)
async def get_health_trend(
    store_id: str,
    request: Request,
    platform: Optional[str] = Query(None, description="平台筛选，不传则返回全部"),
    days: int = Query(30, ge=7, le=90, description="查询天数"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回近N天平台健康度每日快照列表，可按平台筛选。

    数据来源：platform_health_snapshots 表（由外部数据同步任务写入）。
    """
    if platform:
        _validate_platform(platform)
    tenant_id = _get_tenant_id(request)
    svc = DeliveryOpsService()
    try:
        trend = await svc.get_health_trend(
            store_id=store_id,
            tenant_id=tenant_id,
            db=db,
            platform=platform,
            days=days,
        )
        # 将 date/Decimal 序列化
        serialized = []
        for row in trend:
            serialized.append(
                {
                    k: (
                        v.isoformat() if hasattr(v, "isoformat") else
                        float(v) if hasattr(v, "__float__") and not isinstance(v, (int, bool)) else
                        str(v) if hasattr(v, "hex") else  # UUID
                        v
                    )
                    for k, v in row.items()
                }
            )
        return {"ok": True, "data": {"trend": serialized, "days": days}, "error": None}
    except DeliveryOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
