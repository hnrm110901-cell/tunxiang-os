"""自提渠道 API — 线上下单 → 备餐 → 取餐码叫号 → 顾客确认取货

业务流程：
  1. 顾客在小程序/H5下单（order_type=self_pickup）→ 立即支付 → 返回 pickup_code
  2. KDS 出品完成 → 所有任务 done → 回填 pickup_ready_at → 推送叫号
  3. 门店员工扫码 / 顾客在屏幕上确认取货 → 写入 pickup_confirmed_at

差异于外卖（delivery）：
  - 无骑手，顾客自己到店
  - 无配送费，无平台佣金
  - 须有取餐码显示屏或叫号系统

四个端点：
  POST /self-pickup/orders        — 创建自提单（生成 pickup_code）
  GET  /self-pickup/queue         — 门店自提排队大板
  POST /self-pickup/{id}/ready    — 标记备餐完成（KDS 回调）
  POST /self-pickup/{id}/confirm  — 顾客确认取货
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/self-pickup", tags=["self-pickup"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return str(tid)


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> HTTPException:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _gen_pickup_code(length: int = 4) -> str:
    """生成数字取餐码（4位，当日门店唯一由数据库唯一索引保证）"""
    return "".join(random.choices(string.digits, k=length))


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class CreateSelfPickupOrderReq(BaseModel):
    store_id: uuid.UUID
    customer_id: Optional[uuid.UUID] = None
    items: list[dict] = Field(..., description="[{dish_id, qty, price_fen, name}]")
    total_amount_fen: int = Field(..., ge=1)
    pickup_channel: str = Field(
        "miniapp",
        description="渠道来源：miniapp/h5/wechat/store",
    )
    notes: Optional[str] = None


class MarkReadyReq(BaseModel):
    operator_id: Optional[uuid.UUID] = None


class ConfirmPickupReq(BaseModel):
    confirmed_by: Optional[uuid.UUID] = Field(None, description="员工ID（扫码确认时填写）")


# ─── 端点 ─────────────────────────────────────────────────────────────────────


@router.post("/orders", summary="创建自提单")
async def create_self_pickup_order(
    body: CreateSelfPickupOrderReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建自提单，生成唯一取餐码。

    - 订单类型固定为 self_pickup
    - 先付模式：调用方须在创建前完成支付（或同步调用微信支付接口）
    - 返回 order_id + pickup_code 用于小程序显示和叫号系统
    """
    tid = _get_tenant_id(request)
    now = _now_utc()

    # 生成唯一取餐码（重试3次）
    pickup_code: Optional[str] = None
    for _ in range(3):
        candidate = _gen_pickup_code()
        conflict = await db.execute(
            text("""
                SELECT id FROM orders
                WHERE store_id = :store_id
                  AND pickup_code = :code
                  AND DATE(created_at AT TIME ZONE 'UTC') = CURRENT_DATE
                  AND is_deleted = false
                LIMIT 1
            """),
            {"store_id": body.store_id, "code": candidate},
        )
        if conflict.one_or_none() is None:
            pickup_code = candidate
            break

    if pickup_code is None:
        return _err("取餐码生成失败，请重试", code=503)

    order_no = f"SP{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"
    order_id = uuid.uuid4()

    await db.execute(
        text("""
            INSERT INTO orders (
                id, tenant_id, store_id, order_no, order_type,
                customer_id, status, total_amount_fen, discount_amount_fen,
                final_amount_fen, notes, pickup_code, pickup_channel,
                sales_channel, created_at, updated_at, is_deleted
            ) VALUES (
                :id, :tenant_id, :store_id, :order_no, 'self_pickup',
                :customer_id, 'paid', :total_amount_fen, 0,
                :total_amount_fen, :notes, :pickup_code, :pickup_channel,
                'self_pickup', :now, :now, FALSE
            )
        """),
        {
            "id": order_id,
            "tenant_id": tid,
            "store_id": body.store_id,
            "order_no": order_no,
            "customer_id": body.customer_id,
            "total_amount_fen": body.total_amount_fen,
            "notes": body.notes,
            "pickup_code": pickup_code,
            "pickup_channel": body.pickup_channel,
            "now": now,
        },
    )
    await db.commit()

    return _ok({
        "order_id": str(order_id),
        "order_no": order_no,
        "pickup_code": pickup_code,
        "status": "paid",
        "total_amount_fen": body.total_amount_fen,
        "pickup_channel": body.pickup_channel,
        "created_at": now.isoformat(),
    })


