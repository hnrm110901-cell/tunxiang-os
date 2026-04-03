"""P2 稽核报表: 对账单列表

按日期列出所有待对账和已对账的订单明细，含支付方式、折扣、实收。
关联 orders + order_items + stores。
"""

REPORT_ID = "audit_bill_list"
REPORT_NAME = "对账单列表"
CATEGORY = "audit"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
    o.order_no,
    o.order_type,
    o.table_number,
    o.status,
    o.total_amount_fen,
    COALESCE(o.discount_amount_fen, 0) AS discount_fen,
    COALESCE(o.final_amount_fen, o.total_amount_fen) AS actual_fen,
    o.discount_type,
    o.guest_count,
    -- 菜品数
    (SELECT COALESCE(SUM(oi.quantity), 0) FROM order_items oi
     WHERE oi.order_id = o.id AND oi.tenant_id = o.tenant_id AND oi.is_deleted = FALSE
    ) AS total_qty,
    -- BOM 成本
    (SELECT COALESCE(SUM(oi.food_cost_fen * oi.quantity), 0) FROM order_items oi
     WHERE oi.order_id = o.id AND oi.tenant_id = o.tenant_id AND oi.is_deleted = FALSE
       AND oi.food_cost_fen IS NOT NULL
    ) AS cost_fen,
    -- 毛利率
    CASE WHEN COALESCE(o.final_amount_fen, o.total_amount_fen) > 0
         THEN ROUND(
             (COALESCE(o.final_amount_fen, o.total_amount_fen)
              - (SELECT COALESCE(SUM(oi.food_cost_fen * oi.quantity), 0) FROM order_items oi
                 WHERE oi.order_id = o.id AND oi.tenant_id = o.tenant_id AND oi.is_deleted = FALSE
                   AND oi.food_cost_fen IS NOT NULL)
             )::NUMERIC / COALESCE(o.final_amount_fen, o.total_amount_fen) * 100, 2)
         ELSE 0
    END AS margin_rate,
    COALESCE(o.sales_channel_id, 'pos_dine_in') AS channel_id,
    o.created_at,
    o.completed_at
FROM orders o
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND o.status IN ('completed', 'paid', 'cancelled')
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
ORDER BY o.created_at DESC
"""

DIMENSIONS = [
    "store_name", "biz_date", "order_no", "order_type",
    "table_number", "status", "discount_type", "channel_id",
]
METRICS = [
    "total_amount_fen", "discount_fen", "actual_fen",
    "guest_count", "total_qty", "cost_fen", "margin_rate",
]
FILTERS = ["start_date", "end_date", "store_id"]
