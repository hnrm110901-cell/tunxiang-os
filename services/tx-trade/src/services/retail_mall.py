"""甄选商城 — 徐记海鲜线上零售（海味礼盒/预制菜/调味品/周边）

独立于堂食订单系统。所有金额单位：分(fen)。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ── 商品分类常量 ──────────────────────────────────────────────
RETAIL_CATEGORIES = ("seafood_gift", "prepared_dish", "seasoning", "merchandise")

# ── 零售订单状态 ──────────────────────────────────────────────
RETAIL_ORDER_STATUSES = (
    "pending",       # 待支付
    "paid",          # 已支付
    "preparing",     # 备货中
    "shipped",       # 已发货
    "delivered",     # 已签收
    "completed",     # 已完成
    "cancelled",     # 已取消
    "refunded",      # 已退款
)


# ── 工具函数 ──────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS tenant 上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def validate_retail_items(items: list[dict]) -> tuple[bool, str]:
    """校验零售订单商品列表"""
    if not items:
        return False, "items_empty"
    for i, item in enumerate(items):
        if "product_id" not in item:
            return False, f"missing_product_id_at_{i}"
        qty = item.get("quantity", 0)
        if not isinstance(qty, int) or qty <= 0:
            return False, f"invalid_quantity_at_{i}:{qty}"
        if "sku_id" not in item:
            return False, f"missing_sku_id_at_{i}"
    return True, "ok"


def validate_address(address: dict) -> tuple[bool, str]:
    """校验收货地址"""
    required_fields = ("name", "phone", "province", "city", "district", "detail")
    for field in required_fields:
        if not address.get(field):
            return False, f"missing_address_field:{field}"
    return True, "ok"


# ── 服务函数 ──────────────────────────────────────────────────


async def list_products(
    category: Optional[str],
    tenant_id: str,
    db: AsyncSession,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """商品列表 — 海味礼盒/预制菜/调味品/周边

    Args:
        category: 商品分类，None 表示全部
        tenant_id: 租户 ID
        db: 数据库会话
        page: 页码
        size: 每页数量

    Returns:
        {"items": [...], "total": int, "page": int, "size": int}
    """
    await _set_tenant(db, tenant_id)

    if category and category not in RETAIL_CATEGORIES:
        raise ValueError(f"invalid_category:{category}, valid: {RETAIL_CATEGORIES}")

    offset = (page - 1) * size

    # 查询总数
    count_params: dict[str, Any] = {"tid": tenant_id}
    count_sql = """
        SELECT COUNT(*) FROM retail_products
        WHERE tenant_id = :tid AND is_deleted = false AND status = 'on_sale'
    """
    if category:
        count_sql += " AND category = :cat"
        count_params["cat"] = category

    total_row = await db.execute(text(count_sql), count_params)
    total = total_row.scalar() or 0

    # 查询商品列表
    query_params: dict[str, Any] = {"tid": tenant_id, "lim": size, "off": offset}
    query_sql = """
        SELECT id, name, category, cover_image, price_fen, original_price_fen,
               sales_count, rating, tags
        FROM retail_products
        WHERE tenant_id = :tid AND is_deleted = false AND status = 'on_sale'
    """
    if category:
        query_sql += " AND category = :cat"
        query_params["cat"] = category
    query_sql += " ORDER BY sort_order ASC, created_at DESC LIMIT :lim OFFSET :off"

    rows = await db.execute(text(query_sql), query_params)
    items = [dict(r._mapping) for r in rows]

    logger.info(
        "retail_products_listed",
        tenant_id=tenant_id,
        category=category,
        total=total,
        page=page,
    )

    return {"items": items, "total": total, "page": page, "size": size}


async def get_product_detail(
    product_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """商品详情 — 图片/规格/产地/保质期

    Returns:
        {"product_id", "name", "images", "skus", "origin", "shelf_life", ...}
    """
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT id, name, category, description, images, skus,
                   origin, shelf_life_days, storage_method,
                   price_fen, original_price_fen, cover_image,
                   sales_count, rating, stock_count, tags
            FROM retail_products
            WHERE id = :pid AND tenant_id = :tid AND is_deleted = false
        """),
        {"pid": product_id, "tid": tenant_id},
    )
    product = row.mappings().first()
    if not product:
        raise ValueError("product_not_found")

    result = dict(product)
    # 解析 JSON 字段
    for json_field in ("images", "skus", "tags"):
        if isinstance(result.get(json_field), str):
            result[json_field] = json.loads(result[json_field])

    logger.info(
        "retail_product_detail",
        tenant_id=tenant_id,
        product_id=product_id,
        name=result["name"],
    )

    return result


