"""供应链报表: 当前库存余额表

展示每个门店各原料的当前库存数量和金额。
"""

REPORT_ID = "scm_inventory_balance"
REPORT_NAME = "当前库存余额表"
CATEGORY = "supply"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    i.name AS ingredient_name,
    i.category AS ingredient_category,
    inv.unit,
    inv.current_qty,
    inv.avg_cost_fen,
    ROUND(inv.current_qty * inv.avg_cost_fen) AS balance_fen,
    inv.min_qty,
    inv.max_qty,
    CASE
        WHEN inv.current_qty <= inv.min_qty THEN '不足'
        WHEN inv.current_qty >= inv.max_qty THEN '过量'
        ELSE '正常'
    END AS stock_status,
    inv.updated_at AS last_updated
FROM inventory inv
JOIN stores s ON inv.store_id = s.id AND s.tenant_id = inv.tenant_id
JOIN ingredients i ON inv.ingredient_id = i.id AND i.tenant_id = inv.tenant_id
WHERE inv.tenant_id = :tenant_id
  AND inv.is_deleted = FALSE
  AND i.is_deleted = FALSE
  AND (:store_id IS NULL OR inv.store_id = :store_id::UUID)
ORDER BY balance_fen DESC
"""

DIMENSIONS = ["store_name", "ingredient_name", "ingredient_category", "unit", "stock_status"]
METRICS = ["current_qty", "avg_cost_fen", "balance_fen", "min_qty", "max_qty"]
FILTERS = ["store_id"]
