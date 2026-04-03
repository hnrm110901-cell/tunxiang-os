"""P2 毛利报表: 整单毛利率一览表

按日汇总全部订单的整体毛利率（总营收 vs 总BOM成本），展示日维度趋势。
关联 orders + order_items（BOM 成本 food_cost_fen）。
"""

REPORT_ID = "margin_total_order"
REPORT_NAME = "整单毛利率一览表"
CATEGORY = "margin"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
    COUNT(DISTINCT o.id) AS order_count,
    SUM(o.final_amount_fen) AS revenue_fen,
    SUM(COALESCE(oi.food_cost_fen, 0) * oi.quantity) AS cost_fen,
    SUM(o.final_amount_fen) - SUM(COALESCE(oi.food_cost_fen, 0) * oi.quantity) AS margin_fen,
    CASE WHEN SUM(o.final_amount_fen) > 0
         THEN ROUND((SUM(o.final_amount_fen) - SUM(COALESCE(oi.food_cost_fen, 0) * oi.quantity))::NUMERIC
                     / SUM(o.final_amount_fen) * 100, 2)
         ELSE 0
    END AS margin_rate,
    CASE WHEN COUNT(DISTINCT o.id) > 0
         THEN SUM(o.final_amount_fen) / COUNT(DISTINCT o.id)
         ELSE 0
    END AS avg_ticket_fen
FROM orders o
JOIN order_items oi ON oi.order_id = o.id AND oi.tenant_id = o.tenant_id
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND oi.is_deleted = FALSE
  AND o.status IN ('completed', 'paid')
  AND oi.food_cost_fen IS NOT NULL
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY s.store_name, COALESCE(o.biz_date, DATE(o.created_at))
ORDER BY biz_date DESC, margin_rate DESC
"""

DIMENSIONS = ["store_name", "biz_date"]
METRICS = [
    "order_count", "revenue_fen", "cost_fen", "margin_fen",
    "margin_rate", "avg_ticket_fen",
]
FILTERS = ["start_date", "end_date", "store_id"]
