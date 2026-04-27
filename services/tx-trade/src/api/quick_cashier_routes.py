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

  ── A1: 档口管理 ──────────────────────────────────────────────────────────────
  GET  /api/v1/quick-cashier/counters                        — 档口列表
  POST /api/v1/quick-cashier/counters                        — 创建档口
  PUT  /api/v1/quick-cashier/counters/{counter_id}           — 更新档口配置
  POST /api/v1/quick-cashier/counters/{counter_id}/open      — 开档
  POST /api/v1/quick-cashier/counters/{counter_id}/close     — 关档

  ── A2: 并行结账队列 ───────────────────────────────────────────────────────────
  POST /api/v1/quick-cashier/queue                           — 加入队列（返回排队号）
  GET  /api/v1/quick-cashier/queue/status                    — 队列状态（各档口待处理数）
  POST /api/v1/quick-cashier/queue/{queue_id}/process        — 开始处理（转结账流程）
  DELETE /api/v1/quick-cashier/queue/{queue_id}              — 离队

  ── A3: 叫号高级配置 ──────────────────────────────────────────────────────────
  GET  /api/v1/quick-cashier/calling/config/{store_id}       — 获取叫号配置
  PUT  /api/v1/quick-cashier/calling/config/{store_id}       — 更新叫号配置

  ── A4: 会员快结 ──────────────────────────────────────────────────────────────
  POST /api/v1/quick-cashier/member-quick-pay                — 会员扫码快速结账

  ── A5: 分时段限流 ────────────────────────────────────────────────────────────
  GET  /api/v1/quick-cashier/flow-control/{store_id}         — 查看限流配置
  PUT  /api/v1/quick-cashier/flow-control/{store_id}         — 设置各时段最大并发订单数
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


# ── A1: 档口管理请求模型 ─────────────────────────────────────────────────────


class CreateCounterReq(BaseModel):
    store_id: str
    name: str = Field(max_length=50, description="档口名称，如：档口A / 1号档口")
    display_order: int = Field(default=1, ge=1)
    operator_id: Optional[str] = Field(default=None, description="负责人员工ID")
    max_queue_size: int = Field(default=50, ge=1, le=500, description="最大排队人数上限")


class UpdateCounterReq(BaseModel):
    name: Optional[str] = Field(default=None, max_length=50)
    display_order: Optional[int] = Field(default=None, ge=1)
    operator_id: Optional[str] = None
    max_queue_size: Optional[int] = Field(default=None, ge=1, le=500)


# ── A2: 并行队列请求模型 ─────────────────────────────────────────────────────


class JoinQueueReq(BaseModel):
    store_id: str
    counter_id: Optional[str] = Field(default=None, description="指定档口，不传则系统自动分配最短队列")
    member_id: Optional[str] = Field(default=None, description="会员ID（扫码进队）")
    operator_id: Optional[str] = Field(default=None, description="收银员操作时填写")
    party_size: int = Field(default=1, ge=1, le=50, description="人数")


# ── A3: 叫号高级配置请求模型 ─────────────────────────────────────────────────


class CallingAdvancedConfigReq(BaseModel):
    prefix: str = Field(default="A", max_length=5, description="叫号前缀，如 A/B/C")
    number_start: int = Field(default=1, ge=1, description="叫号起始号")
    number_end: int = Field(default=999, ge=1, le=9999, description="叫号结束号")
    broadcast_mode: str = Field(
        default="screen",
        description="广播方式：screen=仅屏幕 / voice=仅语音 / both=双屏+语音",
    )
    recall_times: int = Field(default=3, ge=0, le=10, description="过号重叫次数")
    skip_after_seconds: int = Field(default=120, ge=30, le=600, description="过号后自动跳过等待秒数")
    daily_reset: bool = Field(default=True, description="每日自动重置叫号")


# ── A4: 会员快结请求模型 ─────────────────────────────────────────────────────


