"""菜品经营分析中心（D3） — 销量排行、退菜率、差评菜、沽清频率、四象限、新菜表现、菜单优化

复用 dish_margin.py 的毛利数据，结合 orders/order_items 的销售数据，
输出全维度菜品经营分析。

金额单位: 分(fen), int
比率: 百分比, Decimal(5,2)
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

import structlog

from .dish_margin import (
    get_dish_margin_ranking,
)

log = structlog.get_logger()

# ─── 四象限阈值 ───
DEFAULT_SALES_MEDIAN_MULTIPLIER = Decimal("1.0")  # 以中位数为界
DEFAULT_MARGIN_THRESHOLD_PCT = Decimal("50.00")  # 毛利率 50% 为界


# ══════════════════════════════════════════════
# 纯函数
# ══════════════════════════════════════════════


def compute_sales_ranking(
    dish_sales: list[dict],
    sort_by: str = "sales_qty",
    ascending: bool = False,
) -> list[dict]:
    """纯函数：对菜品销量列表排序并计算占比

    Args:
        dish_sales: [{"dish_id", "dish_name", "sales_qty", "sales_amount_fen", ...}]
        sort_by: sales_qty / sales_amount_fen
        ascending: True=升序

    Returns:
        排序后的列表，附加 rank / qty_pct / amount_pct
    """
    total_qty = sum(d.get("sales_qty", 0) for d in dish_sales)
    total_amount = sum(d.get("sales_amount_fen", 0) for d in dish_sales)

    for d in dish_sales:
        d["qty_pct"] = (
            (Decimal(d.get("sales_qty", 0)) / Decimal(total_qty) * 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if total_qty > 0
            else Decimal("0.00")
        )
        d["amount_pct"] = (
            (Decimal(d.get("sales_amount_fen", 0)) / Decimal(total_amount) * 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if total_amount > 0
            else Decimal("0.00")
        )

    sorted_list = sorted(
        dish_sales,
        key=lambda x: x.get(sort_by, 0),
        reverse=not ascending,
    )
    for i, item in enumerate(sorted_list, 1):
        item["rank"] = i
    return sorted_list


def compute_return_rate(total_qty: int, return_qty: int) -> Decimal:
    """纯函数：计算退菜率（百分比）"""
    if total_qty <= 0:
        return Decimal("0.00")
    return (Decimal(return_qty) / Decimal(total_qty) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def classify_quadrant(
    sales_qty: int,
    margin_rate: Decimal,
    sales_median: int,
    margin_threshold: Decimal,
) -> str:
    """纯函数：四象限分类

    高销量高毛利 = star（明星）
    低销量高毛利 = cash_cow（金牛）
    高销量低毛利 = question（问号）
    低销量低毛利 = dog（瘦狗）
    """
    high_sales = sales_qty >= sales_median
    high_margin = margin_rate >= margin_threshold

    if high_sales and high_margin:
        return "star"
    elif not high_sales and high_margin:
        return "cash_cow"
    elif high_sales and not high_margin:
        return "question"
    else:
        return "dog"


def generate_optimization_suggestion(
    dish: dict,
    quadrant: str,
    return_rate: Decimal,
    negative_review_count: int,
) -> dict:
    """纯函数：根据菜品指标生成优化建议

    Returns:
        {"dish_id", "dish_name", "action", "reason", "priority"}
        action: eliminate/raise_price/promote/observe
    """
    dish_id = dish.get("dish_id", "")
    dish_name = dish.get("dish_name", "")

    # 瘦狗 + 高退菜率/差评 → 汰换
    if quadrant == "dog" and (return_rate > Decimal("5.00") or negative_review_count >= 3):
        return {
            "dish_id": dish_id,
            "dish_name": dish_name,
            "action": "eliminate",
            "reason": f"低销量低毛利，退菜率{return_rate}%，差评{negative_review_count}条",
            "priority": "high",
        }

    # 瘦狗（无明显质量问题）→ 观察
    if quadrant == "dog":
        return {
            "dish_id": dish_id,
            "dish_name": dish_name,
            "action": "observe",
            "reason": "低销量低毛利，建议观察或考虑汰换",
            "priority": "medium",
        }

    # 问号菜：高销量低毛利 → 提价或降成本
    if quadrant == "question":
        return {
            "dish_id": dish_id,
            "dish_name": dish_name,
            "action": "raise_price",
            "reason": "销量好但毛利低，建议提价或优化配方降成本",
            "priority": "high",
        }

    # 金牛菜：低销量高毛利 → 推广
    if quadrant == "cash_cow":
        return {
            "dish_id": dish_id,
            "dish_name": dish_name,
            "action": "promote",
            "reason": "毛利高但销量低，建议加大推广力度",
            "priority": "medium",
        }

    # 明星菜：保持
    return {
        "dish_id": dish_id,
        "dish_name": dish_name,
        "action": "keep",
        "reason": "高销量高毛利，核心菜品，建议保持",
        "priority": "low",
    }


# ══════════════════════════════════════════════
# 业务函数（需要 DB）
# ══════════════════════════════════════════════


def sales_ranking(
    store_id: uuid.UUID,
    date_range: tuple[date, date],
    tenant_id: uuid.UUID,
    db,
    sort_by: str = "sales_qty",
    limit: int = 50,
) -> list[dict]:
    """菜品销量排行（含金额/数量/占比）

    Args:
        store_id: 门店ID
        date_range: (start_date, end_date)
        tenant_id: 租户ID
        db: 数据库会话
        sort_by: 排序字段 sales_qty / sales_amount_fen
        limit: 返回数量

    Returns:
        排序后的菜品销量列表，含 rank / qty_pct / amount_pct
    """
    raw = _query_dish_sales(store_id, date_range[0], date_range[1], tenant_id, db)
    if not raw:
        return []

    ranked = compute_sales_ranking(raw, sort_by=sort_by)

    log.info(
        "dish_analysis.sales_ranking",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        date_range=str(date_range),
        dish_count=len(ranked),
    )
    return ranked[:limit]


def return_rate_analysis(
    store_id: uuid.UUID,
    date_range: tuple[date, date],
    tenant_id: uuid.UUID,
    db,
    limit: int = 50,
) -> dict:
    """退菜率排行 + 退菜原因分布

    Returns:
        {
            "summary": {"total_orders": int, "total_returns": int, "overall_return_rate": Decimal},
            "dish_ranking": [{"dish_id", "dish_name", "total_qty", "return_qty", "return_rate", "rank"}],
            "reason_distribution": [{"reason": str, "count": int, "pct": Decimal}],
        }
    """
    return_data = _query_return_data(store_id, date_range[0], date_range[1], tenant_id, db)
    reason_data = _query_return_reasons(store_id, date_range[0], date_range[1], tenant_id, db)

    # 汇总
    total_orders = sum(d.get("total_qty", 0) for d in return_data)
    total_returns = sum(d.get("return_qty", 0) for d in return_data)
    overall_rate = compute_return_rate(total_orders, total_returns)

    # 按退菜率排行
    for d in return_data:
        d["return_rate"] = compute_return_rate(d.get("total_qty", 0), d.get("return_qty", 0))
    return_data.sort(key=lambda x: x["return_rate"], reverse=True)
    for i, item in enumerate(return_data, 1):
        item["rank"] = i

    # 原因分布
    total_reason_count = sum(r.get("count", 0) for r in reason_data)
    for r in reason_data:
        r["pct"] = (
            (Decimal(r.get("count", 0)) / Decimal(total_reason_count) * 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if total_reason_count > 0
            else Decimal("0.00")
        )

    log.info(
        "dish_analysis.return_rate",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        overall_return_rate=str(overall_rate),
        total_returns=total_returns,
    )

    return {
        "summary": {
            "total_orders": total_orders,
            "total_returns": total_returns,
            "overall_return_rate": overall_rate,
        },
        "dish_ranking": return_data[:limit],
        "reason_distribution": reason_data,
    }


def negative_review_dishes(
    store_id: uuid.UUID,
    date_range: tuple[date, date],
    tenant_id: uuid.UUID,
    db,
    min_rating: float = 3.0,
    limit: int = 30,
) -> list[dict]:
    """差评菜清单

    Args:
        store_id: 门店ID
        date_range: (start_date, end_date)
        tenant_id: 租户ID
        db: 数据库会话
        min_rating: 低于此评分视为差评（含），默认 3.0
        limit: 返回数量

    Returns:
        [{"dish_id", "dish_name", "avg_rating", "negative_count", "total_reviews",
          "negative_rate", "top_complaints": [str], "rank"}]
    """
    reviews = _query_negative_reviews(store_id, date_range[0], date_range[1], tenant_id, db, min_rating)
    if not reviews:
        return []

    # 按差评数降序排列
    reviews.sort(key=lambda x: x.get("negative_count", 0), reverse=True)
    for i, item in enumerate(reviews, 1):
        item["rank"] = i
        total = item.get("total_reviews", 0)
        neg = item.get("negative_count", 0)
        item["negative_rate"] = (
            (Decimal(neg) / Decimal(total) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if total > 0
            else Decimal("0.00")
        )

    log.info(
        "dish_analysis.negative_reviews",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        dish_count=len(reviews),
    )
    return reviews[:limit]


def stockout_frequency(
    store_id: uuid.UUID,
    date_range: tuple[date, date],
    tenant_id: uuid.UUID,
    db,
    limit: int = 30,
) -> list[dict]:
    """沽清频率排行

    Returns:
        [{"dish_id", "dish_name", "stockout_count", "stockout_days", "total_days",
          "stockout_day_rate", "last_stockout_at", "rank"}]
    """
    data = _query_stockout_records(store_id, date_range[0], date_range[1], tenant_id, db)
    if not data:
        return []

    total_days = max((date_range[1] - date_range[0]).days, 1)
    for d in data:
        d["total_days"] = total_days
        stockout_days = d.get("stockout_days", 0)
        d["stockout_day_rate"] = (Decimal(stockout_days) / Decimal(total_days) * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    data.sort(key=lambda x: x.get("stockout_count", 0), reverse=True)
    for i, item in enumerate(data, 1):
        item["rank"] = i

    log.info(
        "dish_analysis.stockout_frequency",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        dish_count=len(data),
    )
    return data[:limit]


def dish_structure_analysis(
    store_id: uuid.UUID,
    date_range: tuple[date, date],
    tenant_id: uuid.UUID,
    db,
    margin_threshold: Optional[Decimal] = None,
) -> dict:
    """菜品四象限分析（明星/金牛/问号/瘦狗）

    高销量高毛利 = star（明星）
    低销量高毛利 = cash_cow（金牛）
    高销量低毛利 = question（问号）
    低销量低毛利 = dog（瘦狗）

    Returns:
        {
            "summary": {"star": int, "cash_cow": int, "question": int, "dog": int, "total": int},
            "margin_threshold": Decimal,
            "sales_median": int,
            "dishes": [{"dish_id", "dish_name", "sales_qty", "margin_rate", "quadrant", ...}],
        }
    """
    if margin_threshold is None:
        margin_threshold = DEFAULT_MARGIN_THRESHOLD_PCT

    # 复用 dish_margin.py 获取毛利排行（已含 sales_qty）
    margin_data = get_dish_margin_ranking(
        store_id,
        date_range,
        tenant_id,
        db,
        sort_by="margin_rate",
        limit=9999,
    )
    if not margin_data:
        return {
            "summary": {"star": 0, "cash_cow": 0, "question": 0, "dog": 0, "total": 0},
            "margin_threshold": margin_threshold,
            "sales_median": 0,
            "dishes": [],
        }

    # 计算销量中位数
    sales_list = sorted(d.get("sales_qty", 0) for d in margin_data)
    n = len(sales_list)
    if n % 2 == 0:
        sales_median = (sales_list[n // 2 - 1] + sales_list[n // 2]) // 2
    else:
        sales_median = sales_list[n // 2]
    # 中位数至少为1，避免全部归为高销量
    sales_median = max(sales_median, 1)

    counts = {"star": 0, "cash_cow": 0, "question": 0, "dog": 0}
    for d in margin_data:
        q = classify_quadrant(
            d.get("sales_qty", 0),
            d.get("margin_rate", Decimal("0.00")),
            sales_median,
            margin_threshold,
        )
        d["quadrant"] = q
        counts[q] += 1

    log.info(
        "dish_analysis.structure",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        star=counts["star"],
        cash_cow=counts["cash_cow"],
        question=counts["question"],
        dog=counts["dog"],
    )

    return {
        "summary": {**counts, "total": len(margin_data)},
        "margin_threshold": margin_threshold,
        "sales_median": sales_median,
        "dishes": margin_data,
    }


def new_dish_performance(
    store_id: uuid.UUID,
    days_since_launch: int,
    tenant_id: uuid.UUID,
    db,
    limit: int = 30,
) -> list[dict]:
    """新菜表现（销量曲线/复购率）

    Args:
        store_id: 门店ID
        days_since_launch: 上架天数阈值（N天内上架视为新菜）
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        [{"dish_id", "dish_name", "launch_date", "days_on_menu", "total_sales",
          "daily_avg_sales", "sales_trend": [int], "repurchase_rate", "rating", "rank"}]
    """
    cutoff_date = date.today() - timedelta(days=days_since_launch)
    new_dishes = _query_new_dishes(store_id, cutoff_date, tenant_id, db)
    if not new_dishes:
        return []

    for d in new_dishes:
        launch = d.get("launch_date", date.today())
        days_on = max((date.today() - launch).days, 1)
        d["days_on_menu"] = days_on
        total = d.get("total_sales", 0)
        d["daily_avg_sales"] = (Decimal(total) / Decimal(days_on)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # 销量趋势（按天）
        d["sales_trend"] = _query_daily_sales_trend(
            d["dish_id"],
            store_id,
            launch,
            date.today(),
            tenant_id,
            db,
        )

        # 复购率
        d["repurchase_rate"] = _query_repurchase_rate(
            d["dish_id"],
            store_id,
            launch,
            date.today(),
            tenant_id,
            db,
        )

    # 按日均销量排行
    new_dishes.sort(key=lambda x: x.get("daily_avg_sales", 0), reverse=True)
    for i, item in enumerate(new_dishes, 1):
        item["rank"] = i

    log.info(
        "dish_analysis.new_dish_performance",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        days_since_launch=days_since_launch,
        new_dish_count=len(new_dishes),
    )
    return new_dishes[:limit]


def menu_optimization_suggestions(
    store_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db,
    date_range: Optional[tuple[date, date]] = None,
) -> dict:
    """AI菜单优化建议（汰换/提价/推广/保持）

    综合四象限 + 退菜率 + 差评 → 生成 actionable 建议

    Returns:
        {
            "generated_at": str,
            "store_id": str,
            "summary": {"eliminate": int, "raise_price": int, "promote": int, "keep": int, "observe": int},
            "suggestions": [{"dish_id", "dish_name", "action", "reason", "priority", "quadrant",
                             "return_rate", "negative_reviews"}],
        }
    """
    if date_range is None:
        end = date.today()
        start = end - timedelta(days=30)
        date_range = (start, end)

    # 1. 获取四象限数据
    structure = dish_structure_analysis(store_id, date_range, tenant_id, db)
    dishes = structure.get("dishes", [])
    if not dishes:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "store_id": str(store_id),
            "summary": {"eliminate": 0, "raise_price": 0, "promote": 0, "keep": 0, "observe": 0},
            "suggestions": [],
        }

    # 2. 获取退菜数据
    return_info = return_rate_analysis(store_id, date_range, tenant_id, db)
    return_map: dict[str, Decimal] = {}
    for rd in return_info.get("dish_ranking", []):
        return_map[rd.get("dish_id", "")] = rd.get("return_rate", Decimal("0.00"))

    # 3. 获取差评数据
    neg_dishes = negative_review_dishes(store_id, date_range, tenant_id, db)
    neg_map: dict[str, int] = {}
    for nd in neg_dishes:
        neg_map[nd.get("dish_id", "")] = nd.get("negative_count", 0)

    # 4. 为每道菜生成建议
    suggestions = []
    action_counts: dict[str, int] = {"eliminate": 0, "raise_price": 0, "promote": 0, "keep": 0, "observe": 0}

    for d in dishes:
        dish_id = d.get("dish_id", "")
        ret_rate = return_map.get(dish_id, Decimal("0.00"))
        neg_count = neg_map.get(dish_id, 0)
        quadrant = d.get("quadrant", "dog")

        suggestion = generate_optimization_suggestion(d, quadrant, ret_rate, neg_count)
        suggestion["quadrant"] = quadrant
        suggestion["return_rate"] = ret_rate
        suggestion["negative_reviews"] = neg_count
        suggestions.append(suggestion)
        action_counts[suggestion["action"]] = action_counts.get(suggestion["action"], 0) + 1

    # 按优先级排序: high > medium > low
    priority_order = {"high": 0, "medium": 1, "low": 2}
    suggestions.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 2))

    log.info(
        "dish_analysis.menu_optimization",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        total_dishes=len(suggestions),
        eliminate=action_counts.get("eliminate", 0),
        raise_price=action_counts.get("raise_price", 0),
        promote=action_counts.get("promote", 0),
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "store_id": str(store_id),
        "summary": action_counts,
        "suggestions": suggestions,
    }


# ══════════════════════════════════════════════
# DB 访问桩
# ══════════════════════════════════════════════


def _query_dish_sales(
    store_id: uuid.UUID,
    start_date: date,
    end_date: date,
    tenant_id: uuid.UUID,
    db,
) -> list[dict]:
    """查询菜品销量汇总"""
    if db is None:
        return []
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
            SELECT oi.dish_id, d.dish_name, d.category_id,
                   COALESCE(SUM(oi.quantity), 0) AS sales_qty,
                   COALESCE(SUM(oi.subtotal_fen), 0) AS sales_amount_fen
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id AND o.tenant_id = :tenant_id
            JOIN dishes d ON oi.dish_id = d.id AND d.tenant_id = :tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.order_time) BETWEEN :start_date AND :end_date
              AND o.status IN ('completed', 'paid')
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY oi.dish_id, d.dish_name, d.category_id
        """),
            {
                "store_id": store_id,
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        return [
            {
                "dish_id": str(row["dish_id"]),
                "dish_name": row["dish_name"],
                "category_id": str(row["category_id"]) if row["category_id"] else None,
                "sales_qty": row["sales_qty"],
                "sales_amount_fen": row["sales_amount_fen"],
            }
            for row in result.mappings().all()
        ]
    except (ImportError, AttributeError):
        return []


def _query_return_data(
    store_id: uuid.UUID,
    start_date: date,
    end_date: date,
    tenant_id: uuid.UUID,
    db,
) -> list[dict]:
    """查询各菜品退菜数据"""
    if db is None:
        return []
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
            SELECT oi.dish_id, d.dish_name,
                   COALESCE(SUM(oi.quantity), 0) AS total_qty,
                   COALESCE(SUM(CASE WHEN oi.return_flag = TRUE THEN oi.quantity ELSE 0 END), 0) AS return_qty
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id AND o.tenant_id = :tenant_id
            JOIN dishes d ON oi.dish_id = d.id AND d.tenant_id = :tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.order_time) BETWEEN :start_date AND :end_date
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY oi.dish_id, d.dish_name
            HAVING SUM(CASE WHEN oi.return_flag = TRUE THEN oi.quantity ELSE 0 END) > 0
        """),
            {
                "store_id": store_id,
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        return [
            {
                "dish_id": str(row["dish_id"]),
                "dish_name": row["dish_name"],
                "total_qty": row["total_qty"],
                "return_qty": row["return_qty"],
            }
            for row in result.mappings().all()
        ]
    except (ImportError, AttributeError):
        return []


def _query_return_reasons(
    store_id: uuid.UUID,
    start_date: date,
    end_date: date,
    tenant_id: uuid.UUID,
    db,
) -> list[dict]:
    """查询退菜原因分布"""
    if db is None:
        return []
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
            SELECT COALESCE(oi.return_reason, '未说明') AS reason,
                   COUNT(*) AS count
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id AND o.tenant_id = :tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.order_time) BETWEEN :start_date AND :end_date
              AND oi.return_flag = TRUE
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY COALESCE(oi.return_reason, '未说明')
            ORDER BY count DESC
        """),
            {
                "store_id": store_id,
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        return [{"reason": row["reason"], "count": row["count"]} for row in result.mappings().all()]
    except (ImportError, AttributeError):
        return []


def _query_negative_reviews(
    store_id: uuid.UUID,
    start_date: date,
    end_date: date,
    tenant_id: uuid.UUID,
    db,
    min_rating: float = 3.0,
) -> list[dict]:
    """查询差评菜品（评分 <= min_rating 视为差评）"""
    if db is None:
        return []
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
            SELECT r.dish_id, d.dish_name,
                   AVG(r.rating) AS avg_rating,
                   COUNT(*) FILTER (WHERE r.rating <= :min_rating) AS negative_count,
                   COUNT(*) AS total_reviews,
                   ARRAY_AGG(DISTINCT r.comment) FILTER (WHERE r.rating <= :min_rating AND r.comment IS NOT NULL) AS top_complaints
            FROM dish_reviews r
            JOIN dishes d ON r.dish_id = d.id AND d.tenant_id = :tenant_id
            WHERE r.store_id = :store_id
              AND r.tenant_id = :tenant_id
              AND DATE(r.created_at) BETWEEN :start_date AND :end_date
              AND r.is_deleted = FALSE
            GROUP BY r.dish_id, d.dish_name
            HAVING COUNT(*) FILTER (WHERE r.rating <= :min_rating) > 0
            ORDER BY negative_count DESC
        """),
            {
                "store_id": store_id,
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
                "min_rating": min_rating,
            },
        )
        return [
            {
                "dish_id": str(row["dish_id"]),
                "dish_name": row["dish_name"],
                "avg_rating": float(row["avg_rating"]) if row["avg_rating"] else 0.0,
                "negative_count": row["negative_count"],
                "total_reviews": row["total_reviews"],
                "top_complaints": row["top_complaints"] or [],
            }
            for row in result.mappings().all()
        ]
    except (ImportError, AttributeError):
        return []


def _query_stockout_records(
    store_id: uuid.UUID,
    start_date: date,
    end_date: date,
    tenant_id: uuid.UUID,
    db,
) -> list[dict]:
    """查询沽清记录"""
    if db is None:
        return []
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
            SELECT s.dish_id, d.dish_name,
                   COUNT(*) AS stockout_count,
                   COUNT(DISTINCT DATE(s.stockout_at)) AS stockout_days,
                   MAX(s.stockout_at) AS last_stockout_at
            FROM dish_stockouts s
            JOIN dishes d ON s.dish_id = d.id AND d.tenant_id = :tenant_id
            WHERE s.store_id = :store_id
              AND s.tenant_id = :tenant_id
              AND DATE(s.stockout_at) BETWEEN :start_date AND :end_date
              AND s.is_deleted = FALSE
            GROUP BY s.dish_id, d.dish_name
            ORDER BY stockout_count DESC
        """),
            {
                "store_id": store_id,
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        return [
            {
                "dish_id": str(row["dish_id"]),
                "dish_name": row["dish_name"],
                "stockout_count": row["stockout_count"],
                "stockout_days": row["stockout_days"],
                "last_stockout_at": row["last_stockout_at"].isoformat() if row["last_stockout_at"] else None,
            }
            for row in result.mappings().all()
        ]
    except (ImportError, AttributeError):
        return []


def _query_new_dishes(
    store_id: uuid.UUID,
    cutoff_date: date,
    tenant_id: uuid.UUID,
    db,
) -> list[dict]:
    """查询新上架菜品"""
    if db is None:
        return []
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
            SELECT d.id AS dish_id, d.dish_name, d.sell_start_date AS launch_date,
                   d.rating,
                   COALESCE(SUM(oi.quantity), 0) AS total_sales
            FROM dishes d
            LEFT JOIN order_items oi ON oi.dish_id = d.id AND oi.is_deleted = FALSE
            LEFT JOIN orders o ON oi.order_id = o.id AND o.is_deleted = FALSE
                AND o.status IN ('completed', 'paid') AND o.tenant_id = :tenant_id
            WHERE d.tenant_id = :tenant_id
              AND (d.store_id = :store_id OR d.store_id IS NULL)
              AND d.is_available = TRUE AND d.is_deleted = FALSE
              AND d.sell_start_date >= :cutoff_date
            GROUP BY d.id, d.dish_name, d.sell_start_date, d.rating
        """),
            {
                "store_id": store_id,
                "tenant_id": tenant_id,
                "cutoff_date": cutoff_date,
            },
        )
        return [
            {
                "dish_id": str(row["dish_id"]),
                "dish_name": row["dish_name"],
                "launch_date": row["launch_date"],
                "rating": float(row["rating"]) if row["rating"] else None,
                "total_sales": row["total_sales"],
            }
            for row in result.mappings().all()
        ]
    except (ImportError, AttributeError):
        return []


def _query_daily_sales_trend(
    dish_id: str,
    store_id: uuid.UUID,
    start_date: date,
    end_date: date,
    tenant_id: uuid.UUID,
    db,
) -> list[int]:
    """查询菜品每日销量趋势"""
    if db is None:
        return []
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
            SELECT DATE(o.order_time) AS sale_date,
                   COALESCE(SUM(oi.quantity), 0) AS daily_qty
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id AND o.tenant_id = :tenant_id
            WHERE oi.dish_id = :dish_id
              AND o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.order_time) BETWEEN :start_date AND :end_date
              AND o.status IN ('completed', 'paid')
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY DATE(o.order_time)
            ORDER BY sale_date
        """),
            {
                "dish_id": dish_id,
                "store_id": store_id,
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        return [row["daily_qty"] for row in result.mappings().all()]
    except (ImportError, AttributeError):
        return []


def _query_repurchase_rate(
    dish_id: str,
    store_id: uuid.UUID,
    start_date: date,
    end_date: date,
    tenant_id: uuid.UUID,
    db,
) -> Decimal:
    """查询菜品复购率（购买>=2次的顾客占比）"""
    if db is None:
        return Decimal("0.00")
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
            WITH customer_orders AS (
                SELECT o.customer_id, COUNT(DISTINCT o.id) AS order_count
                FROM order_items oi
                JOIN orders o ON oi.order_id = o.id AND o.tenant_id = :tenant_id
                WHERE oi.dish_id = :dish_id
                  AND o.store_id = :store_id
                  AND o.tenant_id = :tenant_id
                  AND DATE(o.order_time) BETWEEN :start_date AND :end_date
                  AND o.status IN ('completed', 'paid')
                  AND o.is_deleted = FALSE
                  AND oi.is_deleted = FALSE
                  AND o.customer_id IS NOT NULL
                GROUP BY o.customer_id
            )
            SELECT
                COUNT(*) AS total_customers,
                COUNT(*) FILTER (WHERE order_count >= 2) AS repeat_customers
            FROM customer_orders
        """),
            {
                "dish_id": dish_id,
                "store_id": store_id,
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        row = result.mappings().first()
        if row and row["total_customers"] > 0:
            return (Decimal(row["repeat_customers"]) / Decimal(row["total_customers"]) * 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        return Decimal("0.00")
    except (ImportError, AttributeError):
        return Decimal("0.00")
