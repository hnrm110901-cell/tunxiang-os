"""速点快速点单终端（Kiosk）API

适用于食堂/档口/自助餐场景，顾客自助扫码或在终端上点单，系统自动生成订单。

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。

端点清单：
  ── 终端管理 ──────────────────────────────────────────────────────────────────
  POST   /api/v1/kiosk/terminals                            — 注册速点终端
  GET    /api/v1/kiosk/terminals                            — 终端列表（按store_id）
  PUT    /api/v1/kiosk/terminals/{terminal_id}              — 更新终端配置
  POST   /api/v1/kiosk/terminals/{terminal_id}/activate     — 激活终端
  POST   /api/v1/kiosk/terminals/{terminal_id}/deactivate   — 停用终端
  GET    /api/v1/kiosk/terminals/{terminal_id}/config       — 终端获取自身配置

  ── 点单流程（终端调用）──────────────────────────────────────────────────────
  GET    /api/v1/kiosk/{terminal_id}/menu                   — 获取终端可点菜单
  POST   /api/v1/kiosk/{terminal_id}/cart                   — 创建/更新购物车
  GET    /api/v1/kiosk/{terminal_id}/cart/{cart_id}         — 获取购物车
  POST   /api/v1/kiosk/{terminal_id}/orders                 — 下单（购物车→订单）
  GET    /api/v1/kiosk/{terminal_id}/orders/{order_id}/status — 查询订单状态

  ── 支付（终端扫码支付）─────────────────────────────────────────────────────
  POST   /api/v1/kiosk/{terminal_id}/orders/{order_id}/scan-pay    — 主扫支付
  POST   /api/v1/kiosk/{terminal_id}/orders/{order_id}/qr-pay      — 被扫支付（生成二维码）
  GET    /api/v1/kiosk/{terminal_id}/pay-result/{polling_key}      — 查询被扫结果

  ── 叫号集成 ─────────────────────────────────────────────────────────────────
  GET    /api/v1/kiosk/{terminal_id}/calling/current                — 当前叫号状态
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import OrderEventType
from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/kiosk", tags=["kiosk"])


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


# ─── Pydantic 请求/响应模型 ──────────────────────────────────────────────────


class KioskTerminalReq(BaseModel):
    """注册或更新速点终端"""

    store_id: str = Field(description="门店ID")
    terminal_code: str = Field(max_length=50, description="终端编号，如：KIOSK-01")
    terminal_name: str = Field(max_length=100, description="终端名称，如：1号自助点单机")
    type: str = Field(
        default="self_order",
        description="终端类型：self_order=顾客自助点单 / cashier_assist=收银辅助",
    )
    display_mode: str = Field(
        default="portrait",
        description="显示方向：landscape=横屏 / portrait=竖屏",
    )
    payment_modes: list[str] = Field(
        default=["wechat", "alipay"],
        description="支持的支付方式列表，如：[wechat, alipay, unionpay]",
    )
    idle_timeout_seconds: int = Field(
        default=60,
        ge=10,
        le=600,
        description="闲置超时（秒），超时后返回欢迎屏",
    )
    welcome_screen_config: Optional[dict] = Field(
        default=None,
        description="欢迎屏配置，如：{title, subtitle, background_image_url}",
    )
    ad_images: list[str] = Field(
        default=[],
        description="广告轮播图URL列表",
    )


class UpdateKioskTerminalReq(BaseModel):
    """更新终端配置（部分更新）"""

    terminal_name: Optional[str] = Field(default=None, max_length=100)
    type: Optional[str] = None
    display_mode: Optional[str] = None
    payment_modes: Optional[list[str]] = None
    idle_timeout_seconds: Optional[int] = Field(default=None, ge=10, le=600)
    welcome_screen_config: Optional[dict] = None
    ad_images: Optional[list[str]] = None


class CartItemReq(BaseModel):
    """购物车单项"""

    dish_id: str = Field(description="菜品ID")
    quantity: int = Field(ge=1, description="数量")
    specs: Optional[dict] = Field(
        default=None,
        description="规格选项，如：{size: large, spicy: medium}",
    )
    notes: Optional[str] = Field(default=None, max_length=200, description="备注")


class CartRequest(BaseModel):
    """创建/更新购物车"""

    session_token: str = Field(description="顾客会话Token（终端生成或扫码获取）")
    items: list[CartItemReq] = Field(min_length=1, description="购物车明细")


class KioskOrderRequest(BaseModel):
    """速点下单请求（购物车 → 订单）"""

    cart_id: str = Field(description="购物车ID")
    member_code: Optional[str] = Field(
        default=None,
        description="会员码（可选，顾客自助扫码绑定会员）",
    )
    dining_type: str = Field(
        default="dine_in",
        description="就餐方式：dine_in=堂食 / takeaway=外带",
    )
    table_no: Optional[str] = Field(
        default=None,
        max_length=20,
        description="桌号（堂食时可选填）",
    )


class ScanPayRequest(BaseModel):
    """主扫支付（顾客出示付款码，终端扫码）"""

    scan_code: str = Field(description="顾客付款码内容（微信/支付宝二维码）")


# ─── 终端管理端点 ─────────────────────────────────────────────────────────────


@router.post("/terminals")
async def register_terminal(
    req: KioskTerminalReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """注册速点终端。

    同一门店下 terminal_code 不可重复。
    """
    tenant_id = _get_tenant_id(request)

    if req.type not in ("self_order", "cashier_assist"):
        _err("type 必须是 self_order 或 cashier_assist")
    if req.display_mode not in ("landscape", "portrait"):
        _err("display_mode 必须是 landscape 或 portrait")

    terminal_id = str(uuid4())
    now = datetime.now(timezone.utc)

    try:
        await db.execute(
            text("""
                INSERT INTO kiosk_terminals (
                    id, tenant_id, store_id, terminal_code, terminal_name,
                    type, display_mode, payment_modes, idle_timeout_seconds,
                    welcome_screen_config, ad_images, status, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :store_id, :terminal_code, :terminal_name,
                    :type, :display_mode, :payment_modes::jsonb, :idle_timeout_seconds,
                    :welcome_screen_config::jsonb, :ad_images::jsonb,
                    'inactive', :now, :now
                )
            """),
            {
                "id": terminal_id,
                "tenant_id": tenant_id,
                "store_id": req.store_id,
                "terminal_code": req.terminal_code,
                "terminal_name": req.terminal_name,
                "type": req.type,
                "display_mode": req.display_mode,
                "payment_modes": __import__("json").dumps(req.payment_modes),
                "idle_timeout_seconds": req.idle_timeout_seconds,
                "welcome_screen_config": __import__("json").dumps(req.welcome_screen_config or {}),
                "ad_images": __import__("json").dumps(req.ad_images),
                "now": now,
            },
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("kiosk_register_terminal_failed", error=str(exc), exc_info=True)
        _err(f"注册终端失败：{exc}", code=500)

    logger.info("kiosk_terminal_registered", terminal_id=terminal_id, store_id=req.store_id)
    return _ok({"terminal_id": terminal_id, "status": "inactive", "created_at": now.isoformat()})


@router.get("/terminals")
async def list_terminals(
    store_id: str = Query(description="门店ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """终端列表（按门店过滤）。"""
    tenant_id = _get_tenant_id(request)

    rows = await db.execute(
        text("""
            SELECT id, terminal_code, terminal_name, type, display_mode,
                   payment_modes, status, idle_timeout_seconds, created_at, updated_at
            FROM kiosk_terminals
            WHERE tenant_id = :tenant_id
              AND store_id  = :store_id
              AND is_deleted = FALSE
            ORDER BY created_at ASC
        """),
        {"tenant_id": tenant_id, "store_id": store_id},
    )
    items = [dict(row._mapping) for row in rows]
    return _ok({"items": items, "total": len(items)})


@router.put("/terminals/{terminal_id}")
async def update_terminal(
    terminal_id: str,
    req: UpdateKioskTerminalReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新终端配置。"""
    tenant_id = _get_tenant_id(request)

    updates: dict = {}
    if req.terminal_name is not None:
        updates["terminal_name"] = req.terminal_name
    if req.type is not None:
        if req.type not in ("self_order", "cashier_assist"):
            _err("type 必须是 self_order 或 cashier_assist")
        updates["type"] = req.type
    if req.display_mode is not None:
        if req.display_mode not in ("landscape", "portrait"):
            _err("display_mode 必须是 landscape 或 portrait")
        updates["display_mode"] = req.display_mode
    if req.payment_modes is not None:
        updates["payment_modes"] = __import__("json").dumps(req.payment_modes) + "::jsonb"
    if req.idle_timeout_seconds is not None:
        updates["idle_timeout_seconds"] = req.idle_timeout_seconds
    if req.welcome_screen_config is not None:
        updates["welcome_screen_config"] = __import__("json").dumps(req.welcome_screen_config) + "::jsonb"
    if req.ad_images is not None:
        updates["ad_images"] = __import__("json").dumps(req.ad_images) + "::jsonb"

    if not updates:
        _err("没有提供任何更新字段")

    import json

    set_clauses = []
    params: dict = {"terminal_id": terminal_id, "tenant_id": tenant_id, "now": datetime.now(timezone.utc)}

    if req.terminal_name is not None:
        set_clauses.append("terminal_name = :terminal_name")
        params["terminal_name"] = req.terminal_name
    if req.type is not None:
        set_clauses.append("type = :type")
        params["type"] = req.type
    if req.display_mode is not None:
        set_clauses.append("display_mode = :display_mode")
        params["display_mode"] = req.display_mode
    if req.payment_modes is not None:
        set_clauses.append("payment_modes = :payment_modes::jsonb")
        params["payment_modes"] = json.dumps(req.payment_modes)
    if req.idle_timeout_seconds is not None:
        set_clauses.append("idle_timeout_seconds = :idle_timeout_seconds")
        params["idle_timeout_seconds"] = req.idle_timeout_seconds
    if req.welcome_screen_config is not None:
        set_clauses.append("welcome_screen_config = :welcome_screen_config::jsonb")
        params["welcome_screen_config"] = json.dumps(req.welcome_screen_config)
    if req.ad_images is not None:
        set_clauses.append("ad_images = :ad_images::jsonb")
        params["ad_images"] = json.dumps(req.ad_images)

    set_clauses.append("updated_at = :now")

    result = await db.execute(
        text(f"""
            UPDATE kiosk_terminals
            SET {", ".join(set_clauses)}
            WHERE id = :terminal_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        params,
    )
    await db.commit()

    if result.rowcount == 0:
        _err("终端不存在或无权限", code=404)

    return _ok({"terminal_id": terminal_id, "updated": True})


@router.post("/terminals/{terminal_id}/activate")
async def activate_terminal(
    terminal_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """激活终端（inactive → active）。"""
    tenant_id = _get_tenant_id(request)

    result = await db.execute(
        text("""
            UPDATE kiosk_terminals
            SET status = 'active', updated_at = :now
            WHERE id = :terminal_id AND tenant_id = :tenant_id
              AND is_deleted = FALSE
        """),
        {"terminal_id": terminal_id, "tenant_id": tenant_id, "now": datetime.now(timezone.utc)},
    )
    await db.commit()

    if result.rowcount == 0:
        _err("终端不存在", code=404)

    logger.info("kiosk_terminal_activated", terminal_id=terminal_id)
    return _ok({"terminal_id": terminal_id, "status": "active"})


@router.post("/terminals/{terminal_id}/deactivate")
async def deactivate_terminal(
    terminal_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """停用终端（active → inactive）。"""
    tenant_id = _get_tenant_id(request)

    result = await db.execute(
        text("""
            UPDATE kiosk_terminals
            SET status = 'inactive', updated_at = :now
            WHERE id = :terminal_id AND tenant_id = :tenant_id
              AND is_deleted = FALSE
        """),
        {"terminal_id": terminal_id, "tenant_id": tenant_id, "now": datetime.now(timezone.utc)},
    )
    await db.commit()

    if result.rowcount == 0:
        _err("终端不存在", code=404)

    logger.info("kiosk_terminal_deactivated", terminal_id=terminal_id)
    return _ok({"terminal_id": terminal_id, "status": "inactive"})


@router.get("/terminals/{terminal_id}/config")
async def get_terminal_config(
    terminal_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """终端获取自身完整配置（含菜单分类/支付方式/欢迎屏/广告图）。"""
    tenant_id = _get_tenant_id(request)

    row = await db.execute(
        text("""
            SELECT id, store_id, terminal_code, terminal_name, type, display_mode,
                   payment_modes, idle_timeout_seconds, welcome_screen_config,
                   ad_images, status
            FROM kiosk_terminals
            WHERE id = :terminal_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"terminal_id": terminal_id, "tenant_id": tenant_id},
    )
    terminal = row.fetchone()
    if not terminal:
        _err("终端不存在", code=404)

    t = dict(terminal._mapping)

    # 获取门店可用菜单分类（简略版，供终端启动配置）
    cats = await db.execute(
        text("""
            SELECT DISTINCT category_name
            FROM dish_items
            WHERE store_id = :store_id AND tenant_id = :tenant_id
              AND is_available = TRUE AND is_deleted = FALSE
            ORDER BY category_name
        """),
        {"store_id": t["store_id"], "tenant_id": tenant_id},
    )
    menu_categories = [r[0] for r in cats.fetchall()]

    return _ok(
        {
            "terminal_id": t["id"],
            "terminal_code": t["terminal_code"],
            "terminal_name": t["terminal_name"],
            "type": t["type"],
            "display_mode": t["display_mode"],
            "status": t["status"],
            "menu_categories": menu_categories,
            "payment_modes": t["payment_modes"],
            "welcome_screen_config": t["welcome_screen_config"],
            "idle_timeout_seconds": t["idle_timeout_seconds"],
            "ad_images": t["ad_images"],
        }
    )


