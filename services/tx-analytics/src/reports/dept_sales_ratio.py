"""P1 报表: 出品部门销售占比明细表

按档口(炒炉/蒸菜/凉菜/吧台/明档)汇总销售额和占比。
"""

REPORT_ID = "dept_sales_ratio"
REPORT_NAME = "出品部门销售占比明细表"
CATEGORY = "product"

SQL_TEMPLATE = """
SELECT
    COALESCE(d.department, 'unknown') AS department,
    COUNT(DISTINCT d.id) AS dish_count,
    SUM(oi.quantity) AS sales_qty,
    COALESCE(SUM(oi.subtotal_fen), 0) AS sales_amount_fen,
    CASE WHEN SUM(oi.quantity) > 0
         THEN SUM(oi.subtotal_fen) / SUM(oi.quantity)
         ELSE 0
    END AS avg_unit_price_fen,
    ROUND(
        SUM(oi.subtotal_fen)::numeric * 100.0
        / NULLIF(SUM(SUM(oi.subtotal_fen)) OVER (), 0),
        2
    ) AS dept_pct
FROM order_items oi
JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND oi.is_deleted = FALSE
  AND d.is_deleted = FALSE
  AND o.status = 'paid'
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY COALESCE(d.department, 'unknown')
ORDER BY sales_amount_fen DESC
"""

DIMENSIONS = ["department"]
METRICS = [
    "dish_count",
    "sales_qty",
    "sales_amount_fen",
    "avg_unit_price_fen",
    "dept_pct",
]
FILTERS = ["start_date", "end_date", "store_id"]
