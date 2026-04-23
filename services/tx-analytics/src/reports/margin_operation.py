"""P2 毛利报表: 营业毛利率一览表

对比理论毛利率（BOM）与实际毛利率（库存消耗），分析成本偏差。
关联 orders + order_items（BOM 成本）+ ingredient_transactions（实际消耗）。
"""

REPORT_ID = "margin_operation"
REPORT_NAME = "营业毛利率一览表"
CATEGORY = "margin"

SQL_TEMPLATE = """
WITH bom_cost AS (
    SELECT
        o.store_id,
        COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
        SUM(o.final_amount_fen) AS revenue_fen,
        SUM(COALESCE(oi.food_cost_fen, 0) * oi.quantity) AS theoretical_cost_fen
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.id AND oi.tenant_id = o.tenant_id
    WHERE o.tenant_id = :tenant_id
      AND o.is_deleted = FALSE
      AND oi.is_deleted = FALSE
      AND o.status IN ('completed', 'paid')
      AND oi.food_cost_fen IS NOT NULL
      AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
    GROUP BY o.store_id, COALESCE(o.biz_date, DATE(o.created_at))
),
actual_cost AS (
    SELECT
        it.store_id,
        DATE(it.transaction_time) AS biz_date,
        COALESCE(SUM(ABS(it.total_cost_fen)), 0) AS actual_cost_fen
    FROM ingredient_transactions it
    WHERE it.tenant_id = :tenant_id
      AND it.is_deleted = FALSE
      AND it.transaction_type = 'usage'
      AND DATE(it.transaction_time) BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR it.store_id = :store_id::UUID)
    GROUP BY it.store_id, DATE(it.transaction_time)
)
SELECT
    s.store_name,
    b.biz_date,
    b.revenue_fen,
    b.theoretical_cost_fen,
    COALESCE(a.actual_cost_fen, b.theoretical_cost_fen) AS actual_cost_fen,
    CASE WHEN b.revenue_fen > 0
         THEN ROUND((b.revenue_fen - b.theoretical_cost_fen)::NUMERIC / b.revenue_fen * 100, 2)
         ELSE 0
    END AS theoretical_margin_rate,
    CASE WHEN b.revenue_fen > 0
         THEN ROUND((b.revenue_fen - COALESCE(a.actual_cost_fen, b.theoretical_cost_fen))::NUMERIC
                     / b.revenue_fen * 100, 2)
         ELSE 0
    END AS actual_margin_rate,
    COALESCE(a.actual_cost_fen, b.theoretical_cost_fen) - b.theoretical_cost_fen AS cost_variance_fen,
    CASE WHEN b.theoretical_cost_fen > 0
         THEN ROUND((COALESCE(a.actual_cost_fen, b.theoretical_cost_fen) - b.theoretical_cost_fen)::NUMERIC
                     / b.theoretical_cost_fen * 100, 2)
         ELSE 0
    END AS cost_variance_rate
FROM bom_cost b
JOIN stores s ON b.store_id = s.id AND s.tenant_id = :tenant_id
LEFT JOIN actual_cost a ON a.store_id = b.store_id AND a.biz_date = b.biz_date
ORDER BY b.biz_date DESC, s.store_name
"""

DIMENSIONS = ["store_name", "biz_date"]
METRICS = [
    "revenue_fen",
    "theoretical_cost_fen",
    "actual_cost_fen",
    "theoretical_margin_rate",
    "actual_margin_rate",
    "cost_variance_fen",
    "cost_variance_rate",
]
FILTERS = ["start_date", "end_date", "store_id"]
