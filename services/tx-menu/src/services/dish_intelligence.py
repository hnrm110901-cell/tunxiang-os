"""菜品深度智能服务 -- 口碑指标 / 经营状态推导 / 生命周期 / 动作建议

基于菜品销售数据、评价数据、毛利数据，为每道菜品提供经营智能分析。
所有操作强制 tenant_id 租户隔离。
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import structlog

log = structlog.get_logger()


# ─── 经营状态枚举 ───


class DishStatus(str, Enum):
    star = "star"  # 高销高利（明星菜）
    rising = "rising"  # 销量上升趋势
    declining = "declining"  # 销量下降趋势
    underperform = "underperform"  # 低销低利（瘦狗菜）
    seasonal_peak = "seasonal_peak"  # 季节旺季
    new = "new"  # 新品


class DishLifecycle(str, Enum):
    launch = "launch"  # 上新
    growth = "growth"  # 成长
    mature = "mature"  # 成熟
    decline = "decline"  # 衰退


class DishAction(str, Enum):
    promote = "promote"  # 推广
    raise_price = "raise_price"  # 提价
    lower_price = "lower_price"  # 降价
    replace = "replace"  # 替换
    delist = "delist"  # 下架
    maintain = "maintain"  # 维持现状
    observe = "observe"  # 观察


# ─── 阈值常量 ───


STAR_SALES_PERCENTILE = 0.7  # 销量 top 30% 算高销
STAR_MARGIN_THRESHOLD = 0.55  # 毛利率 > 55% 算高利
LOW_SALES_PERCENTILE = 0.3  # 销量 bottom 30% 算低销
LOW_MARGIN_THRESHOLD = 0.35  # 毛利率 < 35% 算低利
RISING_GROWTH_RATE = 0.10  # 周环比增长 > 10% 算上升
DECLINING_GROWTH_RATE = -0.10  # 周环比下降 > 10% 算下降
NEW_DISH_DAYS = 30  # 上新 30 天内算新品
BAD_REVIEW_THRESHOLD = 0.10  # 差评率 > 10% 需关注
REORDER_THRESHOLD = 0.25  # 复点率 > 25% 算良好
LIFECYCLE_GROWTH_WEEKS = 8  # 上新后 8 周内算成长期
LIFECYCLE_MATURE_WEEKS = 24  # 8-24 周算成熟期


# ─── 内部存储（可替换为 DB 查询） ───


_dish_sales: dict[str, dict] = {}  # dish_id -> 销售统计
_dish_reviews: dict[str, dict] = {}  # dish_id -> 评价统计


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid(val: str | uuid.UUID) -> str:
    """统一转字符串 ID"""
    return str(val)


# ─── 数据注入（供测试和外部服务调用） ───


def inject_dish_sales(dish_id: str, tenant_id: str, data: dict) -> None:
    """注入菜品销售数据（测试用）

    data 结构:
        total_sales: int           -- 累计销量
        total_revenue_fen: int     -- 累计营收（分）
        cost_fen: int              -- 单位成本（分）
        price_fen: int             -- 单位售价（分）
        recent_week_sales: int     -- 近 7 天销量
        previous_week_sales: int   -- 上 7 天销量
        created_at: str(ISO)       -- 上新时间
        season: str|None           -- 季节标记
        is_seasonal: bool          -- 是否季节限定
    """
    key = f"{tenant_id}:{dish_id}"
    _dish_sales[key] = {**data, "tenant_id": tenant_id, "dish_id": dish_id}


def inject_dish_reviews(dish_id: str, tenant_id: str, data: dict) -> None:
    """注入菜品评价数据（测试用）

    data 结构:
        total_reviews: int         -- 评价总数
        positive_count: int        -- 好评数
        negative_count: int        -- 差评数
        neutral_count: int         -- 中评数
        avg_score: float           -- 平均评分 (1-5)
        recommend_count: int       -- 推荐次数
        reorder_count: int         -- 复点次数
        unique_customers: int      -- 独立客户数
    """
    key = f"{tenant_id}:{dish_id}"
    _dish_reviews[key] = {**data, "tenant_id": tenant_id, "dish_id": dish_id}


def _get_sales(dish_id: str, tenant_id: str) -> Optional[dict]:
    return _dish_sales.get(f"{tenant_id}:{dish_id}")


def _get_reviews(dish_id: str, tenant_id: str) -> Optional[dict]:
    return _dish_reviews.get(f"{tenant_id}:{dish_id}")


def _get_all_sales_for_tenant(tenant_id: str) -> list[dict]:
    """获取租户下所有菜品销售数据（用于百分位计算）"""
    return [v for k, v in _dish_sales.items() if k.startswith(f"{tenant_id}:")]


# ─── 核心服务函数 ───


def calculate_dish_reputation(
    dish_id: str,
    tenant_id: str,
    db: object = None,
) -> dict:
    """口碑指标：评分 / 差评率 / 推荐率 / 复点率

    Returns:
        {
            "dish_id": str,
            "avg_score": float,         # 平均评分 1-5
            "negative_rate": float,     # 差评率 0-1
            "recommend_rate": float,    # 推荐率 0-1
            "reorder_rate": float,      # 复点率 0-1
            "total_reviews": int,
            "reputation_level": str,    # excellent/good/average/poor
        }
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    reviews = _get_reviews(dish_id, tenant_id)

    if not reviews or reviews.get("total_reviews", 0) == 0:
        log.info(
            "dish_reputation_no_data",
            dish_id=dish_id,
            tenant_id=tenant_id,
        )
        return {
            "dish_id": dish_id,
            "avg_score": 0.0,
            "negative_rate": 0.0,
            "recommend_rate": 0.0,
            "reorder_rate": 0.0,
            "total_reviews": 0,
            "reputation_level": "no_data",
        }

    total = reviews["total_reviews"]
    negative_rate = reviews.get("negative_count", 0) / total if total else 0.0
    unique_customers = reviews.get("unique_customers", 1) or 1
    recommend_rate = reviews.get("recommend_count", 0) / unique_customers
    reorder_rate = reviews.get("reorder_count", 0) / unique_customers
    avg_score = reviews.get("avg_score", 0.0)

    # 口碑等级判定
    if avg_score >= 4.5 and negative_rate < 0.05:
        reputation_level = "excellent"
    elif avg_score >= 3.8 and negative_rate < BAD_REVIEW_THRESHOLD:
        reputation_level = "good"
    elif avg_score >= 3.0:
        reputation_level = "average"
    else:
        reputation_level = "poor"

    log.info(
        "dish_reputation_calculated",
        dish_id=dish_id,
        avg_score=avg_score,
        negative_rate=round(negative_rate, 4),
        reputation_level=reputation_level,
        tenant_id=tenant_id,
    )

    return {
        "dish_id": dish_id,
        "avg_score": round(avg_score, 2),
        "negative_rate": round(negative_rate, 4),
        "recommend_rate": round(recommend_rate, 4),
        "reorder_rate": round(reorder_rate, 4),
        "total_reviews": total,
        "reputation_level": reputation_level,
    }


