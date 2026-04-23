"""个性化菜单API — 千人千面菜单排序

前缀: /api/v1/menu/personalized

端点:
  GET /  — 返回个性化排序的菜品列表（4因子加权+过敏过滤+会员价标注）

算法:
  1. 历史偏好 (0.35) — 用户近90天高频菜品提权
  2. 时段热销 (0.25) — 当前餐段门店TOP菜品
  3. 购物篮关联 (0.25) — 与已选菜品的关联推荐
  4. 毛利优化 (0.15) — 高毛利菜品适度提权
  5. 过敏原过滤 — 含用户过敏原的菜品降权或隐藏
  6. 会员价标注 — 订阅会员显示折后价
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/menu/personalized", tags=["personalized-menu"])


# ─── Models ────────────────────────────────────────────────────────────────────


class PersonalizedDish(BaseModel):
    dish_id: str
    name: str
    category: str
    price_fen: int
    member_price_fen: Optional[int] = None  # 付费会员价（None=无会员价）
    image_url: str = ""
    personal_score: float = 0.0  # 个性化综合评分 0-1
    reason: str = ""  # 推荐理由
    reason_type: str = ""  # history|hot|association|margin
    allergen_warning: Optional[str] = None  # 过敏原预警文案
    allergens: list[str] = Field(default_factory=list)  # 含有的过敏原
    is_recommended: bool = False  # 是否为推荐菜品
    is_sold_out: bool = False
    tags: list[str] = Field(default_factory=list)  # 招牌/新品/辣 等标签


class PersonalizedMenuResponse(BaseModel):
    dishes: list[PersonalizedDish]
    recommended_count: int
    filtered_count: int  # 被过敏原过滤的数量
    meal_period: str
    user_segment: str  # S1-S5


# ─── 餐段检测 ──────────────────────────────────────────────────────────────────


def _current_meal_period() -> str:
    hour = datetime.now().hour
    if 6 <= hour < 10:
        return "breakfast"
    elif 10 <= hour < 14:
        return "lunch"
    elif 14 <= hour < 17:
        return "afternoon_tea"
    elif 17 <= hour < 21:
        return "dinner"
    else:
        return "late_night"


# ─── 过敏原映射 ────────────────────────────────────────────────────────────────

DISH_ALLERGENS: dict[str, list[str]] = {
    "剁椒鱼头": ["fish"],
    "口味虾": ["seafood"],
    "基围虾（活）": ["seafood"],
    "鲈鱼（活）": ["fish"],
    "皮皮虾": ["seafood"],
    "蒜蓉粉丝蒸扇贝": ["seafood"],
    "夫妻肺片": ["peanut"],
    "酸菜鱼汤": ["fish"],
}

ALLERGEN_LABELS: dict[str, str] = {
    "seafood": "海鲜/甲壳类",
    "fish": "鱼类",
    "peanut": "花生/坚果",
    "dairy": "乳制品",
    "gluten": "麸质",
    "egg": "鸡蛋",
    "soy": "大豆",
    "sesame": "芝麻",
    "alcohol": "酒精",
}


# ─── 4因子评分引擎 ─────────────────────────────────────────────────────────────


def _score_dishes(
    dishes: list[PersonalizedDish],
    history_top: list[str],  # 用户历史高频菜名
    hot_dishes: list[str],  # 当前时段热销菜名
    cart_items: list[str],  # 购物车中已有菜品ID
    user_allergies: list[str],  # 用户过敏原列表
    is_subscriber: bool,  # 是否付费会员
) -> list[PersonalizedDish]:
    """4因子加权 + 过敏过滤 + 会员价"""
    results = []

    for dish in dishes:
        name = dish.name
        price = dish.price_fen

        # ─── 过敏原检测（使用DB字段）─────────────────────────────
        matched_allergens = [a for a in dish.allergens if a in user_allergies]
        allergen_warning = None
        if matched_allergens:
            labels = [ALLERGEN_LABELS.get(a, a) for a in matched_allergens]
            allergen_warning = f"含{'/'.join(labels)}，您已标记过敏"

        # ─── 4因子评分 ─────────────────────────────────────────────
        score = 0.0
        reason = ""
        reason_type = ""

        # 1. 历史偏好 (0.35) — 按菜名匹配
        if name in history_top:
            rank = history_top.index(name)
            history_score = max(0, (10 - rank) / 10) * 0.35
            score += history_score
            if history_score > 0.1:
                reason = "您的常点菜品"
                reason_type = "history"

        # 2. 时段热销 (0.25) — 按菜名匹配
        if name in hot_dishes:
            rank = hot_dishes.index(name)
            hot_score = max(0, (10 - rank) / 10) * 0.25
            score += hot_score
            if not reason and hot_score > 0.1:
                meal = _current_meal_period()
                period_labels = {"lunch": "午餐", "dinner": "晚餐", "late_night": "夜宵"}
                reason = f"{period_labels.get(meal, '')}热销"
                reason_type = "hot"

        # 3. 购物篮关联 (0.25) — 简化版：同品类提权
        dish_cat = dish.category
        cart_cats = [d.category for d in dishes if d.dish_id in cart_items]
        if dish_cat and dish_cat not in cart_cats and cart_items:
            score += 0.15  # 品类互补
            if not reason:
                reason = "搭配推荐"
                reason_type = "association"

        # 4. 毛利优化 (0.15) — 基于价格区间近似
        if price > 5000:  # >50元菜品通常毛利更高
            score += 0.08
            if not reason:
                reason = "主厨推荐"
                reason_type = "margin"

        # ─── 会员价 ───────────────────────────────────────────────
        member_price = None
        if is_subscriber and price > 1000:
            member_price = int(price * 0.9)  # 9折

        # ─── 过敏原降权 ───────────────────────────────────────────
        if matched_allergens:
            score *= 0.1  # 大幅降权但不完全移除（前端控制显隐）

        results.append(
            PersonalizedDish(
                dish_id=dish.dish_id,
                name=name,
                category=dish.category,
                price_fen=price,
                member_price_fen=member_price,
                image_url=dish.image_url,
                personal_score=round(score, 4),
                reason=reason,
                reason_type=reason_type,
                allergen_warning=allergen_warning,
                allergens=dish.allergens,
                is_recommended=score > 0.2,
                is_sold_out=dish.is_sold_out,
                tags=dish.tags,
            )
        )

    # 按个性化分排序（降序）
    results.sort(key=lambda d: d.personal_score, reverse=True)
    return results


# ─── Endpoint ──────────────────────────────────────────────────────────────────


@router.get("")
async def get_personalized_menu(
    store_id: str = Query(..., description="门店ID"),
    customer_id: str = Query("", description="客户ID（未登录为空）"),
    cart_items: str = Query("", description="购物车菜品ID,逗号分隔"),
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """返回个性化排序的菜品列表"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID required")

    # 设置 RLS 租户上下文
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )

    # ─── 1. 从DB读取真实菜品 ──────────────────────────────────────
    dishes: list[PersonalizedDish] = []
    try:
        dish_rows = await db.execute(
            text("""
                SELECT
                    d.id::text AS dish_id,
                    d.dish_name AS name,
                    COALESCE(c.name, '其他') AS category,
                    d.price_fen,
                    d.image_url,
                    d.is_available,
                    d.allergens,
                    d.tags
                FROM dishes d
                LEFT JOIN dish_categories c
                    ON c.id = d.category_id AND c.tenant_id = d.tenant_id
                WHERE d.tenant_id = :tid::uuid
                  AND (d.store_id = :sid::uuid OR d.store_id IS NULL)
                  AND d.is_deleted = false
                ORDER BY COALESCE(c.sort_order, 999), d.dish_name
                LIMIT 200
            """),
            {"tid": x_tenant_id, "sid": store_id},
        )
        for row in dish_rows.mappings():
            dishes.append(
                PersonalizedDish(
                    dish_id=row["dish_id"],
                    name=row["name"],
                    category=row["category"],
                    price_fen=row["price_fen"],
                    member_price_fen=None,
                    image_url=row["image_url"] or "",
                    personal_score=0.0,
                    is_sold_out=not row["is_available"],
                    allergens=row["allergens"] or [],
                    tags=row["tags"] or [],
                )
            )
    except SQLAlchemyError:
        logger.exception("personalized_menu.dishes_query_failed", tenant_id=x_tenant_id, store_id=store_id)
        dishes = []

    # ─── 2. 从DB读取用户历史偏好 ─────────────────────────────────
    history_top: list[str] = []
    if customer_id:
        try:
            history_rows = await db.execute(
                text("""
                    SELECT oi.dish_name, COUNT(*) AS cnt
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                    WHERE oi.tenant_id = :tid::uuid
                      AND o.customer_id = :cid::uuid
                      AND o.created_at >= NOW() - INTERVAL '90 days'
                      AND o.status IN ('paid', 'completed')
                    GROUP BY oi.dish_name
                    ORDER BY cnt DESC
                    LIMIT 10
                """),
                {"tid": x_tenant_id, "cid": customer_id},
            )
            history_top = [row["dish_name"] for row in history_rows.mappings()]
        except SQLAlchemyError:
            logger.exception("personalized_menu.history_query_failed", tenant_id=x_tenant_id, customer_id=customer_id)
            history_top = []

    # ─── 3. 从DB读取当前时段热销菜 ───────────────────────────────
    hot_dishes: list[str] = []
    try:
        hot_rows = await db.execute(
            text("""
                SELECT oi.dish_name, COUNT(*) AS cnt
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                WHERE oi.tenant_id = :tid::uuid
                  AND o.store_id = :sid::uuid
                  AND o.status IN ('paid', 'completed')
                  AND o.created_at >= NOW() - INTERVAL '7 days'
                GROUP BY oi.dish_name
                ORDER BY cnt DESC
                LIMIT 10
            """),
            {"tid": x_tenant_id, "sid": store_id},
        )
        hot_dishes = [row["dish_name"] for row in hot_rows.mappings()]
    except SQLAlchemyError:
        logger.exception("personalized_menu.hot_dishes_query_failed", tenant_id=x_tenant_id, store_id=store_id)
        hot_dishes = []

    # TODO: 从 tx-member 读取用户画像（Phase 3 feature）
    user_allergies: list[str] = []  # 用户过敏原
    is_subscriber = False  # 是否付费会员
    user_segment = "S3"  # RFM分层

    # TODO: 从 X-User-Segment / X-User-Prefs headers读取（Phase 3中间件注入）

    # 从请求参数提取购物车
    cart_list = [c.strip() for c in cart_items.split(",") if c.strip()]

    meal_period = _current_meal_period()

    # 执行个性化评分
    personalized = _score_dishes(
        dishes=dishes,
        history_top=history_top,
        hot_dishes=hot_dishes,
        cart_items=cart_list,
        user_allergies=user_allergies,
        is_subscriber=is_subscriber,
    )

    recommended_count = sum(1 for d in personalized if d.is_recommended)
    filtered_count = sum(1 for d in personalized if d.allergen_warning)

    return {
        "ok": True,
        "data": PersonalizedMenuResponse(
            dishes=personalized,
            recommended_count=recommended_count,
            filtered_count=filtered_count,
            meal_period=meal_period,
            user_segment=user_segment,
        ).model_dump(),
    }