async def create_retail_order(
    customer_id: str,
    items: list[dict],
    address: dict,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """创建零售订单

    Args:
        customer_id: 客户 ID
        items: [{"product_id", "sku_id", "quantity", "price_fen"}]
        address: {"name", "phone", "province", "city", "district", "detail"}
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"order_id", "order_no", "total_fen", "status", "items", "address"}
    """
    await _set_tenant(db, tenant_id)

    valid, msg = validate_retail_items(items)
    if not valid:
        raise ValueError(msg)

    valid_addr, addr_msg = validate_address(address)
    if not valid_addr:
        raise ValueError(addr_msg)

    order_id = str(uuid.uuid4())
    order_no = f"RM{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
    now = _now_utc()

    # 计算订单总金额
    total_fen = 0
    order_items = []
    for item in items:
        # 查询商品价格
        prod_row = await db.execute(
            text("""
                SELECT price_fen, name FROM retail_products
                WHERE id = :pid AND tenant_id = :tid AND is_deleted = false
            """),
            {"pid": item["product_id"], "tid": tenant_id},
        )
        prod = prod_row.mappings().first()
        if not prod:
            raise ValueError(f"product_not_found:{item['product_id']}")

        item_total = prod["price_fen"] * item["quantity"]
        total_fen += item_total
        order_items.append({
            "product_id": item["product_id"],
            "sku_id": item["sku_id"],
            "product_name": prod["name"],
            "quantity": item["quantity"],
            "unit_price_fen": prod["price_fen"],
            "total_fen": item_total,
        })

    # 插入订单主表
    await db.execute(
        text("""
            INSERT INTO retail_orders
                (id, tenant_id, order_no, customer_id, total_fen, status,
                 items, address, created_at, updated_at, is_deleted)
            VALUES (:id, :tid, :ono, :cid, :total, 'pending',
                    :items::jsonb, :addr::jsonb, :now, :now, false)
        """),
        {
            "id": order_id,
            "tid": tenant_id,
            "ono": order_no,
            "cid": customer_id,
            "total": total_fen,
            "items": json.dumps(order_items, ensure_ascii=False),
            "addr": json.dumps(address, ensure_ascii=False),
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "retail_order_created",
        tenant_id=tenant_id,
        order_id=order_id,
        order_no=order_no,
        customer_id=customer_id,
        total_fen=total_fen,
        items_count=len(order_items),
    )

    return {
        "order_id": order_id,
        "order_no": order_no,
        "total_fen": total_fen,
        "status": "pending",
        "items": order_items,
        "address": address,
        "created_at": now.isoformat(),
    }


async def apply_member_discount(
    order_id: str,
    card_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """会员折扣 — 根据会员卡等级计算零售折扣

    Returns:
        {"order_id", "card_id", "original_fen", "discount_fen", "final_fen", "discount_rate"}
    """
    await _set_tenant(db, tenant_id)

    # 查询订单
    order_row = await db.execute(
        text("""
            SELECT total_fen, status FROM retail_orders
            WHERE id = :oid AND tenant_id = :tid AND is_deleted = false
        """),
        {"oid": order_id, "tid": tenant_id},
    )
    order = order_row.mappings().first()
    if not order:
        raise ValueError("order_not_found")
    if order["status"] != "pending":
        raise ValueError("order_not_pending")

    # 查询会员卡等级
    card_row = await db.execute(
        text("""
            SELECT mc.level_rank, ct.levels::text
            FROM member_cards mc
            JOIN card_types ct ON ct.id = mc.card_type_id
            WHERE mc.id = :cid AND mc.tenant_id = :tid AND mc.is_deleted = false
        """),
        {"cid": card_id, "tid": tenant_id},
    )
    card = card_row.mappings().first()
    if not card:
        raise ValueError("card_not_found")

    levels = json.loads(card["levels"]) if card["levels"] else []
    level_rank = card["level_rank"]

    # 找到当前等级的零售折扣
    discount_rate = 100  # 默认无折扣(100%)
    for lvl in levels:
        if lvl["rank"] == level_rank:
            for benefit in lvl.get("benefits", []):
                if benefit.get("key") == "retail_discount":
                    discount_rate = benefit.get("value", 100)
            break

    original_fen = order["total_fen"]
    discount_fen = original_fen - int(original_fen * discount_rate / 100)
    final_fen = original_fen - discount_fen

    # 更新订单折扣
    now = _now_utc()
    await db.execute(
        text("""
            UPDATE retail_orders
            SET discount_fen = :disc, final_fen = :final,
                card_id = :cid, updated_at = :now
            WHERE id = :oid AND tenant_id = :tid
        """),
        {
            "disc": discount_fen,
            "final": final_fen,
            "cid": card_id,
            "oid": order_id,
            "tid": tenant_id,
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "retail_member_discount_applied",
        tenant_id=tenant_id,
        order_id=order_id,
        card_id=card_id,
        original_fen=original_fen,
        discount_fen=discount_fen,
        final_fen=final_fen,
        discount_rate=discount_rate,
    )

    return {
        "order_id": order_id,
        "card_id": card_id,
        "original_fen": original_fen,
        "discount_fen": discount_fen,
        "final_fen": final_fen,
        "discount_rate": discount_rate,
    }


async def track_delivery(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """快递追踪

    Returns:
        {"order_id", "order_no", "status", "express_company", "tracking_no", "traces"}
    """
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT id, order_no, status, express_company, tracking_no,
                   delivery_traces
            FROM retail_orders
            WHERE id = :oid AND tenant_id = :tid AND is_deleted = false
        """),
        {"oid": order_id, "tid": tenant_id},
    )
    order = row.mappings().first()
    if not order:
        raise ValueError("order_not_found")

    traces = order.get("delivery_traces")
    if isinstance(traces, str):
        traces = json.loads(traces)

    logger.info(
        "retail_delivery_tracked",
        tenant_id=tenant_id,
        order_id=order_id,
        status=order["status"],
    )

    return {
        "order_id": order["id"],
        "order_no": order["order_no"],
        "status": order["status"],
        "express_company": order.get("express_company"),
        "tracking_no": order.get("tracking_no"),
        "traces": traces or [],
    }


async def get_gift_cards(
    tenant_id: str,
    db: AsyncSession,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """礼品卡列表 — 送礼场景

    Returns:
        {"items": [...], "total": int}
    """
    await _set_tenant(db, tenant_id)
    offset = (page - 1) * size

    total_row = await db.execute(
        text("""
            SELECT COUNT(*) FROM retail_gift_cards
            WHERE tenant_id = :tid AND is_deleted = false AND status = 'on_sale'
        """),
        {"tid": tenant_id},
    )
    total = total_row.scalar() or 0

    rows = await db.execute(
        text("""
            SELECT id, name, cover_image, price_fen, face_value_fen,
                   description, valid_days, sales_count
            FROM retail_gift_cards
            WHERE tenant_id = :tid AND is_deleted = false AND status = 'on_sale'
            ORDER BY sort_order ASC, created_at DESC
            LIMIT :lim OFFSET :off
        """),
        {"tid": tenant_id, "lim": size, "off": offset},
    )
    items = [dict(r._mapping) for r in rows]

    logger.info(
        "retail_gift_cards_listed",
        tenant_id=tenant_id,
        total=total,
    )

    return {"items": items, "total": total, "page": page, "size": size}
