"""P0 报表: 外卖单统计

按门店按外卖平台统计外卖订单量、营收、平台佣金、净收入。
关联 delivery_orders + stores。
金额单位: 分(fen), int。
"""

REPORT_ID = "delivery_order_stats"
REPORT_NAME = "外卖单统计"
CATEGORY = "revenue"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    s.store_code,
    COALESCE(d.biz_date, DATE(d.created_at)) AS biz_date,
    d.platform,
    COUNT(*) AS order_count,
    COUNT(*) FILTER (WHERE d.status = 'completed') AS completed_count,
    COUNT(*) FILTER (WHERE d.status = 'cancelled') AS cancelled_count,
    COUNT(*) FILTER (WHERE d.status = 'refunded') AS refunded_count,
    SUM(COALESCE(d.order_amount_fen, 0)) AS revenue_fen,
    SUM(COALESCE(d.commission_fen, 0)) AS commission_fen,
    SUM(COALESCE(d.delivery_fee_fen, 0)) AS delivery_fee_fen,
    SUM(COALESCE(d.order_amount_fen, 0))
        - SUM(COALESCE(d.commission_fen, 0))
        - SUM(COALESCE(d.delivery_fee_fen, 0)) AS net_fen,
    -- 平均客单价
    CASE WHEN COUNT(*) FILTER (WHERE d.status = 'completed') > 0
         THEN SUM(COALESCE(d.order_amount_fen, 0))
              / COUNT(*) FILTER (WHERE d.status = 'completed')
         ELSE 0
    END AS avg_ticket_fen,
    -- 佣金率
    CASE WHEN SUM(COALESCE(d.order_amount_fen, 0)) > 0
         THEN ROUND(
             SUM(COALESCE(d.commission_fen, 0))::NUMERIC
             / SUM(COALESCE(d.order_amount_fen, 0)) * 100, 2
         )
         ELSE 0
    END AS commission_rate_pct
FROM delivery_orders d
JOIN stores s ON d.store_id = s.id AND s.tenant_id = d.tenant_id
WHERE d.tenant_id = :tenant_id
  AND d.is_deleted = FALSE
  AND COALESCE(d.biz_date, DATE(d.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR d.store_id = :store_id::UUID)
GROUP BY s.store_name, s.store_code, COALESCE(d.biz_date, DATE(d.created_at)), d.platform
ORDER BY biz_date DESC, revenue_fen DESC
"""

DIMENSIONS = ["store_name", "store_code", "biz_date", "platform"]
METRICS = [
    "order_count", "completed_count", "cancelled_count", "refunded_count",
    "revenue_fen", "commission_fen", "delivery_fee_fen", "net_fen",
    "avg_ticket_fen", "commission_rate_pct",
]
FILTERS = ["start_date", "end_date", "store_id"]