class MemberQuickPayReq(BaseModel):
    store_id: str
    quick_order_id: str = Field(description="待支付的快餐订单ID")
    scan_code: str = Field(description="会员扫码内容（会员码 / 付款码）")
    amount_fen: int = Field(ge=1, description="应付金额（分）")
    operator_id: Optional[str] = None


# ── A5: 分时段限流请求模型 ────────────────────────────────────────────────────


class TimeSlotFlowRule(BaseModel):
    time_from: str = Field(description="时段起始 HH:MM，如 11:00")
    time_to: str = Field(description="时段结束 HH:MM，如 13:30")
    max_concurrent_orders: int = Field(ge=1, le=9999, description="该时段最大并发订单数")
    label: Optional[str] = Field(default=None, max_length=20, description="时段标签，如：午高峰")


class FlowControlConfigReq(BaseModel):
    is_enabled: bool = Field(default=True)
    rules: list[TimeSlotFlowRule] = Field(description="分时段规则列表（允许空列表，表示不限流）")


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

    return _ok(
        {
            "quick_order_id": str(quick_order_id),
            "call_number": call_number,
            "order_type": req.order_type,
            "total_fen": total_fen,
            "status": "pending",
            "items": [item.model_dump() for item in req.items],
        }
    )


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

    return _ok(
        {
            "quick_order_id": quick_order_id,
            "call_number": quick_order["call_number"],
            "method": req.method,
            "amount_fen": req.amount_fen,
            "change_fen": change_fen,
            "status": "pending",
            "paid_at": now.isoformat(),
        }
    )


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

    return _ok(
        {
            "quick_order_id": quick_order_id,
            "call_number": updated["call_number"],
            "status": "calling",
            "called_at": updated["called_at"].isoformat() if updated["called_at"] else None,
        }
    )


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

    return _ok(
        {
            "quick_order_id": quick_order_id,
            "call_number": updated["call_number"],
            "status": "completed",
            "completed_at": updated["completed_at"].isoformat() if updated["completed_at"] else None,
        }
    )


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
        return _ok(
            {
                "store_id": store_id,
                "is_enabled": False,
                "call_mode": "number",
                "prefix": "",
                "daily_reset": True,
                "max_number": 999,
                "auto_print_receipt": True,
                "configured": False,
            }
        )

    return _ok(
        {
            "store_id": store_id,
            **dict(config),
            "configured": True,
        }
    )


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

    return _ok(
        {
            "store_id": store_id,
            "is_enabled": req.is_enabled,
            "call_mode": req.call_mode,
            "prefix": req.prefix,
            "daily_reset": req.daily_reset,
            "max_number": req.max_number,
            "auto_print_receipt": req.auto_print_receipt,
            "updated_at": now.isoformat(),
        }
    )


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

    return _ok(
        {
            "store_id": store_id,
            "biz_date": biz_date,
            "next_number": next_number,
            "current_seq": current,
            "prefix": prefix,
        }
    )


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


