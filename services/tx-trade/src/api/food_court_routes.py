"""智慧商街多商户POS — API 路由

核心场景：美食广场/食堂多档口并行运营，统一收银，按档口分账独立核算。

端点清单：
  ── 商街管理（总部后台） ──────────────────────────────────────────────────────
  POST   /api/v1/food-courts                                  — 创建商街
  GET    /api/v1/food-courts                                  — 商街列表（按store_id过滤）
  GET    /api/v1/food-courts/{fc_id}                          — 商街详情（含档口列表）
  PUT    /api/v1/food-courts/{fc_id}                          — 更新商街信息

  POST   /api/v1/food-courts/{fc_id}/vendors                  — 新增档口
  GET    /api/v1/food-courts/{fc_id}/vendors                  — 档口列表
  PUT    /api/v1/food-courts/{fc_id}/vendors/{v_id}           — 更新档口信息
  POST   /api/v1/food-courts/{fc_id}/vendors/{v_id}/suspend   — 暂停档口营业

  ── POS收银（统一收银台） ─────────────────────────────────────────────────────
  GET    /api/v1/food-courts/{fc_id}/menu                     — 获取所有档口菜品（按vendor分组）
  POST   /api/v1/food-courts/{fc_id}/orders                   — 创建商街订单（含多档口菜品）
  GET    /api/v1/food-courts/{fc_id}/orders/{order_id}        — 订单详情
  POST   /api/v1/food-courts/{fc_id}/orders/{order_id}/pay    — 统一结账（触发KDS+分账）
  POST   /api/v1/food-courts/{fc_id}/orders/{order_id}/cancel — 取消订单

  ── 档口KDS（各档口独立屏幕） ────────────────────────────────────────────────
  GET    /api/v1/food-courts/vendor/{v_id}/queue              — 当前档口待出餐列表
  POST   /api/v1/food-courts/vendor/{v_id}/items/{item_id}/ready  — 标记已出餐
  GET    /api/v1/food-courts/vendor/{v_id}/stats              — 档口今日营业数据

  ── 结算（总部财务） ──────────────────────────────────────────────────────────
  GET    /api/v1/food-courts/{fc_id}/settlements              — 结算记录列表
  POST   /api/v1/food-courts/{fc_id}/settlements/generate     — 生成指定日期结算单
  POST   /api/v1/food-courts/{fc_id}/settlements/{s_id}/confirm — 确认结算
  GET    /api/v1/food-courts/{fc_id}/settlements/summary      — 结算汇总报表

统一响应格式：{"ok": bool, "data": {}, "error": {}}
所有接口需要 X-Tenant-ID header。
金额全部用分（整数）。
"""

import asyncio
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func as sa_func
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import OrderEventType
from shared.ontology.src.database import get_db

