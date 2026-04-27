"""供应链报表: 菜品BOM成本分析报表

按菜品展示BOM配方成本明细，含售价、成本、毛利率。
"""

REPORT_ID = "scm_bom_cost_analysis"
REPORT_NAME = "菜品BOM成本分析报表"
CATEGORY = "supply"

SQL_TEMPLATE = """
SELECT
    ds.name AS dish_name,
    ds.category AS dish_category,
    bt.version AS bom_version,
    ds.price_fen AS sell_price_fen,
    COALESCE(SUM(bd.standard_qty * COALESCE(lp.latest_price_fen, 0)), 0) AS bom_cost_fen,
    ds.price_fen - COALESCE(SUM(bd.standard_qty * COALESCE(lp.latest_price_fen, 0)), 0) AS margin_fen,
    CASE WHEN ds.price_fen > 0
         THEN ROUND(
             (ds.price_fen - COALESCE(SUM(bd.standard_qty * COALESCE(lp.latest_price_fen, 0)), 0))::NUMERIC
             / ds.price_fen * 100, 2)
         ELSE 0
    END AS margin_rate,
    COUNT(bd.ingredient_id) AS ingredient_count,
    bt.yield_rate
FROM dishes ds
JOIN bom_templates bt ON bt.dish_id = ds.id AND bt.tenant_id = ds.tenant_id AND bt.is_active = TRUE
JOIN bom_details bd ON bd.bom_template_id = bt.id AND bd.tenant_id = ds.tenant_id
LEFT JOIN LATERAL (
    SELECT it.unit_price_fen AS latest_price_fen
    FROM inventory_transactions it
    WHERE it.ingredient_id = bd.ingredient_id
      AND it.tenant_id = ds.tenant_id
      AND it.tx_type = 'purchase'
      AND it.is_deleted = FALSE
    ORDER BY it.tx_date DESC
    LIMIT 1
) lp ON TRUE
WHERE ds.tenant_id = :tenant_id
  AND ds.is_deleted = FALSE
  AND (:store_id IS NULL OR ds.store_id = :store_id::UUID)
GROUP BY ds.name, ds.category, bt.version, ds.price_fen, bt.yield_rate
ORDER BY margin_rate ASC
"""

DIMENSIONS = ["dish_name", "dish_category", "bom_version"]
METRICS = ["sell_price_fen", "bom_cost_fen", "margin_fen", "margin_rate", "ingredient_count", "yield_rate"]
FILTERS = ["store_id"]