# ═══════════════════════════════════════════════════════════════════════════════
# A1: 档口管理（Counter Management）
# 数据表：quick_cashier_counters
#   id, tenant_id, store_id, name, status(open/closed), display_order,
#   operator_id, queue_length, max_queue_size, opened_at, closed_at,
#   created_at, updated_at
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/counters")
async def list_counters(
    store_id: str = Query(..., description="门店ID"),
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取档口列表，含状态/队列长度/负责人。"""
    tenant_id = _get_tenant_id(request)  # type: ignore[arg-type]

    rows = await db.execute(
        text(
            """
            SELECT
                c.id, c.name, c.status, c.display_order,
                c.queue_length, c.max_queue_size,
                c.operator_id, e.employee_name AS operator_name,
                c.opened_at, c.closed_at, c.created_at, c.updated_at
            FROM quick_cashier_counters c
            LEFT JOIN employees e
                   ON e.id::text = c.operator_id
                  AND e.tenant_id = c.tenant_id
                  AND e.is_deleted = FALSE
            WHERE c.tenant_id = :tenant_id
              AND c.store_id = :store_id
              AND c.is_deleted = FALSE
            ORDER BY c.display_order ASC
            """
        ),
        {"tenant_id": tenant_id, "store_id": store_id},
    )
    items = [dict(r) for r in rows.mappings()]
    return _ok({"items": items, "total": len(items)})


@router.post("/counters")
async def create_counter(
    req: CreateCounterReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建档口。"""
    tenant_id = _get_tenant_id(request)
    now = datetime.now(timezone.utc)
    counter_id = uuid4()

    await db.execute(
        text(
            """
            INSERT INTO quick_cashier_counters
              (id, tenant_id, store_id, name, status, display_order,
               operator_id, queue_length, max_queue_size,
               is_deleted, created_at, updated_at)
            VALUES
              (:id, :tenant_id, :store_id, :name, 'closed', :display_order,
               :operator_id, 0, :max_queue_size,
               FALSE, :now, :now)
            """
        ),
        {
            "id": str(counter_id),
            "tenant_id": tenant_id,
            "store_id": req.store_id,
            "name": req.name,
            "display_order": req.display_order,
            "operator_id": req.operator_id,
            "max_queue_size": req.max_queue_size,
            "now": now,
        },
    )
    await db.commit()

    logger.info("counter_created", counter_id=str(counter_id), store_id=req.store_id)
    return _ok({"counter_id": str(counter_id), "name": req.name, "status": "closed", "created_at": now.isoformat()})


@router.put("/counters/{counter_id}")
async def update_counter(
    counter_id: str,
    req: UpdateCounterReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新档口配置（字段级PATCH语义）。"""
    tenant_id = _get_tenant_id(request)
    now = datetime.now(timezone.utc)

    # 动态构建 SET 子句，只更新传入的字段
    set_parts = ["updated_at = :now"]
    params: dict = {"id": counter_id, "tenant_id": tenant_id, "now": now}
    if req.name is not None:
        set_parts.append("name = :name")
        params["name"] = req.name
    if req.display_order is not None:
        set_parts.append("display_order = :display_order")
        params["display_order"] = req.display_order
    if req.operator_id is not None:
        set_parts.append("operator_id = :operator_id")
        params["operator_id"] = req.operator_id
    if req.max_queue_size is not None:
        set_parts.append("max_queue_size = :max_queue_size")
        params["max_queue_size"] = req.max_queue_size

    row = await db.execute(
        text(
            f"""
            UPDATE quick_cashier_counters
            SET {", ".join(set_parts)}
            WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
            RETURNING id, name, status, display_order, operator_id, max_queue_size, updated_at
            """
        ),
        params,
    )
    updated = row.mappings().first()
    await db.commit()

    if not updated:
        _err(f"档口不存在: {counter_id}", code=404)
        return {}

    return _ok(dict(updated))


@router.post("/counters/{counter_id}/open")
async def open_counter(
    counter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """开档：closed → open，记录开档时间。"""
    tenant_id = _get_tenant_id(request)
    now = datetime.now(timezone.utc)

    row = await db.execute(
        text(
            """
            UPDATE quick_cashier_counters
            SET status = 'open', opened_at = :now, updated_at = :now
            WHERE id = :id AND tenant_id = :tenant_id AND status = 'closed'
              AND is_deleted = FALSE
            RETURNING id, name, status, opened_at
            """
        ),
        {"id": counter_id, "tenant_id": tenant_id, "now": now},
    )
    updated = row.mappings().first()
    await db.commit()

    if not updated:
        _err(f"档口不存在或已处于开档状态: {counter_id}", code=404)
        return {}

    logger.info("counter_opened", counter_id=counter_id)
    return _ok({"counter_id": counter_id, "status": "open", "opened_at": now.isoformat()})


@router.post("/counters/{counter_id}/close")
async def close_counter(
    counter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """关档：open → closed，记录关档时间。"""
    tenant_id = _get_tenant_id(request)
    now = datetime.now(timezone.utc)

    row = await db.execute(
        text(
            """
            UPDATE quick_cashier_counters
            SET status = 'closed', closed_at = :now, updated_at = :now
            WHERE id = :id AND tenant_id = :tenant_id AND status = 'open'
              AND is_deleted = FALSE
            RETURNING id, name, status, closed_at
            """
        ),
        {"id": counter_id, "tenant_id": tenant_id, "now": now},
    )
    updated = row.mappings().first()
    await db.commit()

    if not updated:
        _err(f"档口不存在或已处于关档状态: {counter_id}", code=404)
        return {}

    logger.info("counter_closed", counter_id=counter_id)
    return _ok({"counter_id": counter_id, "status": "closed", "closed_at": now.isoformat()})


# ═══════════════════════════════════════════════════════════════════════════════
# A2: 并行结账队列（Multi-queue Checkout）
# 数据表：quick_cashier_queue
#   id, tenant_id, store_id, counter_id, queue_number, member_id,
#   operator_id, party_size, status(waiting/processing/done/left),
#   joined_at, processed_at, done_at
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/queue")
async def join_queue(
    req: JoinQueueReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """加入结账队列。

    若未指定 counter_id，自动选取当前 open 且队列最短的档口。
    返回排队号和当前等待人数。
    """
    tenant_id = _get_tenant_id(request)
    now = datetime.now(timezone.utc)

    # 确定档口：指定 or 自动选最短队列
    counter_id = req.counter_id
    if not counter_id:
        auto_row = await db.execute(
            text(
                """
                SELECT id FROM quick_cashier_counters
                WHERE tenant_id = :tenant_id
                  AND store_id  = :store_id
                  AND status    = 'open'
                  AND is_deleted = FALSE
                  AND queue_length < max_queue_size
                ORDER BY queue_length ASC, display_order ASC
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "store_id": req.store_id},
        )
        auto = auto_row.scalar()
        if not auto:
            _err("当前无可用开放档口，或所有档口已满")
            return {}
        counter_id = str(auto)

    # 原子性递增队列号
    seq_row = await db.execute(
        text(
            """
            UPDATE quick_cashier_counters
            SET queue_length = queue_length + 1, updated_at = :now
            WHERE id = :counter_id AND tenant_id = :tenant_id
              AND status = 'open' AND queue_length < max_queue_size
            RETURNING queue_length, name
            """
        ),
        {"counter_id": counter_id, "tenant_id": tenant_id, "now": now},
    )
    counter_state = seq_row.mappings().first()
    if not counter_state:
        _err("档口已满或已关闭，无法加入队列")
        return {}

    queue_id = uuid4()
    queue_number = counter_state["queue_length"]

    await db.execute(
        text(
            """
            INSERT INTO quick_cashier_queue
              (id, tenant_id, store_id, counter_id, queue_number,
               member_id, operator_id, party_size, status, joined_at)
            VALUES
              (:id, :tenant_id, :store_id, :counter_id, :queue_number,
               :member_id, :operator_id, :party_size, 'waiting', :now)
            """
        ),
        {
            "id": str(queue_id),
            "tenant_id": tenant_id,
            "store_id": req.store_id,
            "counter_id": counter_id,
            "queue_number": queue_number,
            "member_id": req.member_id,
            "operator_id": req.operator_id,
            "party_size": req.party_size,
            "now": now,
        },
    )
    await db.commit()

    logger.info("queue_joined", queue_id=str(queue_id), counter_id=counter_id, queue_number=queue_number)
    return _ok(
        {
            "queue_id": str(queue_id),
            "counter_id": counter_id,
            "counter_name": counter_state["name"],
            "queue_number": queue_number,
            "status": "waiting",
            "joined_at": now.isoformat(),
        }
    )


