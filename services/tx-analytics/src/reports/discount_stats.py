"""P1 报表: 营业折扣统计表

折扣按类型(会员/优惠券/促销/店长特批/平台)/金额/占营收比例汇总。
"""

REPORT_ID = "discount_stats"
REPORT_NAME = "营业折扣统计表"
CATEGORY = "revenue"

SQL_TEMPLATE = """
SELECT
    COALESCE(o.discount_type, 'none') AS discount_type,
    COUNT(o.id) AS order_count,
    COALESCE(SUM(o.discount_amount_fen), 0) AS total_discount_fen,
    CASE WHEN COUNT(o.id) > 0
         THEN SUM(o.discount_amount_fen) / COUNT(o.id)
         ELSE 0
    END AS avg_discount_fen,
    COALESCE(SUM(o.total_amount_fen), 0) AS order_total_fen,
    ROUND(
        SUM(o.discount_amount_fen)::numeric * 100.0
        / NULLIF(SUM(o.total_amount_fen + COALESCE(o.discount_amount_fen, 0)), 0),
        2
    ) AS discount_rate_pct,
    ROUND(
        SUM(o.discount_amount_fen)::numeric * 100.0
        / NULLIF(SUM(SUM(o.discount_amount_fen)) OVER (), 0),
        2
    ) AS type_pct
FROM orders o
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND o.status = 'paid'
  AND COALESCE(o.discount_amount_fen, 0) > 0
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY COALESCE(o.discount_type, 'none')
ORDER BY total_discount_fen DESC
"""

DIMENSIONS = ["discount_type"]
METRICS = [
    "order_count", "total_discount_fen", "avg_discount_fen",
    "order_total_fen", "discount_rate_pct", "type_pct",
]
FILTERS = ["start_date", "end_date", "store_id"]
