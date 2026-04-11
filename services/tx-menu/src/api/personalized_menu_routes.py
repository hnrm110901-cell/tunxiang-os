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

import hashlib
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

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
    personal_score: float = 0.0              # 个性化综合评分 0-1
    reason: str = ""                         # 推荐理由
    reason_type: str = ""                    # history|hot|association|margin
    allergen_warning: Optional[str] = None   # 过敏原预警文案
    allergens: list[str] = Field(default_factory=list)  # 含有的过敏原
    is_recommended: bool = False             # 是否为推荐菜品
    is_sold_out: bool = False
    tags: list[str] = Field(default_factory=list)  # 招牌/新品/辣 等标签


class PersonalizedMenuResponse(BaseModel):
    dishes: list[PersonalizedDish]
    recommended_count: int
    filtered_count: int   # 被过敏原过滤的数量
    meal_period: str
    user_segment: str     # S1-S5


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
    dishes: list[dict],
    history_top: list[str],      # 用户历史高频菜品ID
    hot_dishes: list[str],       # 当前时段热销菜品ID
    cart_items: list[str],       # 购物车中已有菜品ID
    user_allergies: list[str],   # 用户过敏原列表
    is_subscriber: bool,         # 是否付费会员
) -> list[PersonalizedDish]:
    """4因子加权 + 过敏过滤 + 会员价"""
    results = []
    filtered_count = 0

    for dish in dishes:
        did = dish.get("id", "")
        name = dish.get("name", "")
        price = dish.get("price_fen", 0)

        # ─── 过敏原检测 ────────────────────────────────────────────
        dish_allergens = DISH_ALLERGENS.get(name, [])
        matched_allergens = [a for a in dish_allergens if a in user_allergies]
        allergen_warning = None
        if matched_allergens:
            labels = [ALLERGEN_LABELS.get(a, a) for a in matched_allergens]
            allergen_warning = f"含{'/'.join(labels)}，您已标记过敏"
            filtered_count += 1

        # ─── 4因子评分 ─────────────────────────────────────────────
        score = 0.0
        reason = ""
        reason_type = ""

        # 1. 历史偏好 (0.35)
        if did in history_top:
            rank = history_top.index(did)
            history_score = max(0, (10 - rank) / 10) * 0.35
            score += history_score
            if history_score > 0.1:
                reason = "您的常点菜品"
                reason_type = "history"

        # 2. 时段热销 (0.25)
        if did in hot_dishes:
            rank = hot_dishes.index(did)
            hot_score = max(0, (10 - rank) / 10) * 0.25
            score += hot_score
            if not reason and hot_score > 0.1:
                meal = _current_meal_period()
                period_labels = {"lunch": "午餐", "dinner": "晚餐", "late_night": "夜宵"}
                reason = f"{period_labels.get(meal, '')}热销"
                reason_type = "hot"

        # 3. 购物篮关联 (0.25) — 简化版：同品类提权
        dish_cat = dish.get("category", "")
        cart_cats = [d.get("category", "") for d in dishes if d.get("id") in cart_items]
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

        results.append(PersonalizedDish(
            dish_id=did,
            name=name,
            category=dish.get("category", ""),
            price_fen=price,
            member_price_fen=member_price,
            image_url=dish.get("image_url", ""),
            personal_score=round(score, 4),
            reason=reason,
            reason_type=reason_type,
            allergen_warning=allergen_warning,
            allergens=dish_allergens,
            is_recommended=score > 0.2,
            is_sold_out=dish.get("is_sold_out", False),
            tags=dish.get("tags", []),
        ))

    # 按个性化分排序（降序）
    results.sort(key=lambda d: d.personal_score, reverse=True)
    return results


# ─── Endpoint ──────────────────────────────────────────────────────────────────

# Demo数据（生产环境从DB读取）
DEMO_DISHES = [
    {"id": "d01", "name": "剁椒鱼头", "category": "招牌菜", "price_fen": 8800, "tags": ["招牌"]},
    {"id": "d02", "name": "农家小炒肉", "category": "热菜", "price_fen": 4200},
    {"id": "d03", "name": "口味虾", "category": "招牌菜", "price_fen": 12800, "tags": ["季节"]},
    {"id": "d04", "name": "辣椒炒肉", "category": "热菜", "price_fen": 3800},
    {"id": "d05", "name": "红烧肉", "category": "热菜", "price_fen": 5800},
    {"id": "d06", "name": "蒜蓉粉丝蒸扇贝", "category": "海鲜", "price_fen": 6800},
    {"id": "d07", "name": "凉拌黄瓜", "category": "凉菜", "price_fen": 900},
    {"id": "d08", "name": "夫妻肺片", "category": "凉菜", "price_fen": 3200},
    {"id": "d09", "name": "皮蛋豆腐", "category": "凉菜", "price_fen": 1800},
    {"id": "d10", "name": "鲈鱼（活）", "category": "活鲜", "price_fen": 5800},
    {"id": "d11", "name": "基围虾（活）", "category": "活鲜", "price_fen": 9800},
    {"id": "d13", "name": "番茄蛋汤", "category": "汤羹", "price_fen": 1200},
    {"id": "d15", "name": "米饭", "category": "主食", "price_fen": 300},
    {"id": "d17", "name": "酸梅汤", "category": "饮品", "price_fen": 800},
]


@router.get("")
async def get_personalized_menu(
    store_id: str = Query(..., description="门店ID"),
    customer_id: str = Query("", description="客户ID（未登录为空）"),
    cart_items: str = Query("", description="购物车菜品ID,逗号分隔"),
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
):
    """返回个性化排序的菜品列表"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID required")

    # TODO: 从DB读取真实菜品数据
    dishes = DEMO_DISHES

    # TODO: 从 tx-member 读取用户画像（当前mock）
    # 真实场景：调用 GET /api/v1/member/recommend/order-time
    history_top = ["d01", "d03", "d02", "d05"]  # 用户历史Top菜品
    user_allergies: list[str] = []               # 用户过敏原
    is_subscriber = False                        # 是否付费会员
    user_segment = "S3"                          # RFM分层

    # 从请求参数提取
    cart_list = [c.strip() for c in cart_items.split(",") if c.strip()]

    # TODO: 从 X-User-Segment / X-User-Prefs headers读取（Phase 3中间件注入）
    # segment_header = request.headers.get("X-User-Segment", "")
    # prefs_header = request.headers.get("X-User-Prefs", "")

    meal_period = _current_meal_period()
    hot_dishes = ["d03", "d01", "d05", "d06", "d11"]  # 当前时段热销

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
