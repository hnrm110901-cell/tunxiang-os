"""快餐模式平行流程 API — 模块3.1

端点清单：
  POST /api/v1/fastfood/orders                         — 快餐下单（无桌台，自动生成取餐号）
  GET  /api/v1/fastfood/orders                         — 查询订单列表（按状态过滤）
  POST /api/v1/fastfood/orders/{id}/ready              — 出餐（触发叫号推送）
  GET  /api/v1/fastfood/call-numbers                   — 待取餐号列表
  POST /api/v1/fastfood/call-numbers/{number}/recalled — 叫号（记录叫号时间）

取餐号生成逻辑：
  当日递增，001~999 循环，跨日重置。
  使用 daily_call_numbers 表（store_id + biz_date 联合唯一）。

数据表依赖：
  fast_food_orders       — 快餐订单主表
  fast_food_order_items  — 订单行项目
  daily_call_numbers     — 取餐号流水（每日重置）

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""
import asyncio
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import OrderEventType
from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/fastfood", tags=["fastfood"])


# ─── Helpers ────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


# ─── Request / Response Models ───────────────────────────────────────────────


class FastFoodOrderItem(BaseModel):
    dish_id: str
    dish_name: str
    qty: int = Field(ge=1)
    unit_price_fen: int = Field(ge=0, description="单价（分）")
    notes: Optional[str] = None


class CreateFastFoodOrderReq(BaseModel):
    store_id: str
    items: list[FastFoodOrderItem] = Field(min_length=1)
    order_type: str = Field(
        default="dine_in",
        description="dine_in=堂食 / pack=打包",
    )
    operator_id: Optional[str] = None


class RecallReq(BaseModel):
    operator_id: Optional[str] = None


# ─── 1. 快餐下单 ──────────────────────────────────────────────────────────────


@router.post("/orders")
async def create_fastfood_order(
    req: CreateFastFoodOrderReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """快餐下单——无桌台，自动生成取餐号。

    流程：
      1. 原子性分配取餐号（daily_call_numbers UPSERT）
      2. 创建 fast_food_orders 主记录（status=pending）
      3. 插入 fast_food_order_items 行项目
      4. 旁路写入事件总线（不阻塞主流程）
    """
    tenant_id = _get_tenant_id(request)

    if req.order_type not in ("dine_in", "pack"):
        _err("order_type 必须是 dine_in 或 pack")

    try:
        store_uuid = UUID(req.store_id)
    except ValueError:
        _err(f"store_id 格式非法: {req.store_id}")
        return {}  # unreachable

    # ── Step 1: 原子性分配取餐号 ──
    call_number = await _allocate_daily_call_number(db, store_uuid, tenant_id)

    # ── Step 2: 创建订单主记录 ──
    order_id = uuid4()
    total_fen = sum(item.qty * item.unit_price_fen for item in req.items)
    now = datetime.now(timezone.utc)

    await db.execute(
        text(
            """
            INSERT INTO fast_food_orders
              (id, tenant_id, store_id, call_number, order_type, status,
               total_fen, operator_id, created_at, updated_at)
            VALUES
              (:id, :tenant_id, :store_id, :call_number, :order_type, 'pending',
               :total_fen, :operator_id, :now, :now)
            """
        ),
        {
            "id": str(order_id),
            "tenant_id": tenant_id,
            "store_id": str(store_uuid),
            "call_number": call_number,
            "order_type": req.order_type,
            "total_fen": total_fen,
            "operator_id": req.operator_id,
            "now": now,
        },
    )

    # ── Step 3: 插入行项目 ──
    for item in req.items:
        await db.execute(
            text(
                """
                INSERT INTO fast_food_order_items
                  (id, order_id, tenant_id, dish_id, dish_name, qty,
                   unit_price_fen, subtotal_fen, notes, created_at)
                VALUES
                  (gen_random_uuid(), :order_id, :tenant_id, :dish_id, :dish_name,
                   :qty, :unit_price_fen, :subtotal_fen, :notes, :now)
                """
            ),
            {
                "order_id": str(order_id),
                "tenant_id": tenant_id,
                "dish_id": item.dish_id,
                "dish_name": item.dish_name,
                "qty": item.qty,
                "unit_price_fen": item.unit_price_fen,
                "subtotal_fen": item.qty * item.unit_price_fen,
                "notes": item.notes,
                "now": now,
            },
        )

    await db.commit()

    # ── Step 4: 事件总线旁路写入 ──
    asyncio.create_task(
        emit_event(
            event_type=OrderEventType.PAID,
            tenant_id=tenant_id,
            stream_id=str(order_id),
            payload={
                "call_number": call_number,
                "order_type": req.order_type,
                "total_fen": total_fen,
                "item_count": len(req.items),
                "source": "fastfood",
            },
            store_id=req.store_id,
            source_service="tx-trade",
            metadata={"operator_id": req.operator_id or ""},
        )
    )

    logger.info(
        "fastfood_order_created",
        order_id=str(order_id),
        call_number=call_number,
        store_id=req.store_id,
        total_fen=total_fen,
    )

    return _ok({
        "fast_food_order_id": str(order_id),
        "call_number": call_number,
        "order_type": req.order_type,
        "total_fen": total_fen,
        "status": "pending",
        "items": [item.model_dump() for item in req.items],
        "created_at": now.isoformat(),
    })


# ─── 2. 查询订单列表 ──────────────────────────────────────────────────────────


@router.get("/orders")
async def list_fastfood_orders(
    store_id: str = Query(...),
    status: str = Query(default="pending,preparing", description="逗号分隔，如 pending,preparing"),
    limit: int = Query(default=50, ge=1, le=200),
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询快餐订单列表，支持多状态过滤。

    status 可选值：pending / preparing / ready / called / completed / cancelled
    多状态用逗号分隔，例如：pending,preparing
    """
    tenant_id = _get_tenant_id(request)  # type: ignore[arg-type]

    valid_statuses = {"pending", "preparing", "ready", "called", "completed", "cancelled"}
    status_list = [s.strip() for s in status.split(",") if s.strip()]
    invalid = set(status_list) - valid_statuses
    if invalid:
        _err(f"非法 status 值: {', '.join(sorted(invalid))}，可选: {', '.join(sorted(valid_statuses))}")

    placeholders = ", ".join(f":s{i}" for i in range(len(status_list)))
    params: dict = {"tenant_id": tenant_id, "store_id": store_id, "limit": limit}
    for i, s in enumerate(status_list):
        params[f"s{i}"] = s

    rows = await db.execute(
        text(
            f"""
            SELECT o.id AS fast_food_order_id,
                   o.call_number,
                   o.order_type,
                   o.status,
                   o.total_fen,
                   o.operator_id,
                   o.ready_at,
                   o.called_at,
                   o.completed_at,
                   o.created_at,
                   COALESCE(
                     json_agg(
                       json_build_object(
                         'dish_id', i.dish_id,
                         'dish_name', i.dish_name,
                         'qty', i.qty,
                         'unit_price_fen', i.unit_price_fen,
                         'subtotal_fen', i.subtotal_fen,
                         'notes', i.notes
                       ) ORDER BY i.created_at
                     ) FILTER (WHERE i.id IS NOT NULL),
                     '[]'::json
                   ) AS items
            FROM fast_food_orders o
            LEFT JOIN fast_food_order_items i
              ON i.order_id = o.id AND i.tenant_id = o.tenant_id
            WHERE o.tenant_id = :tenant_id
              AND o.store_id = :store_id
              AND o.status IN ({placeholders})
            GROUP BY o.id
            ORDER BY o.created_at ASC
            LIMIT :limit
            """
        ),
        params,
    )
    items = [dict(row) for row in rows.mappings()]

    return _ok({"items": items, "total": len(items)})


