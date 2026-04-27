"""P2 毛利报表: 每单毛利率一览表

逐单展示毛利率明细，支持按毛利率排序和筛选，定位低毛利订单。
关联 orders + order_items（BOM 成本 food_cost_fen）。
"""

REPORT_ID = "margin_each_order"
REPORT_NAME = "每单毛利率一览表"
CATEGORY = "margin"

SQL_TEMPLATE = """
SELECT
    o.order_no,
    s.store_name,
    COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
    o.order_type,
    o.table_number,
    e.emp_name AS waiter_name,
    o.final_amount_fen AS revenue_fen,
    COALESCE(SUM(oi.food_cost_fen * oi.quantity), 0) AS cost_fen,
    o.final_amount_fen - COALESCE(SUM(oi.food_cost_fen * oi.quantity), 0) AS margin_fen,
    CASE WHEN o.final_amount_fen > 0
         THEN ROUND((o.final_amount_fen - COALESCE(SUM(oi.food_cost_fen * oi.quantity), 0))::NUMERIC
                     / o.final_amount_fen * 100, 2)
         ELSE 0
    END AS margin_rate,
    COUNT(oi.id) AS item_count,
    o.guest_count,
    COALESCE(o.discount_amount_fen, 0) AS discount_fen,
    o.discount_type,
    o.created_at
FROM orders o
JOIN order_items oi ON oi.order_id = o.id AND oi.tenant_id = o.tenant_id
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
LEFT JOIN employees e ON o.waiter_id = e.id::TEXT AND e.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND oi.is_deleted = FALSE
  AND o.status IN ('completed', 'paid')
  AND oi.food_cost_fen IS NOT NULL
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY o.id, o.order_no, s.store_name, o.order_type, o.table_number,
         e.emp_name, o.final_amount_fen, o.guest_count,
         o.discount_amount_fen, o.discount_type, o.created_at, o.biz_date
ORDER BY margin_rate ASC
"""

DIMENSIONS = [
    "order_no",
    "store_name",
    "biz_date",
    "order_type",
    "table_number",
    "waiter_name",
    "discount_type",
]
METRICS = [
    "revenue_fen",
    "cost_fen",
    "margin_fen",
    "margin_rate",
    "item_count",
    "guest_count",
    "discount_fen",
]
FILTERS = ["start_date", "end_date", "store_id"]