@router.get("/queue", summary="门店自提排队大板")
async def get_pickup_queue(
    store_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    include_confirmed: bool = Query(False, description="是否包含已取货订单"),
) -> dict:
    """自提排队大板：显示当日所有自提单，区分备餐中/已备好/已取货。

    前端用于：
    - KDS 旁边的叫号显示屏
    - 收银台管理页面
    - 顾客小程序查询进度
    """
    tid = _get_tenant_id(request)

    where_clause = (
        "AND pickup_confirmed_at IS NOT NULL" if include_confirmed
        else "AND pickup_confirmed_at IS NULL"
    )

    result = await db.execute(
        text(f"""
            SELECT
                id, order_no, pickup_code, pickup_channel,
                total_amount_fen, status, notes,
                pickup_ready_at, pickup_confirmed_at, created_at,
                CASE
                    WHEN pickup_confirmed_at IS NOT NULL THEN 'confirmed'
                    WHEN pickup_ready_at IS NOT NULL THEN 'ready'
                    ELSE 'preparing'
                END AS pickup_status
            FROM orders
            WHERE tenant_id = :tenant_id
              AND store_id  = :store_id
              AND order_type = 'self_pickup'
              AND DATE(created_at AT TIME ZONE 'UTC') = CURRENT_DATE
              AND is_deleted = false
              {where_clause}
            ORDER BY
                CASE WHEN pickup_ready_at IS NOT NULL AND pickup_confirmed_at IS NULL THEN 0 ELSE 1 END,
                created_at ASC
        """),
        {"tenant_id": tid, "store_id": store_id},
    )
    rows = [dict(r) for r in result.mappings()]

    # 统计
    preparing = sum(1 for r in rows if r["pickup_status"] == "preparing")
    ready = sum(1 for r in rows if r["pickup_status"] == "ready")
    confirmed = sum(1 for r in rows if r["pickup_status"] == "confirmed")

    return _ok({
        "orders": rows,
        "summary": {"preparing": preparing, "ready": ready, "confirmed": confirmed},
    })


@router.post("/{order_id}/ready", summary="标记备餐完成（KDS 回调）")
async def mark_ready(
    order_id: uuid.UUID,
    body: MarkReadyReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """KDS 所有任务 done 后调用，填写 pickup_ready_at，触发叫号推送。

    通常由 kds_actions.finish_cooking() 在最后一道菜完成时自动触发。
    也可由员工手动标记（如部分菜品无需KDS制作）。
    """
    tid = _get_tenant_id(request)
    now = _now_utc()

    result = await db.execute(
        text("""
            UPDATE orders
            SET pickup_ready_at = :now, updated_at = :now
            WHERE id = :order_id
              AND tenant_id = :tenant_id
              AND order_type = 'self_pickup'
              AND pickup_ready_at IS NULL
              AND is_deleted = false
            RETURNING id, order_no, pickup_code
        """),
        {"now": now, "order_id": order_id, "tenant_id": tid},
    )
    row = result.mappings().one_or_none()
    if row is None:
        _err("自提单不存在或已标记备餐完成", code=404)

    # TODO: 触发叫号推送（WebSocket → 叫号屏 + 顾客小程序通知）

    return _ok({
        "order_id": str(order_id),
        "order_no": row["order_no"],
        "pickup_code": row["pickup_code"],
        "pickup_ready_at": now.isoformat(),
        "message": f"取餐码 {row['pickup_code']} 备餐完成，请叫号",
    })


@router.post("/{order_id}/confirm", summary="顾客确认取货")
async def confirm_pickup(
    order_id: uuid.UUID,
    body: ConfirmPickupReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """顾客到达窗口，员工扫码或顾客自助确认取货。

    须先 pickup_ready_at 非空（备餐完成）才允许确认。
    写入 pickup_confirmed_at，订单流程结束。
    """
    tid = _get_tenant_id(request)
    now = _now_utc()

    check = await db.execute(
        text("""
            SELECT id, order_no, pickup_code, pickup_ready_at
            FROM orders
            WHERE id = :order_id AND tenant_id = :tenant_id
              AND order_type = 'self_pickup' AND is_deleted = false
        """),
        {"order_id": order_id, "tenant_id": tid},
    )
    row = check.mappings().one_or_none()
    if row is None:
        _err("自提单不存在", code=404)
    if row["pickup_ready_at"] is None:
        _err("备餐尚未完成，无法确认取货", code=422)

    await db.execute(
        text("""
            UPDATE orders
            SET pickup_confirmed_at = :now, updated_at = :now
            WHERE id = :order_id AND tenant_id = :tenant_id
        """),
        {"now": now, "order_id": order_id, "tenant_id": tid},
    )
    await db.commit()

    return _ok({
        "order_id": str(order_id),
        "order_no": row["order_no"],
        "pickup_code": row["pickup_code"],
        "pickup_confirmed_at": now.isoformat(),
        "message": "取货完成",
    })
