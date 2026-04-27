"""P0 报表: 门店实时营业统计表

当日 orders 实时汇总，建议每15分钟刷新。包含实时营收、订单数、客单价、
按小时分布，用于门店经理实时监控。
"""

REPORT_ID = "realtime_stats"
REPORT_NAME = "门店实时营业统计表"
CATEGORY = "realtime"

# 刷新间隔(秒)
REFRESH_INTERVAL_SECONDS = 900  # 15分钟

SQL_TEMPLATE = """
SELECT
    s.store_name,
    COUNT(*) AS order_count,
    COUNT(*) FILTER (WHERE o.status = 'paid') AS paid_count,
    COUNT(*) FILTER (WHERE o.status = 'cancelled') AS cancelled_count,
    COUNT(*) FILTER (WHERE o.status = 'refunded') AS refunded_count,
    SUM(CASE WHEN o.status = 'paid' THEN o.total_amount_fen ELSE 0 END) AS total_amount_fen,
    SUM(CASE WHEN o.status = 'paid' THEN COALESCE(o.discount_amount_fen, 0) ELSE 0 END) AS discount_fen,
    SUM(CASE WHEN o.status = 'paid'
             THEN COALESCE(o.final_amount_fen, o.total_amount_fen - COALESCE(o.discount_amount_fen, 0))
             ELSE 0 END) AS actual_fen,
    CASE WHEN COUNT(*) FILTER (WHERE o.status = 'paid') > 0
         THEN SUM(CASE WHEN o.status = 'paid'
                       THEN COALESCE(o.final_amount_fen, o.total_amount_fen)
                       ELSE 0 END)
              / COUNT(*) FILTER (WHERE o.status = 'paid')
         ELSE 0
    END AS avg_ticket_fen,
    EXTRACT(HOUR FROM MAX(o.created_at)) AS latest_order_hour,
    MAX(o.created_at) AS latest_order_at
FROM orders o
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND COALESCE(o.biz_date, DATE(o.created_at)) = CURRENT_DATE
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY s.store_name
ORDER BY actual_fen DESC
"""

# 按小时分布的辅助查询
SQL_HOURLY = """
SELECT
    s.store_name,
    EXTRACT(HOUR FROM o.created_at)::INT AS hour,
    COUNT(*) AS order_count,
    SUM(CASE WHEN o.status = 'paid' THEN o.total_amount_fen ELSE 0 END) AS revenue_fen
FROM orders o
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND COALESCE(o.biz_date, DATE(o.created_at)) = CURRENT_DATE
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY s.store_name, EXTRACT(HOUR FROM o.created_at)::INT
ORDER BY s.store_name, hour
"""

DIMENSIONS = ["store_name"]
METRICS = [
    "order_count",
    "paid_count",
    "cancelled_count",
    "refunded_count",
    "total_amount_fen",
    "discount_fen",
    "actual_fen",
    "avg_ticket_fen",
    "latest_order_hour",
    "latest_order_at",
]
FILTERS = ["store_id"]
