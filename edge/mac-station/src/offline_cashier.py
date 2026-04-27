"""
离线收银模块 — mac-station 断网优先写入

当云端 API 不可达时，POS 收银数据先写入本地 PostgreSQL，
sync-engine 恢复网络后自动回灌到云端。

关键特性：
- 本地 PG（由 LOCAL_DB_URL 环境变量配置）
- sync_status: pending / synced / conflict / voided
- idempotency_key 防重，云端已有同一 key 则标记 conflict，不覆盖
- 金额全部使用分（整数）
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from offline_db import local_db_dependency
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/offline", tags=["offline_cashier"])

# 云端 API 基础地址（用于 health 检测和冲突检查）
_CLOUD_API_URL = os.getenv("CLOUD_API_URL", "http://localhost:8001")
_HEALTH_TIMEOUT = 3.0


# ─── 模型定义 ─────────────────────────────────────────────────────────────────


class OfflineOrderItem(BaseModel):
    dish_id: str = Field(..., description="菜品 ID")
    dish_name: str = Field(..., description="菜品名称")
    quantity: int = Field(..., ge=1, description="数量")
    unit_price_fen: int = Field(..., ge=0, description="单价（分）")
    subtotal_fen: int = Field(..., ge=0, description="小计（分）")


class CreateOfflineOrderRequest(BaseModel):
    idempotency_key: str = Field(..., description="幂等键，防止断网重试导致重复下单（建议用 UUID）")
    store_id: str = Field(..., description="门店 ID")
    table_id: Optional[str] = Field(None, description="桌台 ID（堂食时必填）")
    terminal_id: str = Field(..., description="收银终端 ID")
    items: list[OfflineOrderItem] = Field(..., min_length=1, description="订单明细")
    total_amount_fen: int = Field(..., ge=0, description="订单总金额（分）")
    discount_fen: int = Field(0, ge=0, description="优惠金额（分）")
    actual_amount_fen: int = Field(..., ge=0, description="实收金额（分）")
    payment_method: str = Field("cash", description="支付方式: cash/alipay/wechat/card")
    cashier_id: Optional[str] = Field(None, description="收银员工 ID")
    remark: Optional[str] = Field(None, description="备注")

    @field_validator("payment_method")
    @classmethod
    def check_payment_method(cls, v: str) -> str:
        allowed = {"cash", "alipay", "wechat", "card", "member_card"}
        if v not in allowed:
            raise ValueError(f"payment_method 必须是: {', '.join(sorted(allowed))}")
        return v


class VoidOrderRequest(BaseModel):
    reason: str = Field(..., description="撤单原因")
    operator_id: str = Field(..., description="操作人员工 ID")


# ─── 内部工具 ─────────────────────────────────────────────────────────────────


async def _check_cloud_reachable() -> bool:
    """检查云端 API 是否可达（GET /health，超时 3s）"""
    try:
        async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
            resp = await client.get(f"{_CLOUD_API_URL}/health")
            return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException, OSError):
        return False


async def _get_pending_count(db: AsyncSession, store_id: str) -> int:
    """获取本地待同步订单数量"""
    result = await db.execute(
        text("""
            SELECT COUNT(*) AS cnt
            FROM offline_orders
            WHERE store_id = :sid
              AND sync_status = 'pending'
              AND is_deleted = FALSE
        """),
        {"sid": store_id},
    )
    row = result.fetchone()
    return int(row.cnt) if row else 0


# ─── 路由实现 ─────────────────────────────────────────────────────────────────


@router.get("/health", summary="检查网络状态与本地 DB 状态")
async def offline_health(
    store_id: str = Query(..., description="门店 ID"),
    db: AsyncSession = Depends(local_db_dependency),
) -> dict[str, Any]:
    """检查：
    - 云端 API 是否可达（online）
    - 本地待同步订单数（pending_sync_count）
    - 本地 DB 是否可用（local_db_ok）
    """
    online = await _check_cloud_reachable()

    try:
        pending = await _get_pending_count(db, store_id)
        local_db_ok = True
    except (OSError, RuntimeError) as exc:
        log.error("offline_health_db_error", error=str(exc), store_id=store_id)
        pending = -1
        local_db_ok = False

    log.info(
        "offline_health_checked",
        store_id=store_id,
        online=online,
        pending_sync_count=pending,
    )
    return {
        "ok": True,
        "data": {
            "online": online,
            "pending_sync_count": pending,
            "local_db_ok": local_db_ok,
            "store_id": store_id,
        },
    }


@router.post("/orders", summary="离线下单（写本地 PG）", status_code=201)
async def create_offline_order(
    body: CreateOfflineOrderRequest,
    db: AsyncSession = Depends(local_db_dependency),
) -> dict[str, Any]:
    """离线状态下提交订单到本地 PG。

    - sync_status 初始为 'pending'
    - 相同 idempotency_key 直接返回已有记录，保证幂等
    - 明细以 JSONB 存储，sync-engine 回灌时展开
    """
    import json

    # 幂等检查：相同 idempotency_key 直接返回
    existing = await db.execute(
        text("""
            SELECT id, order_no, sync_status, created_at
            FROM offline_orders
            WHERE idempotency_key = :key AND store_id = :sid
        """),
        {"key": body.idempotency_key, "sid": body.store_id},
    )
    row = existing.fetchone()
    if row:
        log.info(
            "offline_order_idempotent_hit",
            idempotency_key=body.idempotency_key,
            order_id=str(row.id),
        )
        return {
            "ok": True,
            "data": {
                "order_id": str(row.id),
                "order_no": row.order_no,
                "sync_status": row.sync_status,
                "idempotent": True,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            },
        }

    order_id = uuid.uuid4()
    order_no = f"OFF-{body.store_id[:4].upper()}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{str(order_id)[:8].upper()}"
    now = datetime.now(timezone.utc)
    items_json = json.dumps([it.model_dump() for it in body.items], ensure_ascii=False)

    await db.execute(
        text("""
            INSERT INTO offline_orders (
                id, idempotency_key, order_no, store_id, table_id,
                terminal_id, items, total_amount_fen, discount_fen,
                actual_amount_fen, payment_method, cashier_id,
                remark, sync_status, is_deleted, created_at, updated_at
            ) VALUES (
                :id, :ikey, :order_no, :sid, :table_id,
                :terminal_id, :items::jsonb, :total, :discount,
                :actual, :payment, :cashier,
                :remark, 'pending', FALSE, :now, :now
            )
        """),
        {
            "id": order_id,
            "ikey": body.idempotency_key,
            "order_no": order_no,
            "sid": body.store_id,
            "table_id": body.table_id,
            "terminal_id": body.terminal_id,
            "items": items_json,
            "total": body.total_amount_fen,
            "discount": body.discount_fen,
            "actual": body.actual_amount_fen,
            "payment": body.payment_method,
            "cashier": body.cashier_id,
            "remark": body.remark,
            "now": now,
        },
    )
    await db.commit()

    log.info(
        "offline_order_created",
        order_id=str(order_id),
        order_no=order_no,
        store_id=body.store_id,
        total_amount_fen=body.total_amount_fen,
        sync_status="pending",
    )
    return {
        "ok": True,
        "data": {
            "order_id": str(order_id),
            "order_no": order_no,
            "sync_status": "pending",
            "idempotent": False,
            "created_at": now.isoformat(),
        },
    }


@router.get("/orders", summary="查询本地待同步订单")
async def list_offline_orders(
    store_id: str = Query(..., description="门店 ID"),
    sync_status: str = Query("pending", description="同步状态: pending/synced/conflict/voided"),
    limit: int = Query(50, ge=1, le=200, description="最多返回条数"),
    db: AsyncSession = Depends(local_db_dependency),
) -> dict[str, Any]:
    """查询本地 PG 中指定同步状态的离线订单。

    sync_status:
      - pending  — 待同步到云端
      - synced   — 已成功同步
      - conflict — 云端已有同一 idempotency_key，需人工处理
      - voided   — 已撤单
    """
    allowed_statuses = {"pending", "synced", "conflict", "voided"}
    if sync_status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"sync_status 必须是: {', '.join(sorted(allowed_statuses))}",
        )

    result = await db.execute(
        text("""
            SELECT id, order_no, idempotency_key, store_id, table_id,
                   terminal_id, total_amount_fen, actual_amount_fen,
                   payment_method, sync_status, created_at, updated_at
            FROM offline_orders
            WHERE store_id = :sid
              AND sync_status = :status
              AND is_deleted = FALSE
            ORDER BY created_at DESC
            LIMIT :lim
        """),
        {"sid": store_id, "status": sync_status, "lim": limit},
    )
    rows = result.fetchall()
    orders = [
        {
            "order_id": str(r.id),
            "order_no": r.order_no,
            "idempotency_key": r.idempotency_key,
            "store_id": r.store_id,
            "table_id": r.table_id,
            "terminal_id": r.terminal_id,
            "total_amount_fen": r.total_amount_fen,
            "actual_amount_fen": r.actual_amount_fen,
            "payment_method": r.payment_method,
            "sync_status": r.sync_status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]

    log.info(
        "offline_orders_listed",
        store_id=store_id,
        sync_status=sync_status,
        count=len(orders),
    )
    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "sync_status": sync_status,
            "orders": orders,
            "total": len(orders),
            "source": "local_pg",
        },
    }


@router.post("/orders/{order_id}/void", summary="撤单（仅本地，不推送云端）")
async def void_offline_order(
    order_id: str = Path(..., description="本地订单 ID"),
    body: VoidOrderRequest = ...,
    db: AsyncSession = Depends(local_db_dependency),
) -> dict[str, Any]:
    """撤销本地离线订单。

    - 只能撤销 sync_status='pending' 的订单（已同步的订单需在云端撤单）
    - 撤单后 sync_status 变为 'voided'，sync-engine 跳过该订单
    """
    result = await db.execute(
        text("""
            SELECT id, order_no, sync_status, store_id
            FROM offline_orders
            WHERE id = :oid AND is_deleted = FALSE
        """),
        {"oid": uuid.UUID(order_id)},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"离线订单 {order_id} 不存在")

    if row.sync_status not in ("pending",):
        raise HTTPException(
            status_code=400,
            detail=f"只能撤销 pending 状态的订单，当前状态: {row.sync_status}",
        )

    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            UPDATE offline_orders
            SET sync_status = 'voided',
                remark = COALESCE(remark, '') || ' [撤单: ' || :reason || ']',
                updated_at = :now
            WHERE id = :oid
        """),
        {"oid": uuid.UUID(order_id), "reason": body.reason, "now": now},
    )
    await db.commit()

    log.info(
        "offline_order_voided",
        order_id=order_id,
        order_no=row.order_no,
        store_id=row.store_id,
        operator_id=body.operator_id,
        reason=body.reason,
    )
    return {
        "ok": True,
        "data": {
            "order_id": order_id,
            "order_no": row.order_no,
            "sync_status": "voided",
            "voided_at": now.isoformat(),
        },
    }


@router.get("/sync-status", summary="同步队列统计")
async def get_sync_status(
    store_id: str = Query(..., description="门店 ID"),
    db: AsyncSession = Depends(local_db_dependency),
) -> dict[str, Any]:
    """返回本地离线订单各同步状态的数量统计。

    供 POS 显示"待同步 N 笔"提示，以及 sync-engine 监控使用。
    """
    result = await db.execute(
        text("""
            SELECT sync_status, COUNT(*) AS cnt
            FROM offline_orders
            WHERE store_id = :sid AND is_deleted = FALSE
            GROUP BY sync_status
        """),
        {"sid": store_id},
    )
    counts = {r.sync_status: int(r.cnt) for r in result.fetchall()}

    online = await _check_cloud_reachable()

    log.info("offline_sync_status_queried", store_id=store_id, counts=counts, online=online)
    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "online": online,
            "pending": counts.get("pending", 0),
            "synced": counts.get("synced", 0),
            "conflict": counts.get("conflict", 0),
            "voided": counts.get("voided", 0),
            "total_local": sum(counts.values()),
        },
    }
