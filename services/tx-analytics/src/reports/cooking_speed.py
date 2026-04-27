"""P2 稽核报表: 上菜速度表

按门店/档口/日期统计上菜速度（从下单到出餐），识别超时单。
关联 orders(order_time/served_at/serve_duration_min) + order_items(kds_station) + stores。
"""

REPORT_ID = "cooking_speed"
REPORT_NAME = "上菜速度表"
CATEGORY = "audit"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
    COALESCE(oi.kds_station, '未分档口') AS kds_station,
    COUNT(DISTINCT o.id) AS order_count,
    -- 出餐时长统计（分钟）
    ROUND(AVG(o.serve_duration_min) FILTER (WHERE o.serve_duration_min IS NOT NULL), 1) AS avg_serve_min,
    MIN(o.serve_duration_min) FILTER (WHERE o.serve_duration_min IS NOT NULL) AS min_serve_min,
    MAX(o.serve_duration_min) FILTER (WHERE o.serve_duration_min IS NOT NULL) AS max_serve_min,
    -- 按时间段分布
    COUNT(DISTINCT o.id) FILTER (WHERE o.serve_duration_min <= 10) AS within_10min,
    COUNT(DISTINCT o.id) FILTER (WHERE o.serve_duration_min > 10 AND o.serve_duration_min <= 20) AS within_20min,
    COUNT(DISTINCT o.id) FILTER (WHERE o.serve_duration_min > 20 AND o.serve_duration_min <= 30) AS within_30min,
    COUNT(DISTINCT o.id) FILTER (WHERE o.serve_duration_min > 30) AS over_30min,
    -- 超时率（超过门店设定上限）
    CASE WHEN COUNT(DISTINCT o.id) > 0
         THEN ROUND(
             COUNT(DISTINCT o.id) FILTER (
                 WHERE o.serve_duration_min > COALESCE(s.serve_time_limit_min, 30)
             )::NUMERIC / COUNT(DISTINCT o.id) * 100, 2)
         ELSE 0
    END AS timeout_rate_pct,
    -- 超时单数
    COUNT(DISTINCT o.id) FILTER (
        WHERE o.serve_duration_min > COALESCE(s.serve_time_limit_min, 30)
    ) AS timeout_count,
    COALESCE(s.serve_time_limit_min, 30) AS time_limit_min
FROM orders o
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
LEFT JOIN order_items oi ON oi.order_id = o.id
    AND oi.tenant_id = o.tenant_id
    AND oi.is_deleted = FALSE
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND o.status IN ('completed', 'paid')
  AND o.serve_duration_min IS NOT NULL
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY s.store_name, COALESCE(o.biz_date, DATE(o.created_at)),
         COALESCE(oi.kds_station, '未分档口'), s.serve_time_limit_min
ORDER BY biz_date DESC, avg_serve_min DESC
"""

DIMENSIONS = ["store_name", "biz_date", "kds_station"]
METRICS = [
    "order_count",
    "avg_serve_min",
    "min_serve_min",
    "max_serve_min",
    "within_10min",
    "within_20min",
    "within_30min",
    "over_30min",
    "timeout_rate_pct",
    "timeout_count",
    "time_limit_min",
]
FILTERS = ["start_date", "end_date", "store_id"]