from ..models.food_court import (
    CreateFoodCourtOrderReq,
    CreateFoodCourtReq,
    CreateVendorReq,
    FoodCourt,
    FoodCourtOrder,
    FoodCourtOrderItem,
    FoodCourtVendor,
    FoodCourtVendorSettlement,
    GenerateSettlementReq,
    PayFoodCourtOrderReq,
    UpdateFoodCourtReq,
    UpdateVendorReq,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/food-courts", tags=["food-court"])


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


def _gen_order_no() -> str:
    """生成商街订单号：FC{YYYYMMDD}{6位随机}"""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    suffix = uuid4().hex[:6].upper()
    return f"FC{today}{suffix}"


def _fc_row_to_dict(fc: FoodCourt) -> dict:
    return {
        "id": str(fc.id),
        "store_id": str(fc.store_id),
        "name": fc.name,
        "description": fc.description,
        "status": fc.status,
        "unified_cashier": fc.unified_cashier,
        "config": fc.config or {},
        "created_at": fc.created_at.isoformat() if fc.created_at else None,
        "updated_at": fc.updated_at.isoformat() if fc.updated_at else None,
    }


def _vendor_row_to_dict(v: FoodCourtVendor) -> dict:
    return {
        "id": str(v.id),
        "food_court_id": str(v.food_court_id),
        "vendor_code": v.vendor_code,
        "vendor_name": v.vendor_name,
        "category": v.category,
        "owner_name": v.owner_name,
        "contact_phone": v.contact_phone,
        "commission_rate": float(v.commission_rate) if v.commission_rate is not None else None,
        "kds_station_id": v.kds_station_id,
        "status": v.status,
        "display_order": v.display_order,
        "settlement_account": v.settlement_account or {},
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


def _order_row_to_dict(o: FoodCourtOrder) -> dict:
    return {
        "id": str(o.id),
        "food_court_id": str(o.food_court_id),
        "order_no": o.order_no,
        "total_amount_fen": o.total_amount_fen,
        "status": o.status,
        "payment_method": o.payment_method,
        "paid_at": o.paid_at.isoformat() if o.paid_at else None,
        "cashier_id": o.cashier_id,
        "notes": o.notes,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


def _item_row_to_dict(i: FoodCourtOrderItem) -> dict:
    return {
        "id": str(i.id),
        "order_id": str(i.order_id),
        "vendor_id": str(i.vendor_id),
        "dish_name": i.dish_name,
        "dish_id": i.dish_id,
        "quantity": i.quantity,
        "unit_price_fen": i.unit_price_fen,
        "subtotal_fen": i.subtotal_fen,
        "notes": i.notes,
        "status": i.status,
        "ready_at": i.ready_at.isoformat() if i.ready_at else None,
    }


def _settlement_row_to_dict(s: FoodCourtVendorSettlement) -> dict:
    return {
        "id": str(s.id),
        "vendor_id": str(s.vendor_id),
        "food_court_id": str(s.food_court_id),
        "settlement_date": s.settlement_date.isoformat() if s.settlement_date else None,
        "order_count": s.order_count,
        "item_count": s.item_count,
        "gross_amount_fen": s.gross_amount_fen,
        "commission_fen": s.commission_fen,
        "net_amount_fen": s.net_amount_fen,
        "status": s.status,
        "settled_at": s.settled_at.isoformat() if s.settled_at else None,
        "operator_id": s.operator_id,
        "details": s.details or {},
    }


async def _push_kds_event(
    tenant_id: str,
    vendor: FoodCourtVendor,
    items: list,
    order_no: str,
) -> None:
    """支付后按 vendor 推送 Redis Streams KDS事件，各档口只收到自己的菜品"""
    try:
        await emit_event(
            event_type=OrderEventType.PAID,
            tenant_id=tenant_id,
            stream_id=str(vendor.id),
            payload={
                "event_subtype": "food_court_kds_push",
                "vendor_id": str(vendor.id),
                "vendor_name": vendor.vendor_name,
                "kds_station_id": vendor.kds_station_id,
                "order_no": order_no,
                "items": [
                    {
                        "item_id": str(i.id),
                        "dish_name": i.dish_name,
                        "quantity": i.quantity,
                        "notes": i.notes,
                    }
                    for i in items
                ],
            },
            source_service="tx-trade",
            metadata={"channel": "food_court_kds"},
        )
    except Exception as exc:  # noqa: BLE001 — 网络/Redis故障不影响支付主流程
        logger.warning("food_court_kds_push_failed", vendor_id=str(vendor.id), error=str(exc))


# ─── 商街管理端点（总部后台） ─────────────────────────────────────────────────


@router.post("")
async def create_food_court(
    req: CreateFoodCourtReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建商街/美食广场"""
    tenant_id = _get_tenant_id(request)

    fc = FoodCourt(
        id=uuid4(),
        tenant_id=UUID(tenant_id),
        store_id=UUID(req.store_id),
        name=req.name,
        description=req.description,
        status="active",
        unified_cashier=req.unified_cashier,
        config=req.config or {},
    )
    db.add(fc)
    await db.commit()
    await db.refresh(fc)

    logger.info("food_court_created", fc_id=str(fc.id), tenant_id=tenant_id, name=fc.name)
    return _ok(_fc_row_to_dict(fc))


@router.get("")
async def list_food_courts(
    request: Request,
    store_id: Optional[str] = Query(default=None, description="按门店过滤"),
    status: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """商街列表"""
    tenant_id = _get_tenant_id(request)

    q = select(FoodCourt).where(
        FoodCourt.tenant_id == UUID(tenant_id),
        FoodCourt.is_deleted == False,
    )
    if store_id:
        q = q.where(FoodCourt.store_id == UUID(store_id))
    if status:
        q = q.where(FoodCourt.status == status)

    count_q = select(sa_func.count()).select_from(q.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    q = q.order_by(FoodCourt.created_at.desc()).offset((page - 1) * size).limit(size)
    result = await db.execute(q)
    items = result.scalars().all()

    return _ok({"items": [_fc_row_to_dict(fc) for fc in items], "total": total})


@router.get("/{fc_id}")
async def get_food_court(
    fc_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """商街详情（含档口列表）"""
    tenant_id = _get_tenant_id(request)

    result = await db.execute(
        select(FoodCourt).where(
            FoodCourt.id == UUID(fc_id),
            FoodCourt.tenant_id == UUID(tenant_id),
            FoodCourt.is_deleted == False,
        )
    )
    fc = result.scalar_one_or_none()
    if not fc:
        _err("商街不存在", 404)

    vendors_result = await db.execute(
        select(FoodCourtVendor)
        .where(
            FoodCourtVendor.food_court_id == UUID(fc_id),
            FoodCourtVendor.tenant_id == UUID(tenant_id),
            FoodCourtVendor.is_deleted == False,
        )
        .order_by(FoodCourtVendor.display_order)
    )
    vendors = vendors_result.scalars().all()

    data = _fc_row_to_dict(fc)
    data["vendors"] = [_vendor_row_to_dict(v) for v in vendors]
    data["vendor_count"] = len(vendors)
    return _ok(data)


@router.put("/{fc_id}")
async def update_food_court(
    fc_id: str,
    req: UpdateFoodCourtReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新商街信息"""
    tenant_id = _get_tenant_id(request)

    result = await db.execute(
        select(FoodCourt).where(
            FoodCourt.id == UUID(fc_id),
            FoodCourt.tenant_id == UUID(tenant_id),
            FoodCourt.is_deleted == False,
        )
    )
    fc = result.scalar_one_or_none()
    if not fc:
        _err("商街不存在", 404)

    if req.name is not None:
        fc.name = req.name
    if req.description is not None:
        fc.description = req.description
    if req.unified_cashier is not None:
        fc.unified_cashier = req.unified_cashier
    if req.status is not None:
        fc.status = req.status
    if req.config is not None:
        fc.config = req.config

    await db.commit()
    await db.refresh(fc)
    return _ok(_fc_row_to_dict(fc))


# ─── 档口管理端点 ─────────────────────────────────────────────────────────────


@router.post("/{fc_id}/vendors")
async def create_vendor(
    fc_id: str,
    req: CreateVendorReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """在商街下新增档口"""
    tenant_id = _get_tenant_id(request)

    fc_result = await db.execute(
        select(FoodCourt).where(
            FoodCourt.id == UUID(fc_id),
            FoodCourt.tenant_id == UUID(tenant_id),
            FoodCourt.is_deleted == False,
        )
    )
    if not fc_result.scalar_one_or_none():
        _err("商街不存在", 404)

    # 同一商街内档口编号唯一校验
    dup_result = await db.execute(
        select(FoodCourtVendor).where(
            FoodCourtVendor.food_court_id == UUID(fc_id),
            FoodCourtVendor.vendor_code == req.vendor_code,
            FoodCourtVendor.tenant_id == UUID(tenant_id),
            FoodCourtVendor.is_deleted == False,
        )
    )
    if dup_result.scalar_one_or_none():
        _err(f"档口编号 {req.vendor_code} 在本商街已存在")

    from decimal import Decimal

    vendor = FoodCourtVendor(
        id=uuid4(),
        tenant_id=UUID(tenant_id),
        food_court_id=UUID(fc_id),
        vendor_code=req.vendor_code,
        vendor_name=req.vendor_name,
        category=req.category,
        owner_name=req.owner_name,
        contact_phone=req.contact_phone,
        commission_rate=Decimal(str(req.commission_rate)) if req.commission_rate is not None else None,
        kds_station_id=req.kds_station_id,
        status="active",
        settlement_account=req.settlement_account or {},
        display_order=req.display_order,
    )
    db.add(vendor)
    await db.commit()
    await db.refresh(vendor)

    logger.info("food_court_vendor_created", vendor_id=str(vendor.id), fc_id=fc_id, name=vendor.vendor_name)
    return _ok(_vendor_row_to_dict(vendor))


@router.get("/{fc_id}/vendors")
async def list_vendors(
    fc_id: str,
    request: Request,
    status: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """商街档口列表"""
    tenant_id = _get_tenant_id(request)

    q = select(FoodCourtVendor).where(
        FoodCourtVendor.food_court_id == UUID(fc_id),
        FoodCourtVendor.tenant_id == UUID(tenant_id),
        FoodCourtVendor.is_deleted == False,
    )
    if status:
        q = q.where(FoodCourtVendor.status == status)
    q = q.order_by(FoodCourtVendor.display_order)

    result = await db.execute(q)
    vendors = result.scalars().all()
    return _ok({"items": [_vendor_row_to_dict(v) for v in vendors], "total": len(vendors)})


@router.put("/{fc_id}/vendors/{v_id}")
async def update_vendor(
    fc_id: str,
    v_id: str,
    req: UpdateVendorReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新档口信息"""
    tenant_id = _get_tenant_id(request)

    result = await db.execute(
        select(FoodCourtVendor).where(
            FoodCourtVendor.id == UUID(v_id),
            FoodCourtVendor.food_court_id == UUID(fc_id),
            FoodCourtVendor.tenant_id == UUID(tenant_id),
            FoodCourtVendor.is_deleted == False,
        )
    )
    vendor = result.scalar_one_or_none()
    if not vendor:
        _err("档口不存在", 404)

    from decimal import Decimal

    if req.vendor_name is not None:
        vendor.vendor_name = req.vendor_name
    if req.category is not None:
        vendor.category = req.category
    if req.owner_name is not None:
        vendor.owner_name = req.owner_name
    if req.contact_phone is not None:
        vendor.contact_phone = req.contact_phone
    if req.commission_rate is not None:
        vendor.commission_rate = Decimal(str(req.commission_rate))
    if req.kds_station_id is not None:
        vendor.kds_station_id = req.kds_station_id
    if req.settlement_account is not None:
        vendor.settlement_account = req.settlement_account
    if req.display_order is not None:
        vendor.display_order = req.display_order
    if req.status is not None:
        vendor.status = req.status

    await db.commit()
    await db.refresh(vendor)
    return _ok(_vendor_row_to_dict(vendor))


@router.post("/{fc_id}/vendors/{v_id}/suspend")
async def suspend_vendor(
    fc_id: str,
    v_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """暂停档口营业（suspended 状态，保留数据）"""
    tenant_id = _get_tenant_id(request)

    result = await db.execute(
        select(FoodCourtVendor).where(
            FoodCourtVendor.id == UUID(v_id),
            FoodCourtVendor.food_court_id == UUID(fc_id),
            FoodCourtVendor.tenant_id == UUID(tenant_id),
            FoodCourtVendor.is_deleted == False,
        )
    )
    vendor = result.scalar_one_or_none()
    if not vendor:
        _err("档口不存在", 404)
    if vendor.status == "suspended":
        _err("档口已处于暂停状态")

    vendor.status = "suspended"
    await db.commit()

    logger.info("food_court_vendor_suspended", vendor_id=v_id, fc_id=fc_id)
    return _ok({"vendor_id": v_id, "status": "suspended"})


# ─── POS收银端点（统一收银台） ────────────────────────────────────────────────


@router.get("/{fc_id}/menu")
async def get_food_court_menu(
    fc_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取商街所有活跃档口（统一收银台选菜用，菜品从 tx-menu 服务拉取）"""
    tenant_id = _get_tenant_id(request)

    vendors_result = await db.execute(
        select(FoodCourtVendor)
        .where(
            FoodCourtVendor.food_court_id == UUID(fc_id),
            FoodCourtVendor.tenant_id == UUID(tenant_id),
            FoodCourtVendor.status == "active",
            FoodCourtVendor.is_deleted == False,
        )
        .order_by(FoodCourtVendor.display_order)
    )
    vendors = vendors_result.scalars().all()

    return _ok(
        {
            "food_court_id": fc_id,
            "vendors": [
                {
                    **_vendor_row_to_dict(v),
                    # 前端凭此 URL 调 tx-menu 服务拉取各档口菜单
                    "menu_url": f"/api/v1/dishes?store_id={v.kds_station_id}" if v.kds_station_id else None,
                }
                for v in vendors
            ],
            "vendor_count": len(vendors),
        }
    )


@router.post("/{fc_id}/orders")
async def create_food_court_order(
    fc_id: str,
    req: CreateFoodCourtOrderReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建商街订单（含多档口菜品）"""
    tenant_id = _get_tenant_id(request)

    fc_result = await db.execute(
        select(FoodCourt).where(
            FoodCourt.id == UUID(fc_id),
            FoodCourt.tenant_id == UUID(tenant_id),
            FoodCourt.status == "active",
            FoodCourt.is_deleted == False,
        )
    )
    if not fc_result.scalar_one_or_none():
        _err("商街不存在或已停用", 404)

    # 校验所有 vendor_id 合法且属于此商街
    vendor_ids = list({UUID(item.vendor_id) for item in req.items})
    vendors_result = await db.execute(
        select(FoodCourtVendor).where(
            FoodCourtVendor.id.in_(vendor_ids),
            FoodCourtVendor.food_court_id == UUID(fc_id),
            FoodCourtVendor.tenant_id == UUID(tenant_id),
            FoodCourtVendor.status == "active",
            FoodCourtVendor.is_deleted == False,
        )
    )
    vendors = {v.id: v for v in vendors_result.scalars().all()}
    for vid in vendor_ids:
        if vid not in vendors:
            _err(f"档口 {vid} 不存在或未营业")

    total_amount_fen = sum(item.quantity * item.unit_price_fen for item in req.items)

    order_id = uuid4()
    order = FoodCourtOrder(
        id=order_id,
        tenant_id=UUID(tenant_id),
        food_court_id=UUID(fc_id),
        order_no=_gen_order_no(),
        total_amount_fen=total_amount_fen,
        status="pending",
        cashier_id=req.cashier_id,
        notes=req.notes,
    )
    db.add(order)

    order_items = []
    for item_req in req.items:
        subtotal = item_req.quantity * item_req.unit_price_fen
        item = FoodCourtOrderItem(
            id=uuid4(),
            tenant_id=UUID(tenant_id),
            order_id=order_id,
            vendor_id=UUID(item_req.vendor_id),
            dish_name=item_req.dish_name,
            dish_id=item_req.dish_id,
            quantity=item_req.quantity,
            unit_price_fen=item_req.unit_price_fen,
            subtotal_fen=subtotal,
            notes=item_req.notes,
            status="pending",
        )
        db.add(item)
        order_items.append(item)

    await db.commit()
    await db.refresh(order)

    logger.info(
        "food_court_order_created",
        order_id=str(order_id),
        order_no=order.order_no,
        fc_id=fc_id,
        total_fen=total_amount_fen,
        vendor_count=len(vendor_ids),
    )

    data = _order_row_to_dict(order)
    data["items"] = [_item_row_to_dict(i) for i in order_items]
    return _ok(data)


@router.get("/{fc_id}/orders/{order_id}")
async def get_food_court_order(
    fc_id: str,
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """订单详情（含各档口菜品明细，按档口分组）"""
    tenant_id = _get_tenant_id(request)

    order_result = await db.execute(
        select(FoodCourtOrder).where(
            FoodCourtOrder.id == UUID(order_id),
            FoodCourtOrder.food_court_id == UUID(fc_id),
            FoodCourtOrder.tenant_id == UUID(tenant_id),
        )
    )
    order = order_result.scalar_one_or_none()
    if not order:
        _err("订单不存在", 404)

    items_result = await db.execute(
        select(FoodCourtOrderItem)
        .where(
            FoodCourtOrderItem.order_id == UUID(order_id),
            FoodCourtOrderItem.tenant_id == UUID(tenant_id),
        )
        .order_by(FoodCourtOrderItem.vendor_id, FoodCourtOrderItem.created_at)
    )
    items = items_result.scalars().all()

    # 按档口分组
    vendor_groups: dict[str, list] = {}
    for item in items:
        vid = str(item.vendor_id)
        vendor_groups.setdefault(vid, []).append(_item_row_to_dict(item))

    data = _order_row_to_dict(order)
    data["items"] = [_item_row_to_dict(i) for i in items]
    data["vendor_groups"] = vendor_groups
    data["vendor_count"] = len(vendor_groups)
    return _ok(data)


@router.post("/{fc_id}/orders/{order_id}/pay")
async def pay_food_court_order(
    fc_id: str,
    order_id: str,
    req: PayFoodCourtOrderReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """统一结账

    关键业务流程：
    1. FOR UPDATE 悲观锁防并发重复支付
    2. 幂等键检查
    3. 金额校验（实付 >= 应付）
    4. 标记订单 paid，更新支付方式和时间
    5. 更新所有订单行状态为 preparing
    6. 按 vendor 分组异步推送 Redis Streams KDS 事件（各档口只收自己的菜）
    7. 按 vendor 生成/累加 pending 结算记录（不立即结算，等日结触发）
    8. 发送统一事件总线 ORDER.PAID
    """
    tenant_id = _get_tenant_id(request)

    # ── 1. FOR UPDATE 锁定订单，防并发重复支付 ──────────────────────────────
    order_result = await db.execute(
        text("""
            SELECT id, food_court_id, order_no, total_amount_fen, status
            FROM food_court_orders
            WHERE id = :order_id
              AND food_court_id = :fc_id
              AND tenant_id = :tenant_id
            FOR UPDATE
        """),
        {"order_id": order_id, "fc_id": fc_id, "tenant_id": tenant_id},
    )
    row = order_result.fetchone()
    if not row:
        _err("订单不存在", 404)
    if row.status == "paid":
        _err("订单已支付，请勿重复提交", 409)
    if row.status == "cancelled":
        _err("订单已取消，无法支付")
    if row.status != "pending":
        _err(f"订单当前状态 {row.status} 不支持支付")

    # ── 2. 幂等键检查 ─────────────────────────────────────────────────────────
    if req.idempotency_key:
        dup = await db.execute(
            text("""
                SELECT id FROM food_court_orders
                WHERE idempotency_key = :key
                  AND tenant_id = :tenant_id
                  AND id != :order_id
            """),
            {"key": req.idempotency_key, "tenant_id": tenant_id, "order_id": order_id},
        )
        if dup.fetchone():
            _err("幂等键已使用，疑似重复请求", 409)

    # ── 3. 金额校验 ───────────────────────────────────────────────────────────
    if req.amount_fen < row.total_amount_fen:
        _err(f"实付金额({req.amount_fen}分) < 应付金额({row.total_amount_fen}分)")

    # ── 4. 标记订单已支付 ─────────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            UPDATE food_court_orders
            SET status = 'paid',
                payment_method = :method,
                paid_at = :paid_at,
                idempotency_key = :idem_key,
                updated_at = :now
            WHERE id = :order_id AND tenant_id = :tenant_id
        """),
        {
            "method": req.payment_method,
            "paid_at": now,
            "idem_key": req.idempotency_key,
            "now": now,
            "order_id": order_id,
            "tenant_id": tenant_id,
        },
    )

    # ── 5. 更新所有订单行为 preparing ─────────────────────────────────────────
    await db.execute(
        text("""
            UPDATE food_court_order_items
            SET status = 'preparing', updated_at = :now
            WHERE order_id = :order_id AND tenant_id = :tenant_id
        """),
        {"order_id": order_id, "now": now, "tenant_id": tenant_id},
    )

    # ── 6. 查询订单行，按 vendor 分组 ────────────────────────────────────────
    items_result = await db.execute(
        select(FoodCourtOrderItem, FoodCourtVendor)
        .join(FoodCourtVendor, FoodCourtOrderItem.vendor_id == FoodCourtVendor.id)
        .where(
            FoodCourtOrderItem.order_id == UUID(order_id),
            FoodCourtOrderItem.tenant_id == UUID(tenant_id),
        )
    )
    rows = items_result.all()

    vendor_items: dict[str, tuple] = {}  # vendor_id -> (vendor, [items])
    for item, vendor in rows:
        vid = str(vendor.id)
        if vid not in vendor_items:
            vendor_items[vid] = (vendor, [])
        vendor_items[vid][1].append(item)

    # ── 7. 生成各档口 pending 结算记录 ───────────────────────────────────────
    settlement_ids = []
    kds_tasks = []
    today = now.date()

    # 批量加载当日所有档口的 pending 结算记录（避免 N+1）
    all_vendor_uuids = [UUID(vid) for vid in vendor_items]
    batch_result = await db.execute(
        select(FoodCourtVendorSettlement).where(
            FoodCourtVendorSettlement.vendor_id.in_(all_vendor_uuids),
            FoodCourtVendorSettlement.food_court_id == UUID(fc_id),
            FoodCourtVendorSettlement.tenant_id == UUID(tenant_id),
            FoodCourtVendorSettlement.settlement_date == today,
            FoodCourtVendorSettlement.status == "pending",
        )
    )
    settlement_by_vendor: dict[str, FoodCourtVendorSettlement] = {
        str(s.vendor_id): s for s in batch_result.scalars().all()
    }

    for vid, (vendor, items) in vendor_items.items():
        vendor_gross = sum(i.subtotal_fen for i in items)
        vendor_item_count = sum(i.quantity for i in items)
        commission_rate = float(vendor.commission_rate) if vendor.commission_rate else 0.0
        commission_fen = int(vendor_gross * commission_rate)
        net_amount_fen = vendor_gross - commission_fen

        # 当日已存在 pending 记录则累加，否则新建
        existing = settlement_by_vendor.get(vid)

        if existing:
            existing.order_count += 1
            existing.item_count += vendor_item_count
            existing.gross_amount_fen += vendor_gross
            existing.commission_fen += commission_fen
            existing.net_amount_fen += net_amount_fen
            settlement_ids.append(str(existing.id))
        else:
            new_s = FoodCourtVendorSettlement(
                id=uuid4(),
                tenant_id=UUID(tenant_id),
                vendor_id=vendor.id,
                food_court_id=UUID(fc_id),
                settlement_date=today,
                order_count=1,
                item_count=vendor_item_count,
                gross_amount_fen=vendor_gross,
                commission_fen=commission_fen,
                net_amount_fen=net_amount_fen,
                status="pending",
            )
            db.add(new_s)
            settlement_ids.append(str(new_s.id))

        kds_tasks.append((vendor, items))

    await db.commit()

    # ── 8. DB提交后异步推送各档口 KDS（失败不回滚支付）──────────────────────
    for vendor, items in kds_tasks:
        asyncio.create_task(_push_kds_event(tenant_id, vendor, items, row.order_no))

    # ── 9. 统一事件总线 ORDER.PAID ────────────────────────────────────────────
    asyncio.create_task(
        emit_event(
            event_type=OrderEventType.PAID,
            tenant_id=tenant_id,
            stream_id=order_id,
            payload={
                "order_no": row.order_no,
                "total_fen": row.total_amount_fen,
                "payment_method": req.payment_method,
                "fc_id": fc_id,
                "vendor_count": len(vendor_items),
            },
            source_service="tx-trade",
            metadata={"channel": "food_court"},
        )
    )

    logger.info(
        "food_court_order_paid",
        order_id=order_id,
        order_no=row.order_no,
        amount_fen=req.amount_fen,
        method=req.payment_method,
        vendor_count=len(vendor_items),
        tenant_id=tenant_id,
    )

    return _ok(
        {
            "order_id": order_id,
            "order_no": row.order_no,
            "status": "paid",
            "paid_at": now.isoformat(),
            "total_amount_fen": row.total_amount_fen,
            "payment_method": req.payment_method,
            "kds_pushed_vendors": len(vendor_items),
            "settlement_records": settlement_ids,
        }
    )


@router.post("/{fc_id}/orders/{order_id}/cancel")
async def cancel_food_court_order(
    fc_id: str,
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """取消订单（仅限 pending 状态）"""
    tenant_id = _get_tenant_id(request)

    order_result = await db.execute(
        select(FoodCourtOrder).where(
            FoodCourtOrder.id == UUID(order_id),
            FoodCourtOrder.food_court_id == UUID(fc_id),
            FoodCourtOrder.tenant_id == UUID(tenant_id),
        )
    )
    order = order_result.scalar_one_or_none()
    if not order:
        _err("订单不存在", 404)
    if order.status != "pending":
        _err(f"订单状态 {order.status} 不可取消（仅 pending 订单可取消）")

    now = datetime.now(timezone.utc)
    order.status = "cancelled"
    await db.execute(
        text("""
            UPDATE food_court_order_items
            SET status = 'cancelled', updated_at = :now
            WHERE order_id = :order_id AND tenant_id = :tenant_id
        """),
        {"order_id": order_id, "now": now, "tenant_id": tenant_id},
    )
    await db.commit()

    logger.info("food_court_order_cancelled", order_id=order_id, fc_id=fc_id)
    return _ok({"order_id": order_id, "status": "cancelled"})


# ─── 档口KDS端点（各档口独立屏幕） ───────────────────────────────────────────


@router.get("/vendor/{v_id}/queue")
async def get_vendor_kds_queue(
    v_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """当前档口待出餐列表（KDS主视图，先进先出排序）"""
    tenant_id = _get_tenant_id(request)

    result = await db.execute(
        select(FoodCourtOrderItem, FoodCourtOrder)
        .join(FoodCourtOrder, FoodCourtOrderItem.order_id == FoodCourtOrder.id)
        .where(
            FoodCourtOrderItem.vendor_id == UUID(v_id),
            FoodCourtOrderItem.tenant_id == UUID(tenant_id),
            FoodCourtOrderItem.status.in_(["pending", "preparing"]),
            FoodCourtOrder.status.in_(["paid"]),
        )
        .order_by(FoodCourtOrder.paid_at.asc())
        .limit(limit)
    )
    rows = result.all()

    queue = []
    for item, order in rows:
        d = _item_row_to_dict(item)
        d["order_no"] = order.order_no
        d["order_paid_at"] = order.paid_at.isoformat() if order.paid_at else None
        queue.append(d)

    return _ok(
        {
            "vendor_id": v_id,
            "queue": queue,
            "pending_count": sum(1 for item, _ in rows if item.status == "pending"),
            "preparing_count": sum(1 for item, _ in rows if item.status == "preparing"),
        }
    )


@router.post("/vendor/{v_id}/items/{item_id}/ready")
async def mark_item_ready(
    v_id: str,
    item_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """档口标记菜品已出餐（KDS操作：preparing → ready）"""
    tenant_id = _get_tenant_id(request)

    result = await db.execute(
        select(FoodCourtOrderItem).where(
            FoodCourtOrderItem.id == UUID(item_id),
            FoodCourtOrderItem.vendor_id == UUID(v_id),
            FoodCourtOrderItem.tenant_id == UUID(tenant_id),
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        _err("菜品不存在", 404)
    if item.status not in ("pending", "preparing"):
        _err(f"菜品状态 {item.status} 无法标记出餐")

    now = datetime.now(timezone.utc)
    item.status = "ready"
    item.ready_at = now
    await db.commit()

    # 检查同一订单该档口所有菜品是否全部出餐
    all_items_result = await db.execute(
        select(FoodCourtOrderItem).where(
            FoodCourtOrderItem.order_id == item.order_id,
            FoodCourtOrderItem.vendor_id == UUID(v_id),
            FoodCourtOrderItem.tenant_id == UUID(tenant_id),
        )
    )
    all_items = all_items_result.scalars().all()
    all_ready = all(i.status in ("ready", "served") for i in all_items)

    logger.info(
        "food_court_item_ready",
        item_id=item_id,
        vendor_id=v_id,
        order_id=str(item.order_id),
        all_vendor_items_ready=all_ready,
    )

    return _ok(
        {
            "item_id": item_id,
            "status": "ready",
            "ready_at": now.isoformat(),
            "all_vendor_items_ready": all_ready,
        }
    )


@router.get("/vendor/{v_id}/stats")
async def get_vendor_stats(
    v_id: str,
    request: Request,
    stats_date: Optional[str] = Query(default=None, description="查询日期 YYYY-MM-DD，默认今日"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """档口今日营业统计（KDS右上角看板数据）"""
    tenant_id = _get_tenant_id(request)

    if stats_date:
        try:
            query_date = date.fromisoformat(stats_date)
        except ValueError:
            _err("日期格式错误，请使用 YYYY-MM-DD")
    else:
        query_date = datetime.now(timezone.utc).date()

    settlement_result = await db.execute(
        select(FoodCourtVendorSettlement).where(
            FoodCourtVendorSettlement.vendor_id == UUID(v_id),
            FoodCourtVendorSettlement.tenant_id == UUID(tenant_id),
            FoodCourtVendorSettlement.settlement_date == query_date,
        )
    )
    settlement = settlement_result.scalar_one_or_none()

    ready_count_result = await db.execute(
        text("""
            SELECT COUNT(*) FROM food_court_order_items fci
            JOIN food_court_orders fco ON fci.order_id = fco.id
            WHERE fci.vendor_id = :v_id
              AND fci.tenant_id = :tenant_id
              AND fci.status = 'ready'
              AND fco.paid_at::date = :query_date
        """),
        {"v_id": v_id, "tenant_id": tenant_id, "query_date": query_date},
    )
    ready_count = ready_count_result.scalar_one()

    pending_count_result = await db.execute(
        text("""
            SELECT COUNT(*) FROM food_court_order_items fci
            JOIN food_court_orders fco ON fci.order_id = fco.id
            WHERE fci.vendor_id = :v_id
              AND fci.tenant_id = :tenant_id
              AND fci.status IN ('pending', 'preparing')
              AND fco.status = 'paid'
        """),
        {"v_id": v_id, "tenant_id": tenant_id},
    )
    pending_in_queue = pending_count_result.scalar_one()

    return _ok(
        {
            "vendor_id": v_id,
            "date": query_date.isoformat(),
            "order_count": settlement.order_count if settlement else 0,
            "item_count": settlement.item_count if settlement else 0,
            "gross_amount_fen": settlement.gross_amount_fen if settlement else 0,
            "commission_fen": settlement.commission_fen if settlement else 0,
            "net_amount_fen": settlement.net_amount_fen if settlement else 0,
            "settlement_status": settlement.status if settlement else "no_data",
            "queue_pending": pending_in_queue,
            "items_ready_today": ready_count,
        }
    )


# ─── 结算端点（总部财务） ─────────────────────────────────────────────────────


@router.get("/{fc_id}/settlements")
async def list_settlements(
    fc_id: str,
    request: Request,
    vendor_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None, description="pending/settled"),
    start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """结算记录列表"""
    tenant_id = _get_tenant_id(request)

    q = select(FoodCourtVendorSettlement).where(
        FoodCourtVendorSettlement.food_court_id == UUID(fc_id),
        FoodCourtVendorSettlement.tenant_id == UUID(tenant_id),
    )
    if vendor_id:
        q = q.where(FoodCourtVendorSettlement.vendor_id == UUID(vendor_id))
    if status:
        q = q.where(FoodCourtVendorSettlement.status == status)
    if start_date:
        q = q.where(FoodCourtVendorSettlement.settlement_date >= date.fromisoformat(start_date))
    if end_date:
        q = q.where(FoodCourtVendorSettlement.settlement_date <= date.fromisoformat(end_date))

    count_q = select(sa_func.count()).select_from(q.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    q = q.order_by(FoodCourtVendorSettlement.settlement_date.desc()).offset((page - 1) * size).limit(size)
    result = await db.execute(q)
    items = result.scalars().all()

    return _ok({"items": [_settlement_row_to_dict(s) for s in items], "total": total})


@router.post("/{fc_id}/settlements/generate")
async def generate_settlements(
    fc_id: str,
    req: GenerateSettlementReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """生成指定日期结算单（日结触发）

    按每个档口汇总当日已付订单 → 计算抽成 → 生成/覆盖 pending 结算记录。
    已 settled 的不重算，支持重新生成 pending 记录（纠错场景）。
    """
    tenant_id = _get_tenant_id(request)

    try:
        settlement_date = date.fromisoformat(req.settlement_date)
    except ValueError:
        _err("日期格式错误，请使用 YYYY-MM-DD")

    vendor_q = select(FoodCourtVendor).where(
        FoodCourtVendor.food_court_id == UUID(fc_id),
        FoodCourtVendor.tenant_id == UUID(tenant_id),
        FoodCourtVendor.is_deleted == False,
    )
    if req.vendor_ids:
        vendor_q = vendor_q.where(FoodCourtVendor.id.in_([UUID(vid) for vid in req.vendor_ids]))

    vendors_result = await db.execute(vendor_q)
    vendors = vendors_result.scalars().all()
    if not vendors:
        _err("没有找到需要结算的档口")

    generated = []
    for vendor in vendors:
        agg_result = await db.execute(
            text("""
                SELECT
                    COUNT(DISTINCT fco.id) AS order_count,
                    COALESCE(SUM(fci.quantity), 0) AS item_count,
                    COALESCE(SUM(fci.subtotal_fen), 0) AS gross_amount_fen
                FROM food_court_order_items fci
                JOIN food_court_orders fco ON fci.order_id = fco.id
                WHERE fci.vendor_id = :vendor_id
                  AND fci.tenant_id = :tenant_id
                  AND fco.status IN ('paid', 'completed')
                  AND fco.paid_at::date = :settlement_date
            """),
            {
                "vendor_id": str(vendor.id),
                "tenant_id": tenant_id,
                "settlement_date": settlement_date,
            },
        )
        agg = agg_result.fetchone()

        gross_amount_fen = agg.gross_amount_fen if agg else 0
        order_count = agg.order_count if agg else 0
        item_count = agg.item_count if agg else 0
        commission_rate = float(vendor.commission_rate) if vendor.commission_rate else 0.0
        commission_fen = int(gross_amount_fen * commission_rate)
        net_amount_fen = gross_amount_fen - commission_fen

        existing_result = await db.execute(
            select(FoodCourtVendorSettlement).where(
                FoodCourtVendorSettlement.vendor_id == vendor.id,
                FoodCourtVendorSettlement.food_court_id == UUID(fc_id),
                FoodCourtVendorSettlement.tenant_id == UUID(tenant_id),
                FoodCourtVendorSettlement.settlement_date == settlement_date,
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            if existing.status == "settled":
                generated.append(
                    {
                        "vendor_id": str(vendor.id),
                        "vendor_name": vendor.vendor_name,
                        "action": "skipped_already_settled",
                        "settlement_id": str(existing.id),
                    }
                )
                continue
            # 覆盖更新 pending 记录
            existing.order_count = order_count
            existing.item_count = item_count
            existing.gross_amount_fen = gross_amount_fen
            existing.commission_fen = commission_fen
            existing.net_amount_fen = net_amount_fen
            generated.append(
                {
                    "vendor_id": str(vendor.id),
                    "vendor_name": vendor.vendor_name,
                    "action": "updated",
                    "settlement_id": str(existing.id),
                    "gross_amount_fen": gross_amount_fen,
                    "net_amount_fen": net_amount_fen,
                }
            )
        else:
            new_s = FoodCourtVendorSettlement(
                id=uuid4(),
                tenant_id=UUID(tenant_id),
                vendor_id=vendor.id,
                food_court_id=UUID(fc_id),
                settlement_date=settlement_date,
                order_count=order_count,
                item_count=item_count,
                gross_amount_fen=gross_amount_fen,
                commission_fen=commission_fen,
                net_amount_fen=net_amount_fen,
                status="pending",
            )
            db.add(new_s)
            generated.append(
                {
                    "vendor_id": str(vendor.id),
                    "vendor_name": vendor.vendor_name,
                    "action": "created",
                    "gross_amount_fen": gross_amount_fen,
                    "net_amount_fen": net_amount_fen,
                }
            )

    await db.commit()

    logger.info(
        "food_court_settlements_generated",
        fc_id=fc_id,
        settlement_date=str(settlement_date),
        vendor_count=len(vendors),
        tenant_id=tenant_id,
    )

    return _ok(
        {
            "settlement_date": req.settlement_date,
            "generated_count": len(generated),
            "results": generated,
        }
    )


@router.post("/{fc_id}/settlements/{s_id}/confirm")
async def confirm_settlement(
    fc_id: str,
    s_id: str,
    request: Request,
    operator_id: Optional[str] = Query(default=None, description="财务操作人ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """确认结算（标记已打款到档口账户）"""
    tenant_id = _get_tenant_id(request)

    result = await db.execute(
        select(FoodCourtVendorSettlement).where(
            FoodCourtVendorSettlement.id == UUID(s_id),
            FoodCourtVendorSettlement.food_court_id == UUID(fc_id),
            FoodCourtVendorSettlement.tenant_id == UUID(tenant_id),
        )
    )
    settlement = result.scalar_one_or_none()
    if not settlement:
        _err("结算记录不存在", 404)
    if settlement.status == "settled":
        _err("结算记录已确认，无需重复操作", 409)
    if settlement.status != "pending":
        _err(f"结算状态 {settlement.status} 不可确认")

    now = datetime.now(timezone.utc)
    settlement.status = "settled"
    settlement.settled_at = now
    settlement.operator_id = operator_id
    await db.commit()

    logger.info("food_court_settlement_confirmed", s_id=s_id, fc_id=fc_id, operator_id=operator_id)
    return _ok(_settlement_row_to_dict(settlement))


@router.get("/{fc_id}/settlements/summary")
async def get_settlement_summary(
    fc_id: str,
    request: Request,
    start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """结算汇总报表（总部财务视角）

    各档口指定时间段：总营收/总抽成/已结算/未结算拆分。
    """
    tenant_id = _get_tenant_id(request)

    params: dict = {"fc_id": fc_id, "tenant_id": tenant_id}
    date_filter = ""
    if start_date:
        date_filter += " AND fcvs.settlement_date >= :start_date"
        params["start_date"] = date.fromisoformat(start_date)
    if end_date:
        date_filter += " AND fcvs.settlement_date <= :end_date"
        params["end_date"] = date.fromisoformat(end_date)

    summary_result = await db.execute(
        text(f"""
            SELECT
                fcv.id               AS vendor_id,
                fcv.vendor_code,
                fcv.vendor_name,
                fcv.category,
                COUNT(fcvs.id)       AS settlement_days,
                COALESCE(SUM(fcvs.order_count), 0)     AS total_orders,
                COALESCE(SUM(fcvs.item_count), 0)      AS total_items,
                COALESCE(SUM(fcvs.gross_amount_fen), 0) AS total_gross_fen,
                COALESCE(SUM(fcvs.commission_fen), 0)  AS total_commission_fen,
                COALESCE(SUM(fcvs.net_amount_fen), 0)  AS total_net_fen,
                COALESCE(SUM(CASE WHEN fcvs.status = 'settled' THEN fcvs.net_amount_fen ELSE 0 END), 0) AS settled_fen,
                COALESCE(SUM(CASE WHEN fcvs.status = 'pending' THEN fcvs.net_amount_fen ELSE 0 END), 0) AS pending_fen
            FROM food_court_vendors fcv
            LEFT JOIN food_court_vendor_settlements fcvs
                ON fcv.id = fcvs.vendor_id
               AND fcvs.tenant_id = :tenant_id
               {date_filter}
            WHERE fcv.food_court_id = :fc_id
              AND fcv.tenant_id = :tenant_id
              AND fcv.is_deleted = FALSE
            GROUP BY fcv.id, fcv.vendor_code, fcv.vendor_name, fcv.category, fcv.display_order
            ORDER BY fcv.display_order
        """),
        params,
    )
    rows = summary_result.fetchall()

    vendor_summaries = [
        {
            "vendor_id": str(r.vendor_id),
            "vendor_code": r.vendor_code,
            "vendor_name": r.vendor_name,
            "category": r.category,
            "settlement_days": r.settlement_days,
            "total_orders": r.total_orders,
            "total_items": r.total_items,
            "total_gross_fen": r.total_gross_fen,
            "total_commission_fen": r.total_commission_fen,
            "total_net_fen": r.total_net_fen,
            "settled_fen": r.settled_fen,
            "pending_fen": r.pending_fen,
        }
        for r in rows
    ]

    fc_totals = {
        "total_gross_fen": sum(v["total_gross_fen"] for v in vendor_summaries),
        "total_commission_fen": sum(v["total_commission_fen"] for v in vendor_summaries),
        "total_net_fen": sum(v["total_net_fen"] for v in vendor_summaries),
        "settled_fen": sum(v["settled_fen"] for v in vendor_summaries),
        "pending_fen": sum(v["pending_fen"] for v in vendor_summaries),
        "total_orders": sum(v["total_orders"] for v in vendor_summaries),
    }

    return _ok(
        {
            "food_court_id": fc_id,
            "period": {"start_date": start_date, "end_date": end_date},
            "fc_totals": fc_totals,
            "vendors": vendor_summaries,
        }
    )
