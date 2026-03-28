"""P1 报表: 赠菜分析表

赠菜按审批人/原因汇总(金额/频次/占营收比例)。
通过子查询计算赠菜金额占同期总营收的比例。
"""

REPORT_ID = "gift_dish_analysis"
REPORT_NAME = "赠菜分析表"
CATEGORY = "quality"

SQL_TEMPLATE = """
SELECT
    COALESCE(oi.gift_reason, 'unknown') AS gift_reason,
    COALESCE(oi.approved_by, 'unknown') AS approved_by,
    e.employee_name AS approver_name,
    COUNT(oi.id) AS gift_count,
    SUM(oi.quantity) AS gift_qty,
    COALESCE(SUM(oi.subtotal_fen), 0) AS gift_amount_fen,
    ROUND(
        SUM(oi.subtotal_fen)::numeric * 100.0
        / NULLIF((
            SELECT SUM(oi2.subtotal_fen)
            FROM order_items oi2
            JOIN orders o2 ON o2.id = oi2.order_id AND o2.tenant_id = oi2.tenant_id
            WHERE o2.tenant_id = :tenant_id
              AND o2.is_deleted = FALSE
              AND oi2.is_deleted = FALSE
              AND o2.status = 'paid'
              AND COALESCE(o2.biz_date, DATE(o2.created_at)) BETWEEN :start_date AND :end_date
              AND (:store_id IS NULL OR o2.store_id = :store_id::UUID)
        ), 0),
        2
    ) AS gift_revenue_pct
FROM order_items oi
JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
LEFT JOIN employees e ON e.id::text = oi.approved_by
                      AND e.tenant_id = oi.tenant_id
                      AND e.is_deleted = FALSE
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND oi.is_deleted = FALSE
  AND oi.is_gift = TRUE
  AND o.status = 'paid'
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY COALESCE(oi.gift_reason, 'unknown'),
         COALESCE(oi.approved_by, 'unknown'),
         e.employee_name
ORDER BY gift_amount_fen DESC
"""

DIMENSIONS = ["gift_reason", "approved_by", "approver_name"]
METRICS = ["gift_count", "gift_qty", "gift_amount_fen", "gift_revenue_pct"]
FILTERS = ["start_date", "end_date", "store_id"]
