"""P1 报表: 菜品超时汇总表

出餐超时按菜品/档口统计(超时次数/平均超时分钟)。
超时标准: 菜品设定的 max_cook_minutes 或门店默认上限(default_max_minutes)。
"""

REPORT_ID = "dish_timeout"
REPORT_NAME = "菜品超时汇总表"
CATEGORY = "quality"

SQL_TEMPLATE = """
SELECT
    oi.dish_id,
    d.dish_name,
    COALESCE(d.department, 'unknown') AS department,
    COUNT(oi.id) AS timeout_count,
    SUM(oi.quantity) AS timeout_qty,
    ROUND(
        AVG(
            EXTRACT(EPOCH FROM (oi.served_at - oi.created_at)) / 60
            - COALESCE(d.max_cook_minutes, :default_max_minutes)
        )::numeric,
        1
    ) AS avg_overtime_minutes,
    ROUND(
        MAX(EXTRACT(EPOCH FROM (oi.served_at - oi.created_at)) / 60)::numeric,
        1
    ) AS max_cook_minutes_actual,
    ROUND(
        COUNT(oi.id)::numeric * 100.0
        / NULLIF(SUM(COUNT(oi.id)) OVER (), 0),
        2
    ) AS timeout_pct
FROM order_items oi
JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND oi.is_deleted = FALSE
  AND o.status = 'paid'
  AND oi.served_at IS NOT NULL
  AND EXTRACT(EPOCH FROM (oi.served_at - oi.created_at)) / 60
      > COALESCE(d.max_cook_minutes, :default_max_minutes)
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY oi.dish_id, d.dish_name, COALESCE(d.department, 'unknown')
ORDER BY timeout_count DESC
"""

DIMENSIONS = ["dish_id", "dish_name", "department"]
METRICS = [
    "timeout_count", "timeout_qty", "avg_overtime_minutes",
    "max_cook_minutes_actual", "timeout_pct",
]
FILTERS = ["start_date", "end_date", "store_id", "default_max_minutes"]
