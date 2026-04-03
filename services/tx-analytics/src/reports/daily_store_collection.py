"""P0 报表: 每日收款分门店统计表

按门店+支付方式汇总 payments 表，展示各门店各支付方式的收款情况。
"""

REPORT_ID = "daily_store_collection"
REPORT_NAME = "每日收款分门店统计表"
CATEGORY = "cashflow"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    COALESCE(o.biz_date, DATE(p.paid_at)) AS biz_date,
    p.method AS payment_method,
    COUNT(*) AS payment_count,
    SUM(p.amount_fen) AS collection_fen,
    CASE WHEN SUM(SUM(p.amount_fen)) OVER (PARTITION BY s.store_name, COALESCE(o.biz_date, DATE(p.paid_at))) > 0
         THEN ROUND(SUM(p.amount_fen)::NUMERIC
                     / SUM(SUM(p.amount_fen)) OVER (PARTITION BY s.store_name, COALESCE(o.biz_date, DATE(p.paid_at))) * 100, 2)
         ELSE 0
    END AS pct
FROM payments p
JOIN orders o ON p.order_id = o.id AND p.tenant_id = o.tenant_id
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
WHERE p.tenant_id = :tenant_id
  AND p.is_deleted = FALSE
  AND p.status = 'paid'
  AND o.is_deleted = FALSE
  AND COALESCE(o.biz_date, DATE(p.paid_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY s.store_name,
         COALESCE(o.biz_date, DATE(p.paid_at)),
         p.method
ORDER BY biz_date DESC, s.store_name, collection_fen DESC
"""

DIMENSIONS = ["store_name", "biz_date", "payment_method"]
METRICS = ["payment_count", "collection_fen", "pct"]
FILTERS = ["start_date", "end_date", "store_id"]
