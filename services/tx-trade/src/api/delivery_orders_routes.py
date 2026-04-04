"""外卖订单接单面板扩展 API — delivery_orders_routes

补充 delivery_panel_router 未覆盖的端点：

  PUT  /api/v1/delivery/orders/{id}/status      — 状态流转（cooking/ready/delivering/completed）
  POST /api/v1/delivery/orders/{id}/cancel      — 取消订单
  POST /api/v1/delivery/webhook/meituan         — 美团 Webhook（mock 200）
  POST /api/v1/delivery/webhook/eleme           — 饿了么 Webhook（mock 200）
  POST /api/v1/delivery/mock/new-order          — 生成 mock 外卖订单（开发调试）

注意：
  - 订单列表/详情/接单/拒单/出餐完成/统计/自动接单规则 已在 delivery_panel_router 实现
  - 本路由注册时加前缀区分，避免与 delivery_panel_router 路径冲突
  - 所有接口遵循 { ok: bool, data: {} } 响应规范
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..models.delivery_order import DeliveryOrder

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/delivery", tags=["delivery-orders-ext"])


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _serialize(order: DeliveryOrder) -> dict:
    """将 DeliveryOrder ORM 对象序列化为前端消费格式"""
    items_raw = order.items_json or []
    # items_json 可能是 list 或 dict（兼容旧数据）
    items: list = items_raw if isinstance(items_raw, list) else []
    return {
        "id": str(order.id),
        "platform": order.platform,
        "platform_name": order.platform_name or order.platform,
        "platform_order_id": order.platform_order_id,
        "platform_order_no": order.platform_order_no,
        "status": order.status,
        "store_id": str(order.store_id),
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "delivery_address": order.delivery_address,
        "items": items,
        "note": order.special_request or order.notes,
        "total_fen": order.total_fen,
        "actual_revenue_fen": order.actual_revenue_fen,
        "commission_fen": order.commission_fen,
        "estimated_delivery_min": getattr(order, "estimated_delivery_min", None),
        "estimated_prep_time": order.estimated_prep_time,
        "rider_name": order.rider_name,
        "rider_phone": order.rider_phone,
        "accepted_at": order.accepted_at.isoformat() if order.accepted_at else None,
        "ready_at": order.ready_at.isoformat() if order.ready_at else None,
        "completed_at": order.completed_at.isoformat() if order.completed_at else None,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


# ─── 请求模型 ──────────────────────────────────────────────────────────────────

_VALID_STATUSES = Literal["cooking", "ready", "delivering", "completed"]


class StatusUpdateRequest(BaseModel):
    status: _VALID_STATUSES = Field(..., description="目标状态: cooking/ready/delivering/completed")


class CancelRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200, description="取消原因")


# ─── 状态流转 ──────────────────────────────────────────────────────────────────

# 合法的前向转换（from → allowed next states）
_FORWARD_MAP: dict[str, set[str]] = {
    "pending_accept": {"accepted"},
    "confirmed":      {"accepted"},   # 兼容旧状态名
    "accepted":       {"cooking", "ready"},
    "cooking":        {"ready"},
    "ready":          {"delivering", "completed"},
    "delivering":     {"completed"},
}


@router.put("/orders/{order_id}/status", summary="外卖订单状态流转")
async def update_order_status(
    order_id: uuid.UUID,
    body: StatusUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    外卖订单状态机推进（进行中订单的操作按钮）：

    - accepted  → cooking    （开始备餐）
    - cooking   → ready      （备餐完成）
    - ready     → delivering （骑手已取）
    - delivering→ completed  （已完成）
    - ready     → completed  （无需配送直接完成）
    """
    tenant_id_str = _get_tenant_id(request)
    log = logger.bind(order_id=str(order_id), target_status=body.status)

    try:
        tenant_id = uuid.UUID(tenant_id_str)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"tenant_id 格式错误: {exc}") from exc

    try:
        stmt = (
            select(DeliveryOrder)
            .where(
                DeliveryOrder.id == order_id,
                DeliveryOrder.tenant_id == tenant_id,
            )
        )
        result = await db.execute(stmt)
        order = result.scalar_one_or_none()

        if order is None:
            raise HTTPException(status_code=404, detail="订单不存在")

        allowed = _FORWARD_MAP.get(order.status, set())
        if body.status not in allowed:
            raise HTTPException(
                status_code=409,
                detail=f"当前状态 '{order.status}' 不允许转换到 '{body.status}'，"
                       f"合法目标: {sorted(allowed) or '无'}",
            )

        now = datetime.now(timezone.utc)
        order.status = body.status

        if body.status == "cooking":
            pass  # 无额外时间戳
        elif body.status == "ready":
            order.ready_at = now
        elif body.status == "delivering":
            # delivering_at 字段由 v110 迁移添加，用 setattr 防止旧 schema 报错
            order.delivering_at = now
        elif body.status == "completed":
            order.completed_at = now

        await db.commit()
        await db.refresh(order)

        log.info("delivery_order.status_updated", new_status=body.status)
        return {"ok": True, "data": _serialize(order)}

    except HTTPException:
        raise
    except ValueError as exc:
        log.warning("delivery_order.status_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 最外层 HTTP 兜底
        log.error("delivery_order.status_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


# ─── 取消订单 ──────────────────────────────────────────────────────────────────

_CANCELLABLE_STATUSES = {"pending_accept", "confirmed", "accepted", "cooking", "ready"}


@router.post("/orders/{order_id}/cancel", summary="取消外卖订单")
async def cancel_order(
    order_id: uuid.UUID,
    body: CancelRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    取消外卖订单（仅允许 pending_accept/accepted/cooking/ready 状态取消）。

    Body: {"reason": "暂停营业"}
    """
    tenant_id_str = _get_tenant_id(request)
    log = logger.bind(order_id=str(order_id), reason=body.reason)

    try:
        tenant_id = uuid.UUID(tenant_id_str)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"tenant_id 格式错误: {exc}") from exc

    try:
        stmt = select(DeliveryOrder).where(
            DeliveryOrder.id == order_id,
            DeliveryOrder.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        order = result.scalar_one_or_none()

        if order is None:
            raise HTTPException(status_code=404, detail="订单不存在")

        if order.status not in _CANCELLABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"状态 '{order.status}' 的订单无法取消",
            )

        now = datetime.now(timezone.utc)
        order.status = "cancelled"
        order.cancel_reason = body.reason
        order.cancelled_at = now
        order.cancel_by = "staff"

        await db.commit()
        await db.refresh(order)

        log.info("delivery_order.cancelled_ok")
        return {"ok": True, "data": _serialize(order)}

    except HTTPException:
        raise
    except ValueError as exc:
        log.warning("delivery_order.cancel_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 最外层 HTTP 兜底
        log.error("delivery_order.cancel_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


# ─── 平台 Webhook 入口（新路径格式，与 delivery_panel_router /webhooks/* 区分）──

@router.post("/webhook/meituan", summary="美团外卖 Webhook 入口（mock）")
async def webhook_meituan_mock(request: Request):
    """
    美团外卖新订单推送 Webhook 入口。

    生产环境：转发到 delivery_panel_router 的 /webhooks/meituan 处理真实签名验签。
    当前：返回 200 mock，供联调测试。
    """
    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError):
        payload = {}
    logger.info("webhook.meituan.received", payload_keys=list(payload.keys()))
    return {"data": "success", "message": "ok", "status": 0}


@router.post("/webhook/eleme", summary="饿了么 Webhook 入口（mock）")
async def webhook_eleme_mock(request: Request):
    """
    饿了么新订单推送 Webhook 入口。

    生产环境：转发到 delivery_panel_router 的 /webhooks/eleme 处理。
    当前：返回 200 mock。
    """
    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError):
        payload = {}
    logger.info("webhook.eleme.received", payload_keys=list(payload.keys()))
    return {"code": 0, "message": "ok"}


# ─── Mock 订单生成（开发调试） ──────────────────────────────────────────────────

_VALID_PLATFORMS = ["meituan", "eleme", "douyin", "wechat"]
_PLATFORM_NAMES = {
    "meituan": "美团外卖",
    "eleme": "饿了么",
    "douyin": "抖音外卖",
    "wechat": "微信外卖",
}

_PLATFORM_SHORT_PREFIXES = {
    "meituan": "MT",
    "eleme": "EL",
    "douyin": "DY",
    "wechat": "WX",
}

_NOTES_POOL = [
    "",
    "不要香菜",
    "少辣",
    "多放辣椒",
    "餐具不用了",
    "麻烦快一点，快饿死了",
    "不要葱",
    "",
    "",
]


def _random_order_no(platform: str) -> str:
    suffix = "".join(random.choices(string.digits, k=8))
    return f"{_PLATFORM_SHORT_PREFIXES.get(platform, 'XX')}{suffix}"


async def _fetch_dish_items_from_db(
    store_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> tuple[list[dict], int]:
    """从 delivery_orders 历史中提取该门店实际存在的菜品，随机选 2-4 个组合。
    若 DB 查询失败或无历史数据，返回空列表+0。
    """
    from sqlalchemy import text as _text  # noqa: PLC0415

    try:
        sql = _text("""
            SELECT DISTINCT elem->>'name' AS name,
                   (elem->>'price_fen')::int AS price_fen,
                   COALESCE(elem->>'spec', '') AS spec
            FROM delivery_orders,
                 jsonb_array_elements(items_json::jsonb) AS elem
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND items_json IS NOT NULL
              AND jsonb_typeof(items_json::jsonb) = 'array'
              AND elem->>'name' IS NOT NULL
              AND (elem->>'price_fen')::int > 0
            LIMIT 50
        """)
        result = await db.execute(sql, {"store_id": store_id, "tenant_id": tenant_id})
        rows = result.fetchall()
    except Exception as exc:  # noqa: BLE001 — 菜品查询失败时生成空订单
        logger.warning("delivery_order.mock_dish_fetch_failed", error=str(exc))
        return [], 0

    if not rows:
        return [], 0

    count = random.randint(2, min(4, len(rows)))
    chosen = random.sample(rows, k=count)
    items = []
    subtotal = 0
    for row in chosen:
        qty = random.randint(1, 2)
        price_fen = row.price_fen or 1000
        subtotal += price_fen * qty
        items.append({
            "name": row.name,
            "qty": qty,
            "price_fen": price_fen,
            "spec": row.spec or "",
        })
    return items, subtotal


async def _fetch_customer_sample_from_db(
    store_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> tuple[str, str, str]:
    """从 delivery_orders 历史中随机取一条订单的客户名/手机/地址。
    若无历史数据，使用通用占位符（不暴露真实 PII）。
    """
    from sqlalchemy import text as _text  # noqa: PLC0415

    try:
        sql = _text("""
            SELECT customer_name, customer_phone, delivery_address
            FROM delivery_orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND customer_name IS NOT NULL
            ORDER BY RANDOM()
            LIMIT 1
        """)
        result = await db.execute(sql, {"store_id": store_id, "tenant_id": tenant_id})
        row = result.fetchone()
        if row:
            return (
                row.customer_name,
                row.customer_phone or "138****0000",
                row.delivery_address or "",
            )
    except Exception as exc:  # noqa: BLE001 — 客户信息查询失败时使用占位符
        logger.warning("delivery_order.mock_customer_fetch_failed", error=str(exc))

    # 无历史数据时使用匿名占位符
    return "测试用户", "138****" + "".join(random.choices(string.digits, k=4)), "（调试地址）"


@router.post("/mock/new-order", summary="生成 mock 外卖新订单（开发调试）")
async def mock_new_order(
    request: Request,
    store_id: uuid.UUID = Query(..., description="门店 ID"),
    platform: Optional[str] = Query(None, description="平台（默认随机）: meituan/eleme/douyin/wechat"),
    db: AsyncSession = Depends(get_db),
):
    """
    生成一条 mock 外卖新订单（状态为 pending_accept），供开发/演示使用。

    - 随机选择平台（或指定 platform 参数）
    - 菜品数据从该门店 delivery_orders 历史中取样（无历史时返回错误提示）
    - 客户信息从历史订单中随机取样（无历史时使用匿名占位符）
    - 配送费 0 或 500 分
    - 平台补贴 0-200 分

    注意：此端点仅用于开发调试，生产环境应通过 Webhook 接收真实订单。
    """
    tenant_id_str = _get_tenant_id(request)
    log = logger.bind(store_id=str(store_id))

    try:
        tenant_id = uuid.UUID(tenant_id_str)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"tenant_id 格式错误: {exc}") from exc

    valid_platforms = set(_VALID_PLATFORMS)
    if platform and platform not in valid_platforms:
        raise HTTPException(
            status_code=400,
            detail=f"platform 无效，允许值: {sorted(valid_platforms)}",
        )

    chosen_platform = platform or random.choice(_VALID_PLATFORMS)

    # 从 DB 历史取样真实菜品和客户信息
    items, subtotal_fen = await _fetch_dish_items_from_db(store_id, tenant_id, db)
    customer_name, customer_phone, delivery_address = await _fetch_customer_sample_from_db(
        store_id, tenant_id, db
    )

    if not items:
        log.warning("delivery_order.mock_no_dish_history", store_id=str(store_id))
        return {
            "ok": False,
            "error": {
                "code": "NO_DISH_HISTORY",
                "message": "该门店暂无历史外卖菜品数据，无法生成 mock 订单。请先通过 Webhook 接收至少一条真实订单。",
            },
        }

    delivery_fee_fen = random.choice([0, 500])
    platform_discount_fen = random.choice([0, 100, 200])
    commission_rate = 0.18
    total_fen = subtotal_fen + delivery_fee_fen - platform_discount_fen
    commission_fen = int(total_fen * commission_rate)
    merchant_receive_fen = total_fen - commission_fen

    order_no_val = _random_order_no(chosen_platform)
    platform_order_id_val = f"PLT{uuid.uuid4().hex[:16].upper()}"

    try:
        order = DeliveryOrder(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            store_id=store_id,
            order_no=f"DO{uuid.uuid4().hex[:12].upper()}",
            brand_id="mock_brand",
            platform=chosen_platform,
            platform_name=_PLATFORM_NAMES[chosen_platform],
            platform_order_id=platform_order_id_val,
            platform_order_no=order_no_val,
            sales_channel=f"delivery_{chosen_platform}",
            status="pending_accept",
            items_json=items,
            total_fen=total_fen,
            commission_rate=commission_rate,
            commission_fen=commission_fen,
            merchant_receive_fen=merchant_receive_fen,
            actual_revenue_fen=merchant_receive_fen,
            customer_name=customer_name,
            customer_phone=customer_phone,
            delivery_address=delivery_address,
            special_request=random.choice(_NOTES_POOL),
            estimated_prep_time=random.randint(15, 35),
            estimated_delivery_min=random.randint(20, 45),
            auto_accepted=False,
        )

        # v110 新增字段（兼容旧 schema）
        order.subtotal_fen = subtotal_fen
        order.delivery_fee_fen = delivery_fee_fen
        order.platform_discount_fen = platform_discount_fen

        db.add(order)
        await db.commit()
        await db.refresh(order)

        log.info(
            "delivery_order.mock_created",
            order_id=str(order.id),
            platform=chosen_platform,
            total_fen=total_fen,
        )
        return {"ok": True, "data": _serialize(order)}

    except ValueError as exc:
        log.warning("delivery_order.mock_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 最外层 HTTP 兜底
        log.error("delivery_order.mock_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")
