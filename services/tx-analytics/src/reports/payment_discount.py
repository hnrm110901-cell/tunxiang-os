"""P0 报表: 门店付款折扣表

按折扣类型汇总订单折扣，区分会员折扣、活动折扣、手工折扣、赠菜等。
折扣类型从 orders.order_metadata->'discount_type' 解析。
"""

REPORT_ID = "payment_discount"
REPORT_NAME = "门店付款折扣表"
CATEGORY = "revenue"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
    COALESCE(o.order_metadata->>'discount_type', 'none') AS discount_type,
    COUNT(*) AS order_count,
    SUM(COALESCE(o.discount_amount_fen, 0)) AS discount_fen,
    SUM(o.total_amount_fen) AS total_amount_fen,
    SUM(COALESCE(o.final_amount_fen, o.total_amount_fen - COALESCE(o.discount_amount_fen, 0))) AS actual_fen,
    CASE WHEN SUM(o.total_amount_fen) > 0
         THEN ROUND(SUM(COALESCE(o.discount_amount_fen, 0))::NUMERIC
                     / SUM(o.total_amount_fen) * 100, 2)
         ELSE 0
    END AS discount_rate_pct
FROM orders o
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND o.status = 'paid'
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY s.store_name,
         COALESCE(o.biz_date, DATE(o.created_at)),
         COALESCE(o.order_metadata->>'discount_type', 'none')
ORDER BY biz_date DESC, discount_fen DESC
"""

DIMENSIONS = ["store_name", "biz_date", "discount_type"]
METRICS = ["order_count", "discount_fen", "total_amount_fen", "actual_fen", "discount_rate_pct"]
FILTERS = ["start_date", "end_date", "store_id"]
