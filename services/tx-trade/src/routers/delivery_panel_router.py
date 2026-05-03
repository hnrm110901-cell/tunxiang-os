"""外卖聚合接单面板 API 路由

端点列表：

Webhook（平台 → 屯象）：
  POST /api/v1/delivery/webhooks/meituan    美团外卖新订单推送
  POST /api/v1/delivery/webhooks/eleme      饿了么新订单推送
  POST /api/v1/delivery/webhooks/douyin     抖音来客新订单推送

订单管理：
  GET  /api/v1/delivery/orders              统一列表（支持平台/状态/日期/门店过滤）
  GET  /api/v1/delivery/orders/{order_id}   订单详情
  POST /api/v1/delivery/orders/{order_id}/accept      手动接单
  POST /api/v1/delivery/orders/{order_id}/reject      拒单
  POST /api/v1/delivery/orders/{order_id}/mark-ready  出餐完成

统计：
  GET  /api/v1/delivery/stats               今日各平台汇总

自动接单规则：
  GET  /api/v1/delivery/auto-accept-rules   查询规则
  PUT  /api/v1/delivery/auto-accept-rules   更新规则

注意：平台配置（app_id/app_secret/commission_rate）目前从环境变量读取（演示），
      生产环境应从 delivery_platform_configs 表查询（已在 delivery_ops_routes 中管理）。
"""

from __future__ import annotations

import os
from datetime import date, time
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.delivery_panel_service import (
    DeliveryOrderNotFound,
    DeliveryOrderStatusError,
    DeliveryPanelService,
    DuplicateOrderError,
    PlatformAdapterError,
    SignatureVerifyError,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/delivery", tags=["delivery-panel"])


# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    """从 request.state 或 Header 获取 tenant_id"""
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _get_platform_config(platform: str, store_id: str) -> dict:
    """
    获取平台配置（app_id/app_secret/shop_id/commission_rate）。

    生产环境：从 delivery_platform_configs 表按 (tenant_id, store_id, platform) 查询，
              app_secret 需要 AES-256 解密后返回。
    当前实现：从环境变量读取（开发/演示用）。
    """
    env_prefix = platform.upper()
    app_id = os.getenv(f"{env_prefix}_APP_ID", f"demo_{platform}_app_id")
    app_secret = os.getenv(f"{env_prefix}_APP_SECRET", f"demo_{platform}_secret")
    shop_id = os.getenv(f"{env_prefix}_SHOP_ID", f"demo_{platform}_shop")
    commission_rate = float(os.getenv(f"{env_prefix}_COMMISSION_RATE", "0.18"))
    brand_id = os.getenv("DEFAULT_BRAND_ID", "default_brand")
    return {
        "app_id": app_id,
        "app_secret": app_secret,
        "shop_id": shop_id,
        "commission_rate": commission_rate,
        "brand_id": brand_id,
    }


def _serialize_order(order) -> dict:
    """将 DeliveryOrder ORM 对象序列化为 API 响应字典"""
    return {
        "id": str(order.id),
        "tenant_id": str(order.tenant_id),
        "store_id": str(order.store_id),
        "order_no": order.order_no,
        "platform": order.platform,
        "platform_name": order.platform_name,
        "platform_order_id": order.platform_order_id,
        "platform_order_no": order.platform_order_no,
        "status": order.status,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "delivery_address": order.delivery_address,
        "expected_time": order.expected_time,
        "estimated_prep_time": order.estimated_prep_time,
        "total_fen": order.total_fen,
        "commission_rate": order.commission_rate,
        "commission_fen": order.commission_fen,
        "merchant_receive_fen": order.merchant_receive_fen,
        "actual_revenue_fen": order.actual_revenue_fen,
        "items": order.items_json or [],
        "special_request": order.special_request,
        "notes": order.notes,
        "auto_accepted": order.auto_accepted,
        "accepted_at": order.accepted_at.isoformat() if order.accepted_at else None,
        "rejected_at": order.rejected_at.isoformat() if order.rejected_at else None,
        "rejected_reason": order.rejected_reason,
        "ready_at": order.ready_at.isoformat() if order.ready_at else None,
        "completed_at": order.completed_at.isoformat() if order.completed_at else None,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }


# ─── Pydantic 请求模型 ─────────────────────────────────────────────────────────


class AcceptOrderRequest(BaseModel):
    prep_time_minutes: int = Field(default=20, ge=5, le=120, description="预计备餐分钟数")


class RejectOrderRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200, description="拒单原因")
    reason_code: str = Field(default="", max_length=50, description="拒单原因代码")


