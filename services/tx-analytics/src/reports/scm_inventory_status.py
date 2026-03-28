"""供应链报表: 库存状况分析表

从周转率、积压、短缺等维度分析库存健康度。
"""

REPORT_ID = "scm_inventory_status"
REPORT_NAME = "库存状况分析表"
CATEGORY = "supply"

SQL_TEMPLATE = """
WITH usage AS (
    SELECT
        it.store_id,
        it.ingredient_id,
        SUM(it.qty) AS period_usage_qty,
        SUM(it.cost_fen) AS period_usage_cost_fen
    FROM inventory_transactions it
    WHERE it.tenant_id = :tenant_id
      AND it.is_deleted = FALSE
      AND it.tx_type = 'usage'
      AND it.tx_date BETWEEN :start_date AND :end_date
    GROUP BY it.store_id, it.ingredient_id
)
SELECT
    s.store_name,
    i.name AS ingredient_name,
    i.category AS ingredient_category,
    inv.current_qty,
    inv.avg_cost_fen,
    ROUND(inv.current_qty * inv.avg_cost_fen) AS balance_fen,
    COALESCE(u.period_usage_qty, 0) AS period_usage_qty,
    COALESCE(u.period_usage_cost_fen, 0) AS period_usage_cost_fen,
    CASE WHEN inv.current_qty > 0 AND COALESCE(u.period_usage_qty, 0) > 0
         THEN ROUND(inv.current_qty / (u.period_usage_qty
              / GREATEST((:end_date::DATE - :start_date::DATE + 1), 1)), 1)
         ELSE 0
    END AS stock_days,
    CASE
        WHEN COALESCE(u.period_usage_qty, 0) = 0 AND inv.current_qty > 0 THEN '积压'
        WHEN inv.current_qty <= inv.min_qty THEN '短缺'
        WHEN inv.current_qty >= inv.max_qty THEN '过量'
        ELSE '正常'
    END AS health_status
FROM inventory inv
JOIN stores s ON inv.store_id = s.id AND s.tenant_id = inv.tenant_id
JOIN ingredients i ON inv.ingredient_id = i.id AND i.tenant_id = inv.tenant_id
LEFT JOIN usage u ON u.store_id = inv.store_id AND u.ingredient_id = inv.ingredient_id
WHERE inv.tenant_id = :tenant_id
  AND inv.is_deleted = FALSE
  AND (:store_id IS NULL OR inv.store_id = :store_id::UUID)
ORDER BY balance_fen DESC
"""

DIMENSIONS = ["store_name", "ingredient_name", "ingredient_category", "health_status"]
METRICS = ["current_qty", "avg_cost_fen", "balance_fen", "period_usage_qty",
           "period_usage_cost_fen", "stock_days"]
FILTERS = ["start_date", "end_date", "store_id"]
