"""P1 报表: 桌数统计表

按桌台类型统计开桌数/翻台率/平均用餐时长。
使用 CTE 分别查询桌台配置和使用情况再关联。
"""

REPORT_ID = "table_stats"
REPORT_NAME = "桌数统计表"
CATEGORY = "operation"

SQL_TEMPLATE = """
WITH table_config AS (
    SELECT
        t.id AS table_id,
        t.table_type,
        t.seats
    FROM tables t
    WHERE t.tenant_id = :tenant_id
      AND t.is_deleted = FALSE
      AND t.is_active = TRUE
      AND (:store_id IS NULL OR t.store_id = :store_id::UUID)
),
table_usage AS (
    SELECT
        o.table_id,
        COUNT(o.id) AS session_count,
        AVG(EXTRACT(EPOCH FROM (o.updated_at - o.created_at)) / 60) AS avg_duration_minutes
    FROM orders o
    WHERE o.tenant_id = :tenant_id
      AND o.is_deleted = FALSE
      AND o.table_id IS NOT NULL
      AND o.status IN ('paid', 'pending_payment')
      AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
    GROUP BY o.table_id
)
SELECT
    COALESCE(tc.table_type, 'standard') AS table_type,
    COUNT(DISTINCT tc.table_id) AS total_tables,
    COALESCE(SUM(tu.session_count), 0) AS total_sessions,
    ROUND(
        COALESCE(SUM(tu.session_count), 0)::numeric
        / NULLIF(COUNT(DISTINCT tc.table_id) * :period_days, 0),
        2
    ) AS turnover_rate,
    ROUND(AVG(tu.avg_duration_minutes)::numeric, 1) AS avg_duration_minutes
FROM table_config tc
LEFT JOIN table_usage tu ON tu.table_id = tc.table_id
GROUP BY COALESCE(tc.table_type, 'standard')
ORDER BY total_sessions DESC
"""

DIMENSIONS = ["table_type"]
METRICS = ["total_tables", "total_sessions", "turnover_rate", "avg_duration_minutes"]
FILTERS = ["start_date", "end_date", "store_id", "period_days"]
