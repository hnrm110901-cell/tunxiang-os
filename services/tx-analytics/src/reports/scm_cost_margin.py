"""供应链报表: 出品部门毛利一览表

按出品部门（如凉菜、热菜、面点）统计收入、成本和毛利率。
"""

REPORT_ID = "scm_cost_margin"
REPORT_NAME = "出品部门毛利一览表"
CATEGORY = "supply"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    d.department_name AS production_dept,
    COUNT(DISTINCT o.id) AS order_count,
    SUM(oi.quantity) AS dish_count,
    SUM(oi.quantity * oi.unit_price_fen) AS revenue_fen,
    SUM(COALESCE(oi.food_cost_fen, 0) * oi.quantity) AS cost_fen,
    SUM(oi.quantity * oi.unit_price_fen)
        - SUM(COALESCE(oi.food_cost_fen, 0) * oi.quantity) AS margin_fen,
    CASE WHEN SUM(oi.quantity * oi.unit_price_fen) > 0
         THEN ROUND(
             (SUM(oi.quantity * oi.unit_price_fen) - SUM(COALESCE(oi.food_cost_fen, 0) * oi.quantity))::NUMERIC
             / SUM(oi.quantity * oi.unit_price_fen) * 100, 2)
         ELSE 0
    END AS margin_rate
FROM orders o
JOIN order_items oi ON oi.order_id = o.id AND oi.tenant_id = o.tenant_id
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
LEFT JOIN dishes ds ON oi.dish_id = ds.id AND ds.tenant_id = o.tenant_id
LEFT JOIN departments d ON ds.department_id = d.id AND d.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND oi.is_deleted = FALSE
  AND o.status IN ('completed', 'paid')
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY s.store_name, d.department_name
ORDER BY revenue_fen DESC
"""

DIMENSIONS = ["store_name", "production_dept"]
METRICS = ["order_count", "dish_count", "revenue_fen", "cost_fen", "margin_fen", "margin_rate"]
FILTERS = ["start_date", "end_date", "store_id"]
