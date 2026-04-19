"""理论成本引擎 — 基于 BOM 配方计算菜品标准成本

连接 bom_templates + bom_items 表，取当前有效 BOM 版本，
按 standard_qty * unit_cost_fen 汇总得出菜品理论成本（分）。

金额单位: 分(fen), int
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog

log = structlog.get_logger()


# ─── 纯函数：单菜品理论成本 ───


def get_dish_theoretical_cost(
    dish_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db,
) -> int:
    """查询菜品当前有效 BOM，汇总理论成本（分）

    逻辑：
      1. 从 bom_templates 取 dish_id 当前有效版本（is_active=True, effective_date <= now, expiry_date is null or > now）
      2. 从 bom_items 取该 BOM 的所有原料行
      3. 理论成本 = SUM(standard_qty * unit_cost_fen) 对每行原料
      4. 考虑 waste_factor: actual_qty = standard_qty * (1 + waste_factor)

    Returns:
        理论成本（分），无 BOM 时返回 0
    """
    now = datetime.now(timezone.utc)

    # 查询当前有效 BOM
    bom = _find_active_bom(dish_id, tenant_id, now, db)
    if bom is None:
        log.warning("theoretical_cost.no_active_bom", dish_id=str(dish_id), tenant_id=str(tenant_id))
        return 0

    bom_id = bom["id"]
    items = _get_bom_items(bom_id, tenant_id, db)
    if not items:
        log.warning("theoretical_cost.empty_bom", bom_id=str(bom_id), dish_id=str(dish_id))
        return 0

    total_cost_fen = _sum_bom_item_costs(items)

    log.info(
        "theoretical_cost.calculated",
        dish_id=str(dish_id),
        bom_id=str(bom_id),
        total_cost_fen=total_cost_fen,
        item_count=len(items),
    )
    return total_cost_fen


def get_order_theoretical_cost(
    order_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db,
) -> int:
    """计算整单理论成本

    逻辑：遍历 order_items，对每个 dish_id 取理论成本 * 数量

    Returns:
        整单理论成本（分）
    """
    order_items = _get_order_items(order_id, tenant_id, db)
    if not order_items:
        log.warning("theoretical_cost.no_order_items", order_id=str(order_id))
        return 0

    total = 0
    for item in order_items:
        dish_id = item.get("dish_id")
        quantity = item.get("quantity", 1)
        if dish_id is None:
            continue
        dish_cost = get_dish_theoretical_cost(dish_id, tenant_id, db)
        total += dish_cost * quantity

    log.info(
        "theoretical_cost.order_total",
        order_id=str(order_id),
        total_cost_fen=total,
        item_count=len(order_items),
    )
    return total


def batch_calculate_daily_costs(
    store_id: uuid.UUID,
    target_date: date,
    tenant_id: uuid.UUID,
    db,
) -> dict:
    """计算门店当日所有菜品的理论成本汇总

    Returns:
        {
            "store_id": str,
            "date": str,
            "dish_costs": [{"dish_id", "dish_name", "quantity_sold", "unit_cost_fen", "total_cost_fen"}],
            "grand_total_fen": int,
        }
    """
    sold_dishes = _get_daily_sold_dishes(store_id, target_date, tenant_id, db)
    if not sold_dishes:
        log.info("theoretical_cost.no_sales", store_id=str(store_id), date=str(target_date))
        return {
            "store_id": str(store_id),
            "date": str(target_date),
            "dish_costs": [],
            "grand_total_fen": 0,
        }

    dish_costs = []
    grand_total = 0

    for dish_info in sold_dishes:
        dish_id = dish_info["dish_id"]
        quantity_sold = dish_info.get("quantity_sold", 0)
        dish_name = dish_info.get("dish_name", "")

        unit_cost = get_dish_theoretical_cost(dish_id, tenant_id, db)
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

    # 按成本降序排列
    dish_costs.sort(key=lambda x: x["total_cost_fen"], reverse=True)

    log.info(
        "theoretical_cost.daily_batch",
        store_id=str(store_id),
        date=str(target_date),
        dish_count=len(dish_costs),
        grand_total_fen=grand_total,
    )
    return {
        "store_id": str(store_id),
        "date": str(target_date),
        "dish_costs": dish_costs,
        "grand_total_fen": grand_total,
    }


# ─── 纯函数：BOM 成本汇总 ───


def _sum_bom_item_costs(items: list[dict]) -> int:
    """汇总 BOM 行项的理论成本

    每行: actual_qty = standard_qty * (1 + waste_factor)
          line_cost = actual_qty * unit_cost_fen
    """
    total = 0
    for item in items:
        standard_qty = Decimal(str(item.get("standard_qty", 0)))
        waste_factor = Decimal(str(item.get("waste_factor", 0)))
        unit_cost_fen = item.get("unit_cost_fen", 0) or 0

        actual_qty = standard_qty * (1 + waste_factor)
        line_cost = int(actual_qty * unit_cost_fen)
        total += line_cost

    return total


def compute_dish_theoretical_cost_from_bom(bom_items: list[dict]) -> int:
    """纯函数：从 BOM 行项列表直接计算理论成本（供测试/外部调用）"""
    return _sum_bom_item_costs(bom_items)


# ─── DB 访问桩（实际项目中由 Repository 层实现） ───


def _find_active_bom(
    dish_id: uuid.UUID,
    tenant_id: uuid.UUID,
    now: datetime,
    db,
) -> Optional[dict]:
    """查询菜品当前有效 BOM 模板

    SQL 逻辑:
        SELECT * FROM bom_templates
        WHERE dish_id = :dish_id AND tenant_id = :tenant_id
          AND is_active = TRUE AND is_deleted = FALSE
          AND effective_date <= :now
          AND (expiry_date IS NULL OR expiry_date > :now)
        ORDER BY effective_date DESC LIMIT 1
    """
    if db is None:
        return None
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
            SELECT id, dish_id, version, yield_rate
            FROM bom_templates
            WHERE dish_id = :dish_id AND tenant_id = :tenant_id
              AND is_active = TRUE AND is_deleted = FALSE
              AND effective_date <= :now
              AND (expiry_date IS NULL OR expiry_date > :now)
            ORDER BY effective_date DESC LIMIT 1
        """),
            {"dish_id": dish_id, "tenant_id": tenant_id, "now": now},
        )
        row = result.mappings().first()
        return dict(row) if row else None
    except (ImportError, AttributeError):
        return None


