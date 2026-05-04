"""
配送商对接 — 自营外卖配送调度（v391 持久化版）
支持达达 / 顺丰同城 / 自有骑手，自动选择最优配送商。

v391 变更（Tier 2）：
  - 内存 list 替换为 PostgreSQL（delivery_dispatches + delivery_provider_configs）
  - 三个 Provider Adapter（DadaAdapter / SfExpressAdapter / OwnRiderAdapter）统一接口
  - KDS 出餐完成 → 自动推送骑手取货事件
  - RLS 多租户隔离 + tenant_id 显式过滤双重保障

路由前缀: /api/v1/delivery/self
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..models.delivery_dispatch import DeliveryDispatch, DeliveryProviderConfig
from ..repositories.delivery_dispatch_repo import (
    DeliveryDispatchRepository,
    DeliveryProviderConfigRepository,
)
from ..services.delivery_dispatch_adapters import (
    DispatchOrderInput,
    ProviderConfigSnapshot,
    get_adapter,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/delivery/self", tags=["delivery-dispatch"])


# ─── 枚举 & 状态机 ───────────────────────────────────────────────────────────


class ProviderEnum(str, Enum):
    DADA = "dada"
    SHUNFENG = "shunfeng"
    SELF_RIDER = "self_rider"


class DispatchStatus(str, Enum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    ACCEPTED = "accepted"
    PICKED_UP = "picked_up"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    FAILED = "failed"


_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"dispatched", "cancelled", "failed"},
    "dispatched": {"accepted", "cancelled", "failed"},
    "accepted": {"picked_up", "cancelled", "failed"},
    "picked_up": {"delivering", "failed"},
    "delivering": {"delivered", "failed"},
    "delivered": set(),
    "cancelled": set(),
    "failed": {"pending"},  # 失败后可重试
}


# ─── 工具函数 ────────────────────────────────────────────────────────────────


def _ok(data: dict | list | None = None) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(code: int, message: str) -> None:
    raise HTTPException(status_code=code, detail=message)


def _parse_tenant_uuid(x_tenant_id: str) -> UUID:
    try:
        return UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid X-Tenant-ID: {exc}") from exc


def _estimate_delivery_minutes(distance_meters: int, provider: str) -> int:
    """根据距离与 provider 估算配送时长。自有骑手熟悉路线略快。"""
    base = max(15, int(distance_meters / 250))
    if provider == ProviderEnum.SELF_RIDER.value:
        return max(10, int(base * 0.85))
    return base


def _mask_secret(secret: Optional[str]) -> Optional[str]:
    if not secret:
        return secret
    if len(secret) > 8:
        return secret[:4] + "****" + secret[-4:]
    return "****"


def _config_to_snapshot(
    cfg: DeliveryProviderConfig,
    tenant_id: UUID,
) -> ProviderConfigSnapshot:
    return ProviderConfigSnapshot(
        provider=cfg.provider,
        tenant_id=str(tenant_id),
        store_id=cfg.store_id,
        app_key=cfg.app_key,
        app_secret=cfg.app_secret,
        merchant_id=cfg.merchant_id,
        shop_no=cfg.shop_no,
        callback_url=cfg.callback_url,
        extra_config=dict(cfg.extra_config or {}),
    )


def _empty_snapshot(provider: str, tenant_id: UUID, store_id: str) -> ProviderConfigSnapshot:
    """preferred_provider 但门店未配置时，用空 snapshot 让 adapter 走默认 mock 流程"""
    return ProviderConfigSnapshot(
        provider=provider,
        tenant_id=str(tenant_id),
        store_id=store_id,
    )


def _serialize_dispatch(d: DeliveryDispatch) -> dict:
    def _iso(v: datetime | None) -> Optional[str]:
        return v.isoformat() if v else None

    return {
        "id": d.dispatch_no,  # 对外暴露业务编号，UUID id 仅做内部主键
        "uuid": str(d.id),
        "tenant_id": str(d.tenant_id),
        "store_id": d.store_id,
        "order_id": d.order_id,
        "provider": d.provider,
        "provider_order_id": d.provider_order_id,
        "status": d.status,
        "rider_name": d.rider_name,
        "rider_phone": d.rider_phone,
        "rider_lat": d.rider_lat,
        "rider_lng": d.rider_lng,
        "rider_updated_at": _iso(d.rider_updated_at),
        "delivery_address": d.delivery_address,
        "delivery_lat": d.delivery_lat,
        "delivery_lng": d.delivery_lng,
        "distance_meters": d.distance_meters,
        "delivery_fee_fen": d.delivery_fee_fen,
        "tip_fen": d.tip_fen,
        "estimated_minutes": d.estimated_minutes,
        "actual_minutes": d.actual_minutes,
        "dispatched_at": _iso(d.dispatched_at),
        "accepted_at": _iso(d.accepted_at),
        "picked_up_at": _iso(d.picked_up_at),
        "delivered_at": _iso(d.delivered_at),
        "cancelled_at": _iso(d.cancelled_at),
        "cancel_reason": d.cancel_reason,
        "fail_reason": d.fail_reason,
        "kds_ready_at": _iso(d.kds_ready_at),
        "rider_notified_at": _iso(d.rider_notified_at),
        "created_at": _iso(d.created_at),
        "updated_at": _iso(d.updated_at),
    }


def _serialize_config(c: DeliveryProviderConfig, *, mask_secret: bool = True) -> dict:
    return {
        "id": str(c.id),
        "provider": c.provider,
        "enabled": c.enabled,
        "priority": c.priority,
        "app_key": c.app_key,
        "app_secret": _mask_secret(c.app_secret) if mask_secret else c.app_secret,
        "merchant_id": c.merchant_id,
        "shop_no": c.shop_no,
        "callback_url": c.callback_url,
        "extra_config": dict(c.extra_config or {}),
    }


# ─── 请求 / 响应模型 ────────────────────────────────────────────────────────


class CreateDispatchReq(BaseModel):
    order_id: str = Field(..., description="关联交易订单ID")
    store_id: str = Field(..., description="门店ID")
    delivery_address: str = Field(..., min_length=1, max_length=500)
    delivery_lat: Optional[float] = None
    delivery_lng: Optional[float] = None
    distance_meters: int = Field(default=0, ge=0)
    delivery_fee_fen: int = Field(default=0, ge=0)
    tip_fen: int = Field(default=0, ge=0)
    customer_phone: Optional[str] = Field(None, max_length=20)
    preferred_provider: Optional[ProviderEnum] = Field(None, description="指定配送商，为空则按门店配置自动选择")


class CancelDispatchReq(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200)


class ProviderConfigReq(BaseModel):
    provider: ProviderEnum
    enabled: bool = True
    priority: int = Field(0, ge=0, le=99)
    app_key: Optional[str] = Field(None, max_length=200)
    app_secret: Optional[str] = Field(None, max_length=200)
    merchant_id: Optional[str] = Field(None, max_length=100)
    shop_no: Optional[str] = Field(None, max_length=100)
    callback_url: Optional[str] = Field(None, max_length=500)
    extra_config: Optional[dict] = None


class UpdateProviderConfigReq(BaseModel):
    store_id: str
    configs: List[ProviderConfigReq] = Field(..., min_length=1, max_length=3)


class TrackInfo(BaseModel):
    dispatch_id: str
    status: str
    rider_name: Optional[str] = None
    rider_phone: Optional[str] = None
    rider_lat: Optional[float] = None
    rider_lng: Optional[float] = None
    rider_updated_at: Optional[str] = None
    estimated_minutes: Optional[int] = None
    provider: str
    provider_order_id: Optional[str] = None


class KdsReadyReq(BaseModel):
    """KDS 出餐完成回调 — 触发骑手取货推送"""

    order_id: str = Field(..., description="交易订单ID（用于反查 dispatch）")


# ─── 1. 创建配送单（DB 持久化 + Adapter 下发）──────────────────────────────


@router.post("/dispatch", summary="创建配送单（自动选择达达/顺丰/骑手）", status_code=201)
async def create_dispatch(
    req: CreateDispatchReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_uuid = _parse_tenant_uuid(x_tenant_id)

    # 1. 选 provider
    if req.preferred_provider is not None:
        provider_str = req.preferred_provider.value
        cfg = await DeliveryProviderConfigRepository.get_one(db, tenant_uuid, req.store_id, provider_str)
        snapshot = (
            _config_to_snapshot(cfg, tenant_uuid)
            if cfg is not None
            else _empty_snapshot(provider_str, tenant_uuid, req.store_id)
        )
    else:
        cfg = await DeliveryProviderConfigRepository.select_best_enabled(db, tenant_uuid, req.store_id)
        if cfg is None:
            _err(422, "该门店未配置任何可用配送商，请先在配送商配置中启用至少一个配送商")
        provider_str = cfg.provider  # type: ignore[union-attr]
        snapshot = _config_to_snapshot(cfg, tenant_uuid)  # type: ignore[arg-type]

    estimated_minutes = _estimate_delivery_minutes(req.distance_meters, provider_str)
    dispatch_no = f"DSP-{uuid.uuid4().hex[:12].upper()}"

    # 2. 调 adapter 下发
    adapter = get_adapter(provider_str, snapshot)
    dispatch_input = DispatchOrderInput(
        dispatch_id=dispatch_no,
        order_id=req.order_id,
        store_id=req.store_id,
        delivery_address=req.delivery_address,
        delivery_lat=req.delivery_lat,
        delivery_lng=req.delivery_lng,
        distance_meters=req.distance_meters,
        delivery_fee_fen=req.delivery_fee_fen,
        tip_fen=req.tip_fen,
        estimated_minutes=estimated_minutes,
        customer_phone=req.customer_phone,
    )
    api_result = await adapter.dispatch(dispatch_input)
    if not api_result.success:
        _err(
            502,
            f"配送商下单失败 [{api_result.error_code or 'UNKNOWN'}]: {api_result.error_message or '未知错误'}",
        )

    # 3. 持久化
    dispatch = await DeliveryDispatchRepository.create(
        db,
        dispatch_no=dispatch_no,
        tenant_id=tenant_uuid,
        store_id=req.store_id,
        order_id=req.order_id,
        provider=provider_str,
        provider_order_id=api_result.provider_order_id,
        delivery_address=req.delivery_address,
        delivery_lat=req.delivery_lat,
        delivery_lng=req.delivery_lng,
        distance_meters=req.distance_meters,
        delivery_fee_fen=req.delivery_fee_fen,
        tip_fen=req.tip_fen,
        estimated_minutes=api_result.estimated_minutes,
    )

    logger.info(
        "delivery_dispatch.created",
        dispatch_no=dispatch_no,
        provider=provider_str,
        order_id=req.order_id,
        estimated_minutes=api_result.estimated_minutes,
    )
    return _ok(_serialize_dispatch(dispatch))


# ─── 2. 骑手位置追踪 ────────────────────────────────────────────────────────


@router.get("/dispatch/{dispatch_id}/track", summary="骑手位置追踪")
async def track_dispatch(
    dispatch_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_uuid = _parse_tenant_uuid(x_tenant_id)
    dispatch = await DeliveryDispatchRepository.get(db, dispatch_id, tenant_uuid)
    if dispatch is None:
        _err(404, f"配送单 '{dispatch_id}' 不存在")

    # 三方 provider：尝试拉位置，若有 provider_order_id
    if (
        dispatch.provider in (ProviderEnum.DADA.value, ProviderEnum.SHUNFENG.value)  # type: ignore[union-attr]
        and dispatch.provider_order_id  # type: ignore[union-attr]
        and dispatch.status in ("accepted", "picked_up", "delivering")  # type: ignore[union-attr]
    ):
        cfg = await DeliveryProviderConfigRepository.get_one(
            db,
            tenant_uuid,
            dispatch.store_id,
            dispatch.provider,  # type: ignore[union-attr]
        )
        snapshot = (
            _config_to_snapshot(cfg, tenant_uuid)
            if cfg is not None
            else _empty_snapshot(dispatch.provider, tenant_uuid, dispatch.store_id)  # type: ignore[union-attr]
        )
        adapter = get_adapter(dispatch.provider, snapshot)  # type: ignore[union-attr]
        loc = await adapter.query_location(dispatch.provider_order_id)  # type: ignore[union-attr]
        if loc.rider_lat is not None and loc.rider_lng is not None:
            await DeliveryDispatchRepository.update_rider_location(
                db,
                dispatch_id,
                tenant_uuid,
                rider_lat=loc.rider_lat,
                rider_lng=loc.rider_lng,
                rider_name=loc.rider_name,
                rider_phone=loc.rider_phone,
            )
            # 重新加载以拿到更新值
            dispatch = await DeliveryDispatchRepository.get(db, dispatch_id, tenant_uuid)

    track = TrackInfo(
        dispatch_id=dispatch.dispatch_no,  # type: ignore[union-attr]
        status=dispatch.status,  # type: ignore[union-attr]
        rider_name=dispatch.rider_name,  # type: ignore[union-attr]
        rider_phone=dispatch.rider_phone,  # type: ignore[union-attr]
        rider_lat=dispatch.rider_lat,  # type: ignore[union-attr]
        rider_lng=dispatch.rider_lng,  # type: ignore[union-attr]
        rider_updated_at=(
            dispatch.rider_updated_at.isoformat()  # type: ignore[union-attr]
            if dispatch.rider_updated_at  # type: ignore[union-attr]
            else None
        ),
        estimated_minutes=dispatch.estimated_minutes,  # type: ignore[union-attr]
        provider=dispatch.provider,  # type: ignore[union-attr]
        provider_order_id=dispatch.provider_order_id,  # type: ignore[union-attr]
    )
    return _ok(track.model_dump())


# ─── 3. 取消配送 ────────────────────────────────────────────────────────────


@router.post("/dispatch/{dispatch_id}/cancel", summary="取消配送")
async def cancel_dispatch(
    dispatch_id: str,
    req: CancelDispatchReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_uuid = _parse_tenant_uuid(x_tenant_id)
    dispatch = await DeliveryDispatchRepository.get(db, dispatch_id, tenant_uuid)
    if dispatch is None:
        _err(404, f"配送单 '{dispatch_id}' 不存在")

    allowed = _STATUS_TRANSITIONS.get(dispatch.status, set())  # type: ignore[union-attr]
    if "cancelled" not in allowed:
        _err(
            409,
            f"当前状态 '{dispatch.status}' 不允许取消。已取货后请走退单流程",  # type: ignore[union-attr]
        )

    # 三方 adapter 取消
    if dispatch.provider_order_id:  # type: ignore[union-attr]
        cfg = await DeliveryProviderConfigRepository.get_one(
            db,
            tenant_uuid,
            dispatch.store_id,
            dispatch.provider,  # type: ignore[union-attr]
        )
        snapshot = (
            _config_to_snapshot(cfg, tenant_uuid)
            if cfg is not None
            else _empty_snapshot(dispatch.provider, tenant_uuid, dispatch.store_id)  # type: ignore[union-attr]
        )
        adapter = get_adapter(dispatch.provider, snapshot)  # type: ignore[union-attr]
        await adapter.cancel(dispatch.provider_order_id, req.reason)  # type: ignore[union-attr]

    await DeliveryDispatchRepository.cancel(db, dispatch_id, tenant_uuid, req.reason)
    dispatch = await DeliveryDispatchRepository.get(db, dispatch_id, tenant_uuid)

    logger.info(
        "delivery_dispatch.cancelled",
        dispatch_id=dispatch_id,
        reason=req.reason,
    )
    return _ok(_serialize_dispatch(dispatch))  # type: ignore[arg-type]


# ─── 4. KDS 出餐完成 → 推送骑手取货 ─────────────────────────────────────────


@router.post("/dispatch/kds-ready", summary="KDS 出餐完成钩子（推送骑手取货）")
async def kds_ready_hook(
    req: KdsReadyReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    KDS 出餐完成事件 → 反查 dispatch → 通过 adapter 推送 PICKUP_READY。

    触发方：tx-trade KDS 路由 / delivery_kds_bridge.mark_kds_ready 在全部出餐完成时调用。
    """
    tenant_uuid = _parse_tenant_uuid(x_tenant_id)
    dispatch = await DeliveryDispatchRepository.get_by_order(db, req.order_id, tenant_uuid)
    if dispatch is None:
        # 未走自营配送的订单（如平台直接派单），静默 200 即可
        logger.info(
            "delivery_dispatch.kds_ready.no_self_dispatch",
            order_id=req.order_id,
        )
        return _ok({"notified": False, "reason": "order has no self-managed dispatch"})

    # 已经推过就幂等返回
    if dispatch.kds_ready_at is not None:
        return _ok(
            {
                "notified": True,
                "dispatch_id": dispatch.dispatch_no,
                "kds_ready_at": dispatch.kds_ready_at.isoformat(),
                "duplicate": True,
            }
        )

    # 标记 KDS ready
    await DeliveryDispatchRepository.mark_kds_ready(db, dispatch.dispatch_no, tenant_uuid)

    # 通过 adapter 推送骑手
    cfg = await DeliveryProviderConfigRepository.get_one(db, tenant_uuid, dispatch.store_id, dispatch.provider)
    snapshot = (
        _config_to_snapshot(cfg, tenant_uuid)
        if cfg is not None
        else _empty_snapshot(dispatch.provider, tenant_uuid, dispatch.store_id)
    )
    adapter = get_adapter(dispatch.provider, snapshot)
    notified = await adapter.notify_pickup_ready(
        dispatch.provider_order_id or dispatch.dispatch_no,
        dispatch.dispatch_no,
    )
    if notified:
        await DeliveryDispatchRepository.mark_rider_notified(db, dispatch.dispatch_no, tenant_uuid)

    logger.info(
        "delivery_dispatch.kds_ready.notified",
        dispatch_no=dispatch.dispatch_no,
        provider=dispatch.provider,
        notified=notified,
    )
    return _ok(
        {
            "notified": notified,
            "dispatch_id": dispatch.dispatch_no,
            "provider": dispatch.provider,
            "kds_ready_at": datetime.now(timezone.utc).isoformat(),
        }
    )


