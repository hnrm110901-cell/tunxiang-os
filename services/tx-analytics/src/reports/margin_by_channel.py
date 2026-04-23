"""P2 毛利报表: 销售渠道毛利一览表

按销售渠道（POS堂食/美团/饿了么/抖音/小程序等）分组对比毛利率。
关联 orders + order_items（BOM 成本 food_cost_fen）。
"""

REPORT_ID = "margin_by_channel"
REPORT_NAME = "销售渠道毛利一览表"
CATEGORY = "margin"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    COALESCE(o.sales_channel_id, 'pos_dine_in') AS channel_id,
    COUNT(DISTINCT o.id) AS order_count,
    SUM(o.final_amount_fen) AS revenue_fen,
    SUM(COALESCE(o.discount_amount_fen, 0)) AS discount_fen,
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
    END AS avg_ticket_fen,
    CASE WHEN SUM(SUM(o.final_amount_fen)) OVER () > 0
         THEN ROUND(SUM(o.final_amount_fen)::NUMERIC
                     / SUM(SUM(o.final_amount_fen)) OVER () * 100, 2)
         ELSE 0
    END AS revenue_share_pct
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
GROUP BY s.store_name, COALESCE(o.sales_channel_id, 'pos_dine_in')
ORDER BY revenue_fen DESC
"""

DIMENSIONS = ["store_name", "channel_id"]
METRICS = [
    "order_count",
    "revenue_fen",
    "discount_fen",
    "cost_fen",
    "margin_fen",
    "margin_rate",
    "avg_ticket_fen",
    "revenue_share_pct",
]
FILTERS = ["start_date", "end_date", "store_id"]
