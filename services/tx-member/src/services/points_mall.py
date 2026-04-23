"""积分商城 -- 商品列表/积分兑换/兑换历史/上架商品/成就系统/生日特权

积分兑换流程: 扣积分 + 创建兑换记录 + 库存-1
所有金额单位：分(fen)。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ── 成就里程碑定义 ────────────────────────────────────────────

ACHIEVEMENT_DEFINITIONS = [
    {
        "id": "first_order",
        "name": "初来乍到",
        "description": "完成首单",
        "threshold": 1,
        "metric": "order_count",
        "reward_points": 10,
        "icon": "badge_first",
    },
    {
        "id": "orders_10",
        "name": "常客",
        "description": "累计下单10次",
        "threshold": 10,
        "metric": "order_count",
        "reward_points": 50,
        "icon": "badge_regular",
    },
    {
        "id": "orders_50",
        "name": "铁粉",
        "description": "累计下单50次",
        "threshold": 50,
        "metric": "order_count",
        "reward_points": 200,
        "icon": "badge_super",
    },
    {
        "id": "spent_1000",
        "name": "千元户",
        "description": "累计消费满1000元",
        "threshold": 100000,
        "metric": "total_spent_fen",
        "reward_points": 100,
        "icon": "badge_spender",
    },
    {
        "id": "share_5",
        "name": "美食传播者",
        "description": "分享5次给好友",
        "threshold": 5,
        "metric": "share_count",
        "reward_points": 30,
        "icon": "badge_sharer",
    },
    {
        "id": "review_10",
        "name": "点评达人",
        "description": "发布10条评价",
        "threshold": 10,
        "metric": "review_count",
        "reward_points": 50,
        "icon": "badge_reviewer",
    },
]


# ── 工具函数 ──────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 1. 商城商品列表 ─────────────────────────────────────────


async def list_mall_items(
    category: Optional[str],
    tenant_id: str,
    db: AsyncSession,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """商城商品列表 -- 菜品/周边/优惠券

    Args:
        category: "dish" | "coupon" | "merchandise" | None(全部)

    Returns:
        {"items": [...], "total", "page", "size"}
    """
    await _set_tenant(db, tenant_id)

    offset = (page - 1) * size
    params: dict[str, Any] = {"tid": tenant_id, "lim": size, "off": offset}

    where_clause = "WHERE mi.tenant_id = :tid AND mi.is_deleted = false AND mi.stock > 0"
    if category:
        where_clause += " AND mi.category = :cat"
        params["cat"] = category

    cnt_row = await db.execute(
        text(f"SELECT COUNT(*) FROM mall_items mi {where_clause}"),
        params,
    )
    total = cnt_row.scalar() or 0

    rows = await db.execute(
        text(f"""
            SELECT mi.id, mi.name, mi.category, mi.points_cost,
                   mi.stock, mi.image_url, mi.description
            FROM mall_items mi
            {where_clause}
            ORDER BY mi.sort_order ASC, mi.created_at DESC
            LIMIT :lim OFFSET :off
        """),
        params,
    )
    items = [
        {
            "item_id": str(r["id"]),
            "name": r["name"],
            "category": r["category"],
            "points_cost": r["points_cost"],
            "stock": r["stock"],
            "image_url": r.get("image_url", ""),
            "description": r.get("description", ""),
        }
        for r in rows.mappings().all()
    ]

    logger.info(
        "points_mall.list",
        tenant_id=tenant_id,
        category=category,
        total=total,
        page=page,
    )

    return {"items": items, "total": total, "page": page, "size": size}


# ── 2. 积分兑换 ─────────────────────────────────────────────


async def exchange_item(
    customer_id: str,
    item_id: str,
    points_cost: int,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """积分兑换 -- 扣积分 + 创建兑换记录 + 库存-1

    Returns:
        {"exchange_id", "customer_id", "item_id", "points_deducted", "status"}
    """
    await _set_tenant(db, tenant_id)

    # 1. 检查商品库存
    item_row = await db.execute(
        text("""
            SELECT id, name, points_cost, stock
            FROM mall_items
            WHERE id = :iid AND tenant_id = :tid AND is_deleted = false
        """),
        {"iid": item_id, "tid": tenant_id},
    )
    item = item_row.mappings().first()
    if not item:
        raise ValueError("item_not_found")
    if item["stock"] <= 0:
        raise ValueError("item_out_of_stock")
    if item["points_cost"] != points_cost:
        raise ValueError("points_cost_mismatch")

    # 2. 检查会员积分余额
    bal_row = await db.execute(
        text("""
            SELECT id as card_id, points
            FROM member_cards
            WHERE customer_id = :cid AND tenant_id = :tid AND is_deleted = false
        """),
        {"cid": customer_id, "tid": tenant_id},
    )
    card = bal_row.mappings().first()
    if not card:
        raise ValueError("member_card_not_found")
    if card["points"] < points_cost:
        raise ValueError("insufficient_points")

    now = _now_utc()
    exchange_id = str(uuid.uuid4())

    # 3. 扣积分
    await db.execute(
        text("""
            UPDATE member_cards SET points = points - :pts, updated_at = :now
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
        """),
        {"pts": points_cost, "cid": str(card["card_id"]), "tid": tenant_id, "now": now},
    )

    # 4. 库存-1
    await db.execute(
        text("""
            UPDATE mall_items SET stock = stock - 1, updated_at = :now
            WHERE id = :iid AND tenant_id = :tid
        """),
        {"iid": item_id, "tid": tenant_id, "now": now},
    )

    # 5. 创建兑换记录
    await db.execute(
        text("""
            INSERT INTO exchange_records
                (id, tenant_id, customer_id, item_id, item_name,
                 points_cost, status, created_at)
            VALUES (:eid, :tid, :cid, :iid, :name, :pts, 'confirmed', :now)
        """),
        {
            "eid": exchange_id,
            "tid": tenant_id,
            "cid": customer_id,
            "iid": item_id,
            "name": item["name"],
            "pts": points_cost,
            "now": now,
        },
    )

    # 6. 记录积分流水
    log_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO points_log
                (id, tenant_id, card_id, direction, source, points, created_at)
            VALUES (:id, :tid, :cid, 'spend', 'exchange', :pts, :now)
        """),
        {
            "id": log_id,
            "tid": tenant_id,
            "cid": str(card["card_id"]),
            "pts": points_cost,
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "points_mall.exchange",
        tenant_id=tenant_id,
        exchange_id=exchange_id,
        customer_id=customer_id,
        item_id=item_id,
        points_deducted=points_cost,
    )

    return {
        "exchange_id": exchange_id,
        "customer_id": customer_id,
        "item_id": item_id,
        "item_name": item["name"],
        "points_deducted": points_cost,
        "status": "confirmed",
    }


