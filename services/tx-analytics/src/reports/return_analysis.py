"""P1 报表: 退菜分析表

退菜按原因(品质/等待超时/缺料/客诉/顾客换菜)汇总，统计涉及菜品数和订单数。
"""

REPORT_ID = "return_analysis"
REPORT_NAME = "退菜分析表"
CATEGORY = "quality"

SQL_TEMPLATE = """
SELECT
    COALESCE(oi.return_reason, 'unknown') AS return_reason,
    COUNT(oi.id) AS return_count,
    SUM(oi.quantity) AS return_qty,
    COALESCE(SUM(oi.subtotal_fen), 0) AS return_amount_fen,
    ROUND(
        COUNT(oi.id)::numeric * 100.0
        / NULLIF(SUM(COUNT(oi.id)) OVER (), 0),
        2
    ) AS reason_pct,
    COUNT(DISTINCT oi.dish_id) AS affected_dish_count,
    COUNT(DISTINCT o.id) AS affected_order_count
FROM order_items oi
JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND oi.is_deleted = FALSE
  AND oi.status = 'returned'
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY COALESCE(oi.return_reason, 'unknown')
ORDER BY return_count DESC
"""

DIMENSIONS = ["return_reason"]
METRICS = [
    "return_count",
    "return_qty",
    "return_amount_fen",
    "reason_pct",
    "affected_dish_count",
    "affected_order_count",
]
FILTERS = ["start_date", "end_date", "store_id"]