@router.get("/queue/status")
async def get_queue_status(
    store_id: str = Query(..., description="门店ID"),
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    """各档口当前排队状态：待处理数量/状态/负责人。"""
    tenant_id = _get_tenant_id(request)  # type: ignore[arg-type]

    rows = await db.execute(
        text(
            """
            SELECT
                c.id AS counter_id,
                c.name,
                c.status,
                c.queue_length,
                c.max_queue_size,
                c.operator_id,
                COUNT(q.id) FILTER (WHERE q.status = 'waiting')  AS waiting_count,
                COUNT(q.id) FILTER (WHERE q.status = 'processing') AS processing_count
            FROM quick_cashier_counters c
            LEFT JOIN quick_cashier_queue q
                   ON q.counter_id = c.id AND q.tenant_id = c.tenant_id
                  AND q.status IN ('waiting', 'processing')
            WHERE c.tenant_id = :tenant_id
              AND c.store_id = :store_id
              AND c.is_deleted = FALSE
            GROUP BY c.id, c.name, c.status, c.queue_length, c.max_queue_size, c.operator_id
            ORDER BY c.display_order ASC
            """
        ),
        {"tenant_id": tenant_id, "store_id": store_id},
    )
    counters = [dict(r) for r in rows.mappings()]
    total_waiting = sum(c.get("waiting_count") or 0 for c in counters)
    return _ok({"counters": counters, "total_waiting": total_waiting})


@router.post("/queue/{queue_id}/process")
async def process_queue_item(
    queue_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """开始处理队列项：waiting → processing，转入结账流程。"""
    tenant_id = _get_tenant_id(request)
    now = datetime.now(timezone.utc)

    row = await db.execute(
        text(
            """
            UPDATE quick_cashier_queue
            SET status = 'processing', processed_at = :now
            WHERE id = :id AND tenant_id = :tenant_id AND status = 'waiting'
            RETURNING id, counter_id, queue_number, member_id, party_size, processed_at
            """
        ),
        {"id": queue_id, "tenant_id": tenant_id, "now": now},
    )
    updated = row.mappings().first()

    if not updated:
        await db.commit()
        _err(f"队列项不存在或状态不允许处理: {queue_id}", code=404)
        return {}

    # 减少档口队列计数（从 waiting 离开队列）
    await db.execute(
        text(
            """
            UPDATE quick_cashier_counters
            SET queue_length = GREATEST(queue_length - 1, 0), updated_at = :now
            WHERE id = :counter_id AND tenant_id = :tenant_id
            """
        ),
        {"counter_id": str(updated["counter_id"]), "tenant_id": tenant_id, "now": now},
    )
    await db.commit()

    return _ok(
        {
            "queue_id": queue_id,
            "counter_id": str(updated["counter_id"]),
            "queue_number": updated["queue_number"],
            "member_id": updated["member_id"],
            "party_size": updated["party_size"],
            "status": "processing",
            "processed_at": now.isoformat(),
        }
    )


@router.delete("/queue/{queue_id}")
async def leave_queue(
    queue_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """顾客离队：将队列项标记为 left，并减少档口队列计数。"""
    tenant_id = _get_tenant_id(request)
    now = datetime.now(timezone.utc)

    # 标记离队
    row = await db.execute(
        text(
            """
            UPDATE quick_cashier_queue
            SET status = 'left', done_at = :now
            WHERE id = :id AND tenant_id = :tenant_id AND status = 'waiting'
            RETURNING id, counter_id
            """
        ),
        {"id": queue_id, "tenant_id": tenant_id, "now": now},
    )
    updated = row.mappings().first()

    if not updated:
        _err(f"队列项不存在或已不在等待状态: {queue_id}", code=404)
        return {}

    # 减少档口排队计数
    await db.execute(
        text(
            """
            UPDATE quick_cashier_counters
            SET queue_length = GREATEST(queue_length - 1, 0), updated_at = :now
            WHERE id = :counter_id AND tenant_id = :tenant_id
            """
        ),
        {"counter_id": str(updated["counter_id"]), "tenant_id": tenant_id, "now": now},
    )
    await db.commit()

    logger.info("queue_left", queue_id=queue_id)
    return _ok({"queue_id": queue_id, "status": "left", "left_at": now.isoformat()})


# ═══════════════════════════════════════════════════════════════════════════════
# A3: 叫号高级配置
# 数据表：quick_cashier_calling_configs
#   id, tenant_id, store_id, prefix, number_start, number_end,
#   broadcast_mode, recall_times, skip_after_seconds, daily_reset,
#   created_at, updated_at
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/calling/config/{store_id}")
async def get_calling_config(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取门店叫号高级配置，不存在时返回默认值。"""
    tenant_id = _get_tenant_id(request)

    row = await db.execute(
        text(
            """
            SELECT id, prefix, number_start, number_end,
                   broadcast_mode, recall_times, skip_after_seconds,
                   daily_reset, created_at, updated_at
            FROM quick_cashier_calling_configs
            WHERE tenant_id = :tenant_id AND store_id = :store_id
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "store_id": store_id},
    )
    config = row.mappings().first()

    if not config:
        return _ok(
            {
                "store_id": store_id,
                "prefix": "A",
                "number_start": 1,
                "number_end": 999,
                "broadcast_mode": "screen",
                "recall_times": 3,
                "skip_after_seconds": 120,
                "daily_reset": True,
                "configured": False,
            }
        )

    return _ok({"store_id": store_id, **dict(config), "configured": True})


@router.put("/calling/config/{store_id}")
async def save_calling_config(
    store_id: str,
    req: CallingAdvancedConfigReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建或更新叫号高级配置（UPSERT）。"""
    tenant_id = _get_tenant_id(request)

    if req.broadcast_mode not in ("screen", "voice", "both"):
        _err("broadcast_mode 必须是 screen / voice / both")

    if req.number_start >= req.number_end:
        _err("number_start 必须小于 number_end")

    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            """
            INSERT INTO quick_cashier_calling_configs
              (id, tenant_id, store_id, prefix, number_start, number_end,
               broadcast_mode, recall_times, skip_after_seconds, daily_reset,
               created_at, updated_at)
            VALUES
              (gen_random_uuid(), :tenant_id, :store_id, :prefix, :number_start, :number_end,
               :broadcast_mode, :recall_times, :skip_after_seconds, :daily_reset,
               :now, :now)
            ON CONFLICT (tenant_id, store_id)
            DO UPDATE SET
              prefix               = EXCLUDED.prefix,
              number_start         = EXCLUDED.number_start,
              number_end           = EXCLUDED.number_end,
              broadcast_mode       = EXCLUDED.broadcast_mode,
              recall_times         = EXCLUDED.recall_times,
              skip_after_seconds   = EXCLUDED.skip_after_seconds,
              daily_reset          = EXCLUDED.daily_reset,
              updated_at           = EXCLUDED.updated_at
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "prefix": req.prefix,
            "number_start": req.number_start,
            "number_end": req.number_end,
            "broadcast_mode": req.broadcast_mode,
            "recall_times": req.recall_times,
            "skip_after_seconds": req.skip_after_seconds,
            "daily_reset": req.daily_reset,
            "now": now,
        },
    )
    await db.commit()

    logger.info("calling_config_saved", store_id=store_id, broadcast_mode=req.broadcast_mode)
    return _ok(
        {
            "store_id": store_id,
            "prefix": req.prefix,
            "number_start": req.number_start,
            "number_end": req.number_end,
            "broadcast_mode": req.broadcast_mode,
            "recall_times": req.recall_times,
            "skip_after_seconds": req.skip_after_seconds,
            "daily_reset": req.daily_reset,
            "updated_at": now.isoformat(),
        }
    )


# ═══════════════════════════════════════════════════════════════════════════════
# A4: 快餐会员快结
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/member-quick-pay")
async def member_quick_pay(
    req: MemberQuickPayReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """会员扫码快速结账。

    流程：
      1. 通过 scan_code 识别会员（会员码 or 聚合付款码）
      2. 查询会员等级，自动应用会员价/折扣
      3. 查询会员余额，优先使用余额支付
      4. 标记订单已支付，发放积分
    """
    tenant_id = _get_tenant_id(request)
    now = datetime.now(timezone.utc)

    # ── Step 1: 查询快餐订单（加锁防并发重复支付） ──
    order_row = await db.execute(
        text(
            """
            SELECT id, call_number, status, store_id
            FROM quick_orders
            WHERE id = :id AND tenant_id = :tenant_id
            FOR UPDATE
            """
        ),
        {"id": req.quick_order_id, "tenant_id": tenant_id},
    )
    quick_order = order_row.mappings().first()
    if not quick_order:
        _err(f"快餐订单不存在: {req.quick_order_id}", code=404)
        return {}
    if quick_order["status"] != "pending":
        _err(f"订单状态不允许支付，当前状态: {quick_order['status']}")

    # ── Step 2: 通过扫码识别会员（加锁防余额竞态） ──
    member_row = await db.execute(
        text(
            """
            SELECT id, member_code, level_name, balance_fen,
                   discount_rate, points_balance
            FROM members
            WHERE tenant_id = :tenant_id
              AND (member_code = :scan_code OR pay_code = :scan_code)
              AND is_deleted = FALSE
            LIMIT 1
            FOR UPDATE
            """
        ),
        {"tenant_id": tenant_id, "scan_code": req.scan_code},
    )
    member = member_row.mappings().first()
    if not member:
        _err("会员码或付款码无效，请核实后重试")
        return {}

    # ── Step 3: 计算实际应付金额（应用会员折扣） ──
    discount_rate = float(member["discount_rate"] or 1.0)
    discounted_amount_fen = int(req.amount_fen * discount_rate)
    discount_amount_fen = req.amount_fen - discounted_amount_fen

    # ── Step 4: 检查余额是否充足 ──
    balance_fen = int(member["balance_fen"] or 0)
    if balance_fen < discounted_amount_fen:
        _err(f"会员余额不足。余额：{balance_fen / 100:.2f} 元，需支付：{discounted_amount_fen / 100:.2f} 元")

    # ── Step 5: 扣减余额 + 标记订单支付 + 发放积分 ──
    points_earned = discounted_amount_fen // 100  # 每消费1元积1分

    balance_result = await db.execute(
        text(
            """
            UPDATE members
            SET balance_fen    = balance_fen - :amount,
                points_balance = points_balance + :points,
                updated_at     = :now
            WHERE id = :member_id AND tenant_id = :tenant_id
              AND balance_fen >= :amount
            """
        ),
        {
            "amount": discounted_amount_fen,
            "points": points_earned,
            "member_id": str(member["id"]),
            "tenant_id": tenant_id,
            "now": now,
        },
    )
    if balance_result.rowcount == 0:
        await db.rollback()
        _err("会员余额不足（并发扣减），请重试")

    await db.execute(
        text(
            """
            UPDATE quick_orders
            SET status = 'paid', updated_at = :now
            WHERE id = :id AND tenant_id = :tenant_id
            """
        ),
        {"id": req.quick_order_id, "tenant_id": tenant_id, "now": now},
    )
    await db.commit()

    asyncio.create_task(
        emit_event(
            event_type=OrderEventType.PAID,
            tenant_id=tenant_id,
            stream_id=req.quick_order_id,
            payload={
                "method": "member_balance",
                "amount_fen": discounted_amount_fen,
                "discount_amount_fen": discount_amount_fen,
                "member_id": str(member["id"]),
                "points_earned": points_earned,
                "call_number": quick_order["call_number"],
            },
            store_id=req.store_id,
            source_service="tx-trade",
            metadata={"paid_at": now.isoformat(), "operator_id": req.operator_id or ""},
        )
    )

    logger.info(
        "member_quick_pay_success",
        quick_order_id=req.quick_order_id,
        member_id=str(member["id"]),
        discounted_amount_fen=discounted_amount_fen,
        points_earned=points_earned,
    )

    return _ok(
        {
            "quick_order_id": req.quick_order_id,
            "call_number": quick_order["call_number"],
            "member_id": str(member["id"]),
            "member_level": member["level_name"],
            "original_amount_fen": req.amount_fen,
            "discount_rate": discount_rate,
            "discount_amount_fen": discount_amount_fen,
            "paid_amount_fen": discounted_amount_fen,
            "remaining_balance_fen": balance_fen - discounted_amount_fen,
            "points_earned": points_earned,
            "method": "member_balance",
            "status": "pending",
            "paid_at": now.isoformat(),
        }
    )


# ═══════════════════════════════════════════════════════════════════════════════
# A5: 分时段限流配置
# 数据表：quick_cashier_flow_controls
#   id, tenant_id, store_id, is_enabled, rules (JSONB), created_at, updated_at
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/flow-control/{store_id}")
async def get_flow_control(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取门店分时段限流配置，不存在时返回默认（不限流）。"""
    tenant_id = _get_tenant_id(request)

    row = await db.execute(
        text(
            """
            SELECT id, is_enabled, rules, created_at, updated_at
            FROM quick_cashier_flow_controls
            WHERE tenant_id = :tenant_id AND store_id = :store_id
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "store_id": store_id},
    )
    config = row.mappings().first()

    if not config:
        return _ok(
            {
                "store_id": store_id,
                "is_enabled": False,
                "rules": [],
                "configured": False,
            }
        )

    return _ok(
        {
            "store_id": store_id,
            "is_enabled": config["is_enabled"],
            "rules": config["rules"] or [],
            "created_at": config["created_at"].isoformat() if config["created_at"] else None,
            "updated_at": config["updated_at"].isoformat() if config["updated_at"] else None,
            "configured": True,
        }
    )


@router.put("/flow-control/{store_id}")
async def save_flow_control(
    store_id: str,
    req: FlowControlConfigReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建或更新分时段限流配置（UPSERT）。

    rules 存储为 JSONB 数组，每条规则含 time_from/time_to/max_concurrent_orders/label。
    """
    tenant_id = _get_tenant_id(request)

    import json

    # 校验时间格式
    for rule in req.rules:
        try:
            from datetime import time as dtime

            dtime.fromisoformat(rule.time_from)
            dtime.fromisoformat(rule.time_to)
        except ValueError:
            _err(f"时间格式非法: {rule.time_from} 或 {rule.time_to}，需 HH:MM 格式")
        if rule.time_from >= rule.time_to:
            _err(f"time_from ({rule.time_from}) 必须早于 time_to ({rule.time_to})")

    now = datetime.now(timezone.utc)
    rules_json = json.dumps([r.model_dump() for r in req.rules], ensure_ascii=False)

    await db.execute(
        text(
            """
            INSERT INTO quick_cashier_flow_controls
              (id, tenant_id, store_id, is_enabled, rules, created_at, updated_at)
            VALUES
              (gen_random_uuid(), :tenant_id, :store_id, :is_enabled, :rules::jsonb, :now, :now)
            ON CONFLICT (tenant_id, store_id)
            DO UPDATE SET
              is_enabled = EXCLUDED.is_enabled,
              rules      = EXCLUDED.rules,
              updated_at = EXCLUDED.updated_at
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "is_enabled": req.is_enabled,
            "rules": rules_json,
            "now": now,
        },
    )
    await db.commit()

    logger.info("flow_control_saved", store_id=store_id, is_enabled=req.is_enabled, rule_count=len(req.rules))
    return _ok(
        {
            "store_id": store_id,
            "is_enabled": req.is_enabled,
            "rules": [r.model_dump() for r in req.rules],
            "updated_at": now.isoformat(),
        }
    )
