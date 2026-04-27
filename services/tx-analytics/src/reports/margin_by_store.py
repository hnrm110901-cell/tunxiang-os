"""P2 毛利报表: 各门店毛利率一览表

跨门店对比月度毛利率，含排名，供总部管理层使用。
关联 orders + order_items（BOM 成本）+ stores。
"""

REPORT_ID = "margin_by_store"
REPORT_NAME = "各门店毛利率一览表"
CATEGORY = "margin"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    s.store_code,
    s.region,
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
    END AS avg_ticket_fen,
    RANK() OVER (ORDER BY
        CASE WHEN SUM(o.final_amount_fen) > 0
             THEN (SUM(o.final_amount_fen) - SUM(COALESCE(oi.food_cost_fen, 0) * oi.quantity))::NUMERIC
                  / SUM(o.final_amount_fen) * 100
             ELSE 0
        END DESC
    ) AS margin_rank
FROM stores s
LEFT JOIN orders o ON o.store_id = s.id
    AND o.tenant_id = s.tenant_id
    AND o.is_deleted = FALSE
    AND o.status IN ('completed', 'paid')
    AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
LEFT JOIN order_items oi ON oi.order_id = o.id
    AND oi.tenant_id = o.tenant_id
    AND oi.is_deleted = FALSE
    AND oi.food_cost_fen IS NOT NULL
WHERE s.tenant_id = :tenant_id
  AND s.is_deleted = FALSE
  AND s.store_type = 'physical'
  AND (:store_id IS NULL OR s.id = :store_id::UUID)
GROUP BY s.store_name, s.store_code, s.region
ORDER BY margin_rate DESC
"""

DIMENSIONS = ["store_name", "store_code", "region"]
METRICS = [
    "order_count",
    "revenue_fen",
    "cost_fen",
    "margin_fen",
    "margin_rate",
    "avg_ticket_fen",
    "margin_rank",
]
FILTERS = ["start_date", "end_date", "store_id"]
