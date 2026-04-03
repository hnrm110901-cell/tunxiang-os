"""零售商城服务层 — 商品管理 / 购物车 / 订单 / 库存扣减

所有金额单位：分(fen)。
SELECT FOR UPDATE 防超卖，退款恢复库存。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.retail_mall import RetailProduct, RetailOrder, RetailOrderItem

logger = structlog.get_logger(__name__)

# ── 商品分类常量 ──────────────────────────────────────────────
RETAIL_CATEGORIES = ("seafood_gift", "prepared_dish", "seasoning", "merchandise")

# ── 订单状态常量 ──────────────────────────────────────────────
VALID_ORDER_STATUSES = ("pending", "paid", "refunded", "cancelled")

# ── 商品状态常量 ──────────────────────────────────────────────
VALID_PRODUCT_STATUSES = ("active", "inactive", "sold_out")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ════════════════════════════════════════════════════════════════
# 商品管理
# ════════════════════════════════════════════════════════════════


async def list_products(
    tenant_id: str,
    store_id: str,
    db: AsyncSession,
    category: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """商品列表（分页、分类筛选）

    Args:
        tenant_id: 租户ID
        store_id: 门店ID
        db: 数据库会话
        category: 商品分类筛选，None 表示全部
        page: 页码（从1开始）
        size: 每页数量

    Returns:
        {"items": [...], "total": int, "page": int, "size": int}
    """
    if category and category not in RETAIL_CATEGORIES:
        raise ValueError(f"invalid_category:{category}, valid: {RETAIL_CATEGORIES}")

    tid = uuid.UUID(tenant_id)
    sid = uuid.UUID(store_id)
    offset = (page - 1) * size

    # 构建基础查询条件
    base_filter = [
        RetailProduct.tenant_id == tid,
        RetailProduct.store_id == sid,
        RetailProduct.is_deleted.is_(False),
        RetailProduct.status == "active",
    ]
    if category:
        base_filter.append(RetailProduct.category == category)

    # 查询总数
    count_stmt = select(func.count(RetailProduct.id)).where(*base_filter)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # 查询商品列表
    query_stmt = (
        select(RetailProduct)
        .where(*base_filter)
        .order_by(RetailProduct.created_at.desc())
        .offset(offset)
        .limit(size)
    )
    rows = await db.execute(query_stmt)
    products = rows.scalars().all()

    items = [
        {
            "id": str(p.id),
            "name": p.name,
            "sku": p.sku,
            "category": p.category,
            "price_fen": p.price_fen,
            "cost_fen": p.cost_fen,
            "stock_qty": p.stock_qty,
            "image_url": p.image_url,
            "status": p.status,
            "is_weighable": p.is_weighable,
        }
        for p in products
    ]

    logger.info(
        "retail_products_listed",
        tenant_id=tenant_id,
        store_id=store_id,
        category=category,
        total=total,
        page=page,
    )

    return {"items": items, "total": total, "page": page, "size": size}


async def create_product(
    tenant_id: str,
    store_id: str,
    data: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """创建零售商品

    Args:
        tenant_id: 租户ID
        store_id: 门店ID
        data: 商品数据 {name, sku, category, price_fen, cost_fen, stock_qty, min_stock, image_url, is_weighable}
        db: 数据库会话

    Returns:
        创建后的商品字典
    """
    category = data.get("category", "merchandise")
    if category not in RETAIL_CATEGORIES:
        raise ValueError(f"invalid_category:{category}, valid: {RETAIL_CATEGORIES}")

    price_fen = data.get("price_fen", 0)
    if price_fen <= 0:
        raise ValueError("price_fen must be positive")

    product = RetailProduct(
        tenant_id=uuid.UUID(tenant_id),
        store_id=uuid.UUID(store_id),
        name=data["name"],
        sku=data["sku"],
        category=category,
        price_fen=price_fen,
        cost_fen=data.get("cost_fen", 0),
        stock_qty=data.get("stock_qty", 0),
        min_stock=data.get("min_stock", 0),
        image_url=data.get("image_url"),
        status="active",
        is_weighable=data.get("is_weighable", False),
    )
    db.add(product)
    await db.flush()

    logger.info(
        "retail_product_created",
        tenant_id=tenant_id,
        store_id=store_id,
        product_id=str(product.id),
        name=product.name,
        sku=product.sku,
    )

    return {
        "id": str(product.id),
        "name": product.name,
        "sku": product.sku,
        "category": product.category,
        "price_fen": product.price_fen,
        "cost_fen": product.cost_fen,
        "stock_qty": product.stock_qty,
        "min_stock": product.min_stock,
        "image_url": product.image_url,
        "status": product.status,
        "is_weighable": product.is_weighable,
    }


async def update_product(
    tenant_id: str,
    product_id: str,
    data: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """更新零售商品

    Args:
        tenant_id: 租户ID
        product_id: 商品ID
        data: 更新字段（支持 name, sku, category, price_fen, cost_fen, stock_qty, min_stock, image_url, status, is_weighable）
        db: 数据库会话

    Returns:
        更新后的商品字典
    """
    tid = uuid.UUID(tenant_id)
    pid = uuid.UUID(product_id)

    stmt = (
        select(RetailProduct)
        .where(
            RetailProduct.id == pid,
            RetailProduct.tenant_id == tid,
            RetailProduct.is_deleted.is_(False),
        )
    )
    result = await db.execute(stmt)
    product = result.scalar_one_or_none()
    if not product:
        raise ValueError("product_not_found")

    # 校验可更新字段
    allowed_fields = {
        "name", "sku", "category", "price_fen", "cost_fen",
        "stock_qty", "min_stock", "image_url", "status", "is_weighable",
    }
    for key, value in data.items():
        if key not in allowed_fields:
            continue
        if key == "category" and value not in RETAIL_CATEGORIES:
            raise ValueError(f"invalid_category:{value}")
        if key == "status" and value not in VALID_PRODUCT_STATUSES:
            raise ValueError(f"invalid_status:{value}")
        if key == "price_fen" and value <= 0:
            raise ValueError("price_fen must be positive")
        setattr(product, key, value)

    product.updated_at = _now_utc()
    await db.flush()

    logger.info(
        "retail_product_updated",
        tenant_id=tenant_id,
        product_id=product_id,
        updated_fields=list(data.keys()),
    )

    return {
        "id": str(product.id),
        "name": product.name,
        "sku": product.sku,
        "category": product.category,
        "price_fen": product.price_fen,
        "cost_fen": product.cost_fen,
        "stock_qty": product.stock_qty,
        "min_stock": product.min_stock,
        "image_url": product.image_url,
        "status": product.status,
        "is_weighable": product.is_weighable,
    }


# ════════════════════════════════════════════════════════════════
# 零售订单
# ════════════════════════════════════════════════════════════════


async def create_retail_order(
    tenant_id: str,
    store_id: str,
    items: list[dict[str, Any]],
    db: AsyncSession,
    customer_id: Optional[str] = None,
    payment_method: Optional[str] = None,
) -> dict[str, Any]:
    """创建零售订单（含库存扣减，SELECT FOR UPDATE 防超卖）

    Args:
        tenant_id: 租户ID
        store_id: 门店ID
        items: [{"product_id": str, "quantity": int}]
        db: 数据库会话
        customer_id: 顾客ID（可选）
        payment_method: 支付方式（可选）

    Returns:
        订单信息字典

    Raises:
        ValueError: 参数校验失败或库存不足
    """
    if not items:
        raise ValueError("items_empty")

    tid = uuid.UUID(tenant_id)
    sid = uuid.UUID(store_id)

    order_no = f"RM{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
    now = _now_utc()

    total_fen = 0
    order_items_data: list[dict[str, Any]] = []

    for idx, item in enumerate(items):
        if "product_id" not in item:
            raise ValueError(f"missing_product_id_at_{idx}")
        qty = item.get("quantity", 0)
        if not isinstance(qty, int) or qty <= 0:
            raise ValueError(f"invalid_quantity_at_{idx}:{qty}")

        pid = uuid.UUID(item["product_id"])

        # SELECT FOR UPDATE 锁定商品行，防止并发超卖
        lock_stmt = (
            select(RetailProduct)
            .where(
                RetailProduct.id == pid,
                RetailProduct.tenant_id == tid,
                RetailProduct.is_deleted.is_(False),
                RetailProduct.status == "active",
            )
            .with_for_update()
        )
        lock_result = await db.execute(lock_stmt)
        product = lock_result.scalar_one_or_none()

        if not product:
            raise ValueError(f"product_not_found:{item['product_id']}")

        if product.stock_qty < qty:
            raise ValueError(
                f"insufficient_stock:{product.name},"
                f"available={product.stock_qty},requested={qty}"
            )

        # 扣减库存
        product.stock_qty -= qty
        if product.stock_qty == 0:
            product.status = "sold_out"
        product.updated_at = now

        subtotal = product.price_fen * qty
        total_fen += subtotal

        order_items_data.append({
            "product_id": pid,
            "product_name": product.name,
            "quantity": qty,
            "unit_price_fen": product.price_fen,
            "subtotal_fen": subtotal,
        })

    # 创建订单主记录
    order = RetailOrder(
        tenant_id=tid,
        store_id=sid,
        order_no=order_no,
        customer_id=uuid.UUID(customer_id) if customer_id else None,
        total_fen=total_fen,
        discount_fen=0,
        final_fen=total_fen,
        payment_method=payment_method,
        status="pending",
    )
    db.add(order)
    await db.flush()  # 获取 order.id

    # 创建订单明细
    result_items = []
    for oi_data in order_items_data:
        order_item = RetailOrderItem(
            tenant_id=tid,
            order_id=order.id,
            product_id=oi_data["product_id"],
            product_name=oi_data["product_name"],
            quantity=oi_data["quantity"],
            unit_price_fen=oi_data["unit_price_fen"],
            subtotal_fen=oi_data["subtotal_fen"],
        )
        db.add(order_item)
        result_items.append({
            "product_id": str(oi_data["product_id"]),
            "product_name": oi_data["product_name"],
            "quantity": oi_data["quantity"],
            "unit_price_fen": oi_data["unit_price_fen"],
            "subtotal_fen": oi_data["subtotal_fen"],
        })

    await db.flush()

    logger.info(
        "retail_order_created",
        tenant_id=tenant_id,
        store_id=store_id,
        order_id=str(order.id),
        order_no=order_no,
        customer_id=customer_id,
        total_fen=total_fen,
        items_count=len(result_items),
    )

    return {
        "order_id": str(order.id),
        "order_no": order_no,
        "store_id": store_id,
        "customer_id": customer_id,
        "total_fen": total_fen,
        "discount_fen": 0,
        "final_fen": total_fen,
        "payment_method": payment_method,
        "status": "pending",
        "items": result_items,
        "created_at": order.created_at.isoformat() if order.created_at else now.isoformat(),
    }


async def get_retail_order(
    tenant_id: str,
    order_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """查询零售订单详情（含明细）

    Args:
        tenant_id: 租户ID
        order_id: 订单ID
        db: 数据库会话

    Returns:
        订单信息字典（含 items 列表）

    Raises:
        ValueError: 订单不存在
    """
    tid = uuid.UUID(tenant_id)
    oid = uuid.UUID(order_id)

    stmt = (
        select(RetailOrder)
        .where(
            RetailOrder.id == oid,
            RetailOrder.tenant_id == tid,
            RetailOrder.is_deleted.is_(False),
        )
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise ValueError("order_not_found")

    # 查询订单明细
    items_stmt = (
        select(RetailOrderItem)
        .where(
            RetailOrderItem.order_id == oid,
            RetailOrderItem.tenant_id == tid,
            RetailOrderItem.is_deleted.is_(False),
        )
    )
    items_result = await db.execute(items_stmt)
    order_items = items_result.scalars().all()

    items = [
        {
            "id": str(oi.id),
            "product_id": str(oi.product_id),
            "product_name": oi.product_name,
            "quantity": oi.quantity,
            "unit_price_fen": oi.unit_price_fen,
            "subtotal_fen": oi.subtotal_fen,
        }
        for oi in order_items
    ]

    logger.info(
        "retail_order_queried",
        tenant_id=tenant_id,
        order_id=order_id,
        status=order.status,
    )

    return {
        "order_id": str(order.id),
        "order_no": order.order_no,
        "store_id": str(order.store_id),
        "customer_id": str(order.customer_id) if order.customer_id else None,
        "total_fen": order.total_fen,
        "discount_fen": order.discount_fen,
        "final_fen": order.final_fen,
        "payment_method": order.payment_method,
        "status": order.status,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "items": items,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


async def refund_retail_order(
    tenant_id: str,
    order_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """退款零售订单（恢复库存）

    只有 paid 状态的订单可以退款。退款后恢复商品库存。

    Args:
        tenant_id: 租户ID
        order_id: 订单ID
        db: 数据库会话

    Returns:
        退款后的订单信息

    Raises:
        ValueError: 订单不存在或状态不允许退款
    """
    tid = uuid.UUID(tenant_id)
    oid = uuid.UUID(order_id)
    now = _now_utc()

    # 锁定订单
    stmt = (
        select(RetailOrder)
        .where(
            RetailOrder.id == oid,
            RetailOrder.tenant_id == tid,
            RetailOrder.is_deleted.is_(False),
        )
        .with_for_update()
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise ValueError("order_not_found")

    if order.status != "paid":
        raise ValueError(f"order_cannot_refund:status={order.status}")

    # 查询订单明细并恢复库存
    items_stmt = (
        select(RetailOrderItem)
        .where(
            RetailOrderItem.order_id == oid,
            RetailOrderItem.tenant_id == tid,
            RetailOrderItem.is_deleted.is_(False),
        )
    )
    items_result = await db.execute(items_stmt)
    order_items = items_result.scalars().all()

    for oi in order_items:
        # 锁定商品行恢复库存
        prod_stmt = (
            select(RetailProduct)
            .where(
                RetailProduct.id == oi.product_id,
                RetailProduct.tenant_id == tid,
            )
            .with_for_update()
        )
        prod_result = await db.execute(prod_stmt)
        product = prod_result.scalar_one_or_none()
        if product:
            product.stock_qty += oi.quantity
            if product.status == "sold_out" and product.stock_qty > 0:
                product.status = "active"
            product.updated_at = now

    # 更新订单状态
    order.status = "refunded"
    order.updated_at = now
    await db.flush()

    logger.info(
        "retail_order_refunded",
        tenant_id=tenant_id,
        order_id=order_id,
        order_no=order.order_no,
        refund_fen=order.final_fen,
        items_count=len(order_items),
    )

    return {
        "order_id": str(order.id),
        "order_no": order.order_no,
        "status": "refunded",
        "refund_fen": order.final_fen,
        "items_restored": len(order_items),
    }


# ════════════════════════════════════════════════════════════════
# 零售统计
# ════════════════════════════════════════════════════════════════


async def get_retail_stats(
    tenant_id: str,
    store_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """零售统计 — GMV / 订单量 / 畅销品

    Args:
        tenant_id: 租户ID
        store_id: 门店ID
        db: 数据库会话

    Returns:
        {"gmv_fen": int, "order_count": int, "paid_order_count": int, "top_products": [...]}
    """
    tid = uuid.UUID(tenant_id)
    sid = uuid.UUID(store_id)

    # GMV 和订单量（仅 paid 订单）
    gmv_stmt = (
        select(
            func.coalesce(func.sum(RetailOrder.final_fen), 0).label("gmv_fen"),
            func.count(RetailOrder.id).label("paid_count"),
        )
        .where(
            RetailOrder.tenant_id == tid,
            RetailOrder.store_id == sid,
            RetailOrder.status == "paid",
            RetailOrder.is_deleted.is_(False),
        )
    )
    gmv_result = await db.execute(gmv_stmt)
    gmv_row = gmv_result.one()

    # 总订单量（含所有状态）
    total_stmt = (
        select(func.count(RetailOrder.id))
        .where(
            RetailOrder.tenant_id == tid,
            RetailOrder.store_id == sid,
            RetailOrder.is_deleted.is_(False),
        )
    )
    total_result = await db.execute(total_stmt)
    total_count = total_result.scalar() or 0

    # 畅销品 Top 10
    top_stmt = (
        select(
            RetailOrderItem.product_id,
            RetailOrderItem.product_name,
            func.sum(RetailOrderItem.quantity).label("total_qty"),
            func.sum(RetailOrderItem.subtotal_fen).label("total_revenue_fen"),
        )
        .join(RetailOrder, RetailOrderItem.order_id == RetailOrder.id)
        .where(
            RetailOrderItem.tenant_id == tid,
            RetailOrder.store_id == sid,
            RetailOrder.status == "paid",
            RetailOrderItem.is_deleted.is_(False),
            RetailOrder.is_deleted.is_(False),
        )
        .group_by(RetailOrderItem.product_id, RetailOrderItem.product_name)
        .order_by(func.sum(RetailOrderItem.quantity).desc())
        .limit(10)
    )
    top_result = await db.execute(top_stmt)
    top_products = [
        {
            "product_id": str(row.product_id),
            "product_name": row.product_name,
            "total_qty": int(row.total_qty),
            "total_revenue_fen": int(row.total_revenue_fen),
        }
        for row in top_result
    ]

    logger.info(
        "retail_stats_queried",
        tenant_id=tenant_id,
        store_id=store_id,
        gmv_fen=int(gmv_row.gmv_fen),
        paid_count=int(gmv_row.paid_count),
    )

    return {
        "gmv_fen": int(gmv_row.gmv_fen),
        "order_count": total_count,
        "paid_order_count": int(gmv_row.paid_count),
        "top_products": top_products,
    return {"items": items, "total": total, "page": page, "size": size}


# ── 后台管理 ─────────────────────────────────────────────────

VALID_PRODUCT_STATUSES = ("draft", "on_sale", "off_sale")


async def create_product(
    name: str,
    category: str,
    price_fen: int,
    original_price_fen: Optional[int],
    cover_image: Optional[str],
    description: Optional[str],
    stock: int,
    tags: list[str],
    origin: Optional[str],
    shelf_life: Optional[str],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """创建零售商品（后台）"""
    await _set_tenant(db, tenant_id)

    if category not in RETAIL_CATEGORIES:
        raise ValueError(f"invalid_category:{category}, valid: {RETAIL_CATEGORIES}")

    import json as _json
    product_id = uuid.uuid4()
    now = _now_utc()

    await db.execute(
        text("""
            INSERT INTO retail_products
                (id, tenant_id, name, category, cover_image, description,
                 price_fen, original_price_fen, stock, tags, origin, shelf_life,
                 status, created_at, updated_at)
            VALUES
                (:id, :tid, :name, :cat, :cover, :desc,
                 :price, :orig_price, :stock, :tags::jsonb, :origin, :shelf,
                 'draft', :now, :now)
        """),
        {
            "id": product_id, "tid": uuid.UUID(tenant_id),
            "name": name, "cat": category,
            "cover": cover_image, "desc": description,
            "price": price_fen, "orig_price": original_price_fen or price_fen,
            "stock": stock, "tags": _json.dumps(tags),
            "origin": origin, "shelf": shelf_life,
            "now": now,
        },
    )
    await db.flush()
    logger.info("retail_product_created", product_id=str(product_id), name=name)
    return {
        "product_id": str(product_id),
        "name": name,
        "category": category,
        "price_fen": price_fen,
        "status": "draft",
    }


async def update_product_status(
    product_id: str,
    status: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """商品上下架"""
    await _set_tenant(db, tenant_id)

    if status not in VALID_PRODUCT_STATUSES:
        raise ValueError(f"invalid_status:{status}, valid: {VALID_PRODUCT_STATUSES}")

    result = await db.execute(
        text("""
            UPDATE retail_products
            SET status = :status, updated_at = NOW()
            WHERE id = :id AND tenant_id = :tid AND is_deleted = false
            RETURNING id, name, status
        """),
        {
            "id": uuid.UUID(product_id),
            "tid": uuid.UUID(tenant_id),
            "status": status,
        },
    )
    row = result.fetchone()
    if not row:
        raise ValueError("product_not_found")

    logger.info("retail_product_status_updated", product_id=product_id, status=status)
    return {
        "product_id": str(row.id),
        "name": row.name,
        "status": row.status,
    }
