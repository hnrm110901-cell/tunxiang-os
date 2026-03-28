"""供应链报表: 报损单/菜品报损汇总

按原料/菜品统计报损数量和金额，分析损耗原因。
"""

REPORT_ID = "scm_waste_report"
REPORT_NAME = "报损单/菜品报损汇总"
CATEGORY = "supply"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    i.name AS ingredient_name,
    i.category AS ingredient_category,
    it.waste_reason,
    COUNT(*) AS waste_count,
    SUM(it.qty) AS total_waste_qty,
    SUM(it.cost_fen) AS total_waste_cost_fen,
    CASE WHEN SUM(SUM(it.cost_fen)) OVER () > 0
         THEN ROUND(SUM(it.cost_fen)::NUMERIC / SUM(SUM(it.cost_fen)) OVER () * 100, 2)
         ELSE 0
    END AS waste_share_pct
FROM inventory_transactions it
JOIN stores s ON it.store_id = s.id AND s.tenant_id = it.tenant_id
LEFT JOIN ingredients i ON it.ingredient_id = i.id AND i.tenant_id = it.tenant_id
WHERE it.tenant_id = :tenant_id
  AND it.is_deleted = FALSE
  AND it.tx_type = 'waste'
  AND it.tx_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR it.store_id = :store_id::UUID)
GROUP BY s.store_name, i.name, i.category, it.waste_reason
ORDER BY total_waste_cost_fen DESC
"""

DIMENSIONS = ["store_name", "ingredient_name", "ingredient_category", "waste_reason"]
METRICS = ["waste_count", "total_waste_qty", "total_waste_cost_fen", "waste_share_pct"]
FILTERS = ["start_date", "end_date", "store_id"]
