"""扫码自助点单 API — 顾客扫桌码 → 浏览菜单 → 自助加菜 → 批量提交厨房

对标：Toast Order & Pay + Square AI Recommendations

四个端点：
1. POST /scan-order/init       — 扫桌码初始化（创建或追加订单 + 智能推荐）
2. POST /scan-order/add-item   — 顾客自助加菜
3. POST /scan-order/submit     — 攒一批提交到厨房（触发 KDS 分单 + 厨打）
4. GET  /scan-order/status/{order_id} — 出餐进度查询
"""
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from shared.ontology.src.entities import Dish, Order, OrderItem
from shared.ontology.src.enums import OrderStatus

from ..models.enums import TableStatus
from ..models.tables import Table
from ..services.cashier_engine import CashierEngine
from ..services.kds_dispatch import dispatch_order_to_kds
from ..services.menu_recommender import get_recommendations

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/scan-order", tags=["scan-order"])

# ─── 通用工具 ───

SCAN_ORDER_CHANNEL = "scan_order"


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> dict:
    raise HTTPException(status_code=code, detail={"ok": False, "data": None, "error": {"message": msg}})


# ─── 请求模型 ───


class ScanOrderInitReq(BaseModel):
    table_no: str
    store_id: str
    customer_id: Optional[str] = None
    guest_count: int = Field(default=1, ge=1)


class ScanOrderAddItemReq(BaseModel):
    order_id: str
    dish_id: str
    qty: int = Field(ge=1, default=1)
    notes: Optional[str] = None


class ScanOrderSubmitReq(BaseModel):
    order_id: str


# ─── 1. 扫桌码初始化 ───


