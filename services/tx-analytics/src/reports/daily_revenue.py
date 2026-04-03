"""P0 报表: 营业收入汇总表

按门店按日期汇总订单营收，包括总金额、折扣、实收、订单数、客单价。
"""

REPORT_ID = "daily_revenue"
REPORT_NAME = "营业收入汇总表"
CATEGORY = "revenue"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
    COUNT(*) AS order_count,
    SUM(o.total_amount_fen) AS total_amount_fen,
    SUM(COALESCE(o.discount_amount_fen, 0)) AS discount_fen,
    SUM(COALESCE(o.final_amount_fen, o.total_amount_fen - COALESCE(o.discount_amount_fen, 0))) AS actual_fen,
    CASE WHEN COUNT(*) > 0
         THEN SUM(COALESCE(o.final_amount_fen, o.total_amount_fen)) / COUNT(*)
         ELSE 0
    END AS avg_ticket_fen
FROM orders o
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND o.status = 'paid'
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY s.store_name, COALESCE(o.biz_date, DATE(o.created_at))
ORDER BY biz_date DESC, actual_fen DESC
"""

DIMENSIONS = ["store_name", "biz_date"]
METRICS = ["order_count", "total_amount_fen", "discount_fen", "actual_fen", "avg_ticket_fen"]
FILTERS = ["start_date", "end_date", "store_id"]
