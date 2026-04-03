"""P1 报表: 区域人数桌数汇总分析表

按桌台区域(大厅A/大厅B/包厢)统计人数和桌数，含桌均人数、人均消费。
"""

REPORT_ID = "area_guest_table"
REPORT_NAME = "区域人数桌数汇总分析表"
CATEGORY = "operation"

SQL_TEMPLATE = """
SELECT
    COALESCE(t.area, 'default') AS area,
    COUNT(DISTINCT o.table_id) AS used_table_count,
    COUNT(o.id) AS order_count,
    COALESCE(SUM(o.guest_count), 0) AS total_guest_count,
    ROUND(AVG(o.guest_count)::numeric, 1) AS avg_guest_per_table,
    COALESCE(SUM(o.total_amount_fen), 0) AS total_amount_fen,
    CASE WHEN SUM(o.guest_count) > 0
         THEN SUM(o.total_amount_fen) / SUM(o.guest_count)
         ELSE 0
    END AS per_capita_fen
FROM orders o
JOIN tables t ON t.id = o.table_id
             AND t.tenant_id = o.tenant_id
             AND t.is_deleted = FALSE
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND o.status IN ('paid', 'pending_payment')
  AND o.table_id IS NOT NULL
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY COALESCE(t.area, 'default')
ORDER BY total_guest_count DESC
"""

DIMENSIONS = ["area"]
METRICS = [
    "used_table_count", "order_count", "total_guest_count",
    "avg_guest_per_table", "total_amount_fen", "per_capita_fen",
]
FILTERS = ["start_date", "end_date", "store_id"]