# ─── 3. 出餐（触发叫号） ─────────────────────────────────────────────────────


@router.post("/orders/{order_id}/ready")
async def mark_order_ready(
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """标记快餐订单出餐完成，触发叫号推送。

    状态流转：pending / preparing → ready
    同时向叫号屏广播（通过 calling_screen WebSocket）。
    """
    tenant_id = _get_tenant_id(request)
    now = datetime.now(timezone.utc)

    row = await db.execute(
        text(
            """
            UPDATE fast_food_orders
            SET status = 'ready', ready_at = :now, updated_at = :now
            WHERE id = :id
              AND tenant_id = :tenant_id
              AND status IN ('pending', 'preparing')
            RETURNING id, call_number, store_id, status, ready_at
            """
        ),
        {"id": order_id, "tenant_id": tenant_id, "now": now},
    )
    updated = row.mappings().first()
    await db.commit()

    if not updated:
        _err(f"快餐订单不存在或状态不允许出餐: {order_id}", code=404)
        return {}

    call_number = updated["call_number"]
    store_id = str(updated["store_id"])

    # 广播叫号到叫号屏 WebSocket
    try:
        from .calling_screen_routes import broadcast_call_number
        asyncio.create_task(
            broadcast_call_number(
                store_id=store_id,
                quick_order_id=order_id,
                call_number=call_number,
                called_at=now,
            )
        )
    except ImportError:
        logger.warning("fastfood.calling_screen_import_failed", order_id=order_id)

    logger.info(
        "fastfood_order_ready",
        order_id=order_id,
        call_number=call_number,
        store_id=store_id,
    )

    return _ok({
        "fast_food_order_id": order_id,
        "call_number": call_number,
        "status": "ready",
        "ready_at": now.isoformat(),
    })


# ─── 4. 待取餐号列表 ─────────────────────────────────────────────────────────


@router.get("/call-numbers")
async def list_call_numbers(
    store_id: str = Query(...),
    status: str = Query(default="ready,called", description="ready=已出餐待取 / called=已叫号"),
    limit: int = Query(default=20, ge=1, le=100),
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取待取餐号列表（已出餐/已叫号，按出餐时间排序）。"""
    tenant_id = _get_tenant_id(request)  # type: ignore[arg-type]

    valid_statuses = {"ready", "called", "completed"}
    status_list = [s.strip() for s in status.split(",") if s.strip()]
    invalid = set(status_list) - valid_statuses
    if invalid:
        _err(f"非法 status 值: {', '.join(sorted(invalid))}")

    placeholders = ", ".join(f":s{i}" for i in range(len(status_list)))
    params: dict = {"tenant_id": tenant_id, "store_id": store_id, "limit": limit}
    for i, s in enumerate(status_list):
        params[f"s{i}"] = s

    rows = await db.execute(
        text(
            f"""
            SELECT id AS fast_food_order_id,
                   call_number,
                   order_type,
                   status,
                   total_fen,
                   ready_at,
                   called_at,
                   created_at
            FROM fast_food_orders
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id
              AND status IN ({placeholders})
            ORDER BY ready_at ASC NULLS LAST, created_at ASC
            LIMIT :limit
            """
        ),
        params,
    )
    items = [dict(row) for row in rows.mappings()]

    return _ok({"items": items, "total": len(items)})


# ─── 5. 叫号（记录叫号时间） ─────────────────────────────────────────────────


@router.post("/call-numbers/{call_number}/recalled")
async def recall_number(
    call_number: str,
    req: RecallReq,
    store_id: str = Query(...),
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    """叫号——记录叫号时间，并广播叫号信号到叫号屏。

    支持重复叫号（顾客未听到时再次叫号）。
    状态流转：ready → called（首次）；called 状态可重复叫号（更新 called_at）。
    """
    tenant_id = _get_tenant_id(request)  # type: ignore[arg-type]
    now = datetime.now(timezone.utc)

    row = await db.execute(
        text(
            """
            UPDATE fast_food_orders
            SET status = 'called', called_at = :now, updated_at = :now
            WHERE call_number = :call_number
              AND store_id = :store_id
              AND tenant_id = :tenant_id
              AND status IN ('ready', 'called')
            RETURNING id, call_number, store_id, status, called_at
            """
        ),
        {
            "call_number": call_number,
            "store_id": store_id,
            "tenant_id": tenant_id,
            "now": now,
        },
    )
    updated = row.mappings().first()
    await db.commit()

    if not updated:
        _err(f"取餐号不存在或状态不允许叫号: {call_number}", code=404)
        return {}

    order_id = str(updated["id"])
    updated_store_id = str(updated["store_id"])

    # 广播叫号信号
    try:
        from .calling_screen_routes import broadcast_call_number
        asyncio.create_task(
            broadcast_call_number(
                store_id=updated_store_id,
                quick_order_id=order_id,
                call_number=call_number,
                called_at=now,
            )
        )
    except ImportError:
        logger.warning("fastfood.calling_screen_import_failed", call_number=call_number)

    logger.info(
        "fastfood_number_recalled",
        call_number=call_number,
        order_id=order_id,
        store_id=updated_store_id,
        operator_id=req.operator_id,
    )

    return _ok({
        "call_number": call_number,
        "fast_food_order_id": order_id,
        "status": "called",
        "called_at": now.isoformat(),
    })


# ─── 内部工具：原子性分配取餐号 ──────────────────────────────────────────────


async def _allocate_daily_call_number(
    db: AsyncSession,
    store_id: UUID,
    tenant_id: str,
    max_number: int = 999,
) -> str:
    """原子性获取并递增当日取餐号流水（001~max_number 循环，跨日重置）。

    使用 PostgreSQL INSERT ... ON CONFLICT DO UPDATE 保证原子性。
    依赖表：daily_call_numbers (store_id, biz_date, current_seq)
    """
    biz_date = date.today().isoformat()

    result = await db.execute(
        text(
            """
            INSERT INTO daily_call_numbers (store_id, tenant_id, biz_date, current_seq)
            VALUES (:store_id, :tenant_id, :biz_date, 1)
            ON CONFLICT (store_id, biz_date)
            DO UPDATE SET
              current_seq = CASE
                WHEN daily_call_numbers.current_seq >= :max_number THEN 1
                ELSE daily_call_numbers.current_seq + 1
              END,
              updated_at = NOW()
            RETURNING current_seq
            """
        ),
        {
            "store_id": str(store_id),
            "tenant_id": tenant_id,
            "biz_date": biz_date,
            "max_number": max_number,
        },
    )
    seq = result.scalar()
    return str(seq).zfill(3)
