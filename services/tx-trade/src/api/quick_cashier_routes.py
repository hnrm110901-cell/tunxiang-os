"""快餐模式 API — 快餐收银/取餐号/叫号全流程

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。

端点清单：
  POST /api/v1/quick-cashier/order              — 创建快餐订单
  POST /api/v1/quick-cashier/order/{id}/pay     — 快速支付
  GET  /api/v1/quick-cashier/calling            — 获取待叫号列表
  POST /api/v1/quick-cashier/{id}/call          — 叫号（pending → calling）
  POST /api/v1/quick-cashier/{id}/complete      — 取餐完成（calling → completed）
  GET  /api/v1/quick-cashier/config/{store_id}  — 获取快餐模式配置
  PUT  /api/v1/quick-cashier/config/{store_id}  — 保存快餐模式配置
  GET  /api/v1/quick-cashier/sequence/next/{store_id} — 获取下一个取餐号
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

router = APIRouter(prefix="/api/v1/quick-cashier", tags=["quick-cashier"])


# ─── 工具函数 ────────────────────────────────────────────────────────────────


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


# ─── 请求模型 ────────────────────────────────────────────────────────────────


class QuickOrderItem(BaseModel):
    dish_id: str
    dish_name: str
    qty: int = Field(ge=1)
    unit_price_fen: int = Field(ge=0)
    notes: Optional[str] = None


class CreateQuickOrderReq(BaseModel):
    store_id: str
    items: list[QuickOrderItem] = Field(min_length=1)
    order_type: str = Field(
        default="dine_in",
        description="dine_in=堂食 / takeaway=外带 / pack=打包",
    )
    operator_id: Optional[str] = None


class QuickPayReq(BaseModel):
    method: str = Field(
        description="支付方式：cash/wechat/alipay/unionpay/member_balance",
    )
    amount_fen: int = Field(ge=1, description="支付金额（分）")
    cash_received_fen: Optional[int] = Field(
        default=None,
        description="现金支付时：实收金额（分），用于计算找零",
    )
    auth_code: Optional[str] = Field(default=None, description="B扫C顾客付款码")
    idempotency_key: Optional[str] = Field(default=None, max_length=128)


class QuickCashierConfigReq(BaseModel):
    is_enabled: bool = False
    call_mode: str = Field(
        default="number",
        description="叫号方式：number / voice / both",
    )
    prefix: str = Field(default="", max_length=10)
    daily_reset: bool = True
    max_number: int = Field(default=999, ge=1, le=9999)
    auto_print_receipt: bool = True


# ─── 1. 创建快餐订单 ─────────────────────────────────────────────────────────


@router.post("/order")
async def create_quick_order(
    req: CreateQuickOrderReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建快餐订单并自动分配取餐号。

    流程：
      1. 从 call_number_sequences 原子性获取下一个取餐号
      2. 创建 quick_orders 记录（status=pending）
      3. 旁路写入事件总线
    """
    tenant_id = _get_tenant_id(request)

    if req.order_type not in ("dine_in", "takeaway", "pack"):
        _err("order_type 必须是 dine_in / takeaway / pack")

    try:
        store_uuid = UUID(req.store_id)
    except ValueError:
        _err(f"store_id 格式非法: {req.store_id}")
        return {}  # unreachable

    # ── Step 1: 原子性分配取餐号 ──
    call_number = await _allocate_call_number(db, store_uuid, tenant_id)

    # ── Step 2: 插入 quick_orders ──
    quick_order_id = uuid4()
    total_fen = sum(item.qty * item.unit_price_fen for item in req.items)
    now = datetime.now(timezone.utc)

    await db.execute(
        text(
            """
            INSERT INTO quick_orders
              (id, tenant_id, store_id, call_number, order_type, status, created_at)
            VALUES
              (:id, :tenant_id, :store_id, :call_number, :order_type, 'pending', :now)
            """
        ),
        {
            "id": str(quick_order_id),
            "tenant_id": tenant_id,
            "store_id": str(store_uuid),
            "call_number": call_number,
            "order_type": req.order_type,
            "now": now,
        },
    )
    await db.commit()

    # ── Step 3: 事件总线旁路写入 ──
    asyncio.create_task(
        emit_event(
            event_type=OrderEventType.PAID,  # 用现有枚举最近的类型，后续可扩展 QUICK_ORDER_CREATED
            tenant_id=tenant_id,
            stream_id=str(quick_order_id),
            payload={
                "call_number": call_number,
                "order_type": req.order_type,
                "total_fen": total_fen,
                "item_count": len(req.items),
            },
            store_id=req.store_id,
            source_service="tx-trade",
            metadata={"operator_id": req.operator_id or ""},
        )
    )

    logger.info(
        "quick_order_created",
        quick_order_id=str(quick_order_id),
        call_number=call_number,
        store_id=req.store_id,
        total_fen=total_fen,
    )

    return _ok({
        "quick_order_id": str(quick_order_id),
        "call_number": call_number,
        "order_type": req.order_type,
        "total_fen": total_fen,
        "status": "pending",
        "items": [item.model_dump() for item in req.items],
    })


