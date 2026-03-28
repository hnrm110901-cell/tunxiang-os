"""P2 毛利报表: 点单毛利率合格统计表

按月统计每笔点单的毛利率是否达标(>=55%)，输出合格/不合格分布。
关联 orders + order_items（BOM 成本 food_cost_fen）。
"""

REPORT_ID = "margin_per_order"
REPORT_NAME = "点单毛利率合格统计表"
CATEGORY = "margin"

SQL_TEMPLATE = """
WITH order_margin AS (
    SELECT
        o.id AS order_id,
        o.order_no,
        s.store_name,
        e.emp_name AS orderer_name,
        COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
        o.final_amount_fen AS revenue_fen,
        COALESCE(SUM(oi.food_cost_fen * oi.quantity), 0) AS cost_fen,
        CASE WHEN o.final_amount_fen > 0
             THEN ROUND((o.final_amount_fen - COALESCE(SUM(oi.food_cost_fen * oi.quantity), 0))::NUMERIC
                         / o.final_amount_fen * 100, 2)
             ELSE 0
        END AS margin_rate
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.id AND oi.tenant_id = o.tenant_id
    JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
    LEFT JOIN employees e ON o.waiter_id = e.id::TEXT AND e.tenant_id = o.tenant_id
    WHERE o.tenant_id = :tenant_id
      AND o.is_deleted = FALSE
      AND oi.is_deleted = FALSE
      AND o.status IN ('completed', 'paid')
      AND oi.food_cost_fen IS NOT NULL
      AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
    GROUP BY o.id, o.order_no, s.store_name, e.emp_name, o.final_amount_fen, o.created_at, o.biz_date
)
SELECT
    store_name,
    COUNT(*) AS total_orders,
    COUNT(*) FILTER (WHERE margin_rate >= 55) AS pass_count,
    COUNT(*) FILTER (WHERE margin_rate < 55) AS fail_count,
    CASE WHEN COUNT(*) > 0
         THEN ROUND(COUNT(*) FILTER (WHERE margin_rate >= 55)::NUMERIC / COUNT(*) * 100, 2)
         ELSE 0
    END AS pass_rate,
    ROUND(AVG(margin_rate), 2) AS avg_margin_rate,
    ROUND(AVG(margin_rate) FILTER (WHERE margin_rate < 55), 2) AS avg_fail_margin_rate,
    MIN(margin_rate) AS min_margin_rate,
    MAX(margin_rate) AS max_margin_rate
FROM order_margin
GROUP BY store_name
ORDER BY pass_rate ASC
"""

DIMENSIONS = ["store_name"]
METRICS = [
    "total_orders", "pass_count", "fail_count", "pass_rate",
    "avg_margin_rate", "avg_fail_margin_rate",
    "min_margin_rate", "max_margin_rate",
]
FILTERS = ["start_date", "end_date", "store_id"]