# ─── 5. 获取配送商配置 ──────────────────────────────────────────────────────


@router.get("/config", summary="获取配送商配置（达达/顺丰/自有骑手）")
async def get_provider_config(
    store_id: str = Query(..., description="门店ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_uuid = _parse_tenant_uuid(x_tenant_id)
    rows = await DeliveryProviderConfigRepository.list_for_store(db, tenant_uuid, store_id)

    if not rows:
        # 返回默认模板
        defaults = []
        for p in ProviderEnum:
            defaults.append(
                {
                    "provider": p.value,
                    "enabled": False,
                    "priority": 99,
                    "app_key": None,
                    "app_secret": None,
                    "merchant_id": None,
                    "shop_no": None,
                    "callback_url": None,
                    "extra_config": {},
                }
            )
        return _ok({"store_id": store_id, "configs": defaults})

    return _ok(
        {
            "store_id": store_id,
            "configs": [_serialize_config(c, mask_secret=True) for c in rows],
        }
    )


# ─── 6. 更新配送商配置 ──────────────────────────────────────────────────────


@router.put("/config", summary="更新配送商配置")
async def update_provider_config(
    req: UpdateProviderConfigReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_uuid = _parse_tenant_uuid(x_tenant_id)

    enabled_priorities = [c.priority for c in req.configs if c.enabled]
    if len(enabled_priorities) != len(set(enabled_priorities)):
        _err(422, "已启用的配送商优先级不能重复")

    updated: list[DeliveryProviderConfig] = []
    for cfg in req.configs:
        row = await DeliveryProviderConfigRepository.upsert(
            db,
            tenant_id=tenant_uuid,
            store_id=req.store_id,
            provider=cfg.provider.value,
            enabled=cfg.enabled,
            priority=cfg.priority,
            app_key=cfg.app_key,
            app_secret=cfg.app_secret,
            merchant_id=cfg.merchant_id,
            shop_no=cfg.shop_no,
            callback_url=cfg.callback_url,
            extra_config=cfg.extra_config,
        )
        updated.append(row)

    logger.info(
        "delivery_dispatch.config_updated",
        store_id=req.store_id,
        providers=[c.provider for c in updated],
    )
    return _ok(
        {
            "store_id": req.store_id,
            "configs": [_serialize_config(c, mask_secret=True) for c in updated],
        }
    )
