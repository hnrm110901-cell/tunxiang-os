"""菜品毛利分析 — 单品毛利计算、排行、低毛利预警

连接 tx-supply 的理论成本/实际成本数据，结合 Dish 售价，
输出毛利率、排行、预警。

金额单位: 分(fen), int
毛利率: 百分比, Decimal(5,2)
"""
import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import structlog

log = structlog.get_logger()

# ─── 默认毛利预警阈值 ───
DEFAULT_LOW_MARGIN_THRESHOLD_PCT = Decimal("30.00")  # 30%


# ─── 纯函数：毛利计算 ───

def compute_margin(selling_price_fen: int, cost_fen: int) -> dict:
    """纯函数：计算单品毛利

    Args:
        selling_price_fen: 售价（分）
        cost_fen: 成本（分）

    Returns:
        {
            "selling_price_fen": int,
            "cost_fen": int,
            "margin_fen": int,
            "margin_rate": Decimal,  -- 百分比，如 65.50 表示 65.50%
        }
    """
    margin_fen = selling_price_fen - cost_fen

    if selling_price_fen > 0:
        margin_rate = (Decimal(margin_fen) / Decimal(selling_price_fen) * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    else:
        margin_rate = Decimal("0.00")

    return {
        "selling_price_fen": selling_price_fen,
        "cost_fen": cost_fen,
        "margin_fen": margin_fen,
        "margin_rate": margin_rate,
    }


def compute_margin_ranking(
    dish_margins: list[dict],
    sort_by: str = "margin_rate",
    ascending: bool = False,
) -> list[dict]:
    """纯函数：对菜品毛利列表排序

    Args:
        dish_margins: [{"dish_id", "dish_name", "selling_price_fen", "cost_fen", "margin_fen", "margin_rate", ...}]
        sort_by: margin_rate / margin_fen / cost_fen
        ascending: True=升序（低到高）

    Returns:
        排序后的列表，附加 rank 字段
    """
    sorted_list = sorted(
        dish_margins,
        key=lambda x: x.get(sort_by, 0),
        reverse=not ascending,
    )
    for i, item in enumerate(sorted_list, 1):
        item["rank"] = i
    return sorted_list


def filter_low_margin(
    dish_margins: list[dict],
    threshold_pct: Decimal,
) -> list[dict]:
    """纯函数：筛选低于阈值的菜品"""
    return [
        d for d in dish_margins
        if d.get("margin_rate", Decimal("100")) < threshold_pct
    ]


# ─── 业务函数（需要 DB） ───

def calculate_dish_margin(
    dish_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db,
) -> dict:
    """计算单个菜品毛利

    Returns:
        {"dish_id", "dish_name", "selling_price_fen", "cost_fen", "margin_fen", "margin_rate"}
    """
    dish = _get_dish_info(dish_id, tenant_id, db)
    if dish is None:
        log.warning("dish_margin.dish_not_found", dish_id=str(dish_id))
        return {
            "dish_id": str(dish_id),
            "dish_name": "",
            "selling_price_fen": 0,
            "cost_fen": 0,
            "margin_fen": 0,
            "margin_rate": Decimal("0.00"),
        }

    selling_price_fen = dish.get("price_fen", 0) or 0
    # 优先使用 BOM 理论成本，回退到 dishes.cost_fen
    cost_fen = _get_dish_cost(dish_id, tenant_id, db) or dish.get("cost_fen", 0) or 0

    margin = compute_margin(selling_price_fen, cost_fen)

    log.info(
        "dish_margin.calculated",
        dish_id=str(dish_id),
        dish_name=dish.get("dish_name", ""),
        margin_rate=str(margin["margin_rate"]),
    )
    return {
        "dish_id": str(dish_id),
        "dish_name": dish.get("dish_name", ""),
        **margin,
    }


def get_dish_margin_ranking(
    store_id: uuid.UUID,
    date_range: tuple[date, date],
    tenant_id: uuid.UUID,
    db,
    sort_by: str = "margin_rate",
    limit: int = 50,
) -> list[dict]:
    """菜品毛利排行

    Args:
        store_id: 门店ID
        date_range: (start_date, end_date)
        tenant_id: 租户ID
        db: 数据库会话
        sort_by: 排序字段
        limit: 返回数量

    Returns:
        排序后的菜品毛利列表
    """
    dishes = _get_store_dishes(store_id, tenant_id, db)
    if not dishes:
        return []

    margins = []
    for dish in dishes:
        dish_id = dish["id"]
        selling_price_fen = dish.get("price_fen", 0) or 0
        cost_fen = _get_dish_cost(dish_id, tenant_id, db) or dish.get("cost_fen", 0) or 0

        margin = compute_margin(selling_price_fen, cost_fen)
        # 附加销量信息
        sales_qty = _get_dish_sales_in_range(
            dish_id, store_id, date_range[0], date_range[1], tenant_id, db
        )

        margins.append({
            "dish_id": str(dish_id),
            "dish_name": dish.get("dish_name", ""),
            "category": dish.get("category", ""),
            "sales_qty": sales_qty,
            "revenue_fen": selling_price_fen * sales_qty,
            "total_cost_fen": cost_fen * sales_qty,
            **margin,
        })

    ranked = compute_margin_ranking(margins, sort_by=sort_by)

    log.info(
        "dish_margin.ranking",
        store_id=str(store_id),
        date_range=str(date_range),
        dish_count=len(ranked),
    )
    return ranked[:limit]


def get_low_margin_dishes(
    store_id: uuid.UUID,
    threshold_pct: Optional[Decimal],
    tenant_id: uuid.UUID,
    db,
) -> list[dict]:
    """低毛利预警

    Args:
        store_id: 门店ID
        threshold_pct: 毛利率阈值（百分比），None 时使用默认 30%
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        低于阈值的菜品列表，按毛利率升序（最差在前）
    """
    if threshold_pct is None:
        threshold_pct = DEFAULT_LOW_MARGIN_THRESHOLD_PCT

    dishes = _get_store_dishes(store_id, tenant_id, db)
    if not dishes:
        return []

    margins = []
    for dish in dishes:
        dish_id = dish["id"]
        selling_price_fen = dish.get("price_fen", 0) or 0
        cost_fen = _get_dish_cost(dish_id, tenant_id, db) or dish.get("cost_fen", 0) or 0

        margin = compute_margin(selling_price_fen, cost_fen)
        margins.append({
            "dish_id": str(dish_id),
            "dish_name": dish.get("dish_name", ""),
            **margin,
        })

    low_margin = filter_low_margin(margins, threshold_pct)
    # 按毛利率升序
    low_margin.sort(key=lambda x: x["margin_rate"])

    if low_margin:
        log.warning(
            "dish_margin.low_margin_alert",
            store_id=str(store_id),
            threshold_pct=str(threshold_pct),
            count=len(low_margin),
            worst_dish=low_margin[0].get("dish_name", ""),
            worst_rate=str(low_margin[0].get("margin_rate", "")),
        )
    return low_margin


# ─── DB 访问桩 ───

def _get_dish_info(dish_id: uuid.UUID, tenant_id: uuid.UUID, db) -> Optional[dict]:
    """查询菜品基本信息"""
    if db is None:
        return None
    try:
        from sqlalchemy import text
        result = db.execute(text("""
            SELECT id, dish_name, dish_code, price_fen, cost_fen, category_id
            FROM dishes
            WHERE id = :dish_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """), {"dish_id": dish_id, "tenant_id": tenant_id})
        row = result.mappings().first()
        return dict(row) if row else None
    except (ImportError, AttributeError):
        return None


def _get_store_dishes(store_id: uuid.UUID, tenant_id: uuid.UUID, db) -> list[dict]:
    """查询门店所有在售菜品"""
    if db is None:
        return []
    try:
        from sqlalchemy import text
        result = db.execute(text("""
            SELECT id, dish_name, dish_code, price_fen, cost_fen
            FROM dishes
            WHERE (store_id = :store_id OR store_id IS NULL)
              AND tenant_id = :tenant_id
              AND is_available = TRUE AND is_deleted = FALSE
        """), {"store_id": store_id, "tenant_id": tenant_id})
        return [dict(row) for row in result.mappings().all()]
    except (ImportError, AttributeError):
        return []


def _get_dish_cost(dish_id: uuid.UUID, tenant_id: uuid.UUID, db) -> Optional[int]:
    """从 BOM 取理论成本（调用 tx-supply 的 theoretical_cost）

    实际项目中通过服务间调用或共享函数获取。
    这里直接查 BOM 数据。
    """
    if db is None:
        return None
    try:
        from sqlalchemy import text
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        # 取当前有效 BOM
        bom_result = db.execute(text("""
            SELECT id FROM bom_templates
            WHERE dish_id = :dish_id AND tenant_id = :tenant_id
              AND is_active = TRUE AND is_deleted = FALSE
              AND effective_date <= :now
              AND (expiry_date IS NULL OR expiry_date > :now)
            ORDER BY effective_date DESC LIMIT 1
        """), {"dish_id": dish_id, "tenant_id": tenant_id, "now": now})
        bom_id = bom_result.scalar_one_or_none()
        if bom_id is None:
            return None

        # 汇总 BOM 成本
        cost_result = db.execute(text("""
            SELECT COALESCE(SUM(
                CAST(standard_qty * (1 + COALESCE(waste_factor, 0)) * COALESCE(unit_cost_fen, 0) AS INTEGER)
            ), 0) as total_cost
            FROM bom_items
            WHERE bom_id = :bom_id AND tenant_id = :tenant_id
              AND is_deleted = FALSE AND item_action != 'REMOVE'
        """), {"bom_id": bom_id, "tenant_id": tenant_id})
        return cost_result.scalar_one_or_none() or 0
    except (ImportError, AttributeError):
        return None


def _get_dish_sales_in_range(
    dish_id: uuid.UUID,
    store_id: uuid.UUID,
    start_date: date,
    end_date: date,
    tenant_id: uuid.UUID,
    db,
) -> int:
    """查询菜品在时间范围内的销量"""
    if db is None:
        return 0
    try:
        from sqlalchemy import text
        result = db.execute(text("""
            SELECT COALESCE(SUM(oi.quantity), 0)
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            WHERE oi.dish_id = :dish_id
              AND o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.order_time) BETWEEN :start_date AND :end_date
              AND o.status IN ('completed', 'paid')
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
        """), {
            "dish_id": dish_id,
            "store_id": store_id,
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date,
        })
        return result.scalar_one_or_none() or 0
    except (ImportError, AttributeError):
        return 0
