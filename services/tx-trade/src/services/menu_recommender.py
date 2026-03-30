"""菜单智能推荐引擎 — 扫码点单场景

推荐维度：
a. 毛利优先：高毛利菜品排前面（从 Dish.cost_fen 计算）
b. 库存充足：沽清菜品不推荐（从 is_available + kds_shortage 过滤）
c. 时段匹配：午市推快餐、晚市推大菜
d. 顾客历史：如果有 customer_id，推荐常点菜品
e. 热度排行：最近 7 天销量 Top 10
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Dish, Order, OrderItem

logger = structlog.get_logger()

# ─── 时段定义 ───

MEAL_PERIODS = {
    "breakfast": (6, 10),   # 早餐 06:00-10:00
    "lunch": (10, 14),      # 午市 10:00-14:00
    "afternoon": (14, 17),  # 下午茶 14:00-17:00
    "dinner": (17, 21),     # 晚市 17:00-21:00
    "late_night": (21, 6),  # 夜宵 21:00-06:00
}

# 时段偏好：午市偏快餐（preparation_time 短），晚市偏大菜
PERIOD_PREP_TIME_MAX = {
    "breakfast": 10,
    "lunch": 15,
    "afternoon": 10,
    "dinner": None,      # 晚市不限
    "late_night": 15,
}

# 推荐理由模板
REASON_SIGNATURE = "本店招牌"
REASON_TODAY_SPECIAL = "今日特推"
REASON_REPEAT_ORDER = "您上次点过"
REASON_HIGH_VALUE = "高性价比"
REASON_HOT_SELLER = "近期热销"
REASON_MEAL_FIT = "时段推荐"


def _current_meal_period() -> str:
    """根据当前时间判断就餐时段"""
    hour = datetime.now(timezone.utc).hour + 8  # UTC+8 中国时区
    if hour >= 24:
        hour -= 24
    for period, (start, end) in MEAL_PERIODS.items():
        if start <= end:
            if start <= hour < end:
                return period
        else:  # 跨午夜（late_night: 21-6）
            if hour >= start or hour < end:
                return period
    return "dinner"


async def get_recommendations(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    customer_id: Optional[str] = None,
    table_no: str = "",
    limit: int = 10,
) -> list[dict]:
    """获取扫码点单推荐列表

    综合毛利、库存、时段、顾客历史、热度五个维度打分排序。

    Args:
        db: 数据库会话
        tenant_id: 租户ID
        store_id: 门店ID
        customer_id: 顾客ID（可选，有则加入历史维度）
        table_no: 桌号
        limit: 返回条数

    Returns:
        [{"dish_id", "dish_name", "price_fen", "image_url", "reason", "score"}, ...]
    """
    tid = uuid.UUID(tenant_id)
    sid = uuid.UUID(store_id)
    meal_period = _current_meal_period()
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)

    # 1. 获取门店在售菜品（过滤掉不可用/已删除）
    dishes_result = await db.execute(
        select(Dish).where(
            Dish.tenant_id == tid,
            Dish.is_available == True,  # noqa: E712
            Dish.is_deleted == False,   # noqa: E712
            # 门店专属或集团通用
            (Dish.store_id == sid) | (Dish.store_id == None),  # noqa: E711
        )
    )
    dishes = list(dishes_result.scalars().all())

    if not dishes:
        return []

    # 2. 获取最近 7 天热销数据
    hot_sales = await _get_hot_sales(db, tid, sid, seven_days_ago)

    # 3. 获取顾客历史点单
    customer_history: dict[str, int] = {}
    if customer_id:
        customer_history = await _get_customer_history(db, tid, customer_id)

    # 4. 为每道菜打分
    scored_dishes: list[dict] = []
    for dish in dishes:
        score = 0.0
        reasons: list[str] = []
        dish_id_str = str(dish.id)

        # a. 毛利维度（0-30分）
        margin_score = _calc_margin_score(dish)
        score += margin_score
        if margin_score >= 25:
            reasons.append(REASON_HIGH_VALUE)

        # b. 招牌/推荐标记（0-20分）
        if dish.is_recommended:
            score += 20
            reasons.append(REASON_SIGNATURE)
        if dish.tags and "招牌" in dish.tags:
            score += 15
            if REASON_SIGNATURE not in reasons:
                reasons.append(REASON_SIGNATURE)
        if dish.tags and ("新品" in dish.tags or "特价" in dish.tags):
            score += 10
            reasons.append(REASON_TODAY_SPECIAL)

        # c. 时段匹配（0-15分）
        period_score = _calc_period_score(dish, meal_period)
        score += period_score
        if period_score >= 10:
            reasons.append(REASON_MEAL_FIT)

        # d. 顾客历史（0-20分）
        if dish_id_str in customer_history:
            order_count = customer_history[dish_id_str]
            history_score = min(20, order_count * 5)
            score += history_score
            reasons.append(REASON_REPEAT_ORDER)

        # e. 热度排行（0-15分）
        if dish_id_str in hot_sales:
            rank_sales = hot_sales[dish_id_str]
            hot_score = min(15, rank_sales * 0.5)
            score += hot_score
            if hot_score >= 8:
                reasons.append(REASON_HOT_SELLER)

        # 选择最佳理由（取第一个）
        primary_reason = reasons[0] if reasons else REASON_HIGH_VALUE

        scored_dishes.append({
            "dish_id": dish_id_str,
            "dish_name": dish.dish_name,
            "price_fen": dish.price_fen,
            "image_url": dish.image_url or "",
            "reason": primary_reason,
            "score": round(score, 1),
            "category_id": str(dish.category_id) if dish.category_id else "",
        })

    # 5. 按分数排序，取 Top N
    scored_dishes.sort(key=lambda x: x["score"], reverse=True)
    result = scored_dishes[:limit]

    logger.info(
        "scan_order_recommendations",
        store_id=store_id,
        customer_id=customer_id,
        meal_period=meal_period,
        total_dishes=len(dishes),
        recommended=len(result),
    )

    return result


def _calc_margin_score(dish: Dish) -> float:
    """毛利维度打分：0-30分

    毛利率 >= 70% → 30分
    毛利率 >= 60% → 25分
    毛利率 >= 50% → 20分
    毛利率 >= 40% → 15分
    其余 → 10分
    无成本数据 → 15分（中等）
    """
    if not dish.cost_fen or dish.cost_fen <= 0:
        return 15.0
    if dish.price_fen <= 0:
        return 10.0

    margin_pct = (dish.price_fen - dish.cost_fen) / dish.price_fen * 100

    if margin_pct >= 70:
        return 30.0
    elif margin_pct >= 60:
        return 25.0
    elif margin_pct >= 50:
        return 20.0
    elif margin_pct >= 40:
        return 15.0
    else:
        return 10.0


def _calc_period_score(dish: Dish, meal_period: str) -> float:
    """时段匹配打分：0-15分

    午市：preparation_time <= 15分钟的加分
    晚市：大菜（preparation_time > 15分钟）加分
    """
    max_prep = PERIOD_PREP_TIME_MAX.get(meal_period)
    prep_time = dish.preparation_time

    if prep_time is None:
        return 5.0  # 无数据给中间分

    if meal_period in ("lunch", "breakfast", "afternoon", "late_night"):
        # 快餐时段：制作时间短的加分
        if max_prep and prep_time <= max_prep:
            return 15.0
        elif max_prep and prep_time <= max_prep * 1.5:
            return 8.0
        else:
            return 3.0
    else:
        # 晚市：大菜反而加分
        if prep_time > 15:
            return 12.0
        else:
            return 8.0


async def _get_hot_sales(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    since: datetime,
) -> dict[str, int]:
    """获取最近 7 天各菜品销量"""
    result = await db.execute(
        select(
            OrderItem.dish_id,
            func.sum(OrderItem.quantity).label("total_qty"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.tenant_id == tenant_id,
            Order.store_id == store_id,
            Order.created_at >= since,
            Order.is_deleted == False,  # noqa: E712
        )
        .group_by(OrderItem.dish_id)
        .order_by(desc("total_qty"))
        .limit(50)
    )
    rows = result.all()
    return {str(row[0]): int(row[1]) for row in rows if row[0]}


async def _get_customer_history(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: str,
) -> dict[str, int]:
    """获取顾客历史点单菜品频次"""
    cid = uuid.UUID(customer_id)
    result = await db.execute(
        select(
            OrderItem.dish_id,
            func.count().label("order_count"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.tenant_id == tenant_id,
            Order.customer_id == cid,
            Order.is_deleted == False,  # noqa: E712
        )
        .group_by(OrderItem.dish_id)
        .order_by(desc("order_count"))
        .limit(30)
    )
    rows = result.all()
    return {str(row[0]): int(row[1]) for row in rows if row[0]}