# ── 3. 兑换历史 ─────────────────────────────────────────────


async def get_exchange_history(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """兑换历史

    Returns:
        {"items": [...], "total", "page", "size"}
    """
    await _set_tenant(db, tenant_id)

    offset = (page - 1) * size

    cnt_row = await db.execute(
        text("""
            SELECT COUNT(*) FROM exchange_records
            WHERE customer_id = :cid AND tenant_id = :tid
        """),
        {"cid": customer_id, "tid": tenant_id},
    )
    total = cnt_row.scalar() or 0

    rows = await db.execute(
        text("""
            SELECT id, item_id, item_name, points_cost, status, created_at
            FROM exchange_records
            WHERE customer_id = :cid AND tenant_id = :tid
            ORDER BY created_at DESC
            LIMIT :lim OFFSET :off
        """),
        {"cid": customer_id, "tid": tenant_id, "lim": size, "off": offset},
    )
    items = [
        {
            "exchange_id": str(r["id"]),
            "item_id": str(r["item_id"]),
            "item_name": r["item_name"],
            "points_cost": r["points_cost"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat()
            if hasattr(r["created_at"], "isoformat")
            else str(r["created_at"]),
        }
        for r in rows.mappings().all()
    ]

    logger.info(
        "points_mall.history",
        tenant_id=tenant_id,
        customer_id=customer_id,
        total=total,
    )

    return {"items": items, "total": total, "page": page, "size": size}


# ── 4. 上架商品 ─────────────────────────────────────────────


async def create_mall_item(
    name: str,
    category: str,
    points_cost: int,
    stock: int,
    image_url: str,
    tenant_id: str,
    db: AsyncSession,
    description: str = "",
) -> dict[str, Any]:
    """上架商品

    Args:
        category: "dish" | "coupon" | "merchandise"

    Returns:
        {"item_id", "name", "category", "points_cost", "stock"}
    """
    await _set_tenant(db, tenant_id)

    if category not in ("dish", "coupon", "merchandise"):
        raise ValueError("invalid_category")
    if points_cost <= 0:
        raise ValueError("points_cost_must_be_positive")
    if stock < 0:
        raise ValueError("stock_cannot_be_negative")

    item_id = str(uuid.uuid4())
    now = _now_utc()

    await db.execute(
        text("""
            INSERT INTO mall_items
                (id, tenant_id, name, category, points_cost,
                 stock, image_url, description, sort_order,
                 is_deleted, created_at, updated_at)
            VALUES (:iid, :tid, :name, :cat, :pts,
                    :stock, :img, :desc, 0,
                    false, :now, :now)
        """),
        {
            "iid": item_id,
            "tid": tenant_id,
            "name": name,
            "cat": category,
            "pts": points_cost,
            "stock": stock,
            "img": image_url,
            "desc": description,
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "points_mall.create_item",
        tenant_id=tenant_id,
        item_id=item_id,
        name=name,
        category=category,
        points_cost=points_cost,
    )

    return {
        "item_id": item_id,
        "name": name,
        "category": category,
        "points_cost": points_cost,
        "stock": stock,
        "image_url": image_url,
    }


# ── 5. 成就系统 ─────────────────────────────────────────────


async def get_achievement_list(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """成就系统 -- 消费里程碑 + 徽章

    Returns:
        {"achievements": [...], "earned_count", "total_count"}
    """
    await _set_tenant(db, tenant_id)

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
    for defn in ACHIEVEMENT_DEFINITIONS:
        metric_val = metrics.get(defn["metric"], 0) or 0
        earned = defn["id"] in earned_ids
        if earned:
            earned_count += 1
        progress = min(100, round(metric_val / defn["threshold"] * 100, 1)) if defn["threshold"] > 0 else 0

        achievements.append(
            {
                **defn,
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
        total=len(ACHIEVEMENT_DEFINITIONS),
    )

    return {
        "achievements": achievements,
        "earned_count": earned_count,
        "total_count": len(ACHIEVEMENT_DEFINITIONS),
    }


# ── 6. 生日月特权检查 ───────────────────────────────────────


async def check_birthday_privilege(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """生日月特权检查

    Returns:
        {"eligible", "birthday_month", "current_month", "rewards": [...]}
    """
    await _set_tenant(db, tenant_id)

    # 查客户生日
    row = await db.execute(
        text("""
            SELECT birthday FROM customers
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
        """),
        {"cid": customer_id, "tid": tenant_id},
    )
    result = row.mappings().first()
    if not result:
        raise ValueError("customer_not_found")

    birthday = result.get("birthday")
    if not birthday:
        return {
            "eligible": False,
            "birthday_month": None,
            "current_month": _now_utc().month,
            "rewards": [],
            "reason": "birthday_not_set",
        }

    if hasattr(birthday, "month"):
        birthday_month = birthday.month
    else:
        birthday_month = int(str(birthday).split("-")[1])

    current_month = _now_utc().month
    eligible = birthday_month == current_month

    rewards = []
    if eligible:
        # 检查是否已领取过
        used_row = await db.execute(
            text("""
                SELECT id FROM birthday_rewards
                WHERE customer_id = :cid AND tenant_id = :tid
                  AND reward_year = :year AND reward_month = :month
            """),
            {"cid": customer_id, "tid": tenant_id, "year": _now_utc().year, "month": current_month},
        )
        already_claimed = used_row.scalar() is not None

        if not already_claimed:
            rewards = [
                {"type": "coupon", "description": "生日专属8折券", "discount_rate": 0.8},
                {"type": "points", "description": "生日双倍积分", "multiplier": 2},
                {"type": "gift", "description": "生日惊喜甜品", "dish_name": "生日蛋糕"},
            ]

    logger.info(
        "points_mall.birthday_check",
        tenant_id=tenant_id,
        customer_id=customer_id,
        eligible=eligible,
        birthday_month=birthday_month,
    )

    return {
        "eligible": eligible,
        "birthday_month": birthday_month,
        "current_month": current_month,
        "rewards": rewards,
    }
