"""中台财务报表: 订单流水/支付流水

逐笔订单 + 支付明细。
用于财务核对、审计追溯和异常排查。
"""

REPORT_ID = "finance_order_flow"
REPORT_NAME = "订单流水/支付流水表"
CATEGORY = "finance"

# 订单流水明细
SQL_ORDER_FLOW = """
SELECT
    s.store_name,
    o.order_no,
    o.id AS order_id,
    COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
    o.created_at AS order_time,
    o.status AS order_status,
    o.sales_channel,
    o.total_amount_fen,
    COALESCE(o.discount_amount_fen, 0) AS discount_fen,
    COALESCE(o.final_amount_fen,
        o.total_amount_fen - COALESCE(o.discount_amount_fen, 0)) AS actual_fen,
    COALESCE(o.refund_amount_fen, 0) AS refund_fen,
    o.guest_count,
    o.table_no,
    ec.name AS cashier_name,
    es.name AS server_name,
    o.remark
FROM orders o
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
LEFT JOIN employees ec ON o.cashier_id = ec.id AND ec.tenant_id = o.tenant_id
LEFT JOIN employees es ON o.server_id = es.id AND es.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
ORDER BY o.created_at DESC
LIMIT :page_size OFFSET :page_offset
"""

# 支付流水明细
SQL_PAYMENT_FLOW = """
SELECT
    s.store_name,
    o.order_no,
    p.id AS payment_id,
    COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
    p.created_at AS payment_time,
    p.payment_method,
    p.amount_fen,
    p.status AS payment_status,
    p.trade_no AS third_party_trade_no,
    o.status AS order_status,
    ec.name AS cashier_name
FROM payments p
JOIN orders o ON o.id = p.order_id AND o.tenant_id = p.tenant_id
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
LEFT JOIN employees ec ON o.cashier_id = ec.id AND ec.tenant_id = o.tenant_id
WHERE p.tenant_id = :tenant_id
  AND p.is_deleted = FALSE
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
ORDER BY p.created_at DESC
LIMIT :page_size OFFSET :page_offset
"""

DIMENSIONS_ORDER = [
    "store_name",
    "order_no",
    "biz_date",
    "order_time",
    "order_status",
    "sales_channel",
    "table_no",
    "cashier_name",
    "server_name",
]
METRICS_ORDER = [
    "total_amount_fen",
    "discount_fen",
    "actual_fen",
    "refund_fen",
    "guest_count",
]

DIMENSIONS_PAYMENT = [
    "store_name",
    "order_no",
    "biz_date",
    "payment_time",
    "payment_method",
    "payment_status",
    "third_party_trade_no",
    "cashier_name",
]
METRICS_PAYMENT = ["amount_fen"]

FILTERS = ["start_date", "end_date", "store_id", "page_size", "page_offset"]