# ─── 点单流程端点 ─────────────────────────────────────────────────────────────


@router.get("/{terminal_id}/menu")
async def get_kiosk_menu(
    terminal_id: str,
    request: Request,
    category: Optional[str] = Query(default=None, description="过滤指定分类"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取终端可点菜单（含分类/图片/价格/库存）。

    仅返回当前门店中 is_available=TRUE 的菜品，按分类分组。
    """
    tenant_id = _get_tenant_id(request)

    # 先获取终端所属门店
    row = await db.execute(
        text("""
            SELECT store_id FROM kiosk_terminals
            WHERE id = :terminal_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"terminal_id": terminal_id, "tenant_id": tenant_id},
    )
    terminal = row.fetchone()
    if not terminal:
        _err("终端不存在", code=404)

    store_id = terminal[0]

    params: dict = {"store_id": store_id, "tenant_id": tenant_id}
    category_filter = ""
    if category:
        category_filter = "AND category_name = :category"
        params["category"] = category

    dishes = await db.execute(
        text(f"""
            SELECT id, dish_name, category_name, price_fen, image_url,
                   description, is_available, stock_count,
                   specs_config
            FROM dish_items
            WHERE store_id = :store_id AND tenant_id = :tenant_id
              AND is_available = TRUE AND is_deleted = FALSE
              {category_filter}
            ORDER BY category_name, sort_order NULLS LAST, dish_name
        """),
        params,
    )
    items = [dict(r._mapping) for r in dishes.fetchall()]

    # 按分类分组
    from collections import defaultdict

    grouped: dict = defaultdict(list)
    for dish in items:
        grouped[dish["category_name"]].append(dish)

    return _ok(
        {
            "store_id": store_id,
            "categories": [{"category_name": cat, "dishes": dishes_list} for cat, dishes_list in grouped.items()],
            "total_dishes": len(items),
        }
    )


