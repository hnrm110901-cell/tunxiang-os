"""自助点餐引擎 -- AI推荐/套餐组合/最优优惠/AA分摊/制作进度/最近门店/等待时间

所有金额单位：分(fen)。
AI推荐权重: 历史偏好0.3 + 时段0.2 + 毛利0.2 + 热度0.2 + 天气0.1
制作进度: 5步(received -> preparing -> cooking -> plating -> ready)
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ── 常量 ──────────────────────────────────────────────────────

PREPARATION_STEPS = [
    {"step": 1, "key": "received", "label": "已接单"},
    {"step": 2, "key": "preparing", "label": "备料中"},
    {"step": 3, "key": "cooking", "label": "烹饪中"},
    {"step": 4, "key": "plating", "label": "装盘中"},
    {"step": 5, "key": "ready", "label": "可取餐"},
]
STEP_KEY_TO_INDEX = {s["key"]: s["step"] for s in PREPARATION_STEPS}

# AI推荐权重
W_HISTORY = 0.3
W_TIME = 0.2
W_MARGIN = 0.2
W_POPULARITY = 0.2
W_WEATHER = 0.1

MEAL_PERIODS = {
    "breakfast": (6, 10),
    "lunch": (11, 14),
    "afternoon_tea": (14, 17),
    "dinner": (17, 21),
    "late_night": (21, 6),
}


# ── 工具函数 ──────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _detect_meal_period(hour: int) -> str:
    for period, (start, end) in MEAL_PERIODS.items():
        if start <= end:
            if start <= hour < end:
                return period
        else:
            if hour >= start or hour < end:
                return period
    return "lunch"


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine 公式计算两点距离 (km)"""
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ── 1. AI 智能推荐 ───────────────────────────────────────────