@router.post("/init")
async def scan_order_init(
    req: ScanOrderInitReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """扫桌码初始化

    - 桌台有在进行的订单 → 返回现有订单（追加模式）
    - 桌台空闲 → 创建新订单
    - 同时返回菜单列表 + AI 智能推荐
    """
    tenant_id = _get_tenant_id(request)
    tid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(req.store_id)

    # 查桌台
    table_result = await db.execute(
        select(Table).where(
            Table.store_id == store_uuid,
            Table.table_no == req.table_no,
            Table.tenant_id == tid,
            Table.is_active == True,  # noqa: E712
        )
    )
    table = table_result.scalar_one_or_none()
    if not table:
        _err(f"桌台不存在: {req.table_no}", 404)
        return  # unreachable

    # 判断桌台是否已有订单（追加模式）
    existing_order = None
    existing_items: list[dict] = []
    if table.status == TableStatus.occupied.value and table.current_order_id:
        order_result = await db.execute(
            select(Order).where(
                Order.id == table.current_order_id,
                Order.tenant_id == tid,
                Order.is_deleted == False,  # noqa: E712
            )
        )
        existing_order = order_result.scalar_one_or_none()

        if existing_order:
            # 加载已有菜品
            items_result = await db.execute(
                select(OrderItem).where(
                    OrderItem.order_id == existing_order.id,
                    OrderItem.tenant_id == tid,
                )
            )
            for item in items_result.scalars().all():
                existing_items.append({
                    "item_id": str(item.id),
                    "dish_id": str(item.dish_id) if item.dish_id else "",
                    "dish_name": item.item_name,
                    "quantity": item.quantity,
                    "unit_price_fen": item.unit_price_fen,
                    "notes": item.notes or "",
                    "sent_to_kds": item.sent_to_kds_flag,
                })

    # 如果桌台空闲，创建新订单
    order_id: str
    order_no: str
    is_new_order = False

    if existing_order:
        order_id = str(existing_order.id)
        order_no = existing_order.order_no
    else:
        # 使用 CashierEngine 开台
        engine = CashierEngine(db, tenant_id)
        try:
            result = await engine.open_table(
                store_id=req.store_id,
                table_no=req.table_no,
                waiter_id="scan_order",  # 扫码点单无服务员
                guest_count=req.guest_count,
                order_type="dine_in",
                customer_id=req.customer_id,
            )
            order_id = result["order_id"]
            order_no = result["order_no"]
            is_new_order = True
        except ValueError as e:
            _err(str(e))
            return

        # 标记渠道为扫码点单
        await db.execute(
            Order.__table__.update()
            .where(Order.id == uuid.UUID(order_id))
            .values(sales_channel_id=SCAN_ORDER_CHANNEL)
        )

    # 获取菜单
    menu_items = await _get_menu_items(db, tid, store_uuid)

    # 获取智能推荐
    recommendations = await get_recommendations(
        db=db,
        tenant_id=tenant_id,
        store_id=req.store_id,
        customer_id=req.customer_id,
        table_no=req.table_no,
    )

    await db.commit()

    logger.info(
        "scan_order_init",
        store_id=req.store_id,
        table_no=req.table_no,
        order_id=order_id,
        is_new_order=is_new_order,
        menu_count=len(menu_items),
        recommendation_count=len(recommendations),
    )

    return _ok({
        "order_id": order_id,
        "order_no": order_no,
        "table_no": req.table_no,
        "is_new_order": is_new_order,
        "existing_items": existing_items,
        "menu_items": menu_items,
        "recommendations": recommendations,
    })


# ─── 2. 顾客自助加菜 ───


@router.post("/add-item")
async def scan_order_add_item(
    req: ScanOrderAddItemReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """顾客自助加菜

    调用 CashierEngine.add_item()，标记 channel = scan_order。
    """
    tenant_id = _get_tenant_id(request)
    tid = uuid.UUID(tenant_id)

    # 查菜品信息（获取名称和价格）
    dish_uuid = uuid.UUID(req.dish_id)
    dish_result = await db.execute(
        select(Dish).where(
            Dish.id == dish_uuid,
            Dish.tenant_id == tid,
            Dish.is_deleted == False,  # noqa: E712
        )
    )
    dish = dish_result.scalar_one_or_none()
    if not dish:
        _err("菜品不存在", 404)
        return

    if not dish.is_available:
        _err("该菜品已沽清，请选择其他菜品")
        return

    # 调用收银引擎加菜
    engine = CashierEngine(db, tenant_id)
    try:
        result = await engine.add_item(
            order_id=req.order_id,
            dish_id=req.dish_id,
            dish_name=dish.dish_name,
            qty=req.qty,
            unit_price_fen=dish.price_fen,
            notes=req.notes,
        )
    except ValueError as e:
        _err(str(e))
        return

    await db.commit()

    logger.info(
        "scan_order_add_item",
        order_id=req.order_id,
        dish_id=req.dish_id,
        dish_name=dish.dish_name,
        qty=req.qty,
        channel=SCAN_ORDER_CHANNEL,
    )

    return _ok(result)


# ─── 3. 提交订单到厨房 ───


@router.post("/submit")
async def scan_order_submit(
    req: ScanOrderSubmitReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """提交订单到厨房

    攒一批菜品一次性提交，触发 KDS 分单 + 厨打。
    仅提交 sent_to_kds_flag=False 的菜品（支持追加场景）。
    """
    tenant_id = _get_tenant_id(request)
    tid = uuid.UUID(tenant_id)
    order_uuid = uuid.UUID(req.order_id)

    # 查订单
    order_result = await db.execute(
        select(Order).where(
            Order.id == order_uuid,
            Order.tenant_id == tid,
            Order.is_deleted == False,  # noqa: E712
        )
    )
    order = order_result.scalar_one_or_none()
    if not order:
        _err("订单不存在", 404)
        return

    if order.status not in (OrderStatus.pending.value, "open", "dining"):
        _err(f"订单状态 {order.status} 不允许提交")
        return

    # 查未发送到 KDS 的菜品
    items_result = await db.execute(
        select(OrderItem).where(
            OrderItem.order_id == order_uuid,
            OrderItem.tenant_id == tid,
            OrderItem.sent_to_kds_flag == False,  # noqa: E712
            OrderItem.return_flag == False,        # noqa: E712
        )
    )
    unsent_items = list(items_result.scalars().all())

    if not unsent_items:
        _err("没有新增菜品需要提交")
        return

    # 构造 KDS 分单数据
    kds_items = []
    for item in unsent_items:
        kds_items.append({
            "dish_id": str(item.dish_id) if item.dish_id else "",
            "item_name": item.item_name,
            "quantity": item.quantity,
            "order_item_id": str(item.id),
            "notes": item.notes or "",
        })

    # 触发 KDS 分单 + 厨打
    dispatch_result = await dispatch_order_to_kds(
        order_id=req.order_id,
        order_items=kds_items,
        tenant_id=tenant_id,
        db=db,
        table_number=order.table_number or "",
        order_no=order.order_no,
        auto_print=True,
    )

    # 标记已发送 KDS
    for item in unsent_items:
        item.sent_to_kds_flag = True

    await db.commit()

    logger.info(
        "scan_order_submitted",
        order_id=req.order_id,
        items_submitted=len(unsent_items),
        channel=SCAN_ORDER_CHANNEL,
    )

    return _ok({
        "order_id": req.order_id,
        "items_submitted": len(unsent_items),
        "dispatch": dispatch_result,
    })


# ─── 4. 出餐进度查询 ───


@router.get("/status/{order_id}")
async def scan_order_status(
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """查询出餐进度

    返回每道菜的 KDS 状态：pending(待制作) / cooking(制作中) / done(已出餐)
    """
    tenant_id = _get_tenant_id(request)
    tid = uuid.UUID(tenant_id)
    order_uuid = uuid.UUID(order_id)

    # 查订单
    order_result = await db.execute(
        select(Order).where(
            Order.id == order_uuid,
            Order.tenant_id == tid,
            Order.is_deleted == False,  # noqa: E712
        )
    )
    order = order_result.scalar_one_or_none()
    if not order:
        _err("订单不存在", 404)
        return

    # 查菜品及 KDS 状态
    items_result = await db.execute(
        select(OrderItem).where(
            OrderItem.order_id == order_uuid,
            OrderItem.tenant_id == tid,
            OrderItem.return_flag == False,  # noqa: E712
        )
    )
    items = list(items_result.scalars().all())

    item_statuses = []
    for item in items:
        # KDS 状态来自 kds_station + sent_to_kds_flag 综合判断
        # 实际状态由 KDS 模块回写到 order_item 或 kds_task 表
        kds_status = "pending"
        if not item.sent_to_kds_flag:
            kds_status = "not_submitted"  # 还没提交到厨房
        else:
            # 从 item 的 metadata 或关联 kds_task 获取状态
            meta = getattr(item, "item_metadata", None) or {}
            if isinstance(meta, dict):
                kds_status = meta.get("kds_status", "pending")

        item_statuses.append({
            "item_id": str(item.id),
            "dish_name": item.item_name,
            "quantity": item.quantity,
            "kds_status": kds_status,
            "kds_station": item.kds_station or "",
        })

    # 汇总统计
    total = len(item_statuses)
    done_count = sum(1 for i in item_statuses if i["kds_status"] == "done")
    cooking_count = sum(1 for i in item_statuses if i["kds_status"] == "cooking")
    pending_count = total - done_count - cooking_count

    return _ok({
        "order_id": order_id,
        "order_no": order.order_no,
        "order_status": order.status,
        "items": item_statuses,
        "summary": {
            "total": total,
            "done": done_count,
            "cooking": cooking_count,
            "pending": pending_count,
        },
    })


# ─── 内部工具 ───


async def _get_menu_items(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
) -> list[dict]:
    """获取门店在售菜单"""
    result = await db.execute(
        select(Dish).where(
            Dish.tenant_id == tenant_id,
            Dish.is_available == True,  # noqa: E712
            Dish.is_deleted == False,   # noqa: E712
            (Dish.store_id == store_id) | (Dish.store_id == None),  # noqa: E711
        ).order_by(Dish.sort_order, Dish.dish_name)
    )
    dishes = result.scalars().all()

    return [
        {
            "dish_id": str(d.id),
            "dish_name": d.dish_name,
            "price_fen": d.price_fen,
            "original_price_fen": d.original_price_fen,
            "image_url": d.image_url or "",
            "description": d.description or "",
            "category_id": str(d.category_id) if d.category_id else "",
            "tags": d.tags or [],
            "spicy_level": d.spicy_level,
            "unit": d.unit,
            "is_recommended": d.is_recommended,
        }
        for d in dishes
    ]