def auto_derive_status(
    dish_id: str,
    tenant_id: str,
    db: object = None,
) -> dict:
    """经营状态自动推导

    优先级: new > seasonal_peak > star > rising > declining > underperform

    Returns:
        {
            "dish_id": str,
            "status": str,          # DishStatus 值
            "reason": str,          # 推导原因
            "metrics": dict,        # 依据指标
        }
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    sales = _get_sales(dish_id, tenant_id)
    if not sales:
        log.warning("auto_derive_status_no_data", dish_id=dish_id, tenant_id=tenant_id)
        return {
            "dish_id": dish_id,
            "status": DishStatus.new.value,
            "reason": "无销售数据，默认为新品",
            "metrics": {},
        }

    # 计算指标
    created_at_str = sales.get("created_at")
    days_since_launch = 999
    if created_at_str:
        created_at = datetime.fromisoformat(created_at_str)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        days_since_launch = (datetime.now(timezone.utc) - created_at).days

    recent = sales.get("recent_week_sales", 0)
    previous = sales.get("previous_week_sales", 0)
    growth_rate = (recent - previous) / previous if previous > 0 else 0.0

    price_fen = sales.get("price_fen", 0)
    cost_fen = sales.get("cost_fen", 0)
    margin = (price_fen - cost_fen) / price_fen if price_fen > 0 else 0.0

    # 计算销量百分位
    all_sales = _get_all_sales_for_tenant(tenant_id)
    all_totals = sorted([s.get("total_sales", 0) for s in all_sales])
    total_sales = sales.get("total_sales", 0)
    if all_totals:
        rank = sum(1 for s in all_totals if s <= total_sales) / len(all_totals)
    else:
        rank = 0.5

    metrics = {
        "days_since_launch": days_since_launch,
        "growth_rate": round(growth_rate, 4),
        "margin": round(margin, 4),
        "sales_percentile": round(rank, 4),
        "total_sales": total_sales,
        "recent_week_sales": recent,
    }

    # 推导状态（按优先级）
    # 1. 新品
    if days_since_launch <= NEW_DISH_DAYS:
        status = DishStatus.new
        reason = f"上新 {days_since_launch} 天，仍在新品期"
    # 2. 季节旺季
    elif sales.get("is_seasonal") and sales.get("season"):
        status = DishStatus.seasonal_peak
        reason = f"季节限定菜品（{sales['season']}），当前为旺季"
    # 3. 明星菜（高销高利）
    elif rank >= STAR_SALES_PERCENTILE and margin >= STAR_MARGIN_THRESHOLD:
        status = DishStatus.star
        reason = f"高销量(P{rank:.0%}) + 高毛利({margin:.1%})"
    # 4. 销量上升
    elif growth_rate >= RISING_GROWTH_RATE:
        status = DishStatus.rising
        reason = f"周环比增长 {growth_rate:.1%}"
    # 5. 销量下降
    elif growth_rate <= DECLINING_GROWTH_RATE:
        status = DishStatus.declining
        reason = f"周环比下降 {abs(growth_rate):.1%}"
    # 6. 瘦狗菜（低销低利）
    elif rank <= LOW_SALES_PERCENTILE and margin < LOW_MARGIN_THRESHOLD:
        status = DishStatus.underperform
        reason = f"低销量(P{rank:.0%}) + 低毛利({margin:.1%})"
    # 7. 默认维持
    else:
        status = DishStatus.star if margin >= STAR_MARGIN_THRESHOLD else DishStatus.rising
        reason = "综合表现正常"

    log.info(
        "dish_status_derived",
        dish_id=dish_id,
        status=status.value,
        reason=reason,
        tenant_id=tenant_id,
    )

    return {
        "dish_id": dish_id,
        "status": status.value,
        "reason": reason,
        "metrics": metrics,
    }


def get_dish_lifecycle(
    dish_id: str,
    tenant_id: str,
    db: object = None,
) -> dict:
    """菜品生命周期：上新 -> 成长 -> 成熟 -> 衰退

    基于上新时间和销量趋势判断生命周期阶段。

    Returns:
        {
            "dish_id": str,
            "lifecycle": str,       # launch/growth/mature/decline
            "weeks_since_launch": int,
            "description": str,
            "health_score": float,  # 0-100 健康度
        }
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    sales = _get_sales(dish_id, tenant_id)
    if not sales:
        return {
            "dish_id": dish_id,
            "lifecycle": DishLifecycle.launch.value,
            "weeks_since_launch": 0,
            "description": "无数据，默认为上新阶段",
            "health_score": 50.0,
        }

    created_at_str = sales.get("created_at")
    weeks_since_launch = 0
    if created_at_str:
        created_at = datetime.fromisoformat(created_at_str)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        weeks_since_launch = (datetime.now(timezone.utc) - created_at).days // 7

    recent = sales.get("recent_week_sales", 0)
    previous = sales.get("previous_week_sales", 0)
    growth_rate = (recent - previous) / previous if previous > 0 else 0.0

    # 判断生命周期
    if weeks_since_launch <= 4:
        lifecycle = DishLifecycle.launch
        description = f"上新第 {weeks_since_launch} 周，处于引入期"
        health_score = 60.0
    elif weeks_since_launch <= LIFECYCLE_GROWTH_WEEKS:
        lifecycle = DishLifecycle.growth
        description = f"第 {weeks_since_launch} 周，处于成长期"
        health_score = 80.0 if growth_rate > 0 else 60.0
    elif weeks_since_launch <= LIFECYCLE_MATURE_WEEKS:
        if growth_rate >= -0.05:
            lifecycle = DishLifecycle.mature
            description = f"第 {weeks_since_launch} 周，处于成熟期，销量稳定"
            health_score = 85.0
        else:
            lifecycle = DishLifecycle.decline
            description = f"第 {weeks_since_launch} 周，进入衰退期"
            health_score = 40.0
    else:
        if growth_rate >= RISING_GROWTH_RATE:
            lifecycle = DishLifecycle.mature
            description = f"第 {weeks_since_launch} 周，长期经典菜品"
            health_score = 90.0
        else:
            lifecycle = DishLifecycle.decline
            description = f"第 {weeks_since_launch} 周，销量持续走低"
            health_score = 30.0

    log.info(
        "dish_lifecycle_determined",
        dish_id=dish_id,
        lifecycle=lifecycle.value,
        weeks_since_launch=weeks_since_launch,
        tenant_id=tenant_id,
    )

    return {
        "dish_id": dish_id,
        "lifecycle": lifecycle.value,
        "weeks_since_launch": weeks_since_launch,
        "description": description,
        "health_score": health_score,
    }


