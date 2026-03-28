"""P1 报表: 菜品销售分时段统计表

按小时统计菜品销售分布，标注餐段(早餐/午餐/下午茶/晚餐/夜宵)。
"""

REPORT_ID = "dish_hourly"
REPORT_NAME = "菜品销售分时段统计表"
CATEGORY = "product"

SQL_TEMPLATE = """
SELECT
    EXTRACT(HOUR FROM o.created_at)::int AS hour,
    CASE
        WHEN EXTRACT(HOUR FROM o.created_at) >= 6
             AND EXTRACT(HOUR FROM o.created_at) < 10  THEN 'breakfast'
        WHEN EXTRACT(HOUR FROM o.created_at) >= 10
             AND EXTRACT(HOUR FROM o.created_at) < 14  THEN 'lunch'
        WHEN EXTRACT(HOUR FROM o.created_at) >= 14
             AND EXTRACT(HOUR FROM o.created_at) < 17  THEN 'afternoon_tea'
        WHEN EXTRACT(HOUR FROM o.created_at) >= 17
             AND EXTRACT(HOUR FROM o.created_at) < 21  THEN 'dinner'
        ELSE 'late_night'
    END AS meal_period,
    COUNT(DISTINCT oi.dish_id) AS dish_variety,
    SUM(oi.quantity) AS total_qty,
    COALESCE(SUM(oi.subtotal_fen), 0) AS total_amount_fen,
    CASE WHEN SUM(oi.quantity) > 0
         THEN SUM(oi.subtotal_fen) / SUM(oi.quantity)
         ELSE 0
    END AS avg_item_fen
FROM order_items oi
JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND oi.is_deleted = FALSE
  AND o.status = 'paid'
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY hour, meal_period
ORDER BY hour
"""

DIMENSIONS = ["hour", "meal_period"]
METRICS = ["dish_variety", "total_qty", "total_amount_fen", "avg_item_fen"]
FILTERS = ["start_date", "end_date", "store_id"]
