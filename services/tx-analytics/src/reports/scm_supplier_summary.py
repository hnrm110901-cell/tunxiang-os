"""供应链报表: 供应商供货汇总表

按供应商汇总供货金额、数量、品种数，评估供应商贡献度。
"""

REPORT_ID = "scm_supplier_summary"
REPORT_NAME = "供应商供货汇总表"
CATEGORY = "supply"

SQL_TEMPLATE = """
SELECT
    it.supplier_name,
    s.store_name,
    COUNT(DISTINCT it.ingredient_id) AS ingredient_variety,
    COUNT(*) AS delivery_count,
    SUM(it.qty) AS total_qty,
    SUM(it.cost_fen) AS total_cost_fen,
    CASE WHEN SUM(SUM(it.cost_fen)) OVER () > 0
         THEN ROUND(SUM(it.cost_fen)::NUMERIC / SUM(SUM(it.cost_fen)) OVER () * 100, 2)
         ELSE 0
    END AS cost_share_pct
FROM inventory_transactions it
JOIN stores s ON it.store_id = s.id AND s.tenant_id = it.tenant_id
WHERE it.tenant_id = :tenant_id
  AND it.is_deleted = FALSE
  AND it.tx_type = 'purchase'
  AND it.tx_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR it.store_id = :store_id::UUID)
GROUP BY it.supplier_name, s.store_name
ORDER BY total_cost_fen DESC
"""

DIMENSIONS = ["supplier_name", "store_name"]
METRICS = ["ingredient_variety", "delivery_count", "total_qty", "total_cost_fen", "cost_share_pct"]
FILTERS = ["start_date", "end_date", "store_id"]