async def ai_recommend_dishes(
    customer_id: Optional[str],
    guest_count: int,
    time_slot: Optional[str],
    weather: Optional[str],
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """AI推荐菜品 -- 历史偏好0.3 + 时段0.2 + 毛利0.2 + 热度0.2 + 天气0.1

    Returns:
        {"recommendations": [...], "guest_count", "time_slot", "weather"}
    """
    await _set_tenant(db, tenant_id)

    hour = datetime.now(timezone.utc).hour
    period = time_slot or _detect_meal_period(hour)

    # 获取门店在售菜品
    dish_rows = await db.execute(
        text("""
            SELECT d.id, d.name, d.category, d.price_fen,
                   d.tags, d.margin_rate, d.monthly_sales
            FROM dishes d
            WHERE d.tenant_id = :tid AND d.store_id = :sid
              AND d.is_deleted = false AND d.on_sale = true
            ORDER BY d.monthly_sales DESC
            LIMIT 200
        """),
        {"tid": tenant_id, "sid": store_id},
    )
    dishes = [dict(r) for r in dish_rows.mappings().all()]

    # 获取历史偏好
    history_dish_ids: set[str] = set()
    if customer_id:
        hist_rows = await db.execute(
            text("""
                SELECT DISTINCT oi.dish_id
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                WHERE o.customer_id = :cid AND o.tenant_id = :tid
                ORDER BY oi.dish_id
                LIMIT 50
            """),
            {"cid": customer_id, "tid": tenant_id},
        )
        history_dish_ids = {str(r[0]) for r in hist_rows.fetchall() if r[0]}

    # 计算最大值用于归一化
    max_sales = max((d.get("monthly_sales") or 0 for d in dishes), default=1) or 1
    max_margin = max((d.get("margin_rate") or 0 for d in dishes), default=1) or 1

    scored: list[dict[str, Any]] = []
    for dish in dishes:
        tags = [t.lower() for t in (dish.get("tags") or [])]

        # 历史偏好分 (0~1)
        s_history = 1.0 if str(dish["id"]) in history_dish_ids else 0.0

        # 时段分 (0~1)
        s_time = 0.0
        if period == "breakfast" and "breakfast" in tags:
            s_time = 1.0
        elif period in ("lunch", "dinner") and ("staple" in tags or "main" in tags):
            s_time = 0.8
        elif period == "afternoon_tea" and "dessert" in tags:
            s_time = 0.9
        elif period == "late_night" and "snack" in tags:
            s_time = 0.8

        # 毛利分 (归一化)
        s_margin = (dish.get("margin_rate") or 0) / max_margin

        # 热度分 (归一化)
        s_popularity = (dish.get("monthly_sales") or 0) / max_sales

        # 天气分 (0~1)
        s_weather = 0.0
        if weather == "cold" and ("hot_pot" in tags or "soup" in tags or "warm" in tags):
            s_weather = 1.0
        elif weather == "hot" and ("cold" in tags or "refreshing" in tags or "iced" in tags):
            s_weather = 1.0
        elif weather == "rainy" and ("comfort" in tags or "soup" in tags):
            s_weather = 0.8

        total = (
            W_HISTORY * s_history
            + W_TIME * s_time
            + W_MARGIN * s_margin
            + W_POPULARITY * s_popularity
            + W_WEATHER * s_weather
        )

        reasons: list[str] = []
        if s_history > 0:
            reasons.append("你曾点过")
        if s_time > 0:
            reasons.append(f"{period}推荐")
        if s_weather > 0:
            reasons.append("适合当前天气")
        if s_popularity > 0.7:
            reasons.append("人气热销")

        scored.append({
            "dish_id": str(dish["id"]),
            "dish_name": dish["name"],
            "category": dish.get("category", ""),
            "price_fen": dish.get("price_fen", 0),
            "score": round(total, 4),
            "reason": "，".join(reasons) if reasons else "综合推荐",
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    # 按人数推荐数量: 1~2人6道, 3~4人8道, 5人+10道
    limit = 6 if guest_count <= 2 else (8 if guest_count <= 4 else 10)
    recommendations = scored[:limit]

    logger.info(
        "self_order.ai_recommend",
        tenant_id=tenant_id,
        store_id=store_id,
        customer_id=customer_id,
        guest_count=guest_count,
        period=period,
        weather=weather,
        count=len(recommendations),
    )

    return {
        "recommendations": recommendations,
        "guest_count": guest_count,
        "time_slot": period,
        "weather": weather or "unknown",
    }


# ── 2. 套餐智能组合 ─────────────────────────────────────────


async def calculate_combo_suggestion(
    guest_count: int,
    budget_fen: int,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """按人数+预算自动推荐套餐组合

    Returns:
        {"combos": [...], "guest_count", "budget_fen"}
    """
    await _set_tenant(db, tenant_id)

    # 查询可用菜品 (按类别分组)
    rows = await db.execute(
        text("""
            SELECT id, name, category, price_fen, margin_rate
            FROM dishes
            WHERE tenant_id = :tid AND store_id = :sid
              AND is_deleted = false AND on_sale = true
            ORDER BY margin_rate DESC, price_fen ASC
            LIMIT 100
        """),
        {"tid": tenant_id, "sid": store_id},
    )
    dishes = [dict(r) for r in rows.mappings().all()]

    # 按类别分组
    by_cat: dict[str, list[dict]] = {}
    for d in dishes:
        cat = d.get("category", "other")
        by_cat.setdefault(cat, []).append(d)

    # 简单套餐组合算法: 荤菜+素菜+主食+汤
    combos: list[dict[str, Any]] = []

    # 人均预算
    per_person_fen = budget_fen // max(guest_count, 1)

    # 推荐份数: 荤菜=人数, 素菜=ceil(人数/2), 主食=人数, 汤=1
    meat_count = guest_count
    veg_count = math.ceil(guest_count / 2)
    staple_count = guest_count
    soup_count = 1

    combo_items: list[dict[str, Any]] = []
    total_fen = 0

    for cat_key, need_count in [("meat", meat_count), ("vegetable", veg_count),
                                 ("staple", staple_count), ("soup", soup_count)]:
        available = by_cat.get(cat_key, [])
        for d in available[:need_count]:
            item_cost = d.get("price_fen", 0)
            if total_fen + item_cost <= budget_fen:
                combo_items.append({
                    "dish_id": str(d["id"]),
                    "dish_name": d["name"],
                    "category": cat_key,
                    "price_fen": item_cost,
                    "quantity": 1,
                })
                total_fen += item_cost

    if combo_items:
        combos.append({
            "combo_name": f"{guest_count}人精选套餐",
            "items": combo_items,
            "total_fen": total_fen,
            "savings_fen": max(0, budget_fen - total_fen),
            "per_person_fen": total_fen // max(guest_count, 1),
        })

    logger.info(
        "self_order.combo_suggestion",
        tenant_id=tenant_id,
        store_id=store_id,
        guest_count=guest_count,
        budget_fen=budget_fen,
        combo_count=len(combos),
    )

    return {
        "combos": combos,
        "guest_count": guest_count,
        "budget_fen": budget_fen,
    }


# ── 3. 最优优惠方案 ─────────────────────────────────────────


async def find_best_deal(
    cart_items: list[dict[str, Any]],
    available_coupons: list[dict[str, Any]],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """自动选择最划算的券组合

    Args:
        cart_items: [{"dish_id", "price_fen", "quantity"}]
        available_coupons: [{"coupon_id", "type", "threshold_fen", "discount_fen", "discount_rate"}]

    Returns:
        {"best_plan", "cart_total_fen", "discount_fen", "final_fen", "applied_coupons"}
    """
    await _set_tenant(db, tenant_id)

    cart_total = sum(item.get("price_fen", 0) * item.get("quantity", 1) for item in cart_items)

    # 评估每张券的优惠力度
    coupon_values: list[tuple[int, dict]] = []
    for coupon in available_coupons:
        c_type = coupon.get("type", "")
        threshold = coupon.get("threshold_fen", 0)

        if cart_total < threshold:
            continue

        if c_type == "fixed":
            value = coupon.get("discount_fen", 0)
        elif c_type == "percentage":
            rate = coupon.get("discount_rate", 1.0)
            value = int(cart_total * (1 - rate))
        else:
            value = coupon.get("discount_fen", 0)

        coupon_values.append((value, coupon))

    # 排序选最优 (简单贪心: 选优惠力度最大的)
    coupon_values.sort(key=lambda x: x[0], reverse=True)

    applied: list[dict[str, Any]] = []
    total_discount = 0

    if coupon_values:
        best_value, best_coupon = coupon_values[0]
        applied.append({
            "coupon_id": best_coupon.get("coupon_id", ""),
            "type": best_coupon.get("type", ""),
            "discount_fen": best_value,
        })
        total_discount = best_value

    final_fen = max(0, cart_total - total_discount)

    logger.info(
        "self_order.find_best_deal",
        tenant_id=tenant_id,
        cart_total=cart_total,
        discount=total_discount,
        final=final_fen,
        coupon_count=len(applied),
    )

    return {
        "best_plan": "optimal_single" if applied else "no_coupon",
        "cart_total_fen": cart_total,
        "discount_fen": total_discount,
        "final_fen": final_fen,
        "applied_coupons": applied,
    }


# ── 4. AA 分摊计算 ──────────────────────────────────────────


async def calculate_aa_split(
    order_id: str,
    split_count: int,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """AA分摊: 均分(四舍五入到分) + 按菜分(谁点的谁付)

    Returns:
        {"order_id", "total_fen", "even_split": [...], "by_item_split": [...]}
    """
    await _set_tenant(db, tenant_id)

    if split_count <= 0:
        raise ValueError("split_count_must_be_positive")

    # 查订单总额
    order_row = await db.execute(
        text("""
            SELECT final_amount_fen FROM orders
            WHERE id = :oid AND tenant_id = :tid
        """),
        {"oid": order_id, "tid": tenant_id},
    )
    order = order_row.mappings().first()
    if not order:
        raise ValueError("order_not_found")

    total_fen = order["final_amount_fen"]

    # 均分: 四舍五入到分, 最后一个人补差
    base = total_fen // split_count
    remainder = total_fen - base * split_count
    even_split = []
    for i in range(split_count):
        amount = base + (1 if i < remainder else 0)
        even_split.append({"person_index": i, "amount_fen": amount})

    # 按菜分: 查询订单明细
    item_rows = await db.execute(
        text("""
            SELECT id, item_name, subtotal_fen, notes
            FROM order_items
            WHERE order_id = :oid AND tenant_id = :tid
        """),
        {"oid": order_id, "tid": tenant_id},
    )
    items = [dict(r) for r in item_rows.mappings().all()]

    by_item_split = [
        {
            "item_id": str(item["id"]),
            "item_name": item["item_name"],
            "amount_fen": item["subtotal_fen"],
        }
        for item in items
    ]

    logger.info(
        "self_order.aa_split",
        tenant_id=tenant_id,
        order_id=order_id,
        split_count=split_count,
        total_fen=total_fen,
    )

    return {
        "order_id": order_id,
        "total_fen": total_fen,
        "split_count": split_count,
        "even_split": even_split,
        "by_item_split": by_item_split,
    }


# ── 5. 制作进度追踪 ─────────────────────────────────────────


async def track_preparation(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """制作进度: received -> preparing -> cooking -> plating -> ready (5步)

    Returns:
        {"order_id", "current_step", "steps", "estimated_ready_at", "remaining_seconds"}
    """
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT cooking_status, accepted_at, estimated_minutes
            FROM orders
            WHERE id = :oid AND tenant_id = :tid
        """),
        {"oid": order_id, "tid": tenant_id},
    )
    order = row.mappings().first()
    if not order:
        raise ValueError("order_not_found")

    current_key = order.get("cooking_status") or "received"
    current_idx = STEP_KEY_TO_INDEX.get(current_key, 1)
    accepted_at = order.get("accepted_at")
    est_minutes = order.get("estimated_minutes") or 20

    estimated_ready_at = None
    remaining_seconds = 0
    if accepted_at and current_idx < 5:
        estimated_ready_at = accepted_at + timedelta(minutes=est_minutes)
        remaining = (estimated_ready_at - _now_utc()).total_seconds()
        remaining_seconds = max(0, int(remaining))

    steps_with_state = []
    for s in PREPARATION_STEPS:
        if s["step"] < current_idx:
            state = "done"
        elif s["step"] == current_idx:
            state = "active"
        else:
            state = "pending"
        steps_with_state.append({**s, "state": state})

    logger.info(
        "self_order.track_preparation",
        tenant_id=tenant_id,
        order_id=order_id,
        current_step=current_key,
    )

    return {
        "order_id": order_id,
        "current_step": current_key,
        "current_step_index": current_idx,
        "steps": steps_with_state,
        "estimated_ready_at": estimated_ready_at.isoformat() if estimated_ready_at else None,
        "remaining_seconds": remaining_seconds,
    }


# ── 6. GPS 最近门店 ─────────────────────────────────────────


async def get_nearest_stores(
    lat: float,
    lng: float,
    radius_km: float,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """GPS最近门店 -- 距离排序 + 营业状态 + 等位时间

    Returns:
        {"stores": [...], "center": {"lat", "lng"}, "radius_km"}
    """
    await _set_tenant(db, tenant_id)

    rows = await db.execute(
        text("""
            SELECT id, name, address, lat, lng, is_open,
                   current_queue_count, avg_wait_minutes
            FROM stores
            WHERE tenant_id = :tid AND is_deleted = false
        """),
        {"tid": tenant_id},
    )
    all_stores = [dict(r) for r in rows.mappings().all()]

    results: list[dict[str, Any]] = []
    for store in all_stores:
        s_lat = store.get("lat") or 0
        s_lng = store.get("lng") or 0
        if not s_lat or not s_lng:
            continue
        dist_km = _haversine_km(lat, lng, float(s_lat), float(s_lng))
        if dist_km <= radius_km:
            results.append({
                "store_id": str(store["id"]),
                "name": store["name"],
                "address": store.get("address", ""),
                "distance_m": int(dist_km * 1000),
                "is_open": store.get("is_open", False),
                "current_queue_count": store.get("current_queue_count", 0),
                "avg_wait_minutes": store.get("avg_wait_minutes", 0),
            })

    results.sort(key=lambda s: s["distance_m"])

    logger.info(
        "self_order.nearest_stores",
        tenant_id=tenant_id,
        lat=lat,
        lng=lng,
        radius_km=radius_km,
        found=len(results),
    )

    return {
        "stores": results[:20],
        "center": {"lat": lat, "lng": lng},
        "radius_km": radius_km,
    }


# ── 7. 预计等待时间 ─────────────────────────────────────────


async def estimate_wait_time(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """预计等待时间 -- 基于当前订单量 + 历史出餐速度

    Returns:
        {"store_id", "pending_orders", "avg_cook_minutes", "estimated_wait_minutes"}
    """
    await _set_tenant(db, tenant_id)

    # 当前未完成订单数
    pending_row = await db.execute(
        text("""
            SELECT COUNT(*) as cnt
            FROM orders
            WHERE store_id = :sid AND tenant_id = :tid
              AND status IN ('pending', 'confirmed')
              AND is_deleted = false
        """),
        {"sid": store_id, "tid": tenant_id},
    )
    pending_count = pending_row.scalar() or 0

    # 最近30单的平均出餐时间
    avg_row = await db.execute(
        text("""
            SELECT AVG(EXTRACT(EPOCH FROM (completed_at - order_time)) / 60) as avg_min
            FROM orders
            WHERE store_id = :sid AND tenant_id = :tid
              AND status = 'completed'
              AND completed_at IS NOT NULL
              AND order_time IS NOT NULL
            ORDER BY completed_at DESC
            LIMIT 30
        """),
        {"sid": store_id, "tid": tenant_id},
    )
    avg_cook_minutes = avg_row.scalar() or 15.0

    # 预估: 待处理订单数 * 平均出餐时间 / 并行能力(假设3个灶)
    parallel_capacity = 3
    estimated_wait = math.ceil(pending_count * avg_cook_minutes / parallel_capacity)

    logger.info(
        "self_order.estimate_wait",
        tenant_id=tenant_id,
        store_id=store_id,
        pending=pending_count,
        avg_cook=round(avg_cook_minutes, 1),
        estimated_wait=estimated_wait,
    )

    return {
        "store_id": store_id,
        "pending_orders": pending_count,
        "avg_cook_minutes": round(avg_cook_minutes, 1),
        "estimated_wait_minutes": estimated_wait,
    }
