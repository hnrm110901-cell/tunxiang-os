"""扫码点餐服务 — 桌码生成/解析 + 扫码下单 + 加菜 + 结账 + KDS同步 + 统计

桌码格式: TX-{store_id简码}-{table_no}
同桌多人可同时点餐，合并到同一订单。
下单后自动同步KDS。
"""
import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Dish, Order, OrderItem
from shared.ontology.src.enums import OrderStatus

from ..models.enums import TableStatus
from ..models.tables import Table
from ..services.kds_dispatch import dispatch_order_to_kds
from ..services.order_service import _gen_order_no

logger = structlog.get_logger()

SCAN_ORDER_CHANNEL = "scan_order"


def _store_short_code(store_id: str) -> str:
    """生成门店简码：取 store_id MD5 前6位大写"""
    return hashlib.md5(store_id.encode()).hexdigest()[:6].upper()


# ─── 桌码生成与解析 ───


def generate_table_qrcode(
    store_id: str,
    table_id: str,
    tenant_id: str,
    db: Optional[AsyncSession] = None,
) -> dict:
    """生成桌码（含store+table编码）

    桌码格式: TX-{store简码}-{table_no}
    返回桌码字符串和对应的小程序跳转路径。
    """
    short_code = _store_short_code(store_id)
    qrcode = f"TX-{short_code}-{table_id}"
    # 小程序扫码后跳转的页面路径
    miniapp_path = (
        f"/pages/scan-order/index?code={qrcode}"
        f"&store_id={store_id}&table_id={table_id}"
    )

    logger.info(
        "table_qrcode_generated",
        store_id=store_id,
        table_id=table_id,
        qrcode=qrcode,
        tenant_id=tenant_id,
    )

    return {
        "qrcode": qrcode,
        "store_id": store_id,
        "table_id": table_id,
        "miniapp_path": miniapp_path,
        "short_code": short_code,
    }


def parse_qrcode(code: str) -> dict:
    """解析桌码 → {store_short_code, table_id}

    桌码格式: TX-{store简码}-{table_no}
    返回解析后的门店简码和桌号。
    """
    if not code or not code.startswith("TX-"):
        raise ValueError(f"无效桌码格式: {code}")

    parts = code.split("-", 2)
    if len(parts) != 3:
        raise ValueError(f"桌码格式错误，期望 TX-XXXX-YYY: {code}")

    return {
        "store_short_code": parts[1],
        "table_id": parts[2],
        "raw_code": code,
    }


# ─── 扫码下单 ───


