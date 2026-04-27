"""P2 提成报表: 菜品分类指标分析表

按菜品分类统计销量、营收、毛利、占比，支持四象限分析（高销量高毛利/高销量低毛利等）。
关联 dishes + dish_categories + order_items + orders。
"""

REPORT_ID = "dish_classification_index"
REPORT_NAME = "菜品分类指标分析表"
CATEGORY = "commission"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    COALESCE(dc.name, '未分类') AS category_name,
    COUNT(DISTINCT d.id) AS dish_count,
    SUM(oi.quantity) AS total_qty,
    SUM(oi.subtotal_fen) AS total_revenue_fen,
    SUM(COALESCE(oi.food_cost_fen, 0) * oi.quantity) AS total_cost_fen,
    SUM(oi.subtotal_fen) - SUM(COALESCE(oi.food_cost_fen, 0) * oi.quantity) AS total_margin_fen,
    -- 分类毛利率
    CASE WHEN SUM(oi.subtotal_fen) > 0
         THEN ROUND((SUM(oi.subtotal_fen) - SUM(COALESCE(oi.food_cost_fen, 0) * oi.quantity))::NUMERIC
                     / SUM(oi.subtotal_fen) * 100, 2)
         ELSE 0
    END AS margin_rate,
    -- 营收占比
    CASE WHEN SUM(SUM(oi.subtotal_fen)) OVER () > 0
         THEN ROUND(SUM(oi.subtotal_fen)::NUMERIC
                     / SUM(SUM(oi.subtotal_fen)) OVER () * 100, 2)
         ELSE 0
    END AS revenue_share_pct,
    -- 销量占比
    CASE WHEN SUM(SUM(oi.quantity)) OVER () > 0
         THEN ROUND(SUM(oi.quantity)::NUMERIC
                     / SUM(SUM(oi.quantity)) OVER () * 100, 2)
         ELSE 0
    END AS qty_share_pct,
    -- 均价
    CASE WHEN SUM(oi.quantity) > 0
         THEN SUM(oi.subtotal_fen) / SUM(oi.quantity)
         ELSE 0
    END AS avg_price_fen,
    -- 退菜数
    SUM(oi.quantity) FILTER (WHERE oi.return_flag = TRUE) AS return_qty,
    -- 赠菜数
    SUM(oi.quantity) FILTER (WHERE oi.gift_flag = TRUE) AS gift_qty,
    RANK() OVER (ORDER BY SUM(oi.subtotal_fen) DESC) AS revenue_rank
FROM order_items oi
JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
LEFT JOIN dish_categories dc ON d.category_id = dc.id AND dc.tenant_id = d.tenant_id
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND oi.is_deleted = FALSE
  AND o.status IN ('completed', 'paid')
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY s.store_name, COALESCE(dc.name, '未分类')
ORDER BY total_revenue_fen DESC
"""

DIMENSIONS = ["store_name", "category_name"]
METRICS = [
    "dish_count",
    "total_qty",
    "total_revenue_fen",
    "total_cost_fen",
    "total_margin_fen",
    "margin_rate",
    "revenue_share_pct",
    "qty_share_pct",
    "avg_price_fen",
    "return_qty",
    "gift_qty",
    "revenue_rank",
]
FILTERS = ["start_date", "end_date", "store_id"]
