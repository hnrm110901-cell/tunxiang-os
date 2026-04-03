"""P0 报表: 门店日现金流报表

按支付方式(现金/微信/支付宝/银联/会员余额/挂账等)分类汇总，
同时展示退款，得出净收款。
"""

REPORT_ID = "daily_cashflow"
REPORT_NAME = "门店日现金流报表"
CATEGORY = "cashflow"

SQL_TEMPLATE = """
WITH payment_in AS (
    SELECT
        s.store_name,
        COALESCE(o.biz_date, DATE(p.paid_at)) AS biz_date,
        p.method AS payment_method,
        p.payment_category,
        SUM(p.amount_fen) AS income_fen,
        COUNT(*) AS income_count
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
             p.method,
             p.payment_category
),
refund_out AS (
    SELECT
        s.store_name,
        COALESCE(o.biz_date, DATE(r.refunded_at)) AS biz_date,
        p.method AS payment_method,
        SUM(r.amount_fen) AS refund_fen,
        COUNT(*) AS refund_count
    FROM refunds r
    JOIN orders o ON r.order_id = o.id AND r.tenant_id = o.tenant_id
    JOIN payments p ON r.payment_id = p.id AND r.tenant_id = p.tenant_id
    JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
    WHERE r.tenant_id = :tenant_id
      AND r.is_deleted = FALSE
      AND o.is_deleted = FALSE
      AND COALESCE(o.biz_date, DATE(r.refunded_at)) BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
    GROUP BY s.store_name,
             COALESCE(o.biz_date, DATE(r.refunded_at)),
             p.method
)
SELECT
    pi.store_name,
    pi.biz_date,
    pi.payment_method,
    pi.payment_category,
    pi.income_fen,
    pi.income_count,
    COALESCE(ro.refund_fen, 0) AS refund_fen,
    COALESCE(ro.refund_count, 0) AS refund_count,
    pi.income_fen - COALESCE(ro.refund_fen, 0) AS net_fen
FROM payment_in pi
LEFT JOIN refund_out ro
    ON pi.store_name = ro.store_name
   AND pi.biz_date = ro.biz_date
   AND pi.payment_method = ro.payment_method
ORDER BY pi.biz_date DESC, pi.store_name, pi.income_fen DESC
"""

DIMENSIONS = ["store_name", "biz_date", "payment_method", "payment_category"]
METRICS = ["income_fen", "income_count", "refund_fen", "refund_count", "net_fen"]
FILTERS = ["start_date", "end_date", "store_id"]
