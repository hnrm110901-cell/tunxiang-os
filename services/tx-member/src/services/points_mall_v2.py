"""积分商城 Service — 完整业务实现

功能模块：
  list_products        — 商品列表（带客户已兑次数 + scope过滤）
  get_product          — 商品详情
  redeem               — 积分兑换（原子事务：扣积分+扣库存+建订单+发内容）
  fulfill_order        — 门店核销（pending → fulfilled）
  cancel_order         — 取消订单（退积分+退库存）
  get_customer_orders  — 客户兑换记录（分页）
  get_order_stats      — 商城统计
  create_product       — 新增商品
  update_product       — 更新商品

  # v345 新增
  list_categories      — 分类列表
  create_category      — 新增分类
  update_category      — 更新分类
  delete_category      — 删除分类
  seed_default_achievements — 初始化默认成就配置
  get_achievement_list — 成就列表（从DB读取配置）
  cleanup_expired_products  — 过期商品自动下架
  cleanup_expired_orders    — 过期订单自动清理
  ship_order           — 实物发货
  confirm_delivery     — 确认收货

并发控制：
  库存操作使用 SELECT FOR UPDATE SKIP LOCKED，乐观锁 + 原子 UPDATE WHERE stock >= qty。
  积分扣减使用 UPDATE WHERE points >= deduct，零竞争防超扣。

金额单位全部为分（fen），积分为正整数。
禁止 except Exception，所有捕获指定具体类型。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ── 常量 ──────────────────────────────────────────────────────

PRODUCT_TYPES = frozenset({"physical", "coupon", "dish", "stored_value"})
ORDER_STATUSES = frozenset({"pending", "fulfilled", "cancelled", "expired"})

# 自动发放类型（兑换后立即 fulfilled）
AUTO_FULFILL_TYPES = frozenset({"coupon", "stored_value"})


# ── 工具函数 ──────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _gen_order_no() -> str:
    """生成订单号 PM-{YYYYMMDD}-{6位大写随机}"""
    date_part = _now_utc().strftime("%Y%m%d")
    rand_part = uuid.uuid4().hex[:6].upper()
    return f"PM-{date_part}-{rand_part}"


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS tenant 上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 1. 商品列表 ───────────────────────────────────────────────


async def list_products(
    tenant_id: str,
    db: AsyncSession,
    customer_id: str | None = None,
    product_type: str | None = None,
    category_id: str | None = None,
    store_id: str | None = None,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """商品列表

    查有效商品（is_active=True，在有效期内，stock>0 或 stock=-1）。
    对每个商品附带该客户的已兑换次数（周期内）。
    支持按 category_id 过滤、按 store_id scope 过滤。
    按 sort_order ASC。

    Returns:
        {"items": [...], "total", "page", "size"}
    """
    await _set_tenant(db, tenant_id)

    offset = (page - 1) * size
    now = _now_utc()
    params: dict[str, Any] = {
        "tid": tenant_id,
        "now": now,
        "lim": size,
        "off": offset,
    }

    where_parts = [
        "p.tenant_id = :tid",
        "p.is_deleted = false",
        "p.is_active = true",
        "(p.stock = -1 OR p.stock > 0)",
        "(p.valid_from IS NULL OR p.valid_from <= :now)",
        "(p.valid_until IS NULL OR p.valid_until > :now)",
    ]

    if product_type:
        where_parts.append("p.product_type = :ptype")
        params["ptype"] = product_type

    if category_id:
        where_parts.append("p.category_id = :cat_id")
        params["cat_id"] = category_id

    # 连锁scope过滤：brand=全品牌可见 | store=当前门店在scope_store_ids中
    if store_id:
        where_parts.append(
            "(p.scope_type = 'brand' OR (p.scope_type = 'store' AND :store_id = ANY(p.scope_store_ids)))"
        )
        params["store_id"] = store_id

    where_sql = " AND ".join(where_parts)

    cnt_row = await db.execute(
        text(f"SELECT COUNT(*) FROM points_mall_products p WHERE {where_sql}"),
        params,
    )
    total: int = cnt_row.scalar() or 0

    rows = await db.execute(
        text(f"""
            SELECT p.id, p.name, p.description, p.image_url,
                   p.product_type, p.points_required,
                   p.stock, p.stock_sold,
                   p.limit_per_customer, p.limit_per_period, p.limit_period_days,
                   p.sort_order, p.valid_from, p.valid_until
            FROM points_mall_products p
            WHERE {where_sql}
            ORDER BY p.sort_order ASC, p.created_at DESC
            LIMIT :lim OFFSET :off
        """),
        params,
    )
    products = rows.mappings().all()

    # 查询客户在每个商品的已兑换次数（周期内）
    customer_redeem_counts: dict[str, int] = {}
    if customer_id and products:
        product_ids = [str(r["id"]) for r in products]
        # 构建 IN 参数（用 ANY 数组，避免动态 IN 个数）
        id_array = "{" + ",".join(product_ids) + "}"

        count_rows = await db.execute(
            text("""
                SELECT o.product_id::text,
                       COUNT(*) AS cnt,
                       p.limit_period_days
                FROM points_mall_orders o
                JOIN points_mall_products p ON p.id = o.product_id
                WHERE o.tenant_id = :tid
                  AND o.customer_id = :cid
                  AND o.product_id = ANY(:pids::uuid[])
                  AND o.status != 'cancelled'
                  AND o.created_at >= (NOW() - (p.limit_period_days || ' days')::interval)
                GROUP BY o.product_id, p.limit_period_days
            """),
            {"tid": tenant_id, "cid": customer_id, "pids": id_array},
        )
        for row in count_rows.mappings().all():
            customer_redeem_counts[row["product_id"]] = int(row["cnt"])

    items = [
        {
            "product_id": str(r["id"]),
            "name": r["name"],
            "description": r["description"] or "",
            "image_url": r["image_url"] or "",
            "product_type": r["product_type"],
            "points_required": r["points_required"],
            "stock": r["stock"],
            "stock_sold": r["stock_sold"],
            "stock_remaining": r["stock"] if r["stock"] == -1 else (r["stock"] - r["stock_sold"]),
            "limit_per_customer": r["limit_per_customer"],
            "limit_per_period": r["limit_per_period"],
            "limit_period_days": r["limit_period_days"],
            "sort_order": r["sort_order"],
            "valid_from": r["valid_from"].isoformat() if r["valid_from"] else None,
            "valid_until": r["valid_until"].isoformat() if r["valid_until"] else None,
            "customer_redeemed_count": customer_redeem_counts.get(str(r["id"]), 0),
        }
        for r in products
    ]

    logger.info(
        "points_mall.list_products",
        tenant_id=tenant_id,
        customer_id=customer_id,
        product_type=product_type,
        total=total,
        page=page,
    )

    return {"items": items, "total": total, "page": page, "size": size}


# ── 2. 商品详情 ───────────────────────────────────────────────


async def get_product(
    product_id: str,
    tenant_id: str,
    db: AsyncSession,
    customer_id: str | None = None,
) -> dict[str, Any]:
    """商品详情 + 库存余量 + 当前客户已兑换次数"""
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT id, name, description, image_url,
                   product_type, points_required,
                   stock, stock_sold, product_content,
                   limit_per_customer, limit_per_period, limit_period_days,
                   is_active, sort_order, valid_from, valid_until
            FROM points_mall_products
            WHERE id = :pid AND tenant_id = :tid AND is_deleted = false
        """),
        {"pid": product_id, "tid": tenant_id},
    )
    product = row.mappings().first()
    if not product:
        raise ValueError("product_not_found")

    # 客户已兑换次数（周期内）
    customer_count = 0
    if customer_id:
        cnt_row = await db.execute(
            text("""
                SELECT COUNT(*) FROM points_mall_orders
                WHERE tenant_id = :tid
                  AND customer_id = :cid
                  AND product_id = :pid
                  AND status != 'cancelled'
                  AND created_at >= (NOW() - (:days || ' days')::interval)
            """),
            {
                "tid": tenant_id,
                "cid": customer_id,
                "pid": product_id,
                "days": product["limit_period_days"],
            },
        )
        customer_count = cnt_row.scalar() or 0

    content = product["product_content"]
    if isinstance(content, str):
        content = json.loads(content)

    return {
        "product_id": str(product["id"]),
        "name": product["name"],
        "description": product["description"] or "",
        "image_url": product["image_url"] or "",
        "product_type": product["product_type"],
        "points_required": product["points_required"],
        "stock": product["stock"],
        "stock_sold": product["stock_sold"],
        "stock_remaining": product["stock"] if product["stock"] == -1 else (product["stock"] - product["stock_sold"]),
        "product_content": content,
        "limit_per_customer": product["limit_per_customer"],
        "limit_per_period": product["limit_per_period"],
        "limit_period_days": product["limit_period_days"],
        "is_active": product["is_active"],
        "sort_order": product["sort_order"],
        "valid_from": product["valid_from"].isoformat() if product["valid_from"] else None,
        "valid_until": product["valid_until"].isoformat() if product["valid_until"] else None,
        "customer_redeemed_count": customer_count,
    }


