"""P2 稽核报表: 押金统计表

按门店统计押金收取、退还、挂账情况，用于财务核对。
关联 orders(order_metadata 含押金信息) + stores。
押金数据存储在 order_metadata->>'deposit_fen' 字段。
"""

REPORT_ID = "deposit_stats"
REPORT_NAME = "押金统计表"
CATEGORY = "audit"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    s.store_code,
    COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
    -- 收取押金的订单数
    COUNT(*) FILTER (
        WHERE (o.order_metadata->>'deposit_fen')::INT > 0
    ) AS deposit_order_count,
    -- 押金收取总额
    COALESCE(SUM((o.order_metadata->>'deposit_fen')::INT)
        FILTER (WHERE (o.order_metadata->>'deposit_fen')::INT > 0), 0
    ) AS deposit_collected_fen,
    -- 已退还押金
    COALESCE(SUM((o.order_metadata->>'deposit_refund_fen')::INT)
        FILTER (WHERE (o.order_metadata->>'deposit_refund_fen')::INT > 0), 0
    ) AS deposit_refunded_fen,
    -- 未退还(挂账)押金 = 收取 - 退还
    COALESCE(SUM((o.order_metadata->>'deposit_fen')::INT)
        FILTER (WHERE (o.order_metadata->>'deposit_fen')::INT > 0), 0)
    - COALESCE(SUM((o.order_metadata->>'deposit_refund_fen')::INT)
        FILTER (WHERE (o.order_metadata->>'deposit_refund_fen')::INT > 0), 0
    ) AS deposit_outstanding_fen,
    -- 总订单数
    COUNT(*) AS total_orders,
    -- 押金订单占比
    CASE WHEN COUNT(*) > 0
         THEN ROUND(
             COUNT(*) FILTER (WHERE (o.order_metadata->>'deposit_fen')::INT > 0)::NUMERIC
             / COUNT(*) * 100, 2)
         ELSE 0
    END AS deposit_order_pct
FROM orders o
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND o.status IN ('completed', 'paid', 'cancelled')
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY s.store_name, s.store_code, COALESCE(o.biz_date, DATE(o.created_at))
ORDER BY biz_date DESC, deposit_outstanding_fen DESC
"""

DIMENSIONS = ["store_name", "store_code", "biz_date"]
METRICS = [
    "deposit_order_count",
    "deposit_collected_fen",
    "deposit_refunded_fen",
    "deposit_outstanding_fen",
    "total_orders",
    "deposit_order_pct",
]
FILTERS = ["start_date", "end_date", "store_id"]
