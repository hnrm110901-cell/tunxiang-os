"""
外卖聚合深度 — 美团/饿了么/抖音聚合订单完整落库 + 异常单补偿 + 监控指标
Y-A5

端点（prefix /api/v1/trade/aggregator）：
  POST   /webhook/{platform}                    接收平台推单 Webhook
  GET    /orders                                聚合订单列表（多平台统一视图，分页）
  GET    /orders/{aggregator_order_id}          聚合订单详情
  POST   /orders/{aggregator_order_id}/accept   接单（回调平台）
  POST   /orders/{aggregator_order_id}/ready    备餐完成通知
  POST   /orders/{aggregator_order_id}/cancel   取消单
  GET    /platforms/status                      各平台连接状态 + 今日订单量
  GET    /metrics                               失败率/平均延迟/平台对比 KPI
"""
from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Path, Query
from fastapi import status as http_status
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/trade/aggregator",
    tags=["delivery-aggregator"],
)

# ──────────────────────────────────────────────────────────────────────────────
# 平台枚举与配置
# ──────────────────────────────────────────────────────────────────────────────

SUPPORTED_PLATFORMS = {"meituan", "eleme", "douyin"}

PLATFORM_CONFIG: dict[str, dict] = {
    "meituan": {
        "label": "美团外卖",
        "color": "orange",
        "accept_ack": {"errno": 0, "errmsg": "OK"},
    },
    "eleme": {
        "label": "饿了么",
        "color": "blue",
        "accept_ack": {"code": 200, "msg": "success"},
    },
    "douyin": {
        "label": "抖音外卖",
        "color": "red",
        "accept_ack": {"err_no": 0, "err_tips": "success"},
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# 内存存储（mock 层；生产替换为 DB 写入）
# ──────────────────────────────────────────────────────────────────────────────

# 聚合订单存储：key = aggregator_order_id
_ORDERS: dict[str, dict] = {}

# 幂等去重：key = "{tenant_id}:{platform}:{platform_order_id}"
_IDEMPOTENCY_KEYS: dict[str, str] = {}

# 指标存储（最多 2000 条，FIFO）
_METRICS_STORE: deque[dict] = deque(maxlen=2000)

# 重试队列（Webhook 处理失败时入队，不丢失）
_RETRY_QUEUE: asyncio.Queue[dict] = asyncio.Queue(maxsize=500)

# ──────────────────────────────────────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────────────────────────────────────


class AggregatorOrderItem(BaseModel):
    dish_name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(ge=1)
    unit_price_fen: int = Field(ge=0, description="单价（分）")
    spec: Optional[str] = Field(default=None, max_length=200)


class AggregatorWebhookPayload(BaseModel):
    platform_order_id: str = Field(min_length=1, max_length=100, description="平台单号")
    store_id: str = Field(min_length=1, max_length=100)
    items: list[AggregatorOrderItem] = Field(min_length=1)
    total_fen: int = Field(ge=0, description="订单总金额（分）")
    customer_phone: Optional[str] = Field(default=None, description="顾客手机号（脱敏存储）")
    estimated_delivery_at: Optional[str] = Field(default=None, description="预计送达时间 ISO8601")
    platform_status: str = Field(
        description="new/accepted/ready/delivering/completed/cancelled"
    )
    extra: Optional[dict] = Field(default=None, description="平台特有扩展字段")


# ──────────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_str() -> str:
    return _now().isoformat()


def _hash_phone(phone: Optional[str]) -> Optional[str]:
    """手机号脱敏：SHA-256 哈希，保留末4位用于展示"""
    if not phone:
        return None
    # 存储哈希（不可逆），展示用 *** + 末4位
    return hashlib.sha256(phone.encode()).hexdigest()[:16]


def _mask_phone(phone: Optional[str]) -> Optional[str]:
    """展示用脱敏：保留前3位和后4位"""
    if not phone or len(phone) < 7:
        return phone
    return phone[:3] + "****" + phone[-4:]


def _verify_platform_sign(platform: str, sign: Optional[str]) -> bool:
    """
    [mock] 验签逻辑
    生产替换：
      - 美团：HMAC-SHA256(secret_key, timestamp + body)
      - 饿了么：RSA 公钥签名校验
      - 抖音：SHA-256(app_secret + body + timestamp)
    """
    # mock：仅检查 X-Platform-Sign 非空即通过
    return sign is not None and len(sign.strip()) > 0


def _record_metric(
    platform: str,
    success: bool,
    duration_ms: float,
    error_code: Optional[str] = None,
) -> None:
    """记录 Webhook 处理指标到内存（最多 2000 条，超限自动 FIFO）"""
    _METRICS_STORE.append(
        {
            "platform": platform,
            "success": success,
            "duration_ms": duration_ms,
            "error_code": error_code,
            "ts": _now_str(),
        }
    )


async def _enqueue_reconcile(order_id: str) -> None:
    """异步触发对账任务（挂在后台，Webhook 响应不等待）"""
    logger.debug("aggregator.reconcile.enqueued", order_id=order_id)
    # 生产环境替换为向 Redis Stream / Celery 推送对账任务
    await asyncio.sleep(0)  # 占位，保证 create_task 有 await


def _build_order(
    tenant_id: str,
    platform: str,
    payload: AggregatorWebhookPayload,
) -> dict:
    """构建聚合订单字典"""
    agg_id = f"agg-{uuid.uuid4().hex[:16]}"
    return {
        "id": agg_id,
        "tenant_id": tenant_id,
        "platform": platform,
        "platform_order_id": payload.platform_order_id,
        "store_id": payload.store_id,
        "items": [item.model_dump() for item in payload.items],
        "total_fen": payload.total_fen,
        "customer_phone_hash": _hash_phone(payload.customer_phone),
        "customer_phone_masked": _mask_phone(payload.customer_phone),
        "estimated_delivery_at": payload.estimated_delivery_at,
        "status": payload.platform_status,
        "raw_payload": payload.model_dump(),
        "extra": payload.extra or {},
        "created_at": _now_str(),
        "updated_at": _now_str(),
        "_data_source": "mock",  # 标注数据来源；生产替换为 DB
    }


def _upsert_order(
    tenant_id: str,
    platform: str,
    payload: AggregatorWebhookPayload,
) -> tuple[str, bool]:
    """
    幂等落库（ON CONFLICT 语义）。
    返回 (aggregator_order_id, is_new)。

    生产 DB 语义：
        INSERT INTO aggregator_orders (
            tenant_id, platform, platform_order_id, store_id,
            raw_payload, status, total_fen, customer_phone_hash,
            estimated_delivery_at, created_at, updated_at
        ) VALUES (...)
        ON CONFLICT (tenant_id, platform, platform_order_id)
        DO UPDATE SET status=EXCLUDED.status, updated_at=NOW()
        RETURNING id
    """
    idempotency_key = f"{tenant_id}:{platform}:{payload.platform_order_id}"
    existing_id = _IDEMPOTENCY_KEYS.get(idempotency_key)

    if existing_id:
        # 幂等更新：更新 status 和 updated_at
        if existing_id in _ORDERS:
            _ORDERS[existing_id]["status"] = payload.platform_status
            _ORDERS[existing_id]["updated_at"] = _now_str()
        return existing_id, False

    order = _build_order(tenant_id, platform, payload)
    agg_id = order["id"]
    _ORDERS[agg_id] = order
    _IDEMPOTENCY_KEYS[idempotency_key] = agg_id
    return agg_id, True


# ──────────────────────────────────────────────────────────────────────────────
# 端点 1：Webhook 接收
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/webhook/{platform}", summary="接收平台推单 Webhook")
async def receive_webhook(
    platform: str = Path(..., description="平台标识：meituan / eleme / douyin"),
    payload: AggregatorWebhookPayload = ...,
    x_platform_sign: Optional[str] = Header(None, alias="X-Platform-Sign"),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """
    接收美团/饿了么/抖音平台推单 Webhook。

    验签（mock）：检查 X-Platform-Sign header 非空即通过。
    生产替换：各平台 HMAC/RSA 签名校验。

    幂等：相同 (tenant_id, platform, platform_order_id) 只落库一次，
    重复推送仅更新 status。

    异步触发对账任务（不阻塞响应）。
    """
    t0 = time.monotonic()
    log = logger.bind(
        tenant=x_tenant_id,
        platform=platform,
        platform_order_id=payload.platform_order_id,
    )

    # 平台校验
    if platform not in SUPPORTED_PLATFORMS:
        _record_metric(platform, False, (time.monotonic() - t0) * 1000, "UNSUPPORTED_PLATFORM")
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={
                "ok": False,
                "error": {
                    "code": "UNSUPPORTED_PLATFORM",
                    "message": f"不支持的平台：{platform}，支持：{', '.join(SUPPORTED_PLATFORMS)}",
                },
            },
        )

    # 验签（mock：检查 X-Platform-Sign 非空）
    # [生产替换] 各平台签名验证逻辑
    if not _verify_platform_sign(platform, x_platform_sign):
        _record_metric(platform, False, (time.monotonic() - t0) * 1000, "SIGN_INVALID")
        log.warning("aggregator.webhook.sign_invalid", platform=platform)
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail={
                "ok": False,
                "error": {
                    "code": "SIGN_INVALID",
                    "message": "签名验证失败，请检查 X-Platform-Sign header",
                },
            },
        )

    # 幂等落库
    try:
        agg_order_id, is_new = _upsert_order(x_tenant_id, platform, payload)
    except ValueError as exc:
        _record_metric(platform, False, (time.monotonic() - t0) * 1000, "UPSERT_FAILED")
        log.error("aggregator.webhook.upsert_failed", error=str(exc))
        # 写入重试队列，不丢失
        try:
            _RETRY_QUEUE.put_nowait(
                {
                    "tenant_id": x_tenant_id,
                    "platform": platform,
                    "payload": payload.model_dump(),
                    "error": str(exc),
                    "enqueued_at": _now_str(),
                }
            )
        except asyncio.QueueFull:
            log.error("aggregator.retry_queue.full", platform=platform)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"ok": False, "error": {"code": "UPSERT_FAILED", "message": str(exc)}},
        )

    # 异步触发对账任务（不等待，不阻塞响应）
    asyncio.create_task(_enqueue_reconcile(agg_order_id))

    duration_ms = (time.monotonic() - t0) * 1000
    _record_metric(platform, True, duration_ms)

    log.info(
        "aggregator.webhook.ok",
        agg_order_id=agg_order_id,
        is_new=is_new,
        duration_ms=round(duration_ms, 2),
    )

    # 返回平台期望的确认响应格式
    # [生产替换] 各平台要求的 ACK 格式不同
    platform_ack = PLATFORM_CONFIG[platform]["accept_ack"]

    return {
        "ok": True,
        "data": {
            "aggregator_order_id": agg_order_id,
            "is_new": is_new,
            "platform_ack": platform_ack,
        },
        "error": None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 端点 2：聚合订单列表
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/orders", summary="聚合订单列表（多平台统一视图，分页）")
async def list_aggregator_orders(
    platform: Optional[str] = Query(None, description="平台过滤：meituan/eleme/douyin"),
    status: Optional[str] = Query(None, description="状态过滤"),
    store_id: Optional[str] = Query(None, description="门店ID"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """聚合订单统一列表：支持按平台/状态/门店过滤，分页返回。"""
    orders = [o for o in _ORDERS.values() if o["tenant_id"] == x_tenant_id]

    if platform:
        orders = [o for o in orders if o["platform"] == platform]
    if status:
        orders = [o for o in orders if o["status"] == status]
    if store_id:
        orders = [o for o in orders if o["store_id"] == store_id]

    orders.sort(key=lambda o: o["created_at"], reverse=True)
    total = len(orders)
    page_items = orders[(page - 1) * size : page * size]

    # 列表视图（不含 raw_payload）
    items = [
        {
            "id": o["id"],
            "platform": o["platform"],
            "platform_label": PLATFORM_CONFIG.get(o["platform"], {}).get("label", o["platform"]),
            "platform_color": PLATFORM_CONFIG.get(o["platform"], {}).get("color", "default"),
            "platform_order_id": o["platform_order_id"],
            "store_id": o["store_id"],
            "status": o["status"],
            "total_fen": o["total_fen"],
            "items_count": len(o.get("items", [])),
            "customer_phone_masked": o.get("customer_phone_masked"),
            "estimated_delivery_at": o.get("estimated_delivery_at"),
            "created_at": o["created_at"],
            "updated_at": o["updated_at"],
        }
        for o in page_items
    ]

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
        "error": None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 端点 3：聚合订单详情
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/orders/{aggregator_order_id}", summary="聚合订单详情")
async def get_aggregator_order(
    aggregator_order_id: str = Path(..., description="聚合订单ID"),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    order = _ORDERS.get(aggregator_order_id)
    if order is None or order["tenant_id"] != x_tenant_id:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "ok": False,
                "error": {
                    "code": "ORDER_NOT_FOUND",
                    "message": f"聚合订单 {aggregator_order_id} 不存在",
                },
            },
        )

    return {
        "ok": True,
        "data": {
            **order,
            "platform_label": PLATFORM_CONFIG.get(order["platform"], {}).get(
                "label", order["platform"]
            ),
        },
        "error": None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 端点 4/5/6：接单 / 备餐完成 / 取消单
# ──────────────────────────────────────────────────────────────────────────────

_STATUS_TRANSITIONS: dict[str, dict] = {
    "accept": {
        "allowed_from": {"new"},
        "target": "accepted",
        "log_event": "aggregator.order.accepted",
    },
    "ready": {
        "allowed_from": {"accepted"},
        "target": "ready",
        "log_event": "aggregator.order.ready",
    },
    "cancel": {
        "allowed_from": {"new", "accepted"},
        "target": "cancelled",
        "log_event": "aggregator.order.cancelled",
    },
}


async def _order_action(
    aggregator_order_id: str,
    action: str,
    x_tenant_id: str,
    reason: Optional[str] = None,
) -> dict:
    """通用订单动作处理：状态流转 + 回调平台（mock）"""
    order = _ORDERS.get(aggregator_order_id)
    if order is None or order["tenant_id"] != x_tenant_id:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "ok": False,
                "error": {"code": "ORDER_NOT_FOUND", "message": f"订单 {aggregator_order_id} 不存在"},
            },
        )

    cfg = _STATUS_TRANSITIONS[action]
    if order["status"] not in cfg["allowed_from"]:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={
                "ok": False,
                "error": {
                    "code": "INVALID_STATUS_TRANSITION",
                    "message": (
                        f"当前状态 {order['status']} 不允许执行 {action}，"
                        f"允许的来源状态：{cfg['allowed_from']}"
                    ),
                },
            },
        )

    order["status"] = cfg["target"]
    order["updated_at"] = _now_str()
    if reason:
        order["cancel_reason"] = reason

    # [生产替换] 回调平台 API 通知状态变更
    logger.info(
        cfg["log_event"],
        aggregator_order_id=aggregator_order_id,
        platform=order["platform"],
        new_status=cfg["target"],
        tenant=x_tenant_id,
    )

    return {
        "ok": True,
        "data": {
            "aggregator_order_id": aggregator_order_id,
            "platform": order["platform"],
            "status": order["status"],
            "updated_at": order["updated_at"],
            "platform_callback": "mock_ok",  # [生产替换] 真实回调结果
        },
        "error": None,
    }


class CancelBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=200, description="取消原因")


@router.post("/orders/{aggregator_order_id}/accept", summary="接单（回调平台）")
async def accept_order(
    aggregator_order_id: str = Path(...),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    return await _order_action(aggregator_order_id, "accept", x_tenant_id)


@router.post("/orders/{aggregator_order_id}/ready", summary="备餐完成通知")
async def mark_order_ready(
    aggregator_order_id: str = Path(...),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    return await _order_action(aggregator_order_id, "ready", x_tenant_id)


@router.post("/orders/{aggregator_order_id}/cancel", summary="取消单")
async def cancel_order(
    aggregator_order_id: str = Path(...),
    body: CancelBody = CancelBody(),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    return await _order_action(aggregator_order_id, "cancel", x_tenant_id, body.reason)


# ──────────────────────────────────────────────────────────────────────────────
# 端点 7：平台连接状态
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/platforms/status", summary="各平台连接状态 + 今日订单量")
async def get_platforms_status(
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """
    返回各平台连接状态（online/offline）+ 今日订单量 + 成功率。

    [生产替换] 连接状态从平台心跳检测或 OAuth token 有效性判断。
    """
    today = _now().date().isoformat()
    platforms = []

    for pid, cfg in PLATFORM_CONFIG.items():
        today_orders = [
            o
            for o in _ORDERS.values()
            if o["tenant_id"] == x_tenant_id
            and o["platform"] == pid
            and o["created_at"][:10] == today
        ]
        today_count = len(today_orders)

        # 今日成功单（非 cancelled）
        success_count = sum(1 for o in today_orders if o["status"] != "cancelled")
        success_rate = round(success_count / today_count, 4) if today_count > 0 else 1.0

        # [生产替换] 从平台 OAuth/心跳接口判断在线状态
        platform_online = True  # mock: 默认在线

        platforms.append(
            {
                "platform": pid,
                "label": cfg["label"],
                "color": cfg["color"],
                "online": platform_online,
                "today_order_count": today_count,
                "today_success_rate": success_rate,
                "_data_source": "mock",
            }
        )

    return {
        "ok": True,
        "data": {"platforms": platforms, "checked_at": _now_str()},
        "error": None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 端点 8：监控指标
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/metrics", summary="失败率/平均延迟/平台对比 KPI")
async def get_metrics(
    limit: int = Query(2000, ge=1, le=2000, description="取最近N条指标"),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """
    聚合 Webhook 处理指标：
    - 全局成功率、平均延迟、P99 延迟
    - 按平台维度细分
    """
    records = list(_METRICS_STORE)[-limit:]

    if not records:
        return {
            "ok": True,
            "data": {
                "total_requests": 0,
                "success_rate": 1.0,
                "avg_latency_ms": 0.0,
                "p99_latency_ms": 0.0,
                "by_platform": {},
            },
            "error": None,
        }

    total = len(records)
    success_count = sum(1 for r in records if r["success"])
    success_rate = round(success_count / total, 4) if total else 1.0

    latencies = sorted(r["duration_ms"] for r in records)
    avg_latency = round(sum(latencies) / len(latencies), 2)
    p99_idx = max(0, int(len(latencies) * 0.99) - 1)
    p99_latency = round(latencies[p99_idx], 2)

    # 按平台细分
    by_platform: dict[str, dict] = {}
    for pid in SUPPORTED_PLATFORMS:
        p_records = [r for r in records if r["platform"] == pid]
        p_total = len(p_records)
        if p_total == 0:
            continue
        p_success = sum(1 for r in p_records if r["success"])
        p_latencies = sorted(r["duration_ms"] for r in p_records)
        p_p99_idx = max(0, int(len(p_latencies) * 0.99) - 1)
        by_platform[pid] = {
            "label": PLATFORM_CONFIG[pid]["label"],
            "total_requests": p_total,
            "success_rate": round(p_success / p_total, 4),
            "avg_latency_ms": round(sum(p_latencies) / len(p_latencies), 2),
            "p99_latency_ms": round(p_latencies[p_p99_idx], 2),
            "error_codes": _count_error_codes([r for r in p_records if not r["success"]]),
        }

    return {
        "ok": True,
        "data": {
            "total_requests": total,
            "success_rate": success_rate,
            "avg_latency_ms": avg_latency,
            "p99_latency_ms": p99_latency,
            "by_platform": by_platform,
            "window_size": limit,
        },
        "error": None,
    }


def _count_error_codes(failed_records: list[dict]) -> dict[str, int]:
    """统计失败原因分布"""
    counts: dict[str, int] = {}
    for r in failed_records:
        code = r.get("error_code") or "UNKNOWN"
        counts[code] = counts.get(code, 0) + 1
    return counts
