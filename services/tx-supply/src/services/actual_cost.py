"""实际成本归集 — 基于采购单价计算菜品实际成本

从 ingredient_transactions (type=purchase) 和 supply_orders 取最新采购价，
结合 BOM 配方用量，计算实际食材消耗成本。

金额单位: 分(fen), int
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog

log = structlog.get_logger()


# ─── 核心函数 ───


def get_ingredient_actual_price(
    ingredient_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db,
) -> int:
    """获取食材最新采购单价（分）

    优先级：
      1. ingredient_transactions 中最近一笔 type=purchase 的 unit_cost_fen
      2. ingredients 表的 unit_price_fen（台账价格）
      3. 无数据返回 0

    Returns:
        最新采购单价（分/基本单位）
    """
    # 尝试从采购流水取最新价格
    latest_price = _get_latest_purchase_price(ingredient_id, tenant_id, db)
    if latest_price is not None and latest_price > 0:
        log.debug(
            "actual_cost.price_from_transaction",
            ingredient_id=str(ingredient_id),
            price_fen=latest_price,
        )
        return latest_price

    # 回退到台账价格
    ledger_price = _get_ledger_price(ingredient_id, tenant_id, db)
    if ledger_price is not None and ledger_price > 0:
        log.debug(
            "actual_cost.price_from_ledger",
            ingredient_id=str(ingredient_id),
            price_fen=ledger_price,
        )
        return ledger_price

    log.warning("actual_cost.no_price", ingredient_id=str(ingredient_id))
    return 0


def calculate_actual_dish_cost(
    dish_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db,
) -> int:
    """基于实际采购价计算菜品成本

    逻辑：
      1. 取菜品 BOM（同 theoretical_cost 逻辑）
      2. 对每个原料，用 get_ingredient_actual_price 取实际价格
      3. actual_cost = SUM(standard_qty * (1 + waste_factor) * actual_unit_price)

    Returns:
        菜品实际成本（分）
    """
    bom_items = _get_dish_bom_items(dish_id, tenant_id, db)
    if not bom_items:
        log.warning("actual_cost.no_bom", dish_id=str(dish_id))
        return 0

    total = 0
    for item in bom_items:
        ingredient_id = item.get("ingredient_id")
        if ingredient_id is None:
            continue

        standard_qty = Decimal(str(item.get("standard_qty", 0)))
        waste_factor = Decimal(str(item.get("waste_factor", 0)))
        actual_qty = standard_qty * (1 + waste_factor)

        actual_price = get_ingredient_actual_price(ingredient_id, tenant_id, db)
        line_cost = int(actual_qty * actual_price)
        total += line_cost

    log.info(
        "actual_cost.dish_calculated",
        dish_id=str(dish_id),
        total_fen=total,
        ingredient_count=len(bom_items),
    )
    return total


def get_daily_actual_cost(
    store_id: uuid.UUID,
    target_date: date,
    tenant_id: uuid.UUID,
    db,
) -> dict:
    """计算门店当日实际食材消耗成本

    数据来源：ingredient_transactions (type=usage)，按日期和门店汇总。
    同时计算基于实际采购价 + BOM 用量的理论消耗量。

    Returns:
        {
            "store_id": str,
            "date": str,
            "total_usage_cost_fen": int,  -- 实际领用/消耗记录的成本
            "dish_actual_costs": [{"dish_id", "dish_name", "quantity_sold", "unit_cost_fen", "total_cost_fen"}],
            "grand_total_fen": int,       -- 基于实际价+销量的成本
        }
    """
    # 方法1：从库存流水直接汇总消耗成本
    usage_cost = _sum_daily_usage_transactions(store_id, target_date, tenant_id, db)

    # 方法2：从销售量 + 实际采购价推算
    sold_dishes = _get_daily_sold_dishes(store_id, target_date, tenant_id, db)
    dish_costs = []
    grand_total = 0

    for dish_info in sold_dishes:
        dish_id = dish_info["dish_id"]
        quantity_sold = dish_info.get("quantity_sold", 0)
        dish_name = dish_info.get("dish_name", "")

        unit_cost = calculate_actual_dish_cost(dish_id, tenant_id, db)
        line_total = unit_cost * quantity_sold
        grand_total += line_total

        dish_costs.append(
            {
                "dish_id": str(dish_id),
                "dish_name": dish_name,
                "quantity_sold": quantity_sold,
                "unit_cost_fen": unit_cost,
                "total_cost_fen": line_total,
            }
        )

    dish_costs.sort(key=lambda x: x["total_cost_fen"], reverse=True)

    log.info(
        "actual_cost.daily_summary",
        store_id=str(store_id),
        date=str(target_date),
        usage_cost_fen=usage_cost,
        calculated_cost_fen=grand_total,
    )
    return {
        "store_id": str(store_id),
        "date": str(target_date),
        "total_usage_cost_fen": usage_cost,
        "dish_actual_costs": dish_costs,
        "grand_total_fen": grand_total,
    }


# ─── 纯函数 ───


def compute_actual_cost_from_prices(
    bom_items: list[dict],
    price_map: dict[str, int],
) -> int:
    """纯函数：给定 BOM 行项和价格映射，计算实际成本

    Args:
        bom_items: [{"ingredient_id", "standard_qty", "waste_factor"}]
        price_map: {ingredient_id_str: unit_price_fen}

    Returns:
        实际成本（分）
    """
    total = 0
    for item in bom_items:
        ingredient_id = str(item.get("ingredient_id", ""))
        standard_qty = Decimal(str(item.get("standard_qty", 0)))
        waste_factor = Decimal(str(item.get("waste_factor", 0)))
        actual_qty = standard_qty * (1 + waste_factor)

        unit_price = price_map.get(ingredient_id, 0)
        line_cost = int(actual_qty * unit_price)
        total += line_cost

    return total


# ─── DB 访问（实际项目中由 Repository 层实现） ───


def _get_latest_purchase_price(
    ingredient_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db,
) -> Optional[int]:
    """从 ingredient_transactions 取最近一笔采购的 unit_cost_fen"""
    if db is None:
        return None
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
            SELECT unit_cost_fen
            FROM ingredient_transactions
            WHERE ingredient_id = :ingredient_id
              AND tenant_id = :tenant_id
              AND transaction_type = 'purchase'
              AND unit_cost_fen IS NOT NULL
              AND is_deleted = FALSE
            ORDER BY transaction_time DESC
            LIMIT 1
        """),
            {"ingredient_id": ingredient_id, "tenant_id": tenant_id},
        )
        row = result.scalar_one_or_none()
        return row if row else None
    except (ImportError, AttributeError):
        return None


