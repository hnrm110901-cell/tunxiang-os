"""P0 报表: 账单稽核表

标记异常订单：折扣异常、退菜、反结(退款)、手工操作，供财务稽核。
"""

REPORT_ID = "bill_audit"
REPORT_NAME = "账单稽核表"
CATEGORY = "audit"

SQL_TEMPLATE = """
WITH anomaly_orders AS (
    SELECT
        o.id AS order_id,
        o.order_no,
        s.store_name,
        COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
        o.total_amount_fen,
        COALESCE(o.discount_amount_fen, 0) AS discount_fen,
        COALESCE(o.final_amount_fen, o.total_amount_fen) AS actual_fen,
        o.status,
        o.order_metadata,
        -- 折扣异常: 折扣超过应收50%
        CASE WHEN COALESCE(o.discount_amount_fen, 0) > o.total_amount_fen * 0.5
             THEN TRUE ELSE FALSE
        END AS is_high_discount,
        -- 退菜标记
        (SELECT COUNT(*) FROM order_items oi
         WHERE oi.order_id = o.id
           AND oi.tenant_id = o.tenant_id
           AND oi.is_deleted = FALSE
           AND oi.notes LIKE '%%退菜%%') AS return_item_count,
        -- 反结(退款)标记
        (SELECT COUNT(*) FROM refunds r
         WHERE r.order_id = o.id
           AND r.tenant_id = o.tenant_id
           AND r.is_deleted = FALSE) AS refund_count,
        -- 手工操作标记
        CASE WHEN o.order_metadata->>'manual_adjust' = 'true'
              OR o.order_metadata->>'discount_type' = 'manual'
             THEN TRUE ELSE FALSE
        END AS is_manual_operation,
        o.created_at
    FROM orders o
    JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
    WHERE o.tenant_id = :tenant_id
      AND o.is_deleted = FALSE
      AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
)
SELECT
    order_no,
    store_name,
    biz_date,
    total_amount_fen,
    discount_fen,
    actual_fen,
    status,
    is_high_discount,
    return_item_count,
    refund_count,
    is_manual_operation,
    CASE
        WHEN is_high_discount THEN 'high_discount'
        WHEN return_item_count > 0 THEN 'return_dish'
        WHEN refund_count > 0 THEN 'refund'
        WHEN is_manual_operation THEN 'manual'
        ELSE 'normal'
    END AS anomaly_type,
    created_at
FROM anomaly_orders
WHERE is_high_discount = TRUE
   OR return_item_count > 0
   OR refund_count > 0
   OR is_manual_operation = TRUE
ORDER BY biz_date DESC, created_at DESC
"""

DIMENSIONS = ["order_no", "store_name", "biz_date", "anomaly_type", "status"]
METRICS = [
    "total_amount_fen", "discount_fen", "actual_fen",
    "return_item_count", "refund_count",
]
FILTERS = ["start_date", "end_date", "store_id"]
