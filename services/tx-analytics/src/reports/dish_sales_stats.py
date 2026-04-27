"""P0 报表: 菜品销售统计表

按菜品汇总销量、金额、占比、排名，支持按分类筛选。
"""

REPORT_ID = "dish_sales_stats"
REPORT_NAME = "菜品销售统计表"
CATEGORY = "product"

SQL_TEMPLATE = """
SELECT
    d.dish_name,
    dc.name AS category_name,
    s.store_name,
    SUM(oi.quantity) AS sales_qty,
    SUM(oi.subtotal_fen) AS sales_amount_fen,
    SUM(COALESCE(oi.food_cost_fen, 0) * oi.quantity) AS cost_fen,
    SUM(oi.subtotal_fen) - SUM(COALESCE(oi.food_cost_fen, 0) * oi.quantity) AS profit_fen,
    CASE WHEN SUM(SUM(oi.subtotal_fen)) OVER () > 0
         THEN ROUND(SUM(oi.subtotal_fen)::NUMERIC
                     / SUM(SUM(oi.subtotal_fen)) OVER () * 100, 2)
         ELSE 0
    END AS revenue_pct,
    CASE WHEN SUM(SUM(oi.quantity)) OVER () > 0
         THEN ROUND(SUM(oi.quantity)::NUMERIC
                     / SUM(SUM(oi.quantity)) OVER () * 100, 2)
         ELSE 0
    END AS qty_pct,
    RANK() OVER (ORDER BY SUM(oi.quantity) DESC) AS qty_rank,
    RANK() OVER (ORDER BY SUM(oi.subtotal_fen) DESC) AS revenue_rank
FROM order_items oi
JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
LEFT JOIN dish_categories dc ON d.category_id = dc.id AND dc.tenant_id = d.tenant_id
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND oi.is_deleted = FALSE
  AND o.status = 'paid'
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
  AND (:category_id IS NULL OR d.category_id = :category_id::UUID)
GROUP BY d.dish_name, dc.name, s.store_name
ORDER BY sales_qty DESC
"""

DIMENSIONS = ["dish_name", "category_name", "store_name"]
METRICS = [
    "sales_qty",
    "sales_amount_fen",
    "cost_fen",
    "profit_fen",
    "revenue_pct",
    "qty_pct",
    "qty_rank",
    "revenue_rank",
]
FILTERS = ["start_date", "end_date", "store_id", "category_id"]