def _get_ledger_price(
    ingredient_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db,
) -> Optional[int]:
    """从 ingredients 台账取 unit_price_fen"""
    if db is None:
        return None
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
            SELECT unit_price_fen
            FROM ingredients
            WHERE id = :ingredient_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
        """),
            {"ingredient_id": ingredient_id, "tenant_id": tenant_id},
        )
        row = result.scalar_one_or_none()
        return row if row else None
    except (ImportError, AttributeError):
        return None


def _get_dish_bom_items(
    dish_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db,
) -> list[dict]:
    """取菜品当前有效 BOM 的原料行（复用 theoretical_cost 逻辑）"""
    if db is None:
        return []
    try:
        from sqlalchemy import text

        now = datetime.now(timezone.utc)
        # 先取 BOM 模板
        bom_result = db.execute(
            text("""
            SELECT id FROM bom_templates
            WHERE dish_id = :dish_id AND tenant_id = :tenant_id
              AND is_active = TRUE AND is_deleted = FALSE
              AND effective_date <= :now
              AND (expiry_date IS NULL OR expiry_date > :now)
            ORDER BY effective_date DESC LIMIT 1
        """),
            {"dish_id": dish_id, "tenant_id": tenant_id, "now": now},
        )
        bom_row = bom_result.scalar_one_or_none()
        if bom_row is None:
            return []

        # 取原料行
        items_result = db.execute(
            text("""
            SELECT ingredient_id, standard_qty, unit, unit_cost_fen,
                   waste_factor, is_optional, item_action
            FROM bom_items
            WHERE bom_id = :bom_id AND tenant_id = :tenant_id
              AND is_deleted = FALSE AND item_action != 'REMOVE'
        """),
            {"bom_id": bom_row, "tenant_id": tenant_id},
        )
        return [dict(row) for row in items_result.mappings().all()]
    except (ImportError, AttributeError):
        return []


def _sum_daily_usage_transactions(
    store_id: uuid.UUID,
    target_date: date,
    tenant_id: uuid.UUID,
    db,
) -> int:
    """汇总门店当日 usage 类型流水的 total_cost_fen"""
    if db is None:
        return 0
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
            SELECT COALESCE(SUM(ABS(total_cost_fen)), 0) as total
            FROM ingredient_transactions
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND transaction_type = 'usage'
              AND DATE(transaction_time) = :target_date
              AND is_deleted = FALSE
        """),
            {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
        )
        return result.scalar_one_or_none() or 0
    except (ImportError, AttributeError):
        return 0


def _get_daily_sold_dishes(
    store_id: uuid.UUID,
    target_date: date,
    tenant_id: uuid.UUID,
    db,
) -> list[dict]:
    """查询门店当日售出菜品"""
    if db is None:
        return []
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
            SELECT oi.dish_id, d.dish_name, SUM(oi.quantity) as quantity_sold
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            JOIN dishes d ON oi.dish_id = d.id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.order_time) = :target_date
              AND o.status IN ('completed', 'paid')
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY oi.dish_id, d.dish_name
        """),
            {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
        )
        return [dict(row) for row in result.mappings().all()]
    except (ImportError, AttributeError):
        return []
