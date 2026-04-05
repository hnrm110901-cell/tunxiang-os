"""P0 报表: 开钱箱统计

按门店按收银员统计每日开钱箱次数及时间分布。
关联 cash_drawer_events 表或 payment_records(method='cash')。
用于现金管理稽核，识别异常高频开箱操作。
"""

REPORT_ID = "cash_drawer_log"
REPORT_NAME = "开钱箱统计"
CATEGORY = "audit"

SQL_TEMPLATE = """
WITH drawer_events AS (
    SELECT
        p.store_id,
        p.operator_id,
        p.created_at,
        COALESCE(DATE(p.biz_date), DATE(p.created_at)) AS biz_date
    FROM payment_records p
    WHERE p.tenant_id = :tenant_id
      AND p.is_deleted = FALSE
      AND p.payment_method = 'cash'
      AND COALESCE(DATE(p.biz_date), DATE(p.created_at)) BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR p.store_id = :store_id::UUID)
)
SELECT
    s.store_name,
    s.store_code,
    de.biz_date,
    e.employee_name AS cashier_name,
    COUNT(*) AS open_count,
    MIN(de.created_at) AS first_open_at,
    MAX(de.created_at) AS last_open_at,
    -- 按时段分布
    COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM de.created_at) BETWEEN 10 AND 13) AS lunch_count,
    COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM de.created_at) BETWEEN 17 AND 21) AS dinner_count,
    COUNT(*) FILTER (
        WHERE EXTRACT(HOUR FROM de.created_at) < 10
           OR EXTRACT(HOUR FROM de.created_at) > 21
    ) AS off_peak_count
FROM drawer_events de
JOIN stores s ON de.store_id = s.id AND s.tenant_id = :tenant_id
LEFT JOIN employees e ON de.operator_id = e.id AND e.tenant_id = :tenant_id
GROUP BY s.store_name, s.store_code, de.biz_date, e.employee_name
ORDER BY de.biz_date DESC, open_count DESC
"""

DIMENSIONS = ["store_name", "store_code", "biz_date", "cashier_name"]
METRICS = ["open_count", "first_open_at", "last_open_at", "lunch_count", "dinner_count", "off_peak_count"]
FILTERS = ["start_date", "end_date", "store_id"]
