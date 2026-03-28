"""供应链报表: 商品采购统计表

按商品/供应商汇总采购数量和金额，支持按日期范围和门店筛选。
"""

REPORT_ID = "scm_purchase_stats"
REPORT_NAME = "商品采购统计表"
CATEGORY = "supply"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    i.name AS ingredient_name,
    i.category AS ingredient_category,
    i.unit,
    it.supplier_name,
    COUNT(*) AS purchase_count,
    SUM(it.qty) AS total_qty,
    SUM(it.cost_fen) AS total_cost_fen,
    CASE WHEN SUM(it.qty) > 0
         THEN ROUND(SUM(it.cost_fen)::NUMERIC / SUM(it.qty), 0)
         ELSE 0
    END AS avg_unit_price_fen
FROM inventory_transactions it
JOIN stores s ON it.store_id = s.id AND s.tenant_id = it.tenant_id
LEFT JOIN ingredients i ON it.ingredient_id = i.id AND i.tenant_id = it.tenant_id
WHERE it.tenant_id = :tenant_id
  AND it.is_deleted = FALSE
  AND it.tx_type = 'purchase'
  AND it.tx_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR it.store_id = :store_id::UUID)
GROUP BY s.store_name, i.name, i.category, i.unit, it.supplier_name
ORDER BY total_cost_fen DESC
"""

DIMENSIONS = ["store_name", "ingredient_name", "ingredient_category", "unit", "supplier_name"]
METRICS = ["purchase_count", "total_qty", "total_cost_fen", "avg_unit_price_fen"]
FILTERS = ["start_date", "end_date", "store_id"]
