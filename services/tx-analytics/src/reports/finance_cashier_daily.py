"""中台财务报表: 收银日报表

按收银员按班次汇总订单数、金额、差异。
用于每日收银对账和绩效评估。
"""

REPORT_ID = "finance_cashier_daily"
REPORT_NAME = "收银日报表"
CATEGORY = "finance"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
    e.name AS cashier_name,
    e.employee_no AS cashier_no,
    COALESCE(o.shift, 'all_day') AS shift,
    COUNT(*) AS order_count,
    SUM(o.total_amount_fen) AS total_amount_fen,
    SUM(COALESCE(o.discount_amount_fen, 0)) AS discount_fen,
    SUM(COALESCE(o.final_amount_fen,
        o.total_amount_fen - COALESCE(o.discount_amount_fen, 0))) AS actual_fen,
    SUM(COALESCE(o.refund_amount_fen, 0)) AS refund_fen,
    COUNT(*) FILTER (WHERE o.status = 'cancelled') AS cancel_count,
    COUNT(*) FILTER (WHERE o.status = 'refunded') AS refund_count,
    CASE WHEN COUNT(*) > 0
         THEN SUM(COALESCE(o.final_amount_fen, o.total_amount_fen)) / COUNT(*)
         ELSE 0
    END AS avg_ticket_fen
FROM orders o
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
LEFT JOIN employees e ON o.cashier_id = e.id AND e.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY s.store_name,
         COALESCE(o.biz_date, DATE(o.created_at)),
         e.name, e.employee_no,
         COALESCE(o.shift, 'all_day')
ORDER BY biz_date DESC, cashier_name, shift
"""

DIMENSIONS = ["store_name", "biz_date", "cashier_name", "cashier_no", "shift"]
METRICS = [
    "order_count",
    "total_amount_fen",
    "discount_fen",
    "actual_fen",
    "refund_fen",
    "cancel_count",
    "refund_count",
    "avg_ticket_fen",
]
FILTERS = ["start_date", "end_date", "store_id"]