class AutoAcceptRuleRequest(BaseModel):
    is_enabled: Optional[bool] = None
    business_hours_start: Optional[str] = Field(None, description="营业开始时间 HH:MM，如 09:00")
    business_hours_end: Optional[str] = Field(None, description="营业结束时间 HH:MM，如 22:00")
    max_concurrent_orders: Optional[int] = Field(None, ge=1, le=100)
    excluded_platforms: Optional[list[str]] = Field(None, description='不自动接单的平台列表，如 ["meituan"]')


# ─── Webhook 接收端点 ──────────────────────────────────────────────────────────


async def _handle_platform_webhook(
    platform: str,
    request: Request,
    db: AsyncSession,
) -> dict:
    """通用 Webhook 处理：验签 → 解析 → 写库 → 自动接单检查"""
    tenant_id_str = _get_tenant_id(request)
    log = logger.bind(platform=platform, tenant_id=tenant_id_str)

    try:
        raw_body: bytes = await request.body()
        payload: dict = await request.json()
    except (ValueError, UnicodeDecodeError) as exc:
        log.warning("delivery_webhook.body_parse_failed", error=str(exc))
        raise HTTPException(status_code=400, detail="请求体解析失败") from exc

    # 从请求体或 query 中获取 store_id（生产环境应从平台配置表按 shop_id 反查）
    store_id_str: str = (
        payload.get("store_id") or request.query_params.get("store_id") or os.getenv(f"{platform.upper()}_STORE_ID", "")
    )
    if not store_id_str:
        raise HTTPException(status_code=400, detail="无法确定 store_id，请在请求中携带")

    try:
        tenant_id = UUID(tenant_id_str)
        store_id = UUID(store_id_str)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    # 获取签名（各平台 Header 不同）
    sig_header_map = {
        "meituan": "X-Meituan-Signature",
        "eleme": "X-Eleme-Hmac",
        "douyin": "X-Douyin-Signature",
        "grabfood": "X-GrabFood-Signature",
    }
    signature: str = request.headers.get(sig_header_map.get(platform, ""), "")

    config = _get_platform_config(platform, store_id_str)

    try:
        order = await DeliveryPanelService.receive_webhook(
            platform=platform,
            raw_body=raw_body,
            payload=payload,
            signature=signature,
            tenant_id=tenant_id,
            store_id=store_id,
            brand_id=config["brand_id"],
            app_id=config["app_id"],
            app_secret=config["app_secret"],
            shop_id=config["shop_id"],
            commission_rate=config["commission_rate"],
            db=db,
        )
        log.info(
            "delivery_webhook.processed",
            order_id=str(order.id),
            status=order.status,
        )
        return {"order_id": str(order.id), "status": order.status}

    except DuplicateOrderError as exc:
        # 幂等处理：平台可能重试，返回 200 但不重复处理
        log.info("delivery_webhook.duplicate", error=str(exc))
        return {"status": "duplicate", "message": "订单已处理"}

    except SignatureVerifyError as exc:
        log.warning("delivery_webhook.signature_failed", error=str(exc))
        raise HTTPException(status_code=401, detail=str(exc))

    except ValueError as exc:
        log.warning("delivery_webhook.value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/webhooks/meituan", summary="美团外卖新订单推送")
