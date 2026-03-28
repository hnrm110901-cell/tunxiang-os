"""供应链报表: 门店调拨统计表

按门店统计调出/调入数量和金额。
"""

REPORT_ID = "scm_transfer_stats"
REPORT_NAME = "门店调拨统计表"
CATEGORY = "supply"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    it.tx_type,
    CASE it.tx_type
        WHEN 'transfer_out' THEN '调出'
        WHEN 'transfer_in' THEN '调入'
        ELSE it.tx_type
    END AS direction_label,
    COUNT(*) AS tx_count,
    COUNT(DISTINCT it.ingredient_id) AS ingredient_variety,
    SUM(it.qty) AS total_qty,
    SUM(it.cost_fen) AS total_cost_fen
FROM inventory_transactions it
JOIN stores s ON it.store_id = s.id AND s.tenant_id = it.tenant_id
WHERE it.tenant_id = :tenant_id
  AND it.is_deleted = FALSE
  AND it.tx_type IN ('transfer_out', 'transfer_in')
  AND it.tx_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR it.store_id = :store_id::UUID)
GROUP BY s.store_name, it.tx_type
ORDER BY s.store_name, it.tx_type
"""

DIMENSIONS = ["store_name", "tx_type", "direction_label"]
METRICS = ["tx_count", "ingredient_variety", "total_qty", "total_cost_fen"]
FILTERS = ["start_date", "end_date", "store_id"]
