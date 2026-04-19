"""P1 报表: 门店异常监控报表

按异常类型(折扣异常/退菜/反结/收银差异)统计，含严重程度分级。
"""

REPORT_ID = "store_anomaly"
REPORT_NAME = "门店异常监控报表"
CATEGORY = "audit"

SQL_TEMPLATE = """
SELECT
    a.type AS anomaly_type,
    a.severity,
    COUNT(a.id) AS anomaly_count,
    COUNT(DISTINCT DATE(a.created_at)) AS affected_days,
    COUNT(DISTINCT a.related_order_id) AS affected_order_count,
    COALESCE(SUM(a.amount_fen), 0) AS total_amount_fen,
    CASE WHEN COUNT(a.id) > 0
         THEN SUM(a.amount_fen) / COUNT(a.id)
         ELSE 0
    END AS avg_amount_fen,
    ROUND(
        COUNT(a.id)::numeric * 100.0
        / NULLIF(SUM(COUNT(a.id)) OVER (), 0),
        2
    ) AS type_pct
FROM alerts a
WHERE a.tenant_id = :tenant_id
  AND a.is_deleted = FALSE
  AND a.type IN ('discount_anomaly', 'return_anomaly', 'void_reopen', 'cashier_variance')
  AND DATE(a.created_at) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR a.store_id = :store_id::UUID)
GROUP BY a.type, a.severity
ORDER BY anomaly_count DESC
"""

DIMENSIONS = ["anomaly_type", "severity"]
METRICS = [
    "anomaly_count",
    "affected_days",
    "affected_order_count",
    "total_amount_fen",
    "avg_amount_fen",
    "type_pct",
]
FILTERS = ["start_date", "end_date", "store_id"]