async def webhook_meituan(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    接收美团外卖 Webhook 推送。

    签名：Header X-Meituan-Signature（SHA256）
    美团要求返回：{"data": "success", "message": "ok", "status": 0}
    """
    try:
        await _handle_platform_webhook("meituan", request, db)
        return {"data": "success", "message": "ok", "status": 0}
    except HTTPException:
        raise
    except ValueError as exc:
        logger.warning("webhook_meituan.value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 最外层 HTTP 兜底
        logger.error("webhook_meituan.unexpected", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/webhooks/eleme", summary="饿了么新订单推送")
async def webhook_eleme(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    接收饿了么 Webhook 推送。

    签名：Header X-Eleme-Hmac（HMAC-SHA256）
    饿了么要求返回：{"code": 0, "message": "ok"}
    """
    try:
        await _handle_platform_webhook("eleme", request, db)
        return {"code": 0, "message": "ok"}
    except HTTPException:
        raise
    except ValueError as exc:
        logger.warning("webhook_eleme.value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 最外层 HTTP 兜底
        logger.error("webhook_eleme.unexpected", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/webhooks/douyin", summary="抖音来客新订单推送")
async def webhook_douyin(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    接收抖音外卖 Webhook 推送。

    签名：Header X-Douyin-Signature（SHA1）
    抖音要求返回：{"err_no": 0, "err_tips": "success"}
    """
    try:
        await _handle_platform_webhook("douyin", request, db)
        return {"err_no": 0, "err_tips": "success"}
    except HTTPException:
        raise
    except ValueError as exc:
        logger.warning("webhook_douyin.value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 最外层 HTTP 兜底
        logger.error("webhook_douyin.unexpected", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/webhooks/grabfood", summary="GrabFood 新订单推送")
async def webhook_grabfood(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    接收 GrabFood 马来西亚外卖 Webhook 推送。

    签名：Header X-GrabFood-Signature（HMAC-SHA256）
    GrabFood 要求返回：{"code": "OK", "message": "Order received"}
    """
    try:
        await _handle_platform_webhook("grabfood", request, db)
        return {"code": "OK", "message": "Order received"}
    except HTTPException:
        raise
    except ValueError as exc:
        logger.warning("webhook_grabfood.value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 最外层 HTTP 兜底
        logger.error("webhook_grabfood.unexpected", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


# ─── 订单管理 ──────────────────────────────────────────────────────────────────


@router.get("/orders", summary="外卖订单统一列表")
async def list_delivery_orders(
    request: Request,
    store_id: Optional[UUID] = Query(None, description="门店 ID 过滤"),
    platform: Optional[str] = Query(
        None,
        pattern="^(meituan|eleme|douyin|grabfood)$",
        description="平台过滤",
    ),
    status: Optional[str] = Query(
        None,
        description="状态过滤：pending_accept/accepted/rejected/preparing/ready/delivering/completed/cancelled",
    ),
    date_str: Optional[str] = Query(None, alias="date", description="日期 YYYY-MM-DD"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    统一外卖订单列表，支持按平台/状态/日期/门店过滤。

    前端接单面板默认查询：status=pending_accept，按创建时间倒序。
    """
    tenant_id_str = _get_tenant_id(request)
    log = logger.bind(
        tenant_id=tenant_id_str,
        platform=platform,
        status=status,
        page=page,
    )
    try:
        tenant_id = UUID(tenant_id_str)
        target_date = date.fromisoformat(date_str) if date_str else None

        from ..repositories.delivery_order_repo import DeliveryOrderRepository

        items, total = await DeliveryOrderRepository.list_orders(
            db,
            tenant_id,
            store_id=store_id,
            platform=platform,
            status=status,
            target_date=target_date,
            page=page,
            size=size,
        )
        log.info("delivery_orders.list_ok", total=total)
        return {
            "ok": True,
            "data": {
                "items": [_serialize_order(o) for o in items],
                "total": total,
                "page": page,
                "size": size,
            },
        }
    except HTTPException:
        raise
    except ValueError as exc:
        log.warning("delivery_orders.list_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 最外层 HTTP 兜底
        log.error("delivery_orders.list_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.get("/orders/{order_id}", summary="外卖订单详情")
async def get_delivery_order(
    order_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """查询单条外卖订单详情"""
    tenant_id_str = _get_tenant_id(request)
    log = logger.bind(order_id=str(order_id), tenant_id=tenant_id_str)
    try:
        tenant_id = UUID(tenant_id_str)
        from ..repositories.delivery_order_repo import DeliveryOrderRepository

        order = await DeliveryOrderRepository.get_by_id(db, order_id, tenant_id)
        if order is None:
            raise HTTPException(status_code=404, detail="订单不存在")
        return {"ok": True, "data": _serialize_order(order)}
    except HTTPException:
        raise
    except ValueError as exc:
        log.warning("delivery_order.get_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 最外层 HTTP 兜底
        log.error("delivery_order.get_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/orders/{order_id}/accept", summary="手动接单")
async def accept_delivery_order(
    order_id: UUID,
    body: AcceptOrderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    手动接单。

    1. 校验订单状态为 pending_accept
    2. 调用对应平台接单 API
    3. 更新状态 → accepted，记录 accepted_at
    4. 触发打印外卖出餐单
    5. 推送 KDS 出餐任务

    Body: {"prep_time_minutes": 20}
    """
    tenant_id_str = _get_tenant_id(request)
    log = logger.bind(order_id=str(order_id), tenant_id=tenant_id_str)
    try:
        tenant_id = UUID(tenant_id_str)

        # 先查订单，获取 store_id 以拿平台配置
        from ..repositories.delivery_order_repo import DeliveryOrderRepository

        order_check = await DeliveryOrderRepository.get_by_id(db, order_id, tenant_id)
        if order_check is None:
            raise HTTPException(status_code=404, detail="订单不存在")

        config = _get_platform_config(order_check.platform, str(order_check.store_id))
        updated = await DeliveryPanelService.accept_order(
            order_id=order_id,
            tenant_id=tenant_id,
            prep_time_minutes=body.prep_time_minutes,
            app_id=config["app_id"],
            app_secret=config["app_secret"],
            shop_id=config["shop_id"],
            db=db,
        )
        log.info("delivery_order.accepted_ok")
        return {"ok": True, "data": _serialize_order(updated)}

    except HTTPException:
        raise
    except (DeliveryOrderNotFound, DeliveryOrderStatusError) as exc:
        log.warning("delivery_order.accept_validation_error", error=str(exc))
        raise HTTPException(status_code=409, detail=str(exc))
    except PlatformAdapterError as exc:
        log.error("delivery_order.accept_platform_error", error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        log.warning("delivery_order.accept_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 最外层 HTTP 兜底
        log.error("delivery_order.accept_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/orders/{order_id}/reject", summary="拒单")
async def reject_delivery_order(
    order_id: UUID,
    body: RejectOrderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    拒单（需填写原因）。

    Body: {"reason": "库存不足", "reason_code": "stock_out"}
    """
    tenant_id_str = _get_tenant_id(request)
    log = logger.bind(order_id=str(order_id), tenant_id=tenant_id_str, reason=body.reason)
    try:
        tenant_id = UUID(tenant_id_str)

        from ..repositories.delivery_order_repo import DeliveryOrderRepository

        order_check = await DeliveryOrderRepository.get_by_id(db, order_id, tenant_id)
        if order_check is None:
            raise HTTPException(status_code=404, detail="订单不存在")

        config = _get_platform_config(order_check.platform, str(order_check.store_id))
        updated = await DeliveryPanelService.reject_order(
            order_id=order_id,
            tenant_id=tenant_id,
            reason=body.reason,
            reason_code=body.reason_code,
            app_id=config["app_id"],
            app_secret=config["app_secret"],
            shop_id=config["shop_id"],
            db=db,
        )
        log.info("delivery_order.rejected_ok")
        return {"ok": True, "data": _serialize_order(updated)}

    except HTTPException:
        raise
    except (DeliveryOrderNotFound, DeliveryOrderStatusError) as exc:
        log.warning("delivery_order.reject_validation_error", error=str(exc))
        raise HTTPException(status_code=409, detail=str(exc))
    except PlatformAdapterError as exc:
        log.error("delivery_order.reject_platform_error", error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        log.warning("delivery_order.reject_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 最外层 HTTP 兜底
        log.error("delivery_order.reject_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/orders/{order_id}/mark-ready", summary="出餐完成")
async def mark_order_ready(
    order_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    标记订单出餐完成，通知平台骑手可取单。

    允许状态：accepted → ready 或 preparing → ready
    """
    tenant_id_str = _get_tenant_id(request)
    log = logger.bind(order_id=str(order_id), tenant_id=tenant_id_str)
    try:
        tenant_id = UUID(tenant_id_str)

        from ..repositories.delivery_order_repo import DeliveryOrderRepository

        order_check = await DeliveryOrderRepository.get_by_id(db, order_id, tenant_id)
        if order_check is None:
            raise HTTPException(status_code=404, detail="订单不存在")

        config = _get_platform_config(order_check.platform, str(order_check.store_id))
        updated = await DeliveryPanelService.mark_ready(
            order_id=order_id,
            tenant_id=tenant_id,
            app_id=config["app_id"],
            app_secret=config["app_secret"],
            shop_id=config["shop_id"],
            db=db,
        )
        log.info("delivery_order.ready_ok")
        return {"ok": True, "data": _serialize_order(updated)}

    except HTTPException:
        raise
    except (DeliveryOrderNotFound, DeliveryOrderStatusError) as exc:
        log.warning("delivery_order.ready_validation_error", error=str(exc))
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        log.warning("delivery_order.ready_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 最外层 HTTP 兜底
        log.error("delivery_order.ready_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


# ─── 统计 ──────────────────────────────────────────────────────────────────────


@router.get("/stats", summary="今日外卖汇总统计")
async def delivery_stats(
    request: Request,
    store_id: UUID = Query(..., description="门店 ID"),
    date_str: Optional[str] = Query(None, alias="date", description="日期 YYYY-MM-DD，默认今日"),
    db: AsyncSession = Depends(get_db),
):
    """
    今日外卖汇总：各平台订单数/营收/佣金/实收。
    """
    tenant_id_str = _get_tenant_id(request)
    log = logger.bind(tenant_id=tenant_id_str, store_id=str(store_id))
    try:
        tenant_id = UUID(tenant_id_str)
        target_date = date.fromisoformat(date_str) if date_str else date.today()

        stats = await DeliveryPanelService.get_daily_stats(
            tenant_id=tenant_id,
            store_id=store_id,
            target_date=target_date,
            db=db,
        )
        log.info("delivery_stats.ok", date=str(target_date))
        return {"ok": True, "data": stats}

    except HTTPException:
        raise
    except ValueError as exc:
        log.warning("delivery_stats.value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 最外层 HTTP 兜底
        log.error("delivery_stats.error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


# ─── 自动接单规则 ──────────────────────────────────────────────────────────────


@router.get("/auto-accept-rules", summary="查询自动接单规则")
async def get_auto_accept_rule(
    request: Request,
    store_id: UUID = Query(..., description="门店 ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询门店的自动接单规则配置"""
    tenant_id_str = _get_tenant_id(request)
    log = logger.bind(tenant_id=tenant_id_str, store_id=str(store_id))
    try:
        tenant_id = UUID(tenant_id_str)
        rule = await DeliveryPanelService.get_auto_accept_rule(
            store_id=store_id,
            tenant_id=tenant_id,
            db=db,
        )
        if rule is None:
            return {
                "ok": True,
                "data": None,
                "message": "未配置自动接单规则，默认不自动接单",
            }
        return {
            "ok": True,
            "data": {
                "id": str(rule.id),
                "store_id": str(rule.store_id),
                "is_enabled": rule.is_enabled,
                "business_hours_start": (
                    rule.business_hours_start.strftime("%H:%M") if rule.business_hours_start else None
                ),
                "business_hours_end": (rule.business_hours_end.strftime("%H:%M") if rule.business_hours_end else None),
                "max_concurrent_orders": rule.max_concurrent_orders,
                "excluded_platforms": rule.excluded_platforms or [],
                "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
            },
        }
    except HTTPException:
        raise
    except ValueError as exc:
        log.warning("auto_accept_rule.get_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 最外层 HTTP 兜底
        log.error("auto_accept_rule.get_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.put("/auto-accept-rules", summary="创建或更新自动接单规则")
async def upsert_auto_accept_rule(
    request: Request,
    store_id: UUID = Query(..., description="门店 ID"),
    body: AutoAcceptRuleRequest = ...,
    db: AsyncSession = Depends(get_db),
):
    """
    创建或更新门店自动接单规则（幂等，每门店唯一一条）。

    示例：
    {
      "is_enabled": true,
      "business_hours_start": "09:00",
      "business_hours_end": "22:00",
      "max_concurrent_orders": 15,
      "excluded_platforms": ["douyin"]
    }
    """
    tenant_id_str = _get_tenant_id(request)
    log = logger.bind(tenant_id=tenant_id_str, store_id=str(store_id))
    try:
        tenant_id = UUID(tenant_id_str)

        # 解析时间字符串
        def _parse_time(t_str: Optional[str]) -> Optional[time]:
            if not t_str:
                return None
            try:
                h, m = t_str.split(":")
                return time(int(h), int(m))
            except (ValueError, AttributeError) as exc:
                raise ValueError(f"时间格式错误，应为 HH:MM: {t_str}") from exc

        biz_start = _parse_time(body.business_hours_start)
        biz_end = _parse_time(body.business_hours_end)

        # 校验平台名合法性
        valid_platforms = {"meituan", "eleme", "douyin", "grabfood"}
        if body.excluded_platforms:
            invalid = set(body.excluded_platforms) - valid_platforms
            if invalid:
                raise HTTPException(
                    status_code=400,
                    detail=f"excluded_platforms 包含无效平台: {invalid}",
                )

        rule = await DeliveryPanelService.upsert_auto_accept_rule(
            tenant_id=tenant_id,
            store_id=store_id,
            is_enabled=body.is_enabled,
            business_hours_start=biz_start,
            business_hours_end=biz_end,
            max_concurrent_orders=body.max_concurrent_orders,
            excluded_platforms=body.excluded_platforms,
            db=db,
        )
        log.info("auto_accept_rule.upsert_ok", is_enabled=rule.is_enabled)
        return {
            "ok": True,
            "data": {
                "id": str(rule.id),
                "store_id": str(rule.store_id),
                "is_enabled": rule.is_enabled,
                "business_hours_start": (
                    rule.business_hours_start.strftime("%H:%M") if rule.business_hours_start else None
                ),
                "business_hours_end": (rule.business_hours_end.strftime("%H:%M") if rule.business_hours_end else None),
                "max_concurrent_orders": rule.max_concurrent_orders,
                "excluded_platforms": rule.excluded_platforms or [],
                "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
            },
        }
    except HTTPException:
        raise
    except ValueError as exc:
        log.warning("auto_accept_rule.upsert_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 最外层 HTTP 兜底
        log.error("auto_accept_rule.upsert_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")
