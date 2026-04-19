"""
配送商对接 — 自营外卖配送调度
支持达达/顺丰/自有骑手，自动选择最优配送商

路由前缀: /api/v1/delivery/self
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/delivery/self", tags=["delivery-dispatch"])


# ─── 枚举 & 常量 ────────────────────────────────────────────────────────────


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


# 状态流转
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


# ─── 内存存储（生产替换为 DB via delivery_dispatches / delivery_provider_configs 表）─

_dispatches: list[dict] = []
_provider_configs: list[dict] = []


# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _ok(data: dict | list | None = None) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(code: int, message: str):
    raise HTTPException(status_code=code, detail=message)


def _find_dispatch(dispatch_id: str) -> dict | None:
    for d in _dispatches:
        if d["id"] == dispatch_id and not d.get("is_deleted"):
            return d
    return None


def _find_configs_for_store(tenant_id: str, store_id: str) -> list[dict]:
    return [
        c
        for c in _provider_configs
        if c["tenant_id"] == tenant_id and c["store_id"] == store_id and not c.get("is_deleted")
    ]


def _select_best_provider(tenant_id: str, store_id: str) -> dict | None:
    """按优先级选择已启用的配送商，优先级数字越小越优先"""
    configs = _find_configs_for_store(tenant_id, store_id)
    enabled = [c for c in configs if c.get("enabled")]
    if not enabled:
        return None
    enabled.sort(key=lambda c: c.get("priority", 99))
    return enabled[0]


def _estimate_delivery_minutes(distance_meters: int, provider: str) -> int:
    """根据距离和配送商估算配送时长"""
    base = max(15, int(distance_meters / 250))
    # 自有骑手通常更快（熟悉路线）
    if provider == ProviderEnum.SELF_RIDER:
        return max(10, int(base * 0.85))
    return base


async def _call_provider_api(provider: str, action: str, payload: dict) -> dict:
    """
    调用三方配送商API（达达/顺丰）
    生产环境替换为真实HTTP调用
    """
    logger.info("delivery_dispatch.provider_api_call", provider=provider, action=action)
    # Mock: 模拟三方API返回
    return {
        "success": True,
        "provider_order_id": f"{provider.upper()}-{uuid.uuid4().hex[:10].upper()}",
        "estimated_minutes": payload.get("estimated_minutes", 30),
    }


# ─── 请求/响应模型 ──────────────────────────────────────────────────────────


class CreateDispatchReq(BaseModel):
    order_id: str = Field(..., description="关联交易订单ID")
    store_id: str = Field(..., description="门店ID")
    delivery_address: str = Field(..., min_length=1, max_length=500, description="配送地址")
    delivery_lat: Optional[float] = Field(None, description="收货纬度")
    delivery_lng: Optional[float] = Field(None, description="收货经度")
    distance_meters: int = Field(default=0, ge=0, description="配送距离(米)")
    delivery_fee_fen: int = Field(default=0, ge=0, description="配送费(分)")
    tip_fen: int = Field(default=0, ge=0, description="小费(分)")
    preferred_provider: Optional[ProviderEnum] = Field(None, description="指定配送商，为空则自动选择")


class CancelDispatchReq(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200, description="取消原因")


class ProviderConfigReq(BaseModel):
    provider: ProviderEnum = Field(..., description="配送商类型")
    enabled: bool = Field(True, description="是否启用")
    priority: int = Field(0, ge=0, le=99, description="优先级(0最高)")
    app_key: Optional[str] = Field(None, max_length=200, description="AppKey")
    app_secret: Optional[str] = Field(None, max_length=200, description="AppSecret")
    merchant_id: Optional[str] = Field(None, max_length=100, description="商户号")
    shop_no: Optional[str] = Field(None, max_length=100, description="门店编号")
    callback_url: Optional[str] = Field(None, max_length=500, description="回调URL")
    extra_config: Optional[dict] = Field(None, description="额外配置")


class UpdateProviderConfigReq(BaseModel):
    store_id: str = Field(..., description="门店ID")
    configs: List[ProviderConfigReq] = Field(..., min_length=1, max_length=3, description="配送商配置列表")


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


# ─── 1. 创建配送单（自动选择配送商）──────────────────────────────────────────


@router.post("/dispatch", summary="创建配送单（自动选择达达/顺丰/骑手）", status_code=201)
async def create_dispatch(
    req: CreateDispatchReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """
    创建配送调度单。流程：
    1. 若指定 preferred_provider，使用指定配送商
    2. 否则按门店配送商配置优先级自动选择
    3. 调用三方 API 下单
    4. 记录配送单
    """
    tenant_id = x_tenant_id

    # 选择配送商
    if req.preferred_provider:
        provider = req.preferred_provider.value
    else:
        best = _select_best_provider(tenant_id, req.store_id)
        if best is None:
            _err(422, "该门店未配置任何可用配送商，请先在配送商配置中启用至少一个配送商")
        provider = best["provider"]  # type: ignore[index]

    estimated_minutes = _estimate_delivery_minutes(req.distance_meters, provider)
    dispatch_id = f"DSP-{uuid.uuid4().hex[:12].upper()}"
    now_iso = datetime.now(timezone.utc).isoformat()

    # 调用三方API
    api_result = await _call_provider_api(
        provider,
        "create_order",
        {
            "order_id": req.order_id,
            "store_id": req.store_id,
            "address": req.delivery_address,
            "lat": req.delivery_lat,
            "lng": req.delivery_lng,
            "distance_meters": req.distance_meters,
            "estimated_minutes": estimated_minutes,
        },
    )

    dispatch: dict = {
        "id": dispatch_id,
        "tenant_id": tenant_id,
        "store_id": req.store_id,
        "order_id": req.order_id,
        "provider": provider,
        "provider_order_id": api_result.get("provider_order_id"),
        "status": DispatchStatus.DISPATCHED.value,
        "rider_name": None,
        "rider_phone": None,
        "rider_lat": None,
        "rider_lng": None,
        "rider_updated_at": None,
        "delivery_address": req.delivery_address,
        "delivery_lat": req.delivery_lat,
        "delivery_lng": req.delivery_lng,
        "distance_meters": req.distance_meters,
        "delivery_fee_fen": req.delivery_fee_fen,
        "tip_fen": req.tip_fen,
        "estimated_minutes": estimated_minutes,
        "actual_minutes": None,
        "dispatched_at": now_iso,
        "accepted_at": None,
        "picked_up_at": None,
        "delivered_at": None,
        "cancelled_at": None,
        "cancel_reason": None,
        "fail_reason": None,
        "provider_callback_raw": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        "is_deleted": False,
    }
    _dispatches.append(dispatch)

    logger.info(
        "delivery_dispatch.created",
        dispatch_id=dispatch_id,
        provider=provider,
        order_id=req.order_id,
        estimated_minutes=estimated_minutes,
    )

    return _ok(dispatch)


# ─── 2. 骑手位置追踪 ─────────────────────────────────────────────────────────


@router.get("/dispatch/{dispatch_id}/track", summary="骑手位置追踪")
async def track_dispatch(
    dispatch_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """
    查询骑手实时位置。
    - 自有骑手：直接返回本地存储的位置
    - 达达/顺丰：调用三方API查询后缓存并返回
    """
    dispatch = _find_dispatch(dispatch_id)
    if dispatch is None:
        _err(404, f"配送单 '{dispatch_id}' 不存在")
    if dispatch["tenant_id"] != x_tenant_id:  # type: ignore[index]
        _err(403, "无权访问此配送单")

    # 对于三方配送商，尝试拉取最新位置（Mock）
    if dispatch["provider"] in (ProviderEnum.DADA.value, ProviderEnum.SHUNFENG.value):  # type: ignore[index]
        provider_result = await _call_provider_api(
            dispatch["provider"],
            "query_location",  # type: ignore[index]
            {"provider_order_id": dispatch["provider_order_id"]},  # type: ignore[index]
        )
        # Mock: 模拟骑手位置更新
        if dispatch["status"] in ("accepted", "picked_up", "delivering"):  # type: ignore[index]
            now_iso = datetime.now(timezone.utc).isoformat()
            dispatch.update(
                {  # type: ignore[union-attr]
                    "rider_lat": 28.2282 + (hash(dispatch_id) % 100) * 0.0001,
                    "rider_lng": 112.9388 + (hash(dispatch_id) % 100) * 0.0001,
                    "rider_updated_at": now_iso,
                }
            )

    track = TrackInfo(
        dispatch_id=dispatch["id"],  # type: ignore[index]
        status=dispatch["status"],  # type: ignore[index]
        rider_name=dispatch["rider_name"],  # type: ignore[index]
        rider_phone=dispatch["rider_phone"],  # type: ignore[index]
        rider_lat=dispatch["rider_lat"],  # type: ignore[index]
        rider_lng=dispatch["rider_lng"],  # type: ignore[index]
        rider_updated_at=dispatch["rider_updated_at"],  # type: ignore[index]
        estimated_minutes=dispatch["estimated_minutes"],  # type: ignore[index]
        provider=dispatch["provider"],  # type: ignore[index]
        provider_order_id=dispatch["provider_order_id"],  # type: ignore[index]
    )

    return _ok(track.model_dump())


# ─── 3. 取消配送 ─────────────────────────────────────────────────────────────


@router.post("/dispatch/{dispatch_id}/cancel", summary="取消配送")
async def cancel_dispatch(
    dispatch_id: str,
    req: CancelDispatchReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """
    取消配送单。规则：
    - 仅 pending/dispatched/accepted 状态可取消
    - 三方配送商需调用取消API
    - 已取货后不可取消（需走退单流程）
    """
    dispatch = _find_dispatch(dispatch_id)
    if dispatch is None:
        _err(404, f"配送单 '{dispatch_id}' 不存在")
    if dispatch["tenant_id"] != x_tenant_id:  # type: ignore[index]
        _err(403, "无权操作此配送单")

    allowed = _STATUS_TRANSITIONS.get(dispatch["status"], set())  # type: ignore[index]
    if "cancelled" not in allowed:
        _err(409, f"当前状态 '{dispatch['status']}' 不允许取消。已取货后请走退单流程")

    # 调用三方取消API
    if dispatch["provider"] in (ProviderEnum.DADA.value, ProviderEnum.SHUNFENG.value):  # type: ignore[index]
        await _call_provider_api(
            dispatch["provider"],
            "cancel_order",  # type: ignore[index]
            {
                "provider_order_id": dispatch["provider_order_id"],  # type: ignore[index]
                "reason": req.reason,
            },
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    dispatch.update(
        {  # type: ignore[union-attr]
            "status": DispatchStatus.CANCELLED.value,
            "cancelled_at": now_iso,
            "cancel_reason": req.reason,
            "updated_at": now_iso,
        }
    )

    logger.info("delivery_dispatch.cancelled", dispatch_id=dispatch_id, reason=req.reason)

    return _ok(dispatch)


# ─── 4. 获取配送商配置 ───────────────────────────────────────────────────────


@router.get("/config", summary="获取配送商配置（达达/顺丰/自有骑手）")
async def get_provider_config(
    store_id: str = Query(..., description="门店ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """
    获取指定门店的配送商配置列表。
    返回达达、顺丰、自有骑手三个配送商的账号和优先级。
    """
    configs = _find_configs_for_store(x_tenant_id, store_id)

    # 如果没有配置，返回默认模板
    if not configs:
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

    # 脱敏 app_secret
    safe_configs = []
    for c in configs:
        safe = {**c}
        if safe.get("app_secret"):
            secret = safe["app_secret"]
            safe["app_secret"] = secret[:4] + "****" + secret[-4:] if len(secret) > 8 else "****"
        safe_configs.append(safe)

    return _ok({"store_id": store_id, "configs": safe_configs})


# ─── 5. 更新配送商配置 ───────────────────────────────────────────────────────


@router.put("/config", summary="更新配送商配置")
async def update_provider_config(
    req: UpdateProviderConfigReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """
    批量更新门店的配送商配置。
    - 每个门店每种配送商只能有一条配置
    - 优先级不可重复（同门店内）
    """
    tenant_id = x_tenant_id
    store_id = req.store_id
    now_iso = datetime.now(timezone.utc).isoformat()

    # 检查优先级是否重复（仅启用的配送商）
    enabled_priorities = [c.priority for c in req.configs if c.enabled]
    if len(enabled_priorities) != len(set(enabled_priorities)):
        _err(422, "已启用的配送商优先级不能重复")

    updated_configs = []
    for cfg in req.configs:
        # 查找现有配置
        existing = None
        for c in _provider_configs:
            if (
                c["tenant_id"] == tenant_id
                and c["store_id"] == store_id
                and c["provider"] == cfg.provider.value
                and not c.get("is_deleted")
            ):
                existing = c
                break

        if existing:
            # 更新已有配置
            existing.update(
                {
                    "enabled": cfg.enabled,
                    "priority": cfg.priority,
                    "merchant_id": cfg.merchant_id,
                    "shop_no": cfg.shop_no,
                    "callback_url": cfg.callback_url,
                    "extra_config": cfg.extra_config or {},
                    "updated_at": now_iso,
                }
            )
            # 敏感字段仅在显式提供时更新
            if cfg.app_key is not None:
                existing["app_key"] = cfg.app_key
            if cfg.app_secret is not None:
                existing["app_secret"] = cfg.app_secret
            updated_configs.append(existing)
        else:
            # 新建配置
            new_config: dict = {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "store_id": store_id,
                "provider": cfg.provider.value,
                "enabled": cfg.enabled,
                "priority": cfg.priority,
                "app_key": cfg.app_key,
                "app_secret": cfg.app_secret,
                "merchant_id": cfg.merchant_id,
                "shop_no": cfg.shop_no,
                "callback_url": cfg.callback_url,
                "extra_config": cfg.extra_config or {},
                "created_at": now_iso,
                "updated_at": now_iso,
                "is_deleted": False,
            }
            _provider_configs.append(new_config)
            updated_configs.append(new_config)

    logger.info(
        "delivery_dispatch.config_updated", store_id=store_id, providers=[c["provider"] for c in updated_configs]
    )

    return _ok({"store_id": store_id, "configs": updated_configs})
