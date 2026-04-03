"""P1 报表: 套餐销售统计分析表

套餐类订单汇总(套餐名/销量/金额/溢价率)。
溢价率: (套餐价 - 单点总价) / 单点总价 * 100，负值表示套餐优惠。
"""

REPORT_ID = "combo_sales"
REPORT_NAME = "套餐销售统计分析表"
CATEGORY = "product"

SQL_TEMPLATE = """
SELECT
    oi.dish_id AS combo_id,
    d.dish_name AS combo_name,
    d.category AS combo_category,
    SUM(oi.quantity) AS sales_qty,
    COALESCE(SUM(oi.subtotal_fen), 0) AS total_amount_fen,
    CASE WHEN SUM(oi.quantity) > 0
         THEN SUM(oi.subtotal_fen) / SUM(oi.quantity)
         ELSE 0
    END AS avg_price_fen,
    COALESCE(AVG(d.original_price_fen), 0) AS avg_original_price_fen,
    CASE WHEN AVG(d.original_price_fen) > 0
         THEN ROUND(
             (AVG(oi.subtotal_fen / NULLIF(oi.quantity, 0))
              - AVG(d.original_price_fen))::numeric * 100.0
             / AVG(d.original_price_fen),
             2
         )
         ELSE 0
    END AS premium_rate_pct
FROM order_items oi
JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND oi.is_deleted = FALSE
  AND o.status = 'paid'
  AND d.is_combo = TRUE
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY oi.dish_id, d.dish_name, d.category
ORDER BY sales_qty DESC
"""

DIMENSIONS = ["combo_id", "combo_name", "combo_category"]
METRICS = [
    "sales_qty", "total_amount_fen", "avg_price_fen",
    "avg_original_price_fen", "premium_rate_pct",
]
FILTERS = ["start_date", "end_date", "store_id"]
