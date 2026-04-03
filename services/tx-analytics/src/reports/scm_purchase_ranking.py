"""供应链报表: 采购商品入库排名表

按商品入库金额降序排名，展示TOP商品采购情况。
"""

REPORT_ID = "scm_purchase_ranking"
REPORT_NAME = "采购商品入库排名表"
CATEGORY = "supply"

SQL_TEMPLATE = """
SELECT
    ROW_NUMBER() OVER (ORDER BY SUM(it.cost_fen) DESC) AS ranking,
    i.name AS ingredient_name,
    i.category AS ingredient_category,
    i.unit,
    COUNT(DISTINCT it.store_id) AS store_count,
    SUM(it.qty) AS total_qty,
    SUM(it.cost_fen) AS total_cost_fen,
    CASE WHEN SUM(it.qty) > 0
         THEN ROUND(SUM(it.cost_fen)::NUMERIC / SUM(it.qty), 0)
         ELSE 0
    END AS avg_unit_price_fen,
    CASE WHEN SUM(SUM(it.cost_fen)) OVER () > 0
         THEN ROUND(SUM(it.cost_fen)::NUMERIC / SUM(SUM(it.cost_fen)) OVER () * 100, 2)
         ELSE 0
    END AS cost_share_pct
FROM inventory_transactions it
LEFT JOIN ingredients i ON it.ingredient_id = i.id AND i.tenant_id = it.tenant_id
WHERE it.tenant_id = :tenant_id
  AND it.is_deleted = FALSE
  AND it.tx_type = 'purchase'
  AND it.tx_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR it.store_id = :store_id::UUID)
GROUP BY i.name, i.category, i.unit
ORDER BY total_cost_fen DESC
"""

DIMENSIONS = ["ranking", "ingredient_name", "ingredient_category", "unit"]
METRICS = ["store_count", "total_qty", "total_cost_fen", "avg_unit_price_fen", "cost_share_pct"]
FILTERS = ["start_date", "end_date", "store_id"]
