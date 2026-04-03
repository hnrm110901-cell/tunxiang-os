"""P0 报表: 营业收入汇总报表(按天)

指定日期范围，逐日营收趋势，用于同环比分析。
"""

REPORT_ID = "daily_revenue_by_day"
REPORT_NAME = "营业收入汇总报表(按天)"
CATEGORY = "revenue"

SQL_TEMPLATE = """
SELECT
    COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
    COUNT(*) AS order_count,
    SUM(o.total_amount_fen) AS total_amount_fen,
    SUM(COALESCE(o.discount_amount_fen, 0)) AS discount_fen,
    SUM(COALESCE(o.final_amount_fen, o.total_amount_fen - COALESCE(o.discount_amount_fen, 0))) AS actual_fen,
    CASE WHEN COUNT(*) > 0
         THEN SUM(COALESCE(o.final_amount_fen, o.total_amount_fen)) / COUNT(*)
         ELSE 0
    END AS avg_ticket_fen,
    COUNT(DISTINCT o.store_id) AS store_count
FROM orders o
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND o.status = 'paid'
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
ORDER BY biz_date ASC
"""

DIMENSIONS = ["biz_date"]
METRICS = ["order_count", "total_amount_fen", "discount_fen", "actual_fen", "avg_ticket_fen", "store_count"]
FILTERS = ["start_date", "end_date", "store_id"]