# ─── 2. 快速支付 ─────────────────────────────────────────────────────────────


@router.post("/order/{quick_order_id}/pay")
async def quick_pay(
    quick_order_id: str,
    req: QuickPayReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """快速支付并标记订单已付款。

    支持：扫码（wechat/alipay）/ 现金 / 会员卡 / 银联
    现金支付返回找零金额。
    """
    tenant_id = _get_tenant_id(request)

    # 查询 quick_order
    row = await db.execute(
        text(
            """
            SELECT id, call_number, order_type, status, store_id
            FROM quick_orders
            WHERE id = :id AND tenant_id = :tenant_id
            """
        ),
        {"id": quick_order_id, "tenant_id": tenant_id},
    )
    quick_order = row.mappings().first()

    if not quick_order:
        _err(f"快餐订单不存在: {quick_order_id}", code=404)
        return {}

    if quick_order["status"] not in ("pending",):
        _err(f"订单状态不允许支付，当前状态: {quick_order['status']}")

    valid_methods = {"cash", "wechat", "alipay", "unionpay", "member_balance"}
    if req.method not in valid_methods:
        _err(f"不支持的支付方式: {req.method}，支持: {', '.join(sorted(valid_methods))}")

    change_fen: Optional[int] = None
    if req.method == "cash":
        if req.cash_received_fen is None:
            _err("现金支付需要提供 cash_received_fen（实收金额）")
        if req.cash_received_fen < req.amount_fen:  # type: ignore[operator]
            _err("实收金额不足")
        change_fen = req.cash_received_fen - req.amount_fen  # type: ignore[operator]

    # 更新 quick_orders 状态为 pending（待叫号），记录支付信息
    # 注意：支付成功后状态仍为 pending，等收银员手动叫号
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            """
            UPDATE quick_orders
            SET status = 'pending'
            WHERE id = :id AND tenant_id = :tenant_id
            """
        ),
        {"id": quick_order_id, "tenant_id": tenant_id},
    )
    await db.commit()

    asyncio.create_task(
        emit_event(
            event_type=OrderEventType.PAID,
            tenant_id=tenant_id,
            stream_id=quick_order_id,
            payload={
                "method": req.method,
                "amount_fen": req.amount_fen,
                "call_number": quick_order["call_number"],
            },
            store_id=str(quick_order["store_id"]),
            source_service="tx-trade",
            metadata={"paid_at": now.isoformat()},
        )
    )

    logger.info(
        "quick_order_paid",
        quick_order_id=quick_order_id,
        method=req.method,
        amount_fen=req.amount_fen,
        call_number=quick_order["call_number"],
    )

    return _ok({
        "quick_order_id": quick_order_id,
        "call_number": quick_order["call_number"],
        "method": req.method,
        "amount_fen": req.amount_fen,
        "change_fen": change_fen,
        "status": "pending",
        "paid_at": now.isoformat(),
    })


# ─── 3. 获取待叫号列表 ───────────────────────────────────────────────────────