# ── 3. 积分兑换（核心） ───────────────────────────────────────


async def redeem(
    product_id: str,
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
    store_id: str | None = None,
    quantity: int = 1,
    delivery_address: str | None = None,
    delivery_name: str | None = None,
    delivery_phone: str | None = None,
) -> dict[str, Any]:
    """积分兑换

    事务内原子操作：
      1. FOR UPDATE 锁定商品行（防并发超卖）
      2. 验证商品有效性、库存、限购
      3. 查会员卡积分余额
      4. 原子 UPDATE 扣积分（WHERE points >= deduct，防超扣）
      5. 原子 UPDATE 扣库存（WHERE stock=-1 OR stock>=qty，防超卖）
      6. INSERT PointsMallOrder（status=pending）
      7. 根据 product_type 发放内容（coupon/stored_value → fulfilled；dish/physical → pending）
      8. 写积分流水
      9. 异步更新 customer.total_order_count + 打标签（flush 后触发）

    Returns:
        兑换订单 dict
    """
    await _set_tenant(db, tenant_id)

    if quantity < 1:
        raise ValueError("quantity_must_be_positive")

    now = _now_utc()

    # ── Step 1: FOR UPDATE 锁定商品，防止并发超卖 ──────────────
    prod_row = await db.execute(
        text("""
            SELECT id, name, product_type, points_required,
                   stock, stock_sold, product_content,
                   limit_per_customer, limit_per_period, limit_period_days,
                   is_active, valid_from, valid_until
            FROM points_mall_products
            WHERE id = :pid AND tenant_id = :tid AND is_deleted = false
            FOR UPDATE
        """),
        {"pid": product_id, "tid": tenant_id},
    )
    product = prod_row.mappings().first()
    if not product:
        raise ValueError("product_not_found")

    # ── Step 2: 验证商品可兑换 ────────────────────────────────
    if not product["is_active"]:
        raise ValueError("product_not_active")
    if product["valid_from"] and product["valid_from"] > now:
        raise ValueError("product_not_started")
    if product["valid_until"] and product["valid_until"] <= now:
        raise ValueError("product_expired")

    # 库存检查（-1 = 不限）
    if product["stock"] != -1:
        available = product["stock"] - product["stock_sold"]
        if available < quantity:
            raise ValueError("insufficient_stock")

    total_points = product["points_required"] * quantity

    # ── Step 3: 限购检查 ──────────────────────────────────────
    if product["limit_per_customer"] > 0:
        period_days = product["limit_period_days"]
        limit_count_row = await db.execute(
            text("""
                SELECT COUNT(*) FROM points_mall_orders
                WHERE tenant_id = :tid
                  AND customer_id = :cid
                  AND product_id = :pid
                  AND status != 'cancelled'
                  AND created_at >= (NOW() - (:days || ' days')::interval)
            """),
            {
                "tid": tenant_id,
                "cid": customer_id,
                "pid": product_id,
                "days": period_days,
            },
        )
        already_redeemed = limit_count_row.scalar() or 0
        if already_redeemed + quantity > product["limit_per_customer"]:
            raise ValueError("redeem_limit_exceeded")

    # ── Step 4: 查会员卡 + 验证积分余额 ──────────────────────
    card_row = await db.execute(
        text("""
            SELECT id, points FROM member_cards
            WHERE customer_id = :cid AND tenant_id = :tid
              AND is_deleted = false
            LIMIT 1
        """),
        {"cid": customer_id, "tid": tenant_id},
    )
    card = card_row.mappings().first()
    if not card:
        raise ValueError("member_card_not_found")
    if card["points"] < total_points:
        raise ValueError("insufficient_points")

    card_id = str(card["id"])

    # ── Step 5: 原子扣积分（WHERE points >= deduct 防超扣）────
    deduct_result = await db.execute(
        text("""
            UPDATE member_cards
            SET points = points - :pts, updated_at = :now
            WHERE id = :cid AND tenant_id = :tid
              AND is_deleted = false
              AND points >= :pts
            RETURNING id
        """),
        {"pts": total_points, "cid": card_id, "tid": tenant_id, "now": now},
    )
    if deduct_result.rowcount == 0:
        raise ValueError("insufficient_points")

    # ── Step 6: 原子扣库存 ────────────────────────────────────
    if product["stock"] == -1:
        # 不限库存：只增 stock_sold
        await db.execute(
            text("""
                UPDATE points_mall_products
                SET stock_sold = stock_sold + :qty, updated_at = :now
                WHERE id = :pid AND tenant_id = :tid
            """),
            {"qty": quantity, "pid": product_id, "tid": tenant_id, "now": now},
        )
    else:
        stock_result = await db.execute(
            text("""
                UPDATE points_mall_products
                SET stock = stock - :qty,
                    stock_sold = stock_sold + :qty,
                    updated_at = :now
                WHERE id = :pid AND tenant_id = :tid
                  AND (stock - stock_sold) >= :qty
                RETURNING id
            """),
            {"qty": quantity, "pid": product_id, "tid": tenant_id, "now": now},
        )
        if stock_result.rowcount == 0:
            raise ValueError("insufficient_stock")

    # ── Step 7: 创建订单 ──────────────────────────────────────
    order_id = str(uuid.uuid4())
    order_no = _gen_order_no()
    initial_status = "pending"

    await db.execute(
        text("""
            INSERT INTO points_mall_orders
                (id, tenant_id, order_no, customer_id, product_id, store_id,
                 points_deducted, quantity, status,
                 delivery_address, delivery_name, delivery_phone,
                 created_at, updated_at, is_deleted)
            VALUES
                (:id, :tid, :order_no, :cid, :pid, :sid,
                 :pts, :qty, :status,
                 :daddr, :dname, :dphone,
                 :now, :now, false)
        """),
        {
            "id": order_id,
            "tid": tenant_id,
            "order_no": order_no,
            "cid": customer_id,
            "pid": product_id,
            "sid": store_id,
            "pts": total_points,
            "qty": quantity,
            "status": initial_status,
            "daddr": delivery_address,
            "dname": delivery_name,
            "dphone": delivery_phone,
            "now": now,
        },
    )

    # ── Step 8: 根据 product_type 发放内容 ────────────────────
    coupon_id: str | None = None
    product_content = product["product_content"]
    if isinstance(product_content, str):
        product_content = json.loads(product_content)

    final_status = "pending"

    if product["product_type"] == "coupon":
        coupon_id = await _issue_coupon(
            product_content=product_content,
            customer_id=customer_id,
            tenant_id=tenant_id,
            db=db,
            now=now,
        )
        final_status = "fulfilled"

    elif product["product_type"] == "stored_value":
        await _add_stored_value(
            product_content=product_content,
            customer_id=customer_id,
            tenant_id=tenant_id,
            db=db,
            now=now,
            order_no=order_no,
        )
        final_status = "fulfilled"

    # dish / physical 保持 pending，等门店核销
    if final_status == "fulfilled":
        await db.execute(
            text("""
                UPDATE points_mall_orders
                SET status = 'fulfilled',
                    fulfilled_at = :now,
                    coupon_id = :coupon_id,
                    updated_at = :now
                WHERE id = :oid AND tenant_id = :tid
            """),
            {
                "now": now,
                "coupon_id": coupon_id,
                "oid": order_id,
                "tid": tenant_id,
            },
        )

    # ── Step 9: 写积分流水 ────────────────────────────────────
    log_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO points_log
                (id, tenant_id, card_id, direction, source, points, created_at)
            VALUES (:id, :tid, :cid, 'spend', 'points_mall_redeem', :pts, :now)
        """),
        {
            "id": log_id,
            "tid": tenant_id,
            "cid": card_id,
            "pts": total_points,
            "now": now,
        },
    )

    await db.flush()

    # ── Step 10: 异步更新会员互动统计（不阻塞主流程）──────────
    await _async_update_customer_stats(
        customer_id=customer_id,
        tenant_id=tenant_id,
        db=db,
        now=now,
    )

    logger.info(
        "points_mall.redeem",
        tenant_id=tenant_id,
        order_id=order_id,
        order_no=order_no,
        customer_id=customer_id,
        product_id=product_id,
        product_type=product["product_type"],
        points_deducted=total_points,
        quantity=quantity,
        final_status=final_status,
    )

    return {
        "order_id": order_id,
        "order_no": order_no,
        "customer_id": customer_id,
        "product_id": product_id,
        "product_name": product["name"],
        "product_type": product["product_type"],
        "points_deducted": total_points,
        "quantity": quantity,
        "status": final_status,
        "coupon_id": coupon_id,
        "store_id": store_id,
        "created_at": now.isoformat(),
    }


# ── 4. 门店核销 ──────────────────────────────────────────────


async def fulfill_order(
    order_id: str,
    operator_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """门店核销 — 将 pending 订单标记为 fulfilled

    用于实物/菜品兑换由门店人员手动核销。
    """
    await _set_tenant(db, tenant_id)

    now = _now_utc()
    result = await db.execute(
        text("""
            UPDATE points_mall_orders
            SET status = 'fulfilled',
                fulfilled_at = :now,
                updated_at = :now
            WHERE id = :oid AND tenant_id = :tid
              AND status = 'pending'
              AND is_deleted = false
            RETURNING id, order_no, customer_id, product_id, points_deducted, quantity
        """),
        {"oid": order_id, "tid": tenant_id, "now": now},
    )
    row = result.mappings().first()
    if not row:
        raise ValueError("order_not_found_or_not_pending")

    await db.flush()

    logger.info(
        "points_mall.fulfill_order",
        tenant_id=tenant_id,
        order_id=order_id,
        operator_id=operator_id,
    )

    return {
        "order_id": order_id,
        "order_no": str(row["order_no"]),
        "status": "fulfilled",
        "fulfilled_at": now.isoformat(),
        "operator_id": operator_id,
    }


# ── 5. 取消订单（退积分+退库存）─────────────────────────────


async def cancel_order(
    order_id: str,
    cancel_reason: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """取消订单

    1. 锁定订单行（FOR UPDATE）
    2. 退还积分（写 points_log direction=earn + UPDATE member_cards）
    3. 退还库存（UPDATE points_mall_products）
    4. 更新订单状态
    """
    await _set_tenant(db, tenant_id)

    now = _now_utc()

    # 锁定订单
    order_row = await db.execute(
        text("""
            SELECT id, order_no, customer_id, product_id,
                   points_deducted, quantity, status
            FROM points_mall_orders
            WHERE id = :oid AND tenant_id = :tid
              AND is_deleted = false
            FOR UPDATE
        """),
        {"oid": order_id, "tid": tenant_id},
    )
    order = order_row.mappings().first()
    if not order:
        raise ValueError("order_not_found")
    if order["status"] not in ("pending",):
        raise ValueError(f"order_cannot_cancel_status:{order['status']}")

    customer_id = str(order["customer_id"])
    product_id = str(order["product_id"])
    points_to_refund = order["points_deducted"]
    qty = order["quantity"]

    # 查会员卡
    card_row = await db.execute(
        text("""
            SELECT id FROM member_cards
            WHERE customer_id = :cid AND tenant_id = :tid
              AND is_deleted = false
            LIMIT 1
        """),
        {"cid": customer_id, "tid": tenant_id},
    )
    card = card_row.mappings().first()
    if not card:
        raise ValueError("member_card_not_found")
    card_id = str(card["id"])

    # 退还积分
    await db.execute(
        text("""
            UPDATE member_cards
            SET points = points + :pts, updated_at = :now
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
        """),
        {"pts": points_to_refund, "cid": card_id, "tid": tenant_id, "now": now},
    )

    # 写积分流水
    refund_log_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO points_log
                (id, tenant_id, card_id, direction, source, points, created_at)
            VALUES (:id, :tid, :cid, 'earn', 'points_mall_refund', :pts, :now)
        """),
        {
            "id": refund_log_id,
            "tid": tenant_id,
            "cid": card_id,
            "pts": points_to_refund,
            "now": now,
        },
    )

    # 退还库存
    prod_row = await db.execute(
        text("SELECT stock FROM points_mall_products WHERE id = :pid AND tenant_id = :tid"),
        {"pid": product_id, "tid": tenant_id},
    )
    prod = prod_row.mappings().first()
    if prod and prod["stock"] == -1:
        # 不限库存：只退 stock_sold
        await db.execute(
            text("""
                UPDATE points_mall_products
                SET stock_sold = GREATEST(0, stock_sold - :qty), updated_at = :now
                WHERE id = :pid AND tenant_id = :tid
            """),
            {"qty": qty, "pid": product_id, "tid": tenant_id, "now": now},
        )
    elif prod:
        await db.execute(
            text("""
                UPDATE points_mall_products
                SET stock = stock + :qty,
                    stock_sold = GREATEST(0, stock_sold - :qty),
                    updated_at = :now
                WHERE id = :pid AND tenant_id = :tid
            """),
            {"qty": qty, "pid": product_id, "tid": tenant_id, "now": now},
        )

    # 更新订单状态
    await db.execute(
        text("""
            UPDATE points_mall_orders
            SET status = 'cancelled',
                cancelled_at = :now,
                cancel_reason = :reason,
                updated_at = :now
            WHERE id = :oid AND tenant_id = :tid
        """),
        {
            "now": now,
            "reason": cancel_reason,
            "oid": order_id,
            "tid": tenant_id,
        },
    )

    await db.flush()

    logger.info(
        "points_mall.cancel_order",
        tenant_id=tenant_id,
        order_id=order_id,
        order_no=str(order["order_no"]),
        customer_id=customer_id,
        points_refunded=points_to_refund,
        cancel_reason=cancel_reason,
    )

    return {
        "order_id": order_id,
        "order_no": str(order["order_no"]),
        "status": "cancelled",
        "points_refunded": points_to_refund,
        "cancelled_at": now.isoformat(),
        "cancel_reason": cancel_reason,
    }


