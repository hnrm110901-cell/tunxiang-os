"""供应链报表: 原料用量理论实际对比表

对比BOM理论用量与实际消耗，分析用料差异。
"""

REPORT_ID = "scm_yield_comparison"
REPORT_NAME = "原料用量理论实际对比表"
CATEGORY = "supply"

SQL_TEMPLATE = """
WITH theoretical AS (
    SELECT
        bd.ingredient_id,
        SUM(bd.standard_qty * oi.quantity) AS theory_qty
    FROM order_items oi
    JOIN orders o ON oi.order_id = o.id AND o.tenant_id = oi.tenant_id
    JOIN bom_details bd ON bd.dish_id = oi.dish_id AND bd.tenant_id = oi.tenant_id
        AND bd.is_active = TRUE
    WHERE o.tenant_id = :tenant_id
      AND o.is_deleted = FALSE
      AND oi.is_deleted = FALSE
      AND o.status IN ('completed', 'paid')
      AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
    GROUP BY bd.ingredient_id
),
actual AS (
    SELECT
        it.ingredient_id,
        SUM(it.qty) AS actual_qty
    FROM inventory_transactions it
    WHERE it.tenant_id = :tenant_id
      AND it.is_deleted = FALSE
      AND it.tx_type = 'usage'
      AND it.tx_date BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR it.store_id = :store_id::UUID)
    GROUP BY it.ingredient_id
)
SELECT
    i.name AS ingredient_name,
    i.category AS ingredient_category,
    i.unit,
    COALESCE(t.theory_qty, 0) AS theory_qty,
    COALESCE(a.actual_qty, 0) AS actual_qty,
    COALESCE(a.actual_qty, 0) - COALESCE(t.theory_qty, 0) AS variance_qty,
    CASE WHEN COALESCE(t.theory_qty, 0) > 0
         THEN ROUND(
             (COALESCE(a.actual_qty, 0) - t.theory_qty)::NUMERIC / t.theory_qty * 100, 2)
         ELSE 0
    END AS variance_pct
FROM ingredients i
LEFT JOIN theoretical t ON t.ingredient_id = i.id
LEFT JOIN actual a ON a.ingredient_id = i.id
WHERE i.tenant_id = :tenant_id
  AND i.is_deleted = FALSE
  AND (t.theory_qty IS NOT NULL OR a.actual_qty IS NOT NULL)
ORDER BY ABS(COALESCE(a.actual_qty, 0) - COALESCE(t.theory_qty, 0)) DESC
"""

DIMENSIONS = ["ingredient_name", "ingredient_category", "unit"]
METRICS = ["theory_qty", "actual_qty", "variance_qty", "variance_pct"]
FILTERS = ["start_date", "end_date", "store_id"]