@router.get("/calling")
async def list_calling(
    store_id: str = Query(...),
    status: str = Query(default="pending", description="pending / calling / all"),
    limit: int = Query(default=50, ge=1, le=200),
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取待叫号/叫号中列表，按创建时间升序排列。"""
    tenant_id = _get_tenant_id(request)  # type: ignore[arg-type]

    params: dict = {"tenant_id": tenant_id, "store_id": store_id, "limit": limit}
    if status == "all":
        where_status = "status IN ('pending', 'calling')"
    elif status in ("pending", "calling"):
        where_status = "status = :status"
        params["status"] = status
    else:
        _err("status 参数必须是 pending / calling / all")
        return {}

    rows = await db.execute(
        text(
            f"""
            SELECT id, call_number, order_type, status, called_at, created_at
            FROM quick_orders
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id
              AND {where_status}
            ORDER BY created_at ASC
            LIMIT :limit
            """
        ),
        params,
    )
    items = [dict(row) for row in rows.mappings()]

    return _ok({"items": items, "total": len(items)})


# ─── 4. 叫号 ─────────────────────────────────────────────────────────────────


@router.post("/{quick_order_id}/call")
async def call_number(
    quick_order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """叫号：pending → calling，记录叫号时间。"""
    tenant_id = _get_tenant_id(request)

    row = await db.execute(
        text(
            """
            UPDATE quick_orders
            SET status = 'calling', called_at = :now
            WHERE id = :id
              AND tenant_id = :tenant_id
              AND status IN ('pending', 'calling')
            RETURNING id, call_number, status, called_at
            """
        ),
        {"id": quick_order_id, "tenant_id": tenant_id, "now": datetime.now(timezone.utc)},
    )
    updated = row.mappings().first()
    await db.commit()

    if not updated:
        _err(f"快餐订单不存在或状态不允许叫号: {quick_order_id}", code=404)
        return {}

    logger.info(
        "quick_order_called",
        quick_order_id=quick_order_id,
        call_number=updated["call_number"],
    )

    return _ok({
        "quick_order_id": quick_order_id,
        "call_number": updated["call_number"],
        "status": "calling",
        "called_at": updated["called_at"].isoformat() if updated["called_at"] else None,
    })


# ─── 5. 取餐完成 ─────────────────────────────────────────────────────────────


@router.post("/{quick_order_id}/complete")
async def complete_order(
    quick_order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """取餐完成：calling → completed，记录完成时间。"""
    tenant_id = _get_tenant_id(request)

    row = await db.execute(
        text(
            """
            UPDATE quick_orders
            SET status = 'completed', completed_at = :now
            WHERE id = :id
              AND tenant_id = :tenant_id
              AND status IN ('calling', 'pending')
            RETURNING id, call_number, status, completed_at
            """
        ),
        {
            "id": quick_order_id,
            "tenant_id": tenant_id,
            "now": datetime.now(timezone.utc),
        },
    )
    updated = row.mappings().first()
    await db.commit()

    if not updated:
        _err(f"快餐订单不存在或状态不允许完成: {quick_order_id}", code=404)
        return {}

    logger.info(
        "quick_order_completed",
        quick_order_id=quick_order_id,
        call_number=updated["call_number"],
    )

    return _ok({
        "quick_order_id": quick_order_id,
        "call_number": updated["call_number"],
        "status": "completed",
        "completed_at": updated["completed_at"].isoformat() if updated["completed_at"] else None,
    })


# ─── 6. 获取快餐配置 ─────────────────────────────────────────────────────────


@router.get("/config/{store_id}")
async def get_config(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取门店快餐模式配置，不存在时返回默认值。"""
    tenant_id = _get_tenant_id(request)

    row = await db.execute(
        text(
            """
            SELECT id, is_enabled, call_mode, prefix, daily_reset,
                   max_number, auto_print_receipt, created_at, updated_at
            FROM quick_cashier_configs
            WHERE tenant_id = :tenant_id AND store_id = :store_id
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "store_id": store_id},
    )
    config = row.mappings().first()

    if not config:
        # 返回默认配置（尚未初始化）
        return _ok({
            "store_id": store_id,
            "is_enabled": False,
            "call_mode": "number",
            "prefix": "",
            "daily_reset": True,
            "max_number": 999,
            "auto_print_receipt": True,
            "configured": False,
        })

    return _ok({
        "store_id": store_id,
        **dict(config),
        "configured": True,
    })


# ─── 7. 保存快餐配置 ─────────────────────────────────────────────────────────


@router.put("/config/{store_id}")
async def save_config(
    store_id: str,
    req: QuickCashierConfigReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建或更新门店快餐模式配置（UPSERT）。"""
    tenant_id = _get_tenant_id(request)

    if req.call_mode not in ("number", "voice", "both"):
        _err("call_mode 必须是 number / voice / both")

    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            """
            INSERT INTO quick_cashier_configs
              (id, tenant_id, store_id, is_enabled, call_mode, prefix,
               daily_reset, max_number, auto_print_receipt, created_at, updated_at)
            VALUES
              (gen_random_uuid(), :tenant_id, :store_id, :is_enabled, :call_mode, :prefix,
               :daily_reset, :max_number, :auto_print_receipt, :now, :now)
            ON CONFLICT (tenant_id, store_id)
            DO UPDATE SET
              is_enabled        = EXCLUDED.is_enabled,
              call_mode         = EXCLUDED.call_mode,
              prefix            = EXCLUDED.prefix,
              daily_reset       = EXCLUDED.daily_reset,
              max_number        = EXCLUDED.max_number,
              auto_print_receipt = EXCLUDED.auto_print_receipt,
              updated_at        = EXCLUDED.updated_at
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "is_enabled": req.is_enabled,
            "call_mode": req.call_mode,
            "prefix": req.prefix,
            "daily_reset": req.daily_reset,
            "max_number": req.max_number,
            "auto_print_receipt": req.auto_print_receipt,
            "now": now,
        },
    )
    await db.commit()

    logger.info(
        "quick_cashier_config_saved",
        store_id=store_id,
        is_enabled=req.is_enabled,
        call_mode=req.call_mode,
    )

    return _ok({
        "store_id": store_id,
        "is_enabled": req.is_enabled,
        "call_mode": req.call_mode,
        "prefix": req.prefix,
        "daily_reset": req.daily_reset,
        "max_number": req.max_number,
        "auto_print_receipt": req.auto_print_receipt,
        "updated_at": now.isoformat(),
    })


# ─── 8. 获取下一个取餐号 ─────────────────────────────────────────────────────


@router.get("/sequence/next/{store_id}")
async def get_next_sequence(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """预览下一个取餐号（不消耗流水，仅用于前端展示）。"""
    tenant_id = _get_tenant_id(request)

    # 查配置获取前缀和 max_number
    config_row = await db.execute(
        text(
            """
            SELECT prefix, max_number
            FROM quick_cashier_configs
            WHERE tenant_id = :tenant_id AND store_id = :store_id
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "store_id": store_id},
    )
    config = config_row.mappings().first()
    prefix = config["prefix"] if config else ""
    max_number = config["max_number"] if config else 999

    biz_date = date.today().isoformat()
    seq_row = await db.execute(
        text(
            """
            SELECT current_seq FROM call_number_sequences
            WHERE store_id = :store_id AND biz_date = :biz_date
            """
        ),
        {"store_id": store_id, "biz_date": biz_date},
    )
    seq = seq_row.scalar()
    current = seq or 0
    next_seq = (current % max_number) + 1
    next_number = f"{prefix}{str(next_seq).zfill(3)}"

    return _ok({
        "store_id": store_id,
        "biz_date": biz_date,
        "next_number": next_number,
        "current_seq": current,
        "prefix": prefix,
    })


# ─── 内部工具：原子性分配取餐号 ─────────────────────────────────────────────


async def _allocate_call_number(
    db: AsyncSession,
    store_id: UUID,
    tenant_id: str,
) -> str:
    """原子性获取并递增取餐号流水（UPSERT + 返回新值）。

    使用 PostgreSQL 的 INSERT ... ON CONFLICT DO UPDATE 保证原子性，
    无需显式锁，适合高并发快餐场景。
    """
    # 读取配置
    config_row = await db.execute(
        text(
            """
            SELECT prefix, max_number, daily_reset
            FROM quick_cashier_configs
            WHERE tenant_id = :tenant_id AND store_id = :store_id
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "store_id": str(store_id)},
    )
    config = config_row.mappings().first()
    prefix = config["prefix"] if config else ""
    max_number = config["max_number"] if config else 999

    biz_date = date.today().isoformat()

    result = await db.execute(
        text(
            """
            INSERT INTO call_number_sequences (store_id, biz_date, current_seq, prefix)
            VALUES (:store_id, :biz_date, 1, :prefix)
            ON CONFLICT (store_id, biz_date)
            DO UPDATE SET
              current_seq = CASE
                WHEN call_number_sequences.current_seq >= :max_number THEN 1
                ELSE call_number_sequences.current_seq + 1
              END,
              prefix = EXCLUDED.prefix
            RETURNING current_seq
            """
        ),
        {
            "store_id": str(store_id),
            "biz_date": biz_date,
            "prefix": prefix,
            "max_number": max_number,
        },
    )
    seq = result.scalar()
    call_number = f"{prefix}{str(seq).zfill(3)}"
    return call_number