def _get_bom_items(bom_id: uuid.UUID, tenant_id: uuid.UUID, db) -> list[dict]:
    """查询 BOM 所有原料行"""
    if db is None:
        return []
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
            SELECT ingredient_id, standard_qty, unit, unit_cost_fen,
                   waste_factor, is_optional, item_action
            FROM bom_items
            WHERE bom_id = :bom_id AND tenant_id = :tenant_id
              AND is_deleted = FALSE AND item_action != 'REMOVE'
        """),
            {"bom_id": bom_id, "tenant_id": tenant_id},
        )
        return [dict(row) for row in result.mappings().all()]
    except (ImportError, AttributeError):
        return []


def _get_order_items(order_id: uuid.UUID, tenant_id: uuid.UUID, db) -> list[dict]:
    """查询订单明细"""
    if db is None:
        return []
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
            SELECT dish_id, item_name, quantity, unit_price_fen, subtotal_fen
            FROM order_items
            WHERE order_id = :order_id AND tenant_id = :tenant_id
              AND is_deleted = FALSE
        """),
            {"order_id": order_id, "tenant_id": tenant_id},
        )
        return [dict(row) for row in result.mappings().all()]
    except (ImportError, AttributeError):
        return []


def _get_daily_sold_dishes(
    store_id: uuid.UUID,
    target_date: date,
    tenant_id: uuid.UUID,
    db,
) -> list[dict]:
    """查询门店当日售出菜品及数量

    SQL 逻辑:
        SELECT oi.dish_id, d.dish_name, SUM(oi.quantity) as quantity_sold
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.id
        JOIN dishes d ON oi.dish_id = d.id
        WHERE o.store_id = :store_id
          AND o.tenant_id = :tenant_id
          AND DATE(o.order_time) = :target_date
          AND o.status IN ('completed','paid')
        GROUP BY oi.dish_id, d.dish_name
    """
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
