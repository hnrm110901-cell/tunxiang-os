"""P2 稽核报表: 对账总表

按门店按日汇总对账数据：应收/实收/差异/异常单/退款，供财务核对。
关联 orders + stores。
"""

REPORT_ID = "audit_summary"
REPORT_NAME = "对账总表"
CATEGORY = "audit"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    s.store_code,
    COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
    -- 订单统计
    COUNT(*) AS total_orders,
    COUNT(*) FILTER (WHERE o.status IN ('completed', 'paid')) AS paid_orders,
    COUNT(*) FILTER (WHERE o.status = 'cancelled') AS cancelled_orders,
    -- 金额汇总
    SUM(o.total_amount_fen) AS total_amount_fen,
    COALESCE(SUM(o.discount_amount_fen), 0) AS discount_fen,
    SUM(COALESCE(o.final_amount_fen, o.total_amount_fen)) AS actual_fen,
    -- 应收 vs 实收差异
    SUM(o.total_amount_fen) - SUM(COALESCE(o.final_amount_fen, o.total_amount_fen)) AS variance_fen,
    -- 异常订单
    COUNT(*) FILTER (WHERE o.abnormal_flag = TRUE) AS anomaly_count,
    COUNT(*) FILTER (WHERE o.margin_alert_flag = TRUE) AS margin_alert_count,
    COUNT(*) FILTER (WHERE o.discount_type = 'manual') AS manual_discount_count,
    -- 退菜关联单数
    COUNT(DISTINCT o.id) FILTER (WHERE EXISTS (
        SELECT 1 FROM order_items oi
        WHERE oi.order_id = o.id AND oi.return_flag = TRUE AND oi.is_deleted = FALSE
    )) AS return_order_count,
    -- 折扣率
    CASE WHEN SUM(o.total_amount_fen) > 0
         THEN ROUND(COALESCE(SUM(o.discount_amount_fen), 0)::NUMERIC
                     / SUM(o.total_amount_fen) * 100, 2)
         ELSE 0
    END AS discount_rate_pct
FROM orders o
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY s.store_name, s.store_code, COALESCE(o.biz_date, DATE(o.created_at))
ORDER BY biz_date DESC, s.store_name
"""

DIMENSIONS = ["store_name", "store_code", "biz_date"]
METRICS = [
    "total_orders",
    "paid_orders",
    "cancelled_orders",
    "total_amount_fen",
    "discount_fen",
    "actual_fen",
    "variance_fen",
    "anomaly_count",
    "margin_alert_count",
    "manual_discount_count",
    "return_order_count",
    "discount_rate_pct",
]
FILTERS = ["start_date", "end_date", "store_id"]