async def create_scan_order(
    store_id: str,
    table_id: str,
    items: list[dict],
    customer_id: Optional[str],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """扫码下单 — 创建订单并添加菜品

    如果桌台已有进行中的订单，则追加到现有订单。
    同桌多人可同时点餐，合并到同一订单。

    items格式: [{"dish_id": str, "quantity": int, "notes": str?}]
    """
    tid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    # 查桌台是否已有订单
    table_result = await db.execute(
        select(Table).where(
            Table.store_id == store_uuid,
            Table.table_no == table_id,
            Table.tenant_id == tid,
            Table.is_active == True,  # noqa: E712
        )
    )
    table = table_result.scalar_one_or_none()
    if not table:
        raise ValueError(f"桌台不存在: {table_id}")

    existing_order = None
    is_new_order = True

    # 桌台已占用且有订单 → 追加模式
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
        order_id = str(existing_order.id)
        order_no = existing_order.order_no
        is_new_order = False
    else:
        # 创建新订单
        order_no = _gen_order_no()
        new_order = Order(
            id=uuid.uuid4(),
            tenant_id=tid,
            order_no=order_no,
            store_id=store_uuid,
            table_number=table_id,
            customer_id=uuid.UUID(customer_id) if customer_id else None,
            sales_channel=SCAN_ORDER_CHANNEL,
            total_amount_fen=0,
            discount_amount_fen=0,
            final_amount_fen=0,
            status=OrderStatus.pending.value,
        )
        db.add(new_order)
        order_id = str(new_order.id)

        # 锁定桌台
        await db.execute(
            update(Table)
            .where(Table.id == table.id)
            .values(
                status=TableStatus.occupied.value,
                current_order_id=new_order.id,
            )
        )

    # 添加菜品
    total_added_fen = 0
    added_items = []
    for item_data in items:
        dish_uuid = uuid.UUID(item_data["dish_id"])
        dish_result = await db.execute(
            select(Dish).where(
                Dish.id == dish_uuid,
                Dish.tenant_id == tid,
                Dish.is_deleted == False,  # noqa: E712
            )
        )
        dish = dish_result.scalar_one_or_none()
        if not dish:
            logger.warning("scan_order_dish_not_found", dish_id=item_data["dish_id"])
            continue

        qty = item_data.get("quantity", 1)
        subtotal = dish.price_fen * qty

        order_item = OrderItem(
            id=uuid.uuid4(),
            tenant_id=tid,
            order_id=uuid.UUID(order_id),
            dish_id=dish_uuid,
            item_name=dish.dish_name,
            quantity=qty,
            unit_price_fen=dish.price_fen,
            subtotal_fen=subtotal,
            notes=item_data.get("notes", ""),
        )
        db.add(order_item)
        total_added_fen += subtotal
        added_items.append({
            "item_id": str(order_item.id),
            "dish_name": dish.dish_name,
            "quantity": qty,
            "subtotal_fen": subtotal,
        })

    # 更新订单总额
    if total_added_fen > 0:
        await db.execute(
            update(Order)
            .where(Order.id == uuid.UUID(order_id))
            .values(
                total_amount_fen=Order.total_amount_fen + total_added_fen,
                final_amount_fen=Order.total_amount_fen + total_added_fen - Order.discount_amount_fen,
                status=OrderStatus.confirmed.value,
            )
        )

    await db.flush()

    # 自动同步到KDS
    kds_result = None
    if added_items:
        kds_result = await sync_to_kds(order_id, tenant_id, db)

    logger.info(
        "scan_order_created",
        order_id=order_id,
        order_no=order_no,
        store_id=store_id,
        table_id=table_id,
        is_new_order=is_new_order,
        items_added=len(added_items),
        total_added_fen=total_added_fen,
        tenant_id=tenant_id,
    )

    return {
        "order_id": order_id,
        "order_no": order_no,
        "is_new_order": is_new_order,
        "items": added_items,
        "total_added_fen": total_added_fen,
        "kds_sync": kds_result,
    }


# ─── 加菜（同桌追加） ───


async def add_items_to_order(
    order_id: str,
    items: list[dict],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """加菜 — 同桌追加菜品到现有订单

    支持同桌多人同时加菜，合并到同一订单。
    items格式: [{"dish_id": str, "quantity": int, "notes": str?}]
    """
    tid = uuid.UUID(tenant_id)
    order_uuid = uuid.UUID(order_id)

    # 验证订单存在且可加菜
    order_result = await db.execute(
        select(Order).where(
            Order.id == order_uuid,
            Order.tenant_id == tid,
            Order.is_deleted == False,  # noqa: E712
        )
    )
    order = order_result.scalar_one_or_none()
    if not order:
        raise ValueError(f"订单不存在: {order_id}")

    if order.status in (OrderStatus.completed.value, OrderStatus.cancelled.value):
        raise ValueError(f"订单已{order.status}，不可加菜")

    # 添加菜品
    total_added_fen = 0
    added_items = []
    for item_data in items:
        dish_uuid = uuid.UUID(item_data["dish_id"])
        dish_result = await db.execute(
            select(Dish).where(
                Dish.id == dish_uuid,
                Dish.tenant_id == tid,
                Dish.is_deleted == False,  # noqa: E712
            )
        )
        dish = dish_result.scalar_one_or_none()
        if not dish:
            logger.warning("add_items_dish_not_found", dish_id=item_data["dish_id"])
            continue

        if not dish.is_available:
            logger.warning("add_items_dish_sold_out", dish_id=item_data["dish_id"])
            continue

        qty = item_data.get("quantity", 1)
        subtotal = dish.price_fen * qty

        order_item = OrderItem(
            id=uuid.uuid4(),
            tenant_id=tid,
            order_id=order_uuid,
            dish_id=dish_uuid,
            item_name=dish.dish_name,
            quantity=qty,
            unit_price_fen=dish.price_fen,
            subtotal_fen=subtotal,
            notes=item_data.get("notes", ""),
        )
        db.add(order_item)
        total_added_fen += subtotal
        added_items.append({
            "item_id": str(order_item.id),
            "dish_name": dish.dish_name,
            "quantity": qty,
            "subtotal_fen": subtotal,
        })

    # 更新订单总额
    if total_added_fen > 0:
        await db.execute(
            update(Order)
            .where(Order.id == order_uuid)
            .values(
                total_amount_fen=Order.total_amount_fen + total_added_fen,
                final_amount_fen=Order.total_amount_fen + total_added_fen - Order.discount_amount_fen,
            )
        )

    await db.flush()

    # 自动同步到KDS
    kds_result = None
    if added_items:
        kds_result = await sync_to_kds(order_id, tenant_id, db)

    logger.info(
        "scan_order_items_added",
        order_id=order_id,
        items_added=len(added_items),
        total_added_fen=total_added_fen,
        tenant_id=tenant_id,
    )

    return {
        "order_id": order_id,
        "items": added_items,
        "total_added_fen": total_added_fen,
        "kds_sync": kds_result,
    }


# ─── 查看当桌订单 ───


async def get_table_order(
    store_id: str,
    table_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict | None:
    """查看当桌订单 — 返回桌台当前进行中的订单及明细"""
    tid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    # 查桌台
    table_result = await db.execute(
        select(Table).where(
            Table.store_id == store_uuid,
            Table.table_no == table_id,
            Table.tenant_id == tid,
            Table.is_active == True,  # noqa: E712
        )
    )
    table = table_result.scalar_one_or_none()
    if not table:
        return None

    if not table.current_order_id:
        return None

    # 查订单
    order_result = await db.execute(
        select(Order).where(
            Order.id == table.current_order_id,
            Order.tenant_id == tid,
            Order.is_deleted == False,  # noqa: E712
        )
    )
    order = order_result.scalar_one_or_none()
    if not order:
        return None

    # 查菜品明细
    items_result = await db.execute(
        select(OrderItem).where(
            OrderItem.order_id == order.id,
            OrderItem.tenant_id == tid,
        )
    )
    items = items_result.scalars().all()

    return {
        "order_id": str(order.id),
        "order_no": order.order_no,
        "table_id": table_id,
        "store_id": store_id,
        "status": order.status,
        "total_amount_fen": order.total_amount_fen,
        "discount_amount_fen": order.discount_amount_fen,
        "final_amount_fen": order.final_amount_fen,
        "items": [
            {
                "item_id": str(i.id),
                "dish_id": str(i.dish_id) if i.dish_id else None,
                "dish_name": i.item_name,
                "quantity": i.quantity,
                "unit_price_fen": i.unit_price_fen,
                "subtotal_fen": i.subtotal_fen,
                "notes": i.notes or "",
                "sent_to_kds": getattr(i, "sent_to_kds_flag", False),
            }
            for i in items
        ],
    }


# ─── 请求结账 ───


async def request_checkout(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """请求结账 — 通知收银台该桌需要结账

    将订单状态标记为 pending_checkout，收银员可在POS上看到结账请求。
    """
    tid = uuid.UUID(tenant_id)
    order_uuid = uuid.UUID(order_id)

    order_result = await db.execute(
        select(Order).where(
            Order.id == order_uuid,
            Order.tenant_id == tid,
            Order.is_deleted == False,  # noqa: E712
        )
    )
    order = order_result.scalar_one_or_none()
    if not order:
        raise ValueError(f"订单不存在: {order_id}")

    if order.status in (OrderStatus.completed.value, OrderStatus.cancelled.value):
        raise ValueError(f"订单已{order.status}，无法结账")

    # 更新订单状态为待结账
    order.status = "pending_checkout"
    order.order_metadata = {
        **(order.order_metadata or {}),
        "checkout_requested_at": datetime.now(timezone.utc).isoformat(),
        "checkout_channel": SCAN_ORDER_CHANNEL,
    }

    await db.flush()

    logger.info(
        "scan_order_checkout_requested",
        order_id=order_id,
        order_no=order.order_no,
        final_amount_fen=order.final_amount_fen,
        tenant_id=tenant_id,
    )

    return {
        "order_id": order_id,
        "order_no": order.order_no,
        "status": "pending_checkout",
        "final_amount_fen": order.final_amount_fen,
        "table_number": order.table_number,
    }


# ─── 同步到KDS ───


async def sync_to_kds(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """同步到KDS — 将未发送的菜品推送到后厨

    仅提交 sent_to_kds_flag=False 的菜品，支持追加场景。
    """
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
        raise ValueError(f"订单不存在: {order_id}")

    # 查未发送到 KDS 的菜品
    items_result = await db.execute(
        select(OrderItem).where(
            OrderItem.order_id == order_uuid,
            OrderItem.tenant_id == tid,
            OrderItem.sent_to_kds_flag == False,  # noqa: E712
        )
    )
    unsent_items = list(items_result.scalars().all())

    if not unsent_items:
        return {"order_id": order_id, "items_synced": 0, "message": "无新增菜品需要同步"}

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
        order_id=order_id,
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

    await db.flush()

    logger.info(
        "scan_order_synced_to_kds",
        order_id=order_id,
        items_synced=len(unsent_items),
        tenant_id=tenant_id,
    )

    return {
        "order_id": order_id,
        "items_synced": len(unsent_items),
        "dispatch": dispatch_result,
    }


# ─── 扫码点餐统计 ───


async def get_scan_order_stats(
    store_id: str,
    date_range: tuple[date, date],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """扫码点餐统计 — 指定门店和日期范围的扫码点餐数据

    返回订单数、总金额、平均客单价、菜品排行等。
    """
    tid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)
    start_date, end_date = date_range

    start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    # 查扫码点餐订单
    orders_result = await db.execute(
        select(
            func.count(Order.id).label("order_count"),
            func.coalesce(func.sum(Order.final_amount_fen), 0).label("total_amount_fen"),
            func.coalesce(func.avg(Order.final_amount_fen), 0).label("avg_amount_fen"),
        ).where(
            Order.store_id == store_uuid,
            Order.tenant_id == tid,
            Order.sales_channel == SCAN_ORDER_CHANNEL,
            Order.created_at >= start_dt,
            Order.created_at < end_dt,
            Order.is_deleted == False,  # noqa: E712
            Order.status != OrderStatus.cancelled.value,
        )
    )
    row = orders_result.one()
    order_count = row.order_count or 0
    total_amount_fen = int(row.total_amount_fen or 0)
    avg_amount_fen = int(row.avg_amount_fen or 0)

    # 热门菜品排行（TOP 10）
    popular_result = await db.execute(
        select(
            OrderItem.item_name,
            func.sum(OrderItem.quantity).label("total_qty"),
            func.sum(OrderItem.subtotal_fen).label("total_revenue_fen"),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .where(
            Order.store_id == store_uuid,
            Order.tenant_id == tid,
            Order.sales_channel == SCAN_ORDER_CHANNEL,
            Order.created_at >= start_dt,
            Order.created_at < end_dt,
            Order.is_deleted == False,  # noqa: E712
            Order.status != OrderStatus.cancelled.value,
        )
        .group_by(OrderItem.item_name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(10)
    )
    popular_dishes = [
        {
            "dish_name": r.item_name,
            "total_qty": int(r.total_qty),
            "total_revenue_fen": int(r.total_revenue_fen),
        }
        for r in popular_result.all()
    ]

    logger.info(
        "scan_order_stats",
        store_id=store_id,
        start_date=str(start_date),
        end_date=str(end_date),
        order_count=order_count,
        tenant_id=tenant_id,
    )

    return {
        "store_id": store_id,
        "date_range": {"start": str(start_date), "end": str(end_date)},
        "order_count": order_count,
        "total_amount_fen": total_amount_fen,
        "avg_amount_fen": avg_amount_fen,
        "popular_dishes": popular_dishes,
    }
