"""外卖平台聚合 API 路由

Webhook 接收（外卖平台推送）：
  POST /api/v1/delivery/webhook/meituan    美团订单推送
  POST /api/v1/delivery/webhook/eleme      饿了么订单推送
  POST /api/v1/delivery/webhook/douyin     抖音订单推送

订单管理：
  GET  /api/v1/delivery/orders             外卖订单列表（支持平台/状态筛选）
  GET  /api/v1/delivery/orders/{id}        订单详情
  POST /api/v1/delivery/orders/{id}/confirm 确认接单
  POST /api/v1/delivery/orders/{id}/reject  拒单

数据统计：
  GET  /api/v1/delivery/stats/daily        日统计（各平台汇总）
  GET  /api/v1/delivery/stats/commission   佣金分析

平台配置：
  GET  /api/v1/delivery/platforms          平台配置列表
  POST /api/v1/delivery/platforms          添加平台配置
  PUT  /api/v1/delivery/platforms/{id}     更新配置（费率等）
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..services.delivery_aggregator import DeliveryAggregator

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/delivery", tags=["delivery"])

_aggregator = DeliveryAggregator()

# ─────────────────────────────────────────────────────────────────
# Pydantic 请求/响应模型
# ─────────────────────────────────────────────────────────────────


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200, description="拒单原因")


class PlatformConfigCreate(BaseModel):
    store_id: UUID
    platform: str = Field(..., pattern="^(meituan|eleme|douyin)$")
    app_id: str = Field(..., min_length=1, max_length=100)
    app_secret: str = Field(..., min_length=1)
    shop_id: str = Field(..., min_length=1, max_length=100)
    commission_rate: float = Field(default=0.18, ge=0.0, le=1.0,
                                   description="佣金费率，如 0.18 表示 18%")


class PlatformConfigUpdate(BaseModel):
    commission_rate: Optional[float] = Field(None, ge=0.0, le=1.0)
    is_active: Optional[bool] = None
    app_secret: Optional[str] = Field(None, min_length=1)
    shop_id: Optional[str] = Field(None, min_length=1, max_length=100)


# ─────────────────────────────────────────────────────────────────
# Webhook：外卖平台订单推送
# ─────────────────────────────────────────────────────────────────

async def _handle_webhook(
    platform: str,
    request: Request,
    x_tenant_id: str,
) -> dict:
    """
    通用 Webhook 处理逻辑：
      1. 读取原始 body（用于签名验证）
      2. 解析 JSON
      3. 从 delivery_platform_configs 查出配置（app_id/secret/commission_rate）
      4. 调用 DeliveryAggregator.receive_order
      5. 返回平台要求的确认响应

    注意：生产环境需在此处注入 db_session（通过 FastAPI Depends）。
    签名验证：各平台签名在不同 Header 中传递：
      美团：X-Meituan-Signature
      饿了么：X-Eleme-Hmac
      抖音：X-Douyin-Signature
    """
    log = logger.bind(platform=platform, tenant_id=x_tenant_id)

    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="缺少 X-Tenant-ID")

    try:
        raw_body: bytes = await request.body()
        payload: dict = await request.json()
    except (ValueError, KeyError, UnicodeDecodeError) as exc:  # MLPS3-P0: 异常收窄
        log.warning("delivery_webhook_parse_body_failed", error=str(exc))
        raise HTTPException(status_code=400, detail="请求体解析失败") from exc

    # 生产环境：
    #   1. 从 delivery_platform_configs 查出该平台配置
    #   2. 验证签名：adapter.verify_signature(raw_body, signature_header)
    #   3. 如签名不通过 → return {"code": 1, "msg": "签名校验失败"}（各平台有不同错误协议）
    #   4. 调用 _aggregator.receive_order(platform, payload, tenant_id, ...)

    log.info("delivery_webhook_received",
             platform=platform,
             body_size=len(raw_body),
             note="生产环境需查询配置、验证签名、写入DB")

    # 骨架响应（各平台均接受此格式，生产环境按平台要求调整）
    return {"ok": True, "data": {"platform": platform, "status": "received"}}


@router.post("/webhook/meituan", summary="美团外卖订单推送")
async def webhook_meituan(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """
    接收美团外卖 Webhook 推送。

    美团签名：Header X-Meituan-Signature，算法见 MeituanAdapter.verify_signature。
    美团要求返回：{"data": "success", "message": "ok", "status": 0}
    """
    try:
        result = await _handle_webhook("meituan", request, x_tenant_id)
        # 美团要求特定响应格式
        return {"data": "success", "message": "ok", "status": 0}
    except HTTPException:
        raise
    except ValueError as exc:
        logger.warning("webhook_meituan_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        logger.error("webhook_meituan_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/webhook/eleme", summary="饿了么外卖订单推送")
async def webhook_eleme(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """
    接收饿了么外卖 Webhook 推送。

    饿了么签名：Header X-Eleme-Hmac，算法见 ElemeAdapter.verify_signature。
    饿了么要求返回：{"code": 0, "message": "ok"}
    """
    try:
        await _handle_webhook("eleme", request, x_tenant_id)
        return {"code": 0, "message": "ok"}
    except HTTPException:
        raise
    except ValueError as exc:
        logger.warning("webhook_eleme_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        logger.error("webhook_eleme_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/webhook/douyin", summary="抖音外卖/团购订单推送")
async def webhook_douyin(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """
    接收抖音外卖/团购 Webhook 推送。

    抖音签名：Header X-Douyin-Signature，算法见 DouyinAdapter.verify_signature。
    抖音要求返回：{"err_no": 0, "err_tips": "success"}
    """
    try:
        await _handle_webhook("douyin", request, x_tenant_id)
        return {"err_no": 0, "err_tips": "success"}
    except HTTPException:
        raise
    except ValueError as exc:
        logger.warning("webhook_douyin_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        logger.error("webhook_douyin_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


# ─────────────────────────────────────────────────────────────────
# 订单管理
# ─────────────────────────────────────────────────────────────────

@router.get("/orders", summary="外卖订单列表")
async def list_delivery_orders(
    platform: Optional[str] = Query(None, pattern="^(meituan|eleme|douyin)$",
                                    description="按平台筛选"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    store_id: Optional[UUID] = Query(None, description="按门店筛选"),
    date_str: Optional[str] = Query(None, alias="date",
                                    description="日期筛选 YYYY-MM-DD"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """
    查询外卖订单列表，支持多维度筛选。

    生产环境：
      SELECT * FROM delivery_orders
      WHERE tenant_id = :tenant_id
        AND (:platform IS NULL OR platform = :platform)
        AND (:status IS NULL OR status = :status)
        AND (:store_id IS NULL OR store_id = :store_id)
        AND (:date IS NULL OR created_at::date = :date)
        AND is_deleted = FALSE
      ORDER BY created_at DESC
      LIMIT :size OFFSET (:page-1)*:size
    """
    log = logger.bind(
        tenant_id=x_tenant_id,
        platform=platform,
        status=status,
        page=page,
        size=size,
    )
    try:
        if not x_tenant_id:
            raise HTTPException(status_code=400, detail="缺少 X-Tenant-ID")

        log.info("delivery_list_orders", note="生产环境需查询 delivery_orders 表")
        # 骨架响应
        return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size}}

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("delivery_list_orders_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.get("/orders/{order_id}", summary="外卖订单详情")
async def get_delivery_order(
    order_id: UUID,
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """查询单条外卖订单详情（含原始 payload）"""
    log = logger.bind(order_id=str(order_id), tenant_id=x_tenant_id)
    try:
        if not x_tenant_id:
            raise HTTPException(status_code=400, detail="缺少 X-Tenant-ID")

        log.info("delivery_get_order", note="生产环境需查询 delivery_orders 表")
        # 生产环境：order = await DeliveryOrderRepository.get(db, order_id, tenant_id)
        # if not order: raise HTTPException(404, "订单不存在")
        raise HTTPException(status_code=404, detail="订单不存在（骨架实现）")

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("delivery_get_order_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/orders/{order_id}/confirm", summary="确认接单")
async def confirm_delivery_order(
    order_id: UUID,
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """
    确认接单：
      1. 更新 delivery_orders.status = 'confirmed'
      2. 调用对应平台 API 通知已接单
    """
    log = logger.bind(order_id=str(order_id), tenant_id=x_tenant_id)
    try:
        if not x_tenant_id:
            raise HTTPException(status_code=400, detail="缺少 X-Tenant-ID")

        ok = await _aggregator.confirm_order(order_id, db_session=None)
        log.info("delivery_confirm_ok", order_id=str(order_id))
        return {"ok": ok, "data": {"order_id": str(order_id), "status": "confirmed"}}

    except HTTPException:
        raise
    except ValueError as exc:
        log.warning("delivery_confirm_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("delivery_confirm_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/orders/{order_id}/reject", summary="拒单")
async def reject_delivery_order(
    order_id: UUID,
    body: RejectRequest,
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """
    拒单：
      1. 更新 delivery_orders.status = 'rejected'，记录 reject_reason
      2. 调用对应平台 API 通知拒单
    """
    log = logger.bind(order_id=str(order_id), tenant_id=x_tenant_id, reason=body.reason)
    try:
        if not x_tenant_id:
            raise HTTPException(status_code=400, detail="缺少 X-Tenant-ID")

        ok = await _aggregator.reject_order(order_id, body.reason, db_session=None)
        log.info("delivery_reject_ok", order_id=str(order_id))
        return {"ok": ok, "data": {"order_id": str(order_id), "status": "rejected"}}

    except HTTPException:
        raise
    except ValueError as exc:
        log.warning("delivery_reject_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("delivery_reject_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


# ─────────────────────────────────────────────────────────────────
# 数据统计
# ─────────────────────────────────────────────────────────────────

@router.get("/stats/daily", summary="外卖日统计（各平台汇总）")
async def delivery_daily_stats(
    store_id: UUID = Query(..., description="门店 ID"),
    date_str: Optional[str] = Query(
        None, alias="date", description="日期 YYYY-MM-DD，默认今日"
    ),
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """
    返回指定门店指定日期的外卖统计：
      - 各平台：订单数/营收/佣金/实收
      - 全平台汇总
      - 有效费率（实际佣金 / 营收）
    """
    log = logger.bind(tenant_id=x_tenant_id, store_id=str(store_id), date=date_str)
    try:
        if not x_tenant_id:
            raise HTTPException(status_code=400, detail="缺少 X-Tenant-ID")

        target_date = date.fromisoformat(date_str) if date_str else date.today()
        tenant_uuid = UUID(x_tenant_id)

        stats = await _aggregator.get_daily_stats(
            tenant_id=tenant_uuid,
            store_id=store_id,
            target_date=target_date,
            db_session=None,
        )
        log.info("delivery_daily_stats_ok")
        return {"ok": True, "data": stats.model_dump()}

    except HTTPException:
        raise
    except ValueError as exc:
        log.warning("delivery_daily_stats_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("delivery_daily_stats_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.get("/stats/commission", summary="佣金分析")
async def delivery_commission_stats(
    store_id: UUID = Query(..., description="门店 ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """
    区间佣金分析：
      - 各平台按日趋势（order_count/revenue/commission）
      - 平台佣金费率趋势（用于谈判参考）

    生产环境：
      SELECT
        platform, created_at::date AS day,
        COUNT(*) AS order_count,
        SUM(total_fen) AS revenue_fen,
        SUM(commission_fen) AS commission_fen
      FROM delivery_orders
      WHERE tenant_id = :tenant_id AND store_id = :store_id
        AND created_at::date BETWEEN :start AND :end
        AND status NOT IN ('cancelled', 'rejected')
        AND is_deleted = FALSE
      GROUP BY platform, day
      ORDER BY platform, day
    """
    log = logger.bind(
        tenant_id=x_tenant_id,
        store_id=str(store_id),
        start=start_date,
        end=end_date,
    )
    try:
        if not x_tenant_id:
            raise HTTPException(status_code=400, detail="缺少 X-Tenant-ID")

        # 校验日期格式
        date.fromisoformat(start_date)
        date.fromisoformat(end_date)

        log.info("delivery_commission_stats", note="生产环境需查询 delivery_orders 聚合")
        return {
            "ok": True,
            "data": {
                "store_id": str(store_id),
                "start_date": start_date,
                "end_date": end_date,
                "platforms": [],
            },
        }

    except HTTPException:
        raise
    except ValueError as exc:
        log.warning("delivery_commission_stats_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=f"日期格式错误: {exc}")
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("delivery_commission_stats_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


# ─────────────────────────────────────────────────────────────────
# 平台配置管理
# ─────────────────────────────────────────────────────────────────

@router.get("/platforms", summary="平台配置列表")
async def list_platform_configs(
    store_id: Optional[UUID] = Query(None, description="按门店筛选"),
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """
    查询租户下的外卖平台配置列表。
    注意：响应中不返回 app_secret 明文（仅返回 app_id/shop_id/commission_rate/is_active）。
    """
    log = logger.bind(tenant_id=x_tenant_id, store_id=str(store_id) if store_id else None)
    try:
        if not x_tenant_id:
            raise HTTPException(status_code=400, detail="缺少 X-Tenant-ID")

        log.info("delivery_list_platforms", note="生产环境需查询 delivery_platform_configs 表")
        return {"ok": True, "data": {"items": [], "total": 0}}

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("delivery_list_platforms_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/platforms", summary="添加平台配置", status_code=201)
async def create_platform_config(
    body: PlatformConfigCreate,
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """
    添加外卖平台接入配置。

    安全要求：
      - app_secret 写入前必须使用 AES-256 加密（密钥来自环境变量 DELIVERY_SECRET_KEY）
      - 响应中不返回 app_secret 明文
    """
    log = logger.bind(
        tenant_id=x_tenant_id,
        store_id=str(body.store_id),
        platform=body.platform,
    )
    try:
        if not x_tenant_id:
            raise HTTPException(status_code=400, detail="缺少 X-Tenant-ID")

        config_id = str(uuid.uuid4())
        log.info("delivery_create_platform_config",
                 config_id=config_id,
                 note="生产环境需加密 app_secret 后写入 delivery_platform_configs")

        return {
            "ok": True,
            "data": {
                "id": config_id,
                "tenant_id": x_tenant_id,
                "store_id": str(body.store_id),
                "platform": body.platform,
                "app_id": body.app_id,
                "shop_id": body.shop_id,
                "commission_rate": body.commission_rate,
                "is_active": True,
            },
        }

    except HTTPException:
        raise
    except ValueError as exc:
        log.warning("delivery_create_platform_config_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("delivery_create_platform_config_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.put("/platforms/{config_id}", summary="更新平台配置")
async def update_platform_config(
    config_id: UUID,
    body: PlatformConfigUpdate,
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """
    更新平台配置（佣金费率/启用状态/密钥/店铺ID）。

    - commission_rate 更新后影响后续新订单的佣金计算
    - app_secret 更新时同样需要 AES-256 加密后存储
    """
    log = logger.bind(config_id=str(config_id), tenant_id=x_tenant_id)
    try:
        if not x_tenant_id:
            raise HTTPException(status_code=400, detail="缺少 X-Tenant-ID")

        if body.model_dump(exclude_none=True) == {}:
            raise HTTPException(status_code=400, detail="未提供任何更新字段")

        log.info("delivery_update_platform_config",
                 update_fields=list(body.model_dump(exclude_none=True).keys()),
                 note="生产环境需更新 delivery_platform_configs 表")

        return {
            "ok": True,
            "data": {
                "id": str(config_id),
                "updated_fields": list(body.model_dump(exclude_none=True).keys()),
            },
        }

    except HTTPException:
        raise
    except ValueError as exc:
        log.warning("delivery_update_platform_config_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("delivery_update_platform_config_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")
