"""外卖平台闭环 — 菜单/估清双向同步 + 线上接单 (模块 2.4)

端点（prefix /api/v1/omni）：

  菜单推送：
    POST  /menu-push/{store_id}               将 POS 菜单推送到美团/饿了么/抖音（全部或指定平台）

  估清同步：
    POST  /sold-out-sync                      POS 沽清 → 平台下架
    POST  /sold-out-restore                   补货恢复 → 平台上架

  线上订单：
    GET   /online-orders                      待处理线上订单列表（含渠道标识）
    POST  /online-orders/{id}/accept          接单（emit ORDER.PAID + CHANNEL.ORDER_SYNCED，触发打印）
    POST  /online-orders/{id}/reject          拒单
    POST  /online-orders/{id}/refund          退单（emit INVENTORY.ADJUSTED + PAYMENT.REFUNDED）

设计原则：
  - 金额全部使用分（整数），不使用浮点
  - 事件旁路写入（asyncio.create_task），不阻塞业务响应
  - 适配器通过 delivery_factory.get_delivery_adapter() 获取，Mock 模式下不调真实 API
  - 三条硬约束检查点：接单时毛利底线检查占位（Agent 异步校验）
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.adapters.delivery_factory import get_delivery_adapter
from shared.adapters.delivery_platform_base import DeliveryPlatformError
from shared.events.src.emitter import emit_event
from shared.events.src.event_types import (
    ChannelEventType,
    InventoryEventType,
    OrderEventType,
    PaymentEventType,
)
from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/omni", tags=["omni-sync"])

SUPPORTED_PLATFORMS = ("meituan", "eleme", "douyin")
PLATFORM_LABELS: dict[str, str] = {
    "meituan": "美团外卖",
    "eleme": "饿了么",
    "douyin": "抖音外卖",
}


# ── 工具函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", request.headers.get("X-Tenant-Id", "")
    )
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _get_db(request: Request):
    tenant_id = _get_tenant_id(request)
    async for session in get_db_with_tenant(tenant_id):
        yield session


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=message)


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────


class MenuPushRequest(BaseModel):
    """菜单推送请求"""

    platforms: Optional[list[str]] = Field(
        default=None,
        description="目标平台列表，不传则推送到全部平台（meituan/eleme/douyin）",
    )
    dishes: list[dict] = Field(
        min_length=1,
        description="菜品列表，屯象统一格式：{dish_id, name, price_fen, category, is_available, ...}",
    )
    sync_mode: str = Field(
        default="incremental",
        pattern="^(full|incremental)$",
        description="同步模式：full=全量覆盖，incremental=增量更新",
    )


class SoldOutSyncRequest(BaseModel):
    """估清同步请求（POS 沽清 → 平台下架）"""

    store_id: str = Field(min_length=1, max_length=100)
    dish_id: str = Field(min_length=1, max_length=100, description="POS 内部菜品ID")
    dish_name: str = Field(min_length=1, max_length=200)
    platforms: Optional[list[str]] = Field(
        default=None,
        description="指定推送平台，不传则推送到全部已授权平台",
    )
    reason: Optional[str] = Field(default=None, max_length=200, description="沽清原因（可选）")


class SoldOutRestoreRequest(BaseModel):
    """估清恢复请求（补货 → 平台上架）"""

    store_id: str = Field(min_length=1, max_length=100)
    dish_id: str = Field(min_length=1, max_length=100)
    dish_name: str = Field(min_length=1, max_length=200)
    platforms: Optional[list[str]] = Field(default=None)


class AcceptOrderRequest(BaseModel):
    """接单请求"""

    estimated_minutes: int = Field(default=20, ge=1, le=120, description="预计出餐分钟数")
    trigger_print: bool = Field(default=True, description="是否触发厨房单打印（前端接收后执行）")


class RejectOrderRequest(BaseModel):
    """拒单请求"""

    reason_code: int = Field(
        default=1,
        description="拒单原因码：1=暂时无法接单，2=已打烊，3=食材不足，4=超出配送范围，9=其他",
    )
    reason_desc: Optional[str] = Field(default=None, max_length=200)


class RefundOrderRequest(BaseModel):
    """退单请求"""

    refund_amount_fen: int = Field(ge=0, description="退款金额（分），0=全额退款")
    reason: str = Field(min_length=1, max_length=200, description="退单原因")


# ── 1. 菜单推送 ───────────────────────────────────────────────────────────────


@router.post("/menu-push/{store_id}", summary="推送菜单到外卖平台（美团/饿了么/抖音）")
async def push_menu_to_platforms(
    store_id: str = Path(..., description="门店ID"),
    body: MenuPushRequest = ...,
    request: Request = ...,
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """将 POS 菜品数据推送到外卖平台。

    流程：
      1. 确定目标平台（全部 or 指定）
      2. 逐平台调用适配器 sync_menu()（Mock 模式返回模拟数据）
      3. 写入 delivery_menu_sync_tasks 任务记录
      4. 返回各平台同步结果
    """
    tenant_id = _get_tenant_id(request)
    target_platforms = body.platforms or list(SUPPORTED_PLATFORMS)

    # 校验平台标识
    invalid = [p for p in target_platforms if p not in SUPPORTED_PLATFORMS]
    if invalid:
        raise _err(f"不支持的平台: {invalid}，有效值: {list(SUPPORTED_PLATFORMS)}")

    results: list[dict] = []
    for platform in target_platforms:
        task_id = str(uuid.uuid4())
        platform_result: dict = {"synced": 0, "failed": 0, "errors": []}
        status = "pending"

        try:
            adapter = get_delivery_adapter(platform)
            platform_result = await adapter.sync_menu(store_id=store_id, dishes=body.dishes)
            status = "completed"
        except DeliveryPlatformError as exc:
            logger.error(
                "omni_sync.menu_push.platform_error",
                platform=platform,
                store_id=store_id,
                error=str(exc),
                exc_info=True,
            )
            platform_result["errors"].append(str(exc))
            status = "failed"
        except (ValueError, RuntimeError) as exc:
            logger.error(
                "omni_sync.menu_push.unexpected_error",
                platform=platform,
                store_id=store_id,
                error=str(exc),
                exc_info=True,
            )
            platform_result["errors"].append(str(exc))
            status = "failed"

        # 写任务记录
        try:
            await db.execute(
                text("""
                    INSERT INTO delivery_menu_sync_tasks
                        (id, tenant_id, store_id, platform, sync_mode, items_count,
                         items_snapshot, status, created_at)
                    VALUES
                        (:id, :tid, :sid, :platform, :mode, :cnt,
                         :items::jsonb, :status, :now)
                    ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": task_id,
                    "tid": tenant_id,
                    "sid": store_id,
                    "platform": platform,
                    "mode": body.sync_mode,
                    "cnt": len(body.dishes),
                    "items": "[]",
                    "status": status,
                    "now": _now(),
                },
            )
        except Exception as db_exc:  # noqa: BLE001  # 数据库写入失败不影响推送结果
            logger.warning(
                "omni_sync.menu_push.db_write_failed",
                task_id=task_id,
                error=str(db_exc),
                exc_info=True,
            )

        results.append(
            {
                "platform": platform,
                "platform_label": PLATFORM_LABELS[platform],
                "task_id": task_id,
                "status": status,
                "synced": platform_result.get("synced", 0),
                "failed": platform_result.get("failed", 0),
                "errors": platform_result.get("errors", []),
            }
        )

    await db.commit()

    logger.info(
        "omni_sync.menu_push.done",
        store_id=store_id,
        dish_count=len(body.dishes),
        platforms=target_platforms,
    )

    return _ok(
        {
            "store_id": store_id,
            "dish_count": len(body.dishes),
            "sync_mode": body.sync_mode,
            "platform_results": results,
            "pushed_at": _now().isoformat(),
        }
    )