# ── 6. 客户兑换记录（分页）──────────────────────────────────


async def get_customer_orders(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """客户兑换记录（分页，按 created_at DESC）"""
    await _set_tenant(db, tenant_id)

    offset = (page - 1) * size

    cnt_row = await db.execute(
        text("""
            SELECT COUNT(*) FROM points_mall_orders
            WHERE customer_id = :cid AND tenant_id = :tid
              AND is_deleted = false
        """),
        {"cid": customer_id, "tid": tenant_id},
    )
    total: int = cnt_row.scalar() or 0

    rows = await db.execute(
        text("""
            SELECT o.id, o.order_no, o.product_id, o.store_id,
                   o.points_deducted, o.quantity, o.status,
                   o.coupon_id, o.tracking_no,
                   o.delivery_name, o.delivery_phone, o.delivery_address,
                   o.fulfilled_at, o.cancelled_at, o.cancel_reason,
                   o.created_at,
                   p.name AS product_name, p.product_type, p.image_url
            FROM points_mall_orders o
            LEFT JOIN points_mall_products p ON p.id = o.product_id
            WHERE o.customer_id = :cid AND o.tenant_id = :tid
              AND o.is_deleted = false
            ORDER BY o.created_at DESC
            LIMIT :lim OFFSET :off
        """),
        {"cid": customer_id, "tid": tenant_id, "lim": size, "off": offset},
    )

    items = [
        {
            "order_id": str(r["id"]),
            "order_no": r["order_no"],
            "product_id": str(r["product_id"]),
            "product_name": r["product_name"] or "",
            "product_type": r["product_type"] or "",
            "image_url": r["image_url"] or "",
            "store_id": str(r["store_id"]) if r["store_id"] else None,
            "points_deducted": r["points_deducted"],
            "quantity": r["quantity"],
            "status": r["status"],
            "coupon_id": str(r["coupon_id"]) if r["coupon_id"] else None,
            "tracking_no": r["tracking_no"],
            "delivery_name": r["delivery_name"],
            "delivery_phone": r["delivery_phone"],
            "delivery_address": r["delivery_address"],
            "fulfilled_at": r["fulfilled_at"].isoformat() if r["fulfilled_at"] else None,
            "cancelled_at": r["cancelled_at"].isoformat() if r["cancelled_at"] else None,
            "cancel_reason": r["cancel_reason"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows.mappings().all()
    ]

    return {"items": items, "total": total, "page": page, "size": size}


# ── 7. 订单详情 ──────────────────────────────────────────────


async def get_order_detail(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """单笔订单详情"""
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT o.id, o.order_no, o.customer_id, o.product_id, o.store_id,
                   o.points_deducted, o.quantity, o.status,
                   o.coupon_id, o.tracking_no,
                   o.delivery_name, o.delivery_phone, o.delivery_address,
                   o.fulfilled_at, o.cancelled_at, o.cancel_reason,
                   o.created_at,
                   p.name AS product_name, p.product_type, p.image_url,
                   p.product_content
            FROM points_mall_orders o
            LEFT JOIN points_mall_products p ON p.id = o.product_id
            WHERE o.id = :oid AND o.tenant_id = :tid
              AND o.is_deleted = false
        """),
        {"oid": order_id, "tid": tenant_id},
    )
    r = row.mappings().first()
    if not r:
        raise ValueError("order_not_found")

    content = r["product_content"]
    if isinstance(content, str):
        content = json.loads(content)

    return {
        "order_id": str(r["id"]),
        "order_no": r["order_no"],
        "customer_id": str(r["customer_id"]),
        "product_id": str(r["product_id"]),
        "product_name": r["product_name"] or "",
        "product_type": r["product_type"] or "",
        "image_url": r["image_url"] or "",
        "product_content": content,
        "store_id": str(r["store_id"]) if r["store_id"] else None,
        "points_deducted": r["points_deducted"],
        "quantity": r["quantity"],
        "status": r["status"],
        "coupon_id": str(r["coupon_id"]) if r["coupon_id"] else None,
        "tracking_no": r["tracking_no"],
        "delivery_name": r["delivery_name"],
        "delivery_phone": r["delivery_phone"],
        "delivery_address": r["delivery_address"],
        "fulfilled_at": r["fulfilled_at"].isoformat() if r["fulfilled_at"] else None,
        "cancelled_at": r["cancelled_at"].isoformat() if r["cancelled_at"] else None,
        "cancel_reason": r["cancel_reason"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }


# ── 8. 商城统计（管理端）────────────────────────────────────


async def get_order_stats(
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """商城数据统计：总兑换次数、总消耗积分、各商品兑换排名"""
    await _set_tenant(db, tenant_id)

    # 汇总统计
    summary_row = await db.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE status != 'cancelled') AS total_redeem_count,
                COALESCE(SUM(points_deducted) FILTER (WHERE status != 'cancelled'), 0) AS total_points_consumed,
                COUNT(*) FILTER (WHERE status = 'pending') AS pending_count,
                COUNT(*) FILTER (WHERE status = 'fulfilled') AS fulfilled_count,
                COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_count
            FROM points_mall_orders
            WHERE tenant_id = :tid AND is_deleted = false
        """),
        {"tid": tenant_id},
    )
    summary = summary_row.mappings().first()

    # 各商品兑换排名（TOP 20）
    rank_rows = await db.execute(
        text("""
            SELECT p.id::text AS product_id,
                   p.name AS product_name,
                   p.product_type,
                   COUNT(o.id) FILTER (WHERE o.status != 'cancelled') AS redeem_count,
                   COALESCE(SUM(o.points_deducted) FILTER (WHERE o.status != 'cancelled'), 0) AS total_points
            FROM points_mall_products p
            LEFT JOIN points_mall_orders o ON o.product_id = p.id AND o.tenant_id = p.tenant_id
            WHERE p.tenant_id = :tid AND p.is_deleted = false
            GROUP BY p.id, p.name, p.product_type
            ORDER BY redeem_count DESC
            LIMIT 20
        """),
        {"tid": tenant_id},
    )

    product_ranking = [
        {
            "product_id": r["product_id"],
            "product_name": r["product_name"],
            "product_type": r["product_type"],
            "redeem_count": int(r["redeem_count"]),
            "total_points": int(r["total_points"]),
        }
        for r in rank_rows.mappings().all()
    ]

    logger.info(
        "points_mall.stats",
        tenant_id=tenant_id,
        total_redeem=summary["total_redeem_count"] if summary else 0,
    )

    return {
        "total_redeem_count": int(summary["total_redeem_count"]) if summary else 0,
        "total_points_consumed": int(summary["total_points_consumed"]) if summary else 0,
        "pending_count": int(summary["pending_count"]) if summary else 0,
        "fulfilled_count": int(summary["fulfilled_count"]) if summary else 0,
        "cancelled_count": int(summary["cancelled_count"]) if summary else 0,
        "product_ranking": product_ranking,
    }


# ── 9. 新增商品 ──────────────────────────────────────────────


async def create_product(
    name: str,
    product_type: str,
    points_required: int,
    product_content: dict,
    tenant_id: str,
    db: AsyncSession,
    description: str | None = None,
    image_url: str | None = None,
    stock: int = -1,
    limit_per_customer: int = 0,
    limit_per_period: int = 0,
    limit_period_days: int = 30,
    sort_order: int = 0,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> dict[str, Any]:
    """新增商城商品"""
    await _set_tenant(db, tenant_id)

    if product_type not in PRODUCT_TYPES:
        raise ValueError(f"invalid_product_type:{product_type}")
    if points_required <= 0:
        raise ValueError("points_required_must_be_positive")
    if stock < -1:
        raise ValueError("stock_invalid")

    product_id = str(uuid.uuid4())
    now = _now_utc()

    await db.execute(
        text("""
            INSERT INTO points_mall_products
                (id, tenant_id, name, description, image_url,
                 product_type, points_required,
                 stock, stock_sold, product_content,
                 limit_per_customer, limit_per_period, limit_period_days,
                 is_active, sort_order, valid_from, valid_until,
                 created_at, updated_at, is_deleted)
            VALUES
                (:id, :tid, :name, :desc, :img,
                 :ptype, :pts,
                 :stock, 0, :content::jsonb,
                 :lpc, :lpp, :lpd,
                 true, :sort, :vfrom, :vuntil,
                 :now, :now, false)
        """),
        {
            "id": product_id,
            "tid": tenant_id,
            "name": name,
            "desc": description,
            "img": image_url,
            "ptype": product_type,
            "pts": points_required,
            "stock": stock,
            "content": json.dumps(product_content, ensure_ascii=False),
            "lpc": limit_per_customer,
            "lpp": limit_per_period,
            "lpd": limit_period_days,
            "sort": sort_order,
            "vfrom": valid_from,
            "vuntil": valid_until,
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "points_mall.create_product",
        tenant_id=tenant_id,
        product_id=product_id,
        name=name,
        product_type=product_type,
        points_required=points_required,
    )

    return {
        "product_id": product_id,
        "name": name,
        "product_type": product_type,
        "points_required": points_required,
        "stock": stock,
        "is_active": True,
    }


# ── 10. 更新商品 ─────────────────────────────────────────────


async def update_product(
    product_id: str,
    tenant_id: str,
    db: AsyncSession,
    name: str | None = None,
    description: str | None = None,
    image_url: str | None = None,
    points_required: int | None = None,
    stock: int | None = None,
    limit_per_customer: int | None = None,
    limit_per_period: int | None = None,
    limit_period_days: int | None = None,
    is_active: bool | None = None,
    sort_order: int | None = None,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    product_content: dict | None = None,
) -> dict[str, Any]:
    """更新商品字段（只更新传入的非 None 字段）"""
    await _set_tenant(db, tenant_id)

    # 检查商品是否存在
    check_row = await db.execute(
        text("SELECT id FROM points_mall_products WHERE id = :pid AND tenant_id = :tid AND is_deleted = false"),
        {"pid": product_id, "tid": tenant_id},
    )
    if not check_row.first():
        raise ValueError("product_not_found")

    now = _now_utc()
    set_parts: list[str] = ["updated_at = :now"]
    params: dict[str, Any] = {"pid": product_id, "tid": tenant_id, "now": now}

    field_map = {
        "name": name,
        "description": description,
        "image_url": image_url,
        "points_required": points_required,
        "stock": stock,
        "limit_per_customer": limit_per_customer,
        "limit_per_period": limit_per_period,
        "limit_period_days": limit_period_days,
        "is_active": is_active,
        "sort_order": sort_order,
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    for col, val in field_map.items():
        if val is not None:
            set_parts.append(f"{col} = :{col}")
            params[col] = val

    if product_content is not None:
        set_parts.append("product_content = :content::jsonb")
        params["content"] = json.dumps(product_content, ensure_ascii=False)

    set_sql = ", ".join(set_parts)
    await db.execute(
        text(f"""
            UPDATE points_mall_products
            SET {set_sql}
            WHERE id = :pid AND tenant_id = :tid AND is_deleted = false
        """),
        params,
    )
    await db.flush()

    logger.info(
        "points_mall.update_product",
        tenant_id=tenant_id,
        product_id=product_id,
    )

    return {"product_id": product_id, "updated": True}


# ── 内部辅助：发放优惠券 ─────────────────────────────────────


async def _issue_coupon(
    product_content: dict,
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
    now: datetime,
) -> str | None:
    """根据 coupon 类型商品内容向客户发放优惠券

    暂时通过 INSERT INTO coupons 创建记录。
    若 CouponEngine 独立模块已上线，此处改为调用其接口。

    Returns:
        coupon_id（UUID str）或 None（若失败但不阻断主流程）
    """
    coupon_template_id = product_content.get("coupon_template_id")
    amount_fen = product_content.get("amount_fen", 0)

    if not coupon_template_id:
        logger.warning(
            "points_mall.issue_coupon.missing_template",
            tenant_id=tenant_id,
            customer_id=customer_id,
        )
        return None

    coupon_id = str(uuid.uuid4())

    try:
        await db.execute(
            text("""
                INSERT INTO coupons
                    (id, tenant_id, customer_id, template_id,
                     amount_fen, status, source,
                     created_at, updated_at, is_deleted)
                VALUES
                    (:id, :tid, :cid, :tpl,
                     :amt, 'unused', 'points_mall_redeem',
                     :now, :now, false)
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "id": coupon_id,
                "tid": tenant_id,
                "cid": customer_id,
                "tpl": coupon_template_id,
                "amt": amount_fen,
                "now": now,
            },
        )
    except IntegrityError:
        # coupons 表可能不存在或结构不匹配，记录警告但不阻断兑换
        logger.warning(
            "points_mall.issue_coupon.insert_failed",
            tenant_id=tenant_id,
            customer_id=customer_id,
            coupon_template_id=coupon_template_id,
        )
        return None

    logger.info(
        "points_mall.coupon_issued",
        tenant_id=tenant_id,
        coupon_id=coupon_id,
        customer_id=customer_id,
        template_id=coupon_template_id,
    )
    return coupon_id


# ── 内部辅助：增加储值金 ─────────────────────────────────────


async def _add_stored_value(
    product_content: dict,
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
    now: datetime,
    order_no: str,
) -> None:
    """向客户储值卡增加储值金

    通过 UPDATE stored_value_cards 实现。
    若 StoredValueService 独立模块已上线，此处改为调用其接口。
    """
    amount_fen = product_content.get("amount_fen", 0)
    if amount_fen <= 0:
        logger.warning(
            "points_mall.add_stored_value.zero_amount",
            tenant_id=tenant_id,
            customer_id=customer_id,
        )
        return

    try:
        result = await db.execute(
            text("""
                UPDATE stored_value_cards
                SET main_balance_fen = main_balance_fen + :amt,
                    updated_at = :now
                WHERE customer_id = :cid AND tenant_id = :tid
                  AND is_deleted = false
                  AND status = 'active'
                RETURNING id
            """),
            {"amt": amount_fen, "cid": customer_id, "tid": tenant_id, "now": now},
        )
        if result.rowcount == 0:
            logger.warning(
                "points_mall.add_stored_value.no_active_card",
                tenant_id=tenant_id,
                customer_id=customer_id,
                amount_fen=amount_fen,
            )
        else:
            logger.info(
                "points_mall.stored_value_added",
                tenant_id=tenant_id,
                customer_id=customer_id,
                amount_fen=amount_fen,
                order_no=order_no,
            )
    except IntegrityError:
        logger.warning(
            "points_mall.add_stored_value.failed",
            tenant_id=tenant_id,
            customer_id=customer_id,
        )


# ── 内部辅助：会员互动统计（异步，非阻塞）──────────────────


async def _async_update_customer_stats(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
    now: datetime,
) -> None:
    """兑换成功后更新会员统计 + 打"积分兑换用户"标签

    此函数在 flush 后执行，失败不影响主事务（由调用方事务管理）。
    """
    try:
        # total_order_count += 1（兑换也算一次互动）
        await db.execute(
            text("""
                UPDATE customers
                SET total_order_count = total_order_count + 1,
                    updated_at = :now
                WHERE id = :cid AND tenant_id = :tid
                  AND is_deleted = false
            """),
            {"cid": customer_id, "tid": tenant_id, "now": now},
        )

        # 打标签"积分兑换用户"（若尚未有此标签）
        await db.execute(
            text("""
                UPDATE customers
                SET tags = CASE
                    WHEN tags @> '["积分兑换用户"]'::jsonb THEN tags
                    ELSE COALESCE(tags, '[]'::jsonb) || '["积分兑换用户"]'::jsonb
                END,
                updated_at = :now
                WHERE id = :cid AND tenant_id = :tid
                  AND is_deleted = false
            """),
            {"cid": customer_id, "tid": tenant_id, "now": now},
        )
    except (ValueError, KeyError) as exc:
        # 统计更新失败不阻断主流程，只记录 warning
        logger.warning(
            "points_mall.customer_stats_update_failed",
            tenant_id=tenant_id,
            customer_id=customer_id,
            error=str(exc),
        )


# ══════════════════════════════════════════════════════════════════
#  v345 新增功能
# ══════════════════════════════════════════════════════════════════


# ── 11. 分类 CRUD ──────────────────────────────────────────────


async def list_categories(
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """分类列表（按 sort_order ASC）"""
    await _set_tenant(db, tenant_id)

    rows = await db.execute(
        text("""
            SELECT id, category_name, category_code, icon_url,
                   sort_order, is_active, created_at
            FROM points_mall_categories
            WHERE tenant_id = :tid AND is_deleted = false
            ORDER BY sort_order ASC, created_at ASC
        """),
        {"tid": tenant_id},
    )
    items = [
        {
            "category_id": str(r["id"]),
            "category_name": r["category_name"],
            "category_code": r["category_code"],
            "icon_url": r["icon_url"] or "",
            "sort_order": r["sort_order"],
            "is_active": r["is_active"],
        }
        for r in rows.mappings().all()
    ]

    logger.info("points_mall.list_categories", tenant_id=tenant_id, count=len(items))
    return {"items": items, "total": len(items)}


async def create_category(
    category_name: str,
    category_code: str,
    tenant_id: str,
    db: AsyncSession,
    icon_url: str | None = None,
    sort_order: int = 0,
) -> dict[str, Any]:
    """新增分类"""
    await _set_tenant(db, tenant_id)

    if not category_name or not category_code:
        raise ValueError("category_name_and_code_required")

    cat_id = str(uuid.uuid4())
    now = _now_utc()

    try:
        await db.execute(
            text("""
                INSERT INTO points_mall_categories
                    (id, tenant_id, category_name, category_code,
                     icon_url, sort_order, is_active,
                     created_at, updated_at, is_deleted)
                VALUES
                    (:id, :tid, :name, :code,
                     :icon, :sort, true,
                     :now, :now, false)
            """),
            {
                "id": cat_id,
                "tid": tenant_id,
                "name": category_name,
                "code": category_code,
                "icon": icon_url,
                "sort": sort_order,
                "now": now,
            },
        )
        await db.flush()
    except IntegrityError:
        raise ValueError("category_code_duplicate")

    logger.info(
        "points_mall.create_category",
        tenant_id=tenant_id,
        category_id=cat_id,
        category_code=category_code,
    )

    return {
        "category_id": cat_id,
        "category_name": category_name,
        "category_code": category_code,
        "sort_order": sort_order,
    }


async def update_category(
    category_id: str,
    tenant_id: str,
    db: AsyncSession,
    category_name: str | None = None,
    icon_url: str | None = None,
    sort_order: int | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    """更新分类（只更新传入的非 None 字段）"""
    await _set_tenant(db, tenant_id)

    check_row = await db.execute(
        text("SELECT id FROM points_mall_categories WHERE id = :cid AND tenant_id = :tid AND is_deleted = false"),
        {"cid": category_id, "tid": tenant_id},
    )
    if not check_row.first():
        raise ValueError("category_not_found")

    now = _now_utc()
    set_parts: list[str] = ["updated_at = :now"]
    params: dict[str, Any] = {"cid": category_id, "tid": tenant_id, "now": now}

    if category_name is not None:
        set_parts.append("category_name = :name")
        params["name"] = category_name
    if icon_url is not None:
        set_parts.append("icon_url = :icon")
        params["icon"] = icon_url
    if sort_order is not None:
        set_parts.append("sort_order = :sort")
        params["sort"] = sort_order
    if is_active is not None:
        set_parts.append("is_active = :active")
        params["active"] = is_active

    set_sql = ", ".join(set_parts)
    await db.execute(
        text(f"""
            UPDATE points_mall_categories
            SET {set_sql}
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
        """),
        params,
    )
    await db.flush()

    logger.info(
        "points_mall.update_category",
        tenant_id=tenant_id,
        category_id=category_id,
    )
    return {"category_id": category_id, "updated": True}


async def delete_category(
    category_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """软删除分类"""
    await _set_tenant(db, tenant_id)

    now = _now_utc()
    result = await db.execute(
        text("""
            UPDATE points_mall_categories
            SET is_deleted = true, updated_at = :now
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
            RETURNING id
        """),
        {"cid": category_id, "tid": tenant_id, "now": now},
    )
    if result.rowcount == 0:
        raise ValueError("category_not_found")

    await db.flush()

    logger.info(
        "points_mall.delete_category",
        tenant_id=tenant_id,
        category_id=category_id,
    )
    return {"category_id": category_id, "deleted": True}


# ── 12. 成就可配置化 ──────────────────────────────────────────


# 默认成就定义（用于seed）
_DEFAULT_ACHIEVEMENTS = [
    {
        "code": "first_order",
        "name": "初来乍到",
        "description": "完成首单",
        "trigger_type": "order_count",
        "threshold": 1,
        "reward_points": 10,
        "icon": "badge_first",
    },
    {
        "code": "orders_10",
        "name": "常客",
        "description": "累计下单10次",
        "trigger_type": "order_count",
        "threshold": 10,
        "reward_points": 50,
        "icon": "badge_regular",
    },
    {
        "code": "orders_50",
        "name": "铁粉",
        "description": "累计下单50次",
        "trigger_type": "order_count",
        "threshold": 50,
        "reward_points": 200,
        "icon": "badge_super",
    },
    {
        "code": "spent_1000",
        "name": "千元户",
        "description": "累计消费满1000元",
        "trigger_type": "total_spent_fen",
        "threshold": 100000,
        "reward_points": 100,
        "icon": "badge_spender",
    },
    {
        "code": "share_5",
        "name": "美食传播者",
        "description": "分享5次给好友",
        "trigger_type": "share_count",
        "threshold": 5,
        "reward_points": 30,
        "icon": "badge_sharer",
    },
    {
        "code": "review_10",
        "name": "点评达人",
        "description": "发布10条评价",
        "trigger_type": "review_count",
        "threshold": 10,
        "reward_points": 50,
        "icon": "badge_reviewer",
    },
]


async def seed_default_achievements(
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """初始化默认6个成就配置到DB（幂等操作，已存在的跳过）"""
    await _set_tenant(db, tenant_id)

    now = _now_utc()
    seeded_count = 0

    for idx, defn in enumerate(_DEFAULT_ACHIEVEMENTS):
        ach_id = str(uuid.uuid4())
        try:
            await db.execute(
                text("""
                    INSERT INTO points_mall_achievement_configs
                        (id, tenant_id, achievement_code, achievement_name,
                         description, trigger_type, trigger_threshold,
                         reward_points, badge_icon_url, is_active, sort_order,
                         created_at, updated_at, is_deleted)
                    VALUES
                        (:id, :tid, :code, :name,
                         :desc, :trigger_type, :threshold,
                         :reward_pts, :icon, true, :sort,
                         :now, :now, false)
                    ON CONFLICT (tenant_id, achievement_code) DO NOTHING
                """),
                {
                    "id": ach_id,
                    "tid": tenant_id,
                    "code": defn["code"],
                    "name": defn["name"],
                    "desc": defn["description"],
                    "trigger_type": defn["trigger_type"],
                    "threshold": defn["threshold"],
                    "reward_pts": defn["reward_points"],
                    "icon": defn["icon"],
                    "sort": idx * 10,
                    "now": now,
                },
            )
            seeded_count += 1
        except IntegrityError:
            # 已存在，跳过
            pass

    await db.flush()

    logger.info(
        "points_mall.seed_achievements",
        tenant_id=tenant_id,
        seeded_count=seeded_count,
    )
    return {"seeded_count": seeded_count, "total_defaults": len(_DEFAULT_ACHIEVEMENTS)}


async def get_achievement_list(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """成就系统 -- 从DB读取成就配置 + 计算进度

    Returns:
        {"achievements": [...], "earned_count", "total_count"}
    """
    await _set_tenant(db, tenant_id)

    # 从DB读取成就配置
    config_rows = await db.execute(
        text("""
            SELECT id, achievement_code, achievement_name, description,
                   trigger_type, trigger_threshold, reward_points,
                   badge_icon_url, sort_order
            FROM points_mall_achievement_configs
            WHERE tenant_id = :tid AND is_active = true AND is_deleted = false
            ORDER BY sort_order ASC
        """),
        {"tid": tenant_id},
    )
    configs = config_rows.mappings().all()

    if not configs:
        return {"achievements": [], "earned_count": 0, "total_count": 0}

    # 查询客户指标
    metrics_row = await db.execute(
        text("""
            SELECT
                COALESCE((SELECT COUNT(*) FROM orders
                          WHERE customer_id = :cid AND tenant_id = :tid
                            AND status = 'completed'), 0) as order_count,
                COALESCE((SELECT SUM(final_amount_fen) FROM orders
                          WHERE customer_id = :cid AND tenant_id = :tid
                            AND status = 'completed'), 0) as total_spent_fen,
                COALESCE((SELECT COUNT(*) FROM share_links
                          WHERE customer_id = :cid AND tenant_id = :tid), 0) as share_count,
                COALESCE((SELECT COUNT(*) FROM reviews
                          WHERE customer_id = :cid AND tenant_id = :tid), 0) as review_count
        """),
        {"cid": customer_id, "tid": tenant_id},
    )
    metrics = metrics_row.mappings().first()
    if not metrics:
        metrics = {"order_count": 0, "total_spent_fen": 0, "share_count": 0, "review_count": 0}

    # 已获得的成就
    earned_row = await db.execute(
        text("""
            SELECT achievement_id FROM customer_achievements
            WHERE customer_id = :cid AND tenant_id = :tid
        """),
        {"cid": customer_id, "tid": tenant_id},
    )
    earned_ids = {str(r[0]) for r in earned_row.fetchall()}

    achievements = []
    earned_count = 0
    for cfg in configs:
        metric_val = metrics.get(cfg["trigger_type"], 0) or 0
        earned = cfg["achievement_code"] in earned_ids
        if earned:
            earned_count += 1
        threshold = cfg["trigger_threshold"]
        progress = min(100, round(metric_val / threshold * 100, 1)) if threshold > 0 else 0

        achievements.append(
            {
                "id": cfg["achievement_code"],
                "name": cfg["achievement_name"],
                "description": cfg["description"] or "",
                "threshold": threshold,
                "metric": cfg["trigger_type"],
                "reward_points": cfg["reward_points"],
                "icon": cfg["badge_icon_url"] or "",
                "earned": earned,
                "progress": progress,
                "current_value": int(metric_val),
            }
        )

    logger.info(
        "points_mall.achievements",
        tenant_id=tenant_id,
        customer_id=customer_id,
        earned=earned_count,
        total=len(configs),
    )

    return {
        "achievements": achievements,
        "earned_count": earned_count,
        "total_count": len(configs),
    }


# ── 13. 过期自动清理 ──────────────────────────────────────────


async def cleanup_expired_products(
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """自动下架过期商品（valid_until < NOW() 且仍 is_active=true）"""
    await _set_tenant(db, tenant_id)

    now = _now_utc()
    result = await db.execute(
        text("""
            UPDATE points_mall_products
            SET is_active = false, updated_at = :now
            WHERE tenant_id = :tid
              AND is_deleted = false
              AND is_active = true
              AND valid_until IS NOT NULL
              AND valid_until < :now
            RETURNING id
        """),
        {"tid": tenant_id, "now": now},
    )
    deactivated_ids = [str(r[0]) for r in result.fetchall()]
    await db.flush()

    logger.info(
        "points_mall.cleanup_expired_products",
        tenant_id=tenant_id,
        deactivated_count=len(deactivated_ids),
    )

    return {
        "deactivated_count": len(deactivated_ids),
        "deactivated_product_ids": deactivated_ids,
    }


async def cleanup_expired_orders(
    tenant_id: str,
    db: AsyncSession,
    expire_after_days: int = 30,
) -> dict[str, Any]:
    """自动过期未核销订单

    将 pending 状态且超过 expire_after_days 天的订单标记为 expired。
    同时退还积分 + 退还库存。
    """
    await _set_tenant(db, tenant_id)

    now = _now_utc()

    # 查找待过期订单
    expired_rows = await db.execute(
        text("""
            SELECT id, order_no, customer_id, product_id,
                   points_deducted, quantity
            FROM points_mall_orders
            WHERE tenant_id = :tid
              AND is_deleted = false
              AND status = 'pending'
              AND (
                  (expired_at IS NOT NULL AND expired_at < :now)
                  OR
                  (expired_at IS NULL AND created_at < :now - (:days || ' days')::interval)
              )
            FOR UPDATE
        """),
        {"tid": tenant_id, "now": now, "days": expire_after_days},
    )
    orders_to_expire = expired_rows.mappings().all()

    expired_ids: list[str] = []
    total_points_refunded = 0

    for order in orders_to_expire:
        order_id = str(order["id"])
        customer_id = str(order["customer_id"])
        product_id = str(order["product_id"])
        points = order["points_deducted"]
        qty = order["quantity"]

        # 标记为 expired
        await db.execute(
            text("""
                UPDATE points_mall_orders
                SET status = 'expired', updated_at = :now
                WHERE id = :oid AND tenant_id = :tid
            """),
            {"oid": order_id, "tid": tenant_id, "now": now},
        )

        # 退还积分
        card_row = await db.execute(
            text("""
                SELECT id FROM member_cards
                WHERE customer_id = :cid AND tenant_id = :tid
                  AND is_deleted = false
                LIMIT 1
            """),
            {"cid": customer_id, "tid": tenant_id},
        )
        card = card_row.mappings().first()
        if card:
            card_id = str(card["id"])
            await db.execute(
                text("""
                    UPDATE member_cards
                    SET points = points + :pts, updated_at = :now
                    WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
                """),
                {"pts": points, "cid": card_id, "tid": tenant_id, "now": now},
            )

            # 写退还积分流水
            refund_log_id = str(uuid.uuid4())
            await db.execute(
                text("""
                    INSERT INTO points_log
                        (id, tenant_id, card_id, direction, source, points, created_at)
                    VALUES (:id, :tid, :cid, 'earn', 'points_mall_expired_refund', :pts, :now)
                """),
                {
                    "id": refund_log_id,
                    "tid": tenant_id,
                    "cid": card_id,
                    "pts": points,
                    "now": now,
                },
            )

        # 退还库存
        prod_row = await db.execute(
            text("SELECT stock FROM points_mall_products WHERE id = :pid AND tenant_id = :tid"),
            {"pid": product_id, "tid": tenant_id},
        )
        prod = prod_row.mappings().first()
        if prod and prod["stock"] == -1:
            await db.execute(
                text("""
                    UPDATE points_mall_products
                    SET stock_sold = GREATEST(0, stock_sold - :qty), updated_at = :now
                    WHERE id = :pid AND tenant_id = :tid
                """),
                {"qty": qty, "pid": product_id, "tid": tenant_id, "now": now},
            )
        elif prod:
            await db.execute(
                text("""
                    UPDATE points_mall_products
                    SET stock = stock + :qty,
                        stock_sold = GREATEST(0, stock_sold - :qty),
                        updated_at = :now
                    WHERE id = :pid AND tenant_id = :tid
                """),
                {"qty": qty, "pid": product_id, "tid": tenant_id, "now": now},
            )

        expired_ids.append(order_id)
        total_points_refunded += points

    await db.flush()

    logger.info(
        "points_mall.cleanup_expired_orders",
        tenant_id=tenant_id,
        expired_count=len(expired_ids),
        total_points_refunded=total_points_refunded,
    )

    return {
        "expired_count": len(expired_ids),
        "expired_order_ids": expired_ids,
        "total_points_refunded": total_points_refunded,
    }


# ── 14. 实物发货流转 ──────────────────────────────────────────


async def ship_order(
    order_id: str,
    carrier: str,
    tracking_no: str,
    tenant_id: str,
    db: AsyncSession,
    operator_id: str | None = None,
) -> dict[str, Any]:
    """实物发货 — 更新 fulfillment_status 为 shipped + 记录物流信息

    仅限 status=pending 或 status=fulfilled 且 fulfillment_status=pending 的实物订单。
    """
    await _set_tenant(db, tenant_id)

    if not carrier or not tracking_no:
        raise ValueError("carrier_and_tracking_no_required")

    now = _now_utc()

    # 锁定订单
    order_row = await db.execute(
        text("""
            SELECT o.id, o.order_no, o.customer_id, o.product_id,
                   o.status, o.fulfillment_status,
                   p.product_type
            FROM points_mall_orders o
            LEFT JOIN points_mall_products p ON p.id = o.product_id
            WHERE o.id = :oid AND o.tenant_id = :tid
              AND o.is_deleted = false
            FOR UPDATE OF o
        """),
        {"oid": order_id, "tid": tenant_id},
    )
    order = order_row.mappings().first()
    if not order:
        raise ValueError("order_not_found")

    if order["product_type"] != "physical":
        raise ValueError("only_physical_orders_can_ship")

    if order["fulfillment_status"] not in ("pending",):
        raise ValueError(f"cannot_ship_status:{order['fulfillment_status']}")

    shipping_info = {
        "carrier": carrier,
        "tracking_no": tracking_no,
        "shipped_at": now.isoformat(),
        "operator_id": operator_id,
    }

    await db.execute(
        text("""
            UPDATE points_mall_orders
            SET fulfillment_status = 'shipped',
                shipping_info = :info::jsonb,
                tracking_no = :tracking,
                updated_at = :now
            WHERE id = :oid AND tenant_id = :tid
        """),
        {
            "oid": order_id,
            "tid": tenant_id,
            "info": json.dumps(shipping_info, ensure_ascii=False),
            "tracking": tracking_no,
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "points_mall.ship_order",
        tenant_id=tenant_id,
        order_id=order_id,
        carrier=carrier,
        tracking_no=tracking_no,
    )

    return {
        "order_id": order_id,
        "order_no": str(order["order_no"]),
        "fulfillment_status": "shipped",
        "shipping_info": shipping_info,
    }


async def confirm_delivery(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """确认收货 — 将 fulfillment_status 从 shipped 更新为 delivered，同时 status -> fulfilled"""
    await _set_tenant(db, tenant_id)

    now = _now_utc()

    result = await db.execute(
        text("""
            UPDATE points_mall_orders
            SET fulfillment_status = 'delivered',
                status = 'fulfilled',
                fulfilled_at = :now,
                updated_at = :now
            WHERE id = :oid AND tenant_id = :tid
              AND fulfillment_status = 'shipped'
              AND is_deleted = false
            RETURNING id, order_no, customer_id
        """),
        {"oid": order_id, "tid": tenant_id, "now": now},
    )
    row = result.mappings().first()
    if not row:
        raise ValueError("order_not_found_or_not_shipped")

    await db.flush()

    logger.info(
        "points_mall.confirm_delivery",
        tenant_id=tenant_id,
        order_id=order_id,
    )

    return {
        "order_id": order_id,
        "order_no": str(row["order_no"]),
        "fulfillment_status": "delivered",
        "status": "fulfilled",
        "fulfilled_at": now.isoformat(),
    }
