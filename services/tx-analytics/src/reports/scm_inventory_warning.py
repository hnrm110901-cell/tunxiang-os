"""供应链报表: 库存预警表

列出所有库存异常项（低于安全库存或超过最大库存），供采购/调拨决策参考。
"""

REPORT_ID = "scm_inventory_warning"
REPORT_NAME = "库存预警表"
CATEGORY = "supply"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    i.name AS ingredient_name,
    i.category AS ingredient_category,
    inv.unit,
    inv.current_qty,
    inv.min_qty,
    inv.max_qty,
    inv.avg_cost_fen,
    ROUND(inv.current_qty * inv.avg_cost_fen) AS balance_fen,
    CASE
        WHEN inv.current_qty <= 0 THEN '缺货'
        WHEN inv.current_qty <= inv.min_qty THEN '不足'
        WHEN inv.current_qty >= inv.max_qty THEN '过量'
    END AS warning_type,
    CASE
        WHEN inv.current_qty <= inv.min_qty
             THEN inv.min_qty * 2 - inv.current_qty
        ELSE 0
    END AS suggested_order_qty
FROM inventory inv
JOIN stores s ON inv.store_id = s.id AND s.tenant_id = inv.tenant_id
JOIN ingredients i ON inv.ingredient_id = i.id AND i.tenant_id = inv.tenant_id
WHERE inv.tenant_id = :tenant_id
  AND inv.is_deleted = FALSE
  AND (inv.current_qty <= inv.min_qty OR inv.current_qty >= inv.max_qty)
  AND (:store_id IS NULL OR inv.store_id = :store_id::UUID)
ORDER BY
    CASE WHEN inv.current_qty <= 0 THEN 0
         WHEN inv.current_qty <= inv.min_qty THEN 1
         ELSE 2
    END,
    balance_fen DESC
"""

DIMENSIONS = ["store_name", "ingredient_name", "ingredient_category", "unit", "warning_type"]
METRICS = ["current_qty", "min_qty", "max_qty", "avg_cost_fen", "balance_fen", "suggested_order_qty"]
FILTERS = ["store_id"]