@router.post("/{terminal_id}/cart")
async def upsert_cart(
    terminal_id: str,
    req: CartRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建或更新购物车。

    同一 session_token 多次调用会覆盖购物车内容（整单替换）。
    返回购物车ID、明细、小计、折扣、应付合计。
    """
    tenant_id = _get_tenant_id(request)

    # 验证终端存在
    row = await db.execute(
        text("""
            SELECT store_id, status FROM kiosk_terminals
            WHERE id = :terminal_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"terminal_id": terminal_id, "tenant_id": tenant_id},
    )
    terminal = row.fetchone()
    if not terminal:
        _err("终端不存在", code=404)
    if terminal[1] != "active":
        _err("终端未激活，无法点单")

    store_id = terminal[0]

    # 查询各菜品价格和库存
    dish_ids = [item.dish_id for item in req.items]
    dishes_res = await db.execute(
        text("""
            SELECT id, dish_name, price_fen, is_available, stock_count
            FROM dish_items
            WHERE id = ANY(:dish_ids) AND tenant_id = :tenant_id
              AND is_deleted = FALSE
        """),
        {"dish_ids": dish_ids, "tenant_id": tenant_id},
    )
    dish_map = {str(r[0]): dict(r._mapping) for r in dishes_res.fetchall()}

    # 组装购物车明细
    cart_items = []
    subtotal_fen = 0
    for item in req.items:
        dish = dish_map.get(item.dish_id)
        if not dish:
            _err(f"菜品 {item.dish_id} 不存在或已下架")
        if not dish["is_available"]:
            _err(f"菜品「{dish['dish_name']}」已沽清，请重新选择")
        line_total = dish["price_fen"] * item.quantity
        subtotal_fen += line_total
        cart_items.append(
            {
                "dish_id": item.dish_id,
                "dish_name": dish["dish_name"],
                "price_fen": dish["price_fen"],
                "quantity": item.quantity,
                "specs": item.specs,
                "notes": item.notes,
                "line_total_fen": line_total,
            }
        )

    # 简单折扣计算（预留接入折扣引擎，当前直接返回0折扣）
    discount_fen = 0
    total_fen = subtotal_fen - discount_fen

    import json

    now = datetime.now(timezone.utc)
    cart_id = str(uuid4())

    # 写入或更新购物车（按 session_token upsert）
    try:
        await db.execute(
            text("""
                INSERT INTO kiosk_carts (
                    id, tenant_id, terminal_id, store_id, session_token,
                    items, subtotal_fen, discount_fen, total_fen,
                    created_at, updated_at, expires_at
                ) VALUES (
                    :id, :tenant_id, :terminal_id, :store_id, :session_token,
                    :items::jsonb, :subtotal_fen, :discount_fen, :total_fen,
                    :now, :now, :now + INTERVAL '30 minutes'
                )
                ON CONFLICT (terminal_id, session_token)
                DO UPDATE SET
                    items = EXCLUDED.items,
                    subtotal_fen = EXCLUDED.subtotal_fen,
                    discount_fen = EXCLUDED.discount_fen,
                    total_fen = EXCLUDED.total_fen,
                    updated_at = EXCLUDED.updated_at,
                    expires_at = EXCLUDED.expires_at
                RETURNING id
            """),
            {
                "id": cart_id,
                "tenant_id": tenant_id,
                "terminal_id": terminal_id,
                "store_id": store_id,
                "session_token": req.session_token,
                "items": json.dumps(cart_items),
                "subtotal_fen": subtotal_fen,
                "discount_fen": discount_fen,
                "total_fen": total_fen,
                "now": now,
            },
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("kiosk_cart_upsert_failed", error=str(exc), exc_info=True)
        _err(f"购物车操作失败：{exc}", code=500)

    return _ok(
        {
            "cart_id": cart_id,
            "terminal_id": terminal_id,
            "session_token": req.session_token,
            "items": cart_items,
            "subtotal_fen": subtotal_fen,
            "discounts": [],
            "discount_fen": discount_fen,
            "total_fen": total_fen,
        }
    )


@router.get("/{terminal_id}/cart/{cart_id}")
async def get_cart(
    terminal_id: str,
    cart_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取购物车当前内容。"""
    tenant_id = _get_tenant_id(request)

    row = await db.execute(
        text("""
            SELECT id, session_token, items, subtotal_fen, discount_fen, total_fen,
                   created_at, updated_at, expires_at
            FROM kiosk_carts
            WHERE id = :cart_id AND terminal_id = :terminal_id AND tenant_id = :tenant_id
        """),
        {"cart_id": cart_id, "terminal_id": terminal_id, "tenant_id": tenant_id},
    )
    cart = row.fetchone()
    if not cart:
        _err("购物车不存在或已过期", code=404)

    return _ok(dict(cart._mapping))


@router.post("/{terminal_id}/orders")
async def kiosk_place_order(
    terminal_id: str,
    req: KioskOrderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """速点下单：购物车 → 正式订单。

    流程：
      1. 校验购物车有效性
      2. 若传入 member_code，尝试绑定会员享优惠
      3. 生成订单号（store_id前缀 + 时间戳 + 序列）
      4. 分配取餐叫号
      5. 创建订单记录，状态 pending_payment
      6. 旁路写入事件总线
    """
    tenant_id = _get_tenant_id(request)

    if req.dining_type not in ("dine_in", "takeaway"):
        _err("dining_type 必须是 dine_in 或 takeaway")

    # 拉取购物车
    row = await db.execute(
        text("""
            SELECT c.id, c.store_id, c.items, c.subtotal_fen, c.discount_fen, c.total_fen,
                   t.status as terminal_status
            FROM kiosk_carts c
            JOIN kiosk_terminals t ON t.id = c.terminal_id
            WHERE c.id = :cart_id AND c.terminal_id = :terminal_id AND c.tenant_id = :tenant_id
              AND c.expires_at > NOW()
        """),
        {"cart_id": req.cart_id, "terminal_id": terminal_id, "tenant_id": tenant_id},
    )
    cart = row.fetchone()
    if not cart:
        _err("购物车不存在或已过期，请重新点单")
    if cart["terminal_status"] != "active":
        _err("终端未激活")

    store_id = cart["store_id"]
    now = datetime.now(timezone.utc)

    # 生成取餐叫号
    seq_row = await db.execute(
        text("""
            INSERT INTO call_number_sequences (store_id, current_date, last_number)
            VALUES (:store_id, CURRENT_DATE, 1)
            ON CONFLICT (store_id, current_date)
            DO UPDATE SET last_number = call_number_sequences.last_number + 1
            RETURNING last_number
        """),
        {"store_id": store_id},
    )
    seq_result = seq_row.fetchone()
    queue_number = f"K{seq_result[0]:03d}" if seq_result else "K001"

    order_id = str(uuid4())
    order_no = f"KO{store_id[:4].upper()}{now.strftime('%m%d%H%M%S')}{uuid4().hex[:4].upper()}"

    try:
        await db.execute(
            text("""
                INSERT INTO kiosk_orders (
                    id, tenant_id, store_id, terminal_id, cart_id, order_no,
                    queue_number, member_code, dining_type, table_no,
                    items, subtotal_fen, discount_fen, total_amount_fen,
                    status, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :store_id, :terminal_id, :cart_id, :order_no,
                    :queue_number, :member_code, :dining_type, :table_no,
                    :items, :subtotal_fen, :discount_fen, :total_amount_fen,
                    'pending_payment', :now, :now
                )
            """),
            {
                "id": order_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "terminal_id": terminal_id,
                "cart_id": req.cart_id,
                "order_no": order_no,
                "queue_number": queue_number,
                "member_code": req.member_code,
                "dining_type": req.dining_type,
                "table_no": req.table_no,
                "items": cart["items"],
                "subtotal_fen": cart["subtotal_fen"],
                "discount_fen": cart["discount_fen"],
                "total_amount_fen": cart["total_fen"],
                "now": now,
            },
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("kiosk_place_order_failed", error=str(exc), exc_info=True)
        _err(f"下单失败：{exc}", code=500)

    asyncio.create_task(
        emit_event(
            event_type=OrderEventType.CREATED,
            tenant_id=tenant_id,
            stream_id=order_id,
            payload={
                "order_no": order_no,
                "total_fen": cart["total_fen"],
                "queue_number": queue_number,
                "source": "kiosk",
            },
            store_id=store_id,
            source_service="tx-trade",
        )
    )

    logger.info("kiosk_order_placed", order_id=order_id, order_no=order_no, queue_number=queue_number)
    return _ok(
        {
            "order_id": order_id,
            "order_no": order_no,
            "queue_number": queue_number,
            "total_amount_fen": cart["total_fen"],
            "payment_required": True,
            "status": "pending_payment",
        }
    )


@router.get("/{terminal_id}/orders/{order_id}/status")
async def get_kiosk_order_status(
    terminal_id: str,
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询订单状态（终端轮询使用）。

    返回订单状态、叫号、预计等待时间、各菜品出餐状态。
    """
    tenant_id = _get_tenant_id(request)

    row = await db.execute(
        text("""
            SELECT o.id, o.order_no, o.queue_number, o.status, o.items,
                   o.total_amount_fen, o.created_at,
                   EXTRACT(EPOCH FROM (NOW() - o.created_at)) / 60 AS waiting_minutes
            FROM kiosk_orders o
            WHERE o.id = :order_id AND o.terminal_id = :terminal_id AND o.tenant_id = :tenant_id
        """),
        {"order_id": order_id, "terminal_id": terminal_id, "tenant_id": tenant_id},
    )
    order = row.fetchone()
    if not order:
        _err("订单不存在", code=404)

    o = dict(order._mapping)
    waiting_minutes = round(float(o.get("waiting_minutes") or 0))
    # 简单预估：每单约3分钟出餐，最多显示15分钟
    estimated_wait = max(1, min(15, 5 - waiting_minutes)) if o["status"] == "preparing" else 0

    return _ok(
        {
            "order_id": order_id,
            "order_no": o["order_no"],
            "status": o["status"],
            "queue_number": o["queue_number"],
            "estimated_wait_minutes": estimated_wait,
            "total_amount_fen": o["total_amount_fen"],
            "items_status": o["items"],  # 各菜品出餐状态由KDS推送更新
        }
    )


# ─── 支付端点 ─────────────────────────────────────────────────────────────────


@router.post("/{terminal_id}/orders/{order_id}/scan-pay")
async def kiosk_scan_pay(
    terminal_id: str,
    order_id: str,
    req: ScanPayRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """主扫支付：顾客出示付款码，终端扫码发起收款。

    适用于微信/支付宝主扫场景（C扫B）。
    实际支付调用通过 scan_pay_routes 已有的支付网关完成，此处负责订单状态更新。
    """
    tenant_id = _get_tenant_id(request)

    row = await db.execute(
        text("""
            SELECT id, status, total_amount_fen, store_id, order_no
            FROM kiosk_orders
            WHERE id = :order_id AND terminal_id = :terminal_id AND tenant_id = :tenant_id
        """),
        {"order_id": order_id, "terminal_id": terminal_id, "tenant_id": tenant_id},
    )
    order = row.fetchone()
    if not order:
        _err("订单不存在", code=404)
    if order["status"] not in ("pending_payment",):
        _err(f"订单状态 {order['status']} 不可发起支付")

    # 生成支付单号
    receipt_no = f"KPY{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{order_id[-6:]}"

    # 记录支付请求（实际支付由 payment gateway 处理，此处为占位）
    try:
        await db.execute(
            text("""
                INSERT INTO kiosk_payments (
                    id, tenant_id, order_id, store_id, receipt_no,
                    scan_code, amount_fen, payment_method, status, created_at
                ) VALUES (
                    :id, :tenant_id, :order_id, :store_id, :receipt_no,
                    :scan_code, :amount_fen, 'scan_pay', 'processing', :now
                )
            """),
            {
                "id": str(uuid4()),
                "tenant_id": tenant_id,
                "order_id": order_id,
                "store_id": order["store_id"],
                "receipt_no": receipt_no,
                "scan_code": req.scan_code,
                "amount_fen": order["total_amount_fen"],
                "now": datetime.now(timezone.utc),
            },
        )
        # 更新订单状态 → paying
        await db.execute(
            text("""
                UPDATE kiosk_orders SET status = 'paying', updated_at = :now
                WHERE id = :order_id AND tenant_id = :tenant_id
            """),
            {"order_id": order_id, "tenant_id": tenant_id, "now": datetime.now(timezone.utc)},
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("kiosk_scan_pay_failed", error=str(exc), exc_info=True)
        _err(f"支付请求失败：{exc}", code=500)

    logger.info("kiosk_scan_pay_initiated", order_id=order_id, receipt_no=receipt_no)
    return _ok(
        {
            "payment_status": "processing",
            "receipt_no": receipt_no,
            "amount_fen": order["total_amount_fen"],
            "message": "支付请求已提交，等待支付网关确认",
        }
    )


@router.post("/{terminal_id}/orders/{order_id}/qr-pay")
async def kiosk_qr_pay(
    terminal_id: str,
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """被扫支付：生成支付二维码，顾客用手机扫码付款（B扫C）。

    返回二维码URL、过期时间和轮询Key，终端展示二维码并轮询支付结果。
    """
    tenant_id = _get_tenant_id(request)

    row = await db.execute(
        text("""
            SELECT id, status, total_amount_fen, store_id, order_no
            FROM kiosk_orders
            WHERE id = :order_id AND terminal_id = :terminal_id AND tenant_id = :tenant_id
        """),
        {"order_id": order_id, "terminal_id": terminal_id, "tenant_id": tenant_id},
    )
    order = row.fetchone()
    if not order:
        _err("订单不存在", code=404)
    if order["status"] not in ("pending_payment",):
        _err(f"订单状态 {order['status']} 不可发起支付")

    polling_key = str(uuid4()).replace("-", "")
    expire_seconds = 300  # 5分钟有效

    # 实际项目中此处调用微信/支付宝统一下单接口获取 code_url；此处返回占位 URL
    qr_code_url = f"weixin://wxpay/bizpayurl?pr={polling_key}"

    try:
        await db.execute(
            text("""
                INSERT INTO kiosk_payments (
                    id, tenant_id, order_id, store_id, receipt_no,
                    polling_key, amount_fen, payment_method, status,
                    qr_code_url, expires_at, created_at
                ) VALUES (
                    :id, :tenant_id, :order_id, :store_id, :receipt_no,
                    :polling_key, :amount_fen, 'qr_pay', 'pending',
                    :qr_code_url, NOW() + INTERVAL '5 minutes', :now
                )
            """),
            {
                "id": str(uuid4()),
                "tenant_id": tenant_id,
                "order_id": order_id,
                "store_id": order["store_id"],
                "receipt_no": f"KQR{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                "polling_key": polling_key,
                "amount_fen": order["total_amount_fen"],
                "qr_code_url": qr_code_url,
                "now": datetime.now(timezone.utc),
            },
        )
        await db.execute(
            text(
                "UPDATE kiosk_orders SET status = 'paying', updated_at = :now WHERE id = :order_id AND tenant_id = :tenant_id"
            ),
            {"order_id": order_id, "tenant_id": tenant_id, "now": datetime.now(timezone.utc)},
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("kiosk_qr_pay_failed", error=str(exc), exc_info=True)
        _err(f"生成支付二维码失败：{exc}", code=500)

    return _ok(
        {
            "qr_code_url": qr_code_url,
            "expire_seconds": expire_seconds,
            "polling_key": polling_key,
            "amount_fen": order["total_amount_fen"],
        }
    )


@router.get("/{terminal_id}/pay-result/{polling_key}")
async def get_pay_result(
    terminal_id: str,
    polling_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询被扫支付结果（终端轮询）。"""
    tenant_id = _get_tenant_id(request)

    row = await db.execute(
        text("""
            SELECT p.status, p.order_id, p.amount_fen, p.receipt_no, p.updated_at
            FROM kiosk_payments p
            JOIN kiosk_orders o ON o.id = p.order_id
            WHERE p.polling_key = :polling_key AND p.tenant_id = :tenant_id
              AND o.terminal_id = :terminal_id
        """),
        {"polling_key": polling_key, "tenant_id": tenant_id, "terminal_id": terminal_id},
    )
    payment = row.fetchone()
    if not payment:
        _err("支付记录不存在", code=404)

    p = dict(payment._mapping)
    return _ok(
        {
            "polling_key": polling_key,
            "payment_status": p["status"],
            "order_id": p["order_id"],
            "receipt_no": p["receipt_no"],
            "amount_fen": p["amount_fen"],
        }
    )


# ─── 叫号集成 ─────────────────────────────────────────────────────────────────


@router.get("/{terminal_id}/calling/current")
async def get_calling_current(
    terminal_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """当前叫号状态（供展示屏和顾客终端使用）。

    返回：正在呼叫的号码列表、等待数、平均等待时间（分钟）。
    """
    tenant_id = _get_tenant_id(request)

    row = await db.execute(
        text("""
            SELECT store_id FROM kiosk_terminals
            WHERE id = :terminal_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"terminal_id": terminal_id, "tenant_id": tenant_id},
    )
    terminal = row.fetchone()
    if not terminal:
        _err("终端不存在", code=404)

    store_id = terminal[0]

    # 正在叫号的订单（状态 = calling）
    calling_rows = await db.execute(
        text("""
            SELECT queue_number
            FROM kiosk_orders
            WHERE store_id = :store_id AND tenant_id = :tenant_id
              AND status = 'calling'
              AND DATE(created_at) = CURRENT_DATE
            ORDER BY updated_at DESC
            LIMIT 5
        """),
        {"store_id": store_id, "tenant_id": tenant_id},
    )
    now_calling = [r[0] for r in calling_rows.fetchall()]

    # 等待中的订单数
    waiting_row = await db.execute(
        text("""
            SELECT COUNT(*) as waiting_count,
                   AVG(EXTRACT(EPOCH FROM (NOW() - created_at)) / 60) as avg_wait
            FROM kiosk_orders
            WHERE store_id = :store_id AND tenant_id = :tenant_id
              AND status IN ('paid', 'preparing')
              AND DATE(created_at) = CURRENT_DATE
        """),
        {"store_id": store_id, "tenant_id": tenant_id},
    )
    stats = waiting_row.fetchone()
    waiting_count = int(stats[0] or 0)
    avg_wait_minutes = round(float(stats[1] or 0))

    return _ok(
        {
            "store_id": store_id,
            "now_calling": now_calling,
            "waiting_count": waiting_count,
            "avg_wait_minutes": avg_wait_minutes,
        }
    )