def suggest_dish_action(
    dish_id: str,
    tenant_id: str,
    db: object = None,
) -> dict:
    """基于经营状态和生命周期建议动作

    Returns:
        {
            "dish_id": str,
            "action": str,          # DishAction 值
            "reason": str,
            "priority": str,        # high/medium/low
            "detail": str,          # 具体建议描述
        }
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    status_result = auto_derive_status(dish_id, tenant_id)
    lifecycle_result = get_dish_lifecycle(dish_id, tenant_id)
    reputation = calculate_dish_reputation(dish_id, tenant_id)

    status = status_result["status"]
    lifecycle = lifecycle_result["lifecycle"]
    neg_rate = reputation.get("negative_rate", 0.0)

    # 决策矩阵
    if status == DishStatus.star.value:
        if neg_rate > BAD_REVIEW_THRESHOLD:
            action = DishAction.maintain
            priority = "high"
            detail = "明星菜但差评率偏高，需排查品控问题"
        else:
            action = DishAction.raise_price
            priority = "medium"
            detail = "高销高利，可考虑适度提价测试价格弹性"

    elif status == DishStatus.rising.value:
        action = DishAction.promote
        priority = "high"
        detail = "销量上升趋势，建议加大推广力度"

    elif status == DishStatus.declining.value:
        if lifecycle == DishLifecycle.decline.value:
            action = DishAction.replace
            priority = "high"
            detail = "销量持续下降且已进入衰退期，建议准备替代菜品"
        else:
            action = DishAction.lower_price
            priority = "medium"
            detail = "销量下降，可尝试促销或降价刺激"

    elif status == DishStatus.underperform.value:
        if lifecycle == DishLifecycle.decline.value:
            action = DishAction.delist
            priority = "high"
            detail = "低销低利+衰退期，建议下架"
        else:
            action = DishAction.replace
            priority = "medium"
            detail = "低销低利，建议研发替代菜品或调整配方降本"

    elif status == DishStatus.seasonal_peak.value:
        action = DishAction.promote
        priority = "high"
        detail = "季节旺季，抓住时间窗口加大推广"

    elif status == DishStatus.new.value:
        action = DishAction.observe
        priority = "low"
        detail = "新品观察期，关注销量和口碑数据"

    else:
        action = DishAction.maintain
        priority = "low"
        detail = "状态正常，保持现有策略"

    log.info(
        "dish_action_suggested",
        dish_id=dish_id,
        action=action.value,
        priority=priority,
        status=status,
        lifecycle=lifecycle,
        tenant_id=tenant_id,
    )

    return {
        "dish_id": dish_id,
        "action": action.value,
        "reason": f"状态={status}, 生命周期={lifecycle}",
        "priority": priority,
        "detail": detail,
        "derived_status": status_result,
        "lifecycle": lifecycle_result,
        "reputation": reputation,
    }


# ─── 测试工具 ───


def _clear_store() -> None:
    """清空内部存储，仅供测试用"""
    _dish_sales.clear()
    _dish_reviews.clear()
