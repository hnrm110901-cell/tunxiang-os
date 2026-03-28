"""P2 稽核报表: 对账日志表

按日记录对账操作日志，包含对账时间、操作人、对账结果、差异金额。
关联 orders + ingredient_transactions + employees。
"""

REPORT_ID = "audit_log"
REPORT_NAME = "对账日志表"
CATEGORY = "audit"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
    o.order_no,
    o.status,
    o.total_amount_fen,
    COALESCE(o.discount_amount_fen, 0) AS discount_fen,
    COALESCE(o.final_amount_fen, o.total_amount_fen) AS actual_fen,
    -- 订单明细数
    (SELECT COUNT(*) FROM order_items oi
     WHERE oi.order_id = o.id AND oi.tenant_id = o.tenant_id AND oi.is_deleted = FALSE
    ) AS item_count,
    -- 退菜数
    (SELECT COUNT(*) FROM order_items oi
     WHERE oi.order_id = o.id AND oi.tenant_id = o.tenant_id
       AND oi.is_deleted = FALSE AND oi.return_flag = TRUE
    ) AS return_count,
    -- 折扣类型
    o.discount_type,
    -- 异常标记
    o.abnormal_flag,
    o.abnormal_type,
    o.margin_alert_flag,
    -- 手工调整标记
    CASE WHEN o.order_metadata->>'manual_adjust' = 'true' THEN TRUE ELSE FALSE END AS manual_adjust,
    o.created_at,
    o.completed_at
FROM orders o
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
  AND (
      o.abnormal_flag = TRUE
      OR o.margin_alert_flag = TRUE
      OR o.order_metadata->>'manual_adjust' = 'true'
      OR o.discount_type = 'manual'
      OR o.status = 'cancelled'
  )
ORDER BY o.created_at DESC
"""

DIMENSIONS = [
    "store_name", "biz_date", "order_no", "status",
    "discount_type", "abnormal_type",
]
METRICS = [
    "total_amount_fen", "discount_fen", "actual_fen",
    "item_count", "return_count",
    "abnormal_flag", "margin_alert_flag", "manual_adjust",
]
FILTERS = ["start_date", "end_date", "store_id"]