# ── 2. 估清同步（POS 沽清 → 平台下架） ────────────────────────────────────────


@router.post("/sold-out-sync", summary="估清同步：POS 沽清 → 平台下架")
async def sync_sold_out(
    body: SoldOutSyncRequest,
    request: Request,
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """将 POS 沽清状态同步到外卖平台（标记菜品售罄/下架）。

    调用适配器 update_stock(store_id, dish_id, available=False)。
    写入 delivery_soldout_sync_log 日志表。
    """
    tenant_id = _get_tenant_id(request)
    target_platforms = body.platforms or list(SUPPORTED_PLATFORMS)

    invalid = [p for p in target_platforms if p not in SUPPORTED_PLATFORMS]
    if invalid:
        raise _err(f"不支持的平台: {invalid}")

    results: list[dict] = []
    for platform in target_platforms:
        success = False
        error_msg: Optional[str] = None
        try:
            adapter = get_delivery_adapter(platform)
            success = await adapter.update_stock(
                store_id=body.store_id,
                dish_id=body.dish_id,
                available=False,
            )
        except DeliveryPlatformError as exc:
            error_msg = str(exc)
            logger.error(
                "omni_sync.sold_out.platform_error",
                platform=platform,
                dish_id=body.dish_id,
                error=error_msg,
                exc_info=True,
            )
        except (ValueError, RuntimeError) as exc:
            error_msg = str(exc)
            logger.error(
                "omni_sync.sold_out.unexpected_error",
                platform=platform,
                dish_id=body.dish_id,
                error=error_msg,
                exc_info=True,
            )

        # 写日志
        log_id = str(uuid.uuid4())
        try:
            await db.execute(
                text("""
                    INSERT INTO delivery_soldout_sync_log
                        (id, tenant_id, store_id, platform, dish_id, dish_name,
                         action, reason, success, error_msg, synced_at)
                    VALUES
                        (:id, :tid, :sid, :platform, :dish_id, :dish_name,
                         'soldout', :reason, :success, :error_msg, :now)
                """),
                {
                    "id": log_id,
                    "tid": tenant_id,
                    "sid": body.store_id,
                    "platform": platform,
                    "dish_id": body.dish_id,
                    "dish_name": body.dish_name,
                    "reason": body.reason,
                    "success": success,
                    "error_msg": error_msg,
                    "now": _now(),
                },
            )
        except Exception as db_exc:  # noqa: BLE001
            logger.warning(
                "omni_sync.sold_out.db_write_failed",
                log_id=log_id,
                error=str(db_exc),
                exc_info=True,
            )

        results.append(
            {
                "platform": platform,
                "platform_label": PLATFORM_LABELS[platform],
                "success": success,
                "error": error_msg,
            }
        )

    await db.commit()

    logger.info(
        "omni_sync.sold_out.done",
        store_id=body.store_id,
        dish_id=body.dish_id,
        platforms=target_platforms,
    )

    return _ok(
        {
            "store_id": body.store_id,
            "dish_id": body.dish_id,
            "dish_name": body.dish_name,
            "action": "soldout",
            "platform_results": results,
            "synced_at": _now().isoformat(),
        }
    )


# ── 3. 估清恢复（补货 → 平台上架） ────────────────────────────────────────────


@router.post("/sold-out-restore", summary="估清恢复：补货 → 平台上架")
async def restore_sold_out(
    body: SoldOutRestoreRequest,
    request: Request,
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """补货后恢复外卖平台上架状态。

    调用适配器 update_stock(store_id, dish_id, available=True)。
    """
    tenant_id = _get_tenant_id(request)
    target_platforms = body.platforms or list(SUPPORTED_PLATFORMS)

    invalid = [p for p in target_platforms if p not in SUPPORTED_PLATFORMS]
    if invalid:
        raise _err(f"不支持的平台: {invalid}")

    results: list[dict] = []
    for platform in target_platforms:
        success = False
        error_msg: Optional[str] = None
        try:
            adapter = get_delivery_adapter(platform)
            success = await adapter.update_stock(
                store_id=body.store_id,
                dish_id=body.dish_id,
                available=True,
            )
        except DeliveryPlatformError as exc:
            error_msg = str(exc)
            logger.error(
                "omni_sync.restore.platform_error",
                platform=platform,
                dish_id=body.dish_id,
                error=error_msg,
                exc_info=True,
            )
        except (ValueError, RuntimeError) as exc:
            error_msg = str(exc)
            logger.error(
                "omni_sync.restore.unexpected_error",
                platform=platform,
                dish_id=body.dish_id,
                error=error_msg,
                exc_info=True,
            )

        # 写日志
        log_id = str(uuid.uuid4())
        try:
            await db.execute(
                text("""
                    INSERT INTO delivery_soldout_sync_log
                        (id, tenant_id, store_id, platform, dish_id, dish_name,
                         action, reason, success, error_msg, synced_at)
                    VALUES
                        (:id, :tid, :sid, :platform, :dish_id, :dish_name,
                         'restore', NULL, :success, :error_msg, :now)
                """),
                {
                    "id": log_id,
                    "tid": tenant_id,
                    "sid": body.store_id,
                    "platform": platform,
                    "dish_id": body.dish_id,
                    "dish_name": body.dish_name,
                    "success": success,
                    "error_msg": error_msg,
                    "now": _now(),
                },
            )
        except Exception as db_exc:  # noqa: BLE001
            logger.warning(
                "omni_sync.restore.db_write_failed",
                log_id=log_id,
                error=str(db_exc),
                exc_info=True,
            )

        results.append(
            {
                "platform": platform,
                "platform_label": PLATFORM_LABELS[platform],
                "success": success,
                "error": error_msg,
            }
        )

    await db.commit()

    logger.info(
        "omni_sync.restore.done",
        store_id=body.store_id,
        dish_id=body.dish_id,
        platforms=target_platforms,
    )

    return _ok(
        {
            "store_id": body.store_id,
            "dish_id": body.dish_id,
            "dish_name": body.dish_name,
            "action": "restore",
            "platform_results": results,
            "synced_at": _now().isoformat(),
        }
    )


# ── 4. 线上待处理订单列表 ─────────────────────────────────────────────────────


@router.get("/online-orders", summary="线上待处理订单列表（美团/饿了么/抖音）")
async def list_online_orders(
    store_id: str = Query(..., description="门店ID"),
    platform: Optional[str] = Query(None, description="平台筛选: meituan/eleme/douyin"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    request: Request = ...,
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """查询门店待处理线上订单（status = 'pending'）。

    从 aggregator_orders 表查询，包含渠道标识、菜品明细、金额。
    前端据此渲染接单面板。
    """
    tenant_id = _get_tenant_id(request)

    platform_filter = ""
    params: dict = {
        "tid": tenant_id,
        "sid": store_id,
        "status": "pending",
        "limit": size,
        "offset": (page - 1) * size,
    }

    if platform:
        if platform not in SUPPORTED_PLATFORMS:
            raise _err(f"不支持的平台: {platform}，有效值: {list(SUPPORTED_PLATFORMS)}")
        platform_filter = "AND platform_key = :platform"
        params["platform"] = platform

    # 查 aggregator_orders 表（外卖聚合订单）
    rows_result = await db.execute(
        text(f"""
            SELECT
                id::text AS order_id,
                platform_key AS platform,
                platform_order_id,
                status,
                total_fen,
                items_snapshot,
                customer_phone_masked AS customer_phone,
                delivery_address,
                notes,
                created_at
            FROM aggregator_orders
            WHERE tenant_id = :tid::uuid
              AND store_id = :sid
              AND status = :status
              {platform_filter}
            ORDER BY created_at ASC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )

    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    count_result = await db.execute(
        text(f"""
            SELECT COUNT(*)
            FROM aggregator_orders
            WHERE tenant_id = :tid::uuid
              AND store_id = :sid
              AND status = :status
              {platform_filter}
        """),
        count_params,
    )
    total: int = count_result.scalar() or 0

    import json as _json

    orders = []
    for row in rows_result.mappings():
        items_raw = row["items_snapshot"]
        if isinstance(items_raw, str):
            try:
                items = _json.loads(items_raw)
            except (ValueError, TypeError):
                items = []
        elif isinstance(items_raw, list):
            items = items_raw
        else:
            items = []

        orders.append(
            {
                "order_id": row["order_id"],
                "platform": row["platform"] or "",
                "platform_label": PLATFORM_LABELS.get(row["platform"] or "", row["platform"] or ""),
                "platform_order_id": row["platform_order_id"] or "",
                "status": row["status"],
                "total_fen": row["total_fen"] or 0,
                "items": items,
                "customer_phone": row["customer_phone"] or "",
                "delivery_address": row["delivery_address"] or "",
                "notes": row["notes"] or "",
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
        )

    return _ok(
        {
            "items": orders,
            "total": total,
            "page": page,
            "size": size,
        }
    )


# ── 5. 接单 ───────────────────────────────────────────────────────────────────


@router.post("/online-orders/{order_id}/accept", summary="接单（触发厨房单打印 + 发送事件）")
async def accept_online_order(
    order_id: str = Path(..., description="aggregator_orders 内部ID"),
    body: AcceptOrderRequest = ...,
    request: Request = ...,
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """接单处理流程：

    1. 查询订单，校验状态为 pending
    2. 更新 aggregator_orders.status = 'confirmed'
    3. 旁路写入事件：
       - OrderEventType.PAID（订单支付完成）
       - ChannelEventType.ORDER_SYNCED（渠道订单同步确认）
    4. 回调平台接单接口（适配器，Mock 模式无副作用）
    5. 返回打印数据（前端据此调用 window.TXBridge?.print() 或 HTTP fallback）
    """
    tenant_id = _get_tenant_id(request)

    # 查询订单
    row_result = await db.execute(
        text("""
            SELECT
                id::text AS order_id,
                platform_key AS platform,
                platform_order_id,
                store_id,
                total_fen,
                items_snapshot,
                customer_phone_masked,
                delivery_address,
                notes,
                status
            FROM aggregator_orders
            WHERE id = :oid::uuid
              AND tenant_id = :tid::uuid
        """),
        {"oid": order_id, "tid": tenant_id},
    )
    row = row_result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"订单不存在: {order_id}")
    if row["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"订单状态为 {row['status']}，无法接单（仅 pending 状态可接单）",
        )

    platform: str = row["platform"] or "meituan"
    store_id: str = str(row["store_id"])
    total_fen: int = int(row["total_fen"] or 0)

    # 更新状态
    await db.execute(
        text("""
            UPDATE aggregator_orders
            SET status = 'confirmed',
                accepted_at = :now,
                estimated_ready_minutes = :minutes
            WHERE id = :oid::uuid
        """),
        {"oid": order_id, "now": _now(), "minutes": body.estimated_minutes},
    )
    await db.commit()

    # 旁路事件（不阻塞接单响应）
    asyncio.create_task(
        emit_event(
            event_type=OrderEventType.PAID,
            tenant_id=tenant_id,
            stream_id=order_id,
            payload={
                "total_fen": total_fen,
                "channel": platform,
                "platform_order_id": row["platform_order_id"],
            },
            store_id=store_id,
            source_service="tx-trade",
            metadata={"trigger": "omni_sync.accept_order"},
        )
    )
    asyncio.create_task(
        emit_event(
            event_type=ChannelEventType.ORDER_SYNCED,
            tenant_id=tenant_id,
            stream_id=order_id,
            payload={
                "platform": platform,
                "platform_order_id": row["platform_order_id"],
                "total_fen": total_fen,
                "action": "accepted",
            },
            store_id=store_id,
            source_service="tx-trade",
            metadata={"estimated_minutes": body.estimated_minutes},
        )
    )

    # 回调平台接单接口（Mock 模式下无副作用）
    try:
        adapter = get_delivery_adapter(platform)
        await adapter.accept_order(order_id=row["platform_order_id"])
    except DeliveryPlatformError as exc:
        # 平台回调失败只记录日志，不影响内部接单结果
        logger.warning(
            "omni_sync.accept.platform_callback_failed",
            order_id=order_id,
            platform=platform,
            error=str(exc),
            exc_info=True,
        )
    except (ValueError, RuntimeError) as exc:
        logger.warning(
            "omni_sync.accept.unexpected_callback_error",
            order_id=order_id,
            error=str(exc),
            exc_info=True,
        )

    logger.info(
        "omni_sync.accept.ok",
        order_id=order_id,
        platform=platform,
        total_fen=total_fen,
    )

    # 打印数据（前端收到后调用 TXBridge.print() 或 HTTP 转发到安卓 POS）
    import json as _json

    items_raw = row["items_snapshot"]
    if isinstance(items_raw, str):
        try:
            items = _json.loads(items_raw)
        except (ValueError, TypeError):
            items = []
    elif isinstance(items_raw, list):
        items = items_raw
    else:
        items = []

    return _ok(
        {
            "order_id": order_id,
            "platform": platform,
            "platform_label": PLATFORM_LABELS.get(platform, platform),
            "platform_order_id": row["platform_order_id"],
            "status": "confirmed",
            "estimated_minutes": body.estimated_minutes,
            "trigger_print": body.trigger_print,
            "print_data": {
                "title": f"【{PLATFORM_LABELS.get(platform, platform)}】外卖单",
                "order_id": order_id,
                "platform_order_id": row["platform_order_id"],
                "total_fen": total_fen,
                "items": items,
                "notes": row["notes"] or "",
                "delivery_address": row["delivery_address"] or "",
                "customer_phone": row["customer_phone_masked"] or "",
                "accepted_at": _now().isoformat(),
            },
        }
    )


# ── 6. 拒单 ───────────────────────────────────────────────────────────────────


@router.post("/online-orders/{order_id}/reject", summary="拒单")
async def reject_online_order(
    order_id: str = Path(..., description="aggregator_orders 内部ID"),
    body: RejectOrderRequest = ...,
    request: Request = ...,
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """拒单处理：

    1. 校验订单状态为 pending
    2. 更新 aggregator_orders.status = 'rejected'
    3. 回调平台拒单接口（适配器）
    4. 返回拒单结果
    """
    tenant_id = _get_tenant_id(request)

    row_result = await db.execute(
        text("""
            SELECT id::text AS order_id, platform_key AS platform,
                   platform_order_id, status
            FROM aggregator_orders
            WHERE id = :oid::uuid AND tenant_id = :tid::uuid
        """),
        {"oid": order_id, "tid": tenant_id},
    )
    row = row_result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"订单不存在: {order_id}")
    if row["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"订单状态为 {row['status']}，无法拒单（仅 pending 状态可拒单）",
        )

    platform: str = row["platform"] or "meituan"

    await db.execute(
        text("""
            UPDATE aggregator_orders
            SET status = 'rejected',
                rejected_at = :now,
                reject_reason_code = :code,
                reject_reason_desc = :desc
            WHERE id = :oid::uuid
        """),
        {
            "oid": order_id,
            "now": _now(),
            "code": body.reason_code,
            "desc": body.reason_desc,
        },
    )
    await db.commit()

    # 回调平台拒单接口
    try:
        adapter = get_delivery_adapter(platform)
        await adapter.reject_order(
            order_id=row["platform_order_id"],
            reason=body.reason_desc or str(body.reason_code),
        )
    except DeliveryPlatformError as exc:
        logger.warning(
            "omni_sync.reject.platform_callback_failed",
            order_id=order_id,
            platform=platform,
            error=str(exc),
            exc_info=True,
        )
    except (ValueError, RuntimeError) as exc:
        logger.warning(
            "omni_sync.reject.unexpected_callback_error",
            order_id=order_id,
            error=str(exc),
            exc_info=True,
        )

    logger.info(
        "omni_sync.reject.ok",
        order_id=order_id,
        platform=platform,
        reason_code=body.reason_code,
    )

    return _ok(
        {
            "order_id": order_id,
            "platform": platform,
            "platform_label": PLATFORM_LABELS.get(platform, platform),
            "status": "rejected",
            "reason_code": body.reason_code,
            "reason_desc": body.reason_desc,
            "rejected_at": _now().isoformat(),
        }
    )


# ── 7. 退单 ───────────────────────────────────────────────────────────────────


@router.post("/online-orders/{order_id}/refund", summary="退单（库存回滚 + 财务冲红事件）")
async def refund_online_order(
    order_id: str = Path(..., description="aggregator_orders 内部ID"),
    body: RefundOrderRequest = ...,
    request: Request = ...,
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """退单处理：

    1. 校验订单状态为 confirmed/preparing
    2. 更新 aggregator_orders.status = 'refunded'
    3. 旁路写入事件：
       - InventoryEventType.ADJUSTED（库存回滚，食材重新入账）
       - PaymentEventType.REFUNDED（支付冲红）
    4. 返回退款结果
    """
    tenant_id = _get_tenant_id(request)

    row_result = await db.execute(
        text("""
            SELECT
                id::text AS order_id,
                platform_key AS platform,
                platform_order_id,
                store_id,
                total_fen,
                items_snapshot,
                status
            FROM aggregator_orders
            WHERE id = :oid::uuid AND tenant_id = :tid::uuid
        """),
        {"oid": order_id, "tid": tenant_id},
    )
    row = row_result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"订单不存在: {order_id}")

    refundable_statuses = ("pending", "confirmed", "preparing")
    if row["status"] not in refundable_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"订单状态为 {row['status']}，无法退单（可退单状态: {refundable_statuses}）",
        )

    platform: str = row["platform"] or "meituan"
    store_id: str = str(row["store_id"])
    total_fen: int = int(row["total_fen"] or 0)
    refund_fen: int = body.refund_amount_fen if body.refund_amount_fen > 0 else total_fen

    await db.execute(
        text("""
            UPDATE aggregator_orders
            SET status = 'refunded',
                refunded_at = :now,
                refund_amount_fen = :refund_fen,
                refund_reason = :reason
            WHERE id = :oid::uuid
        """),
        {
            "oid": order_id,
            "now": _now(),
            "refund_fen": refund_fen,
            "reason": body.reason,
        },
    )
    await db.commit()

    # 旁路事件：库存回滚（BOM 反向推算食材回账）
    asyncio.create_task(
        emit_event(
            event_type=InventoryEventType.ADJUSTED,
            tenant_id=tenant_id,
            stream_id=order_id,
            payload={
                "reason": "order_refund",
                "order_id": order_id,
                "platform": platform,
                "direction": "in",  # 食材回入库
                "items_snapshot": row["items_snapshot"],
            },
            store_id=store_id,
            source_service="tx-trade",
            metadata={"refund_reason": body.reason},
        )
    )

    # 旁路事件：支付冲红
    asyncio.create_task(
        emit_event(
            event_type=PaymentEventType.REFUNDED,
            tenant_id=tenant_id,
            stream_id=order_id,
            payload={
                "refund_amount_fen": refund_fen,
                "original_amount_fen": total_fen,
                "channel": platform,
                "platform_order_id": row["platform_order_id"],
                "reason": body.reason,
            },
            store_id=store_id,
            source_service="tx-trade",
            metadata={"trigger": "omni_sync.refund_order"},
        )
    )

    logger.info(
        "omni_sync.refund.ok",
        order_id=order_id,
        platform=platform,
        refund_fen=refund_fen,
        total_fen=total_fen,
    )

    return _ok(
        {
            "order_id": order_id,
            "platform": platform,
            "platform_label": PLATFORM_LABELS.get(platform, platform),
            "status": "refunded",
            "refund_amount_fen": refund_fen,
            "original_amount_fen": total_fen,
            "reason": body.reason,
            "refunded_at": _now().isoformat(),
        }
    )
