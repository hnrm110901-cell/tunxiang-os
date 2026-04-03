"""营收结构汇总表 — 按收入来源(堂食/外卖/宴席/团餐/外带)汇总

P1 每周分析报表 #9
金额单位: 分(fen), int
"""

REPORT_ID = "revenue_structure"
REPORT_NAME = "营收结构汇总表"
CATEGORY = "revenue"

SQL_TEMPLATE = """
SELECT
    COALESCE(o.revenue_source, 'dine_in') AS revenue_source,
    COUNT(o.id) AS order_count,
    COALESCE(SUM(o.total_amount_fen), 0) AS total_amount_fen,
    COALESCE(SUM(o.discount_amount_fen), 0) AS total_discount_fen,
    COALESCE(SUM(COALESCE(o.final_amount_fen, o.total_amount_fen - COALESCE(o.discount_amount_fen, 0))), 0) AS net_amount_fen,
    ROUND(
        SUM(o.total_amount_fen)::numeric * 100.0
        / NULLIF(SUM(SUM(o.total_amount_fen)) OVER (), 0),
        2
    ) AS revenue_pct
FROM orders o
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND o.status = 'paid'
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY COALESCE(o.revenue_source, 'dine_in')
ORDER BY total_amount_fen DESC
"""

DIMENSIONS = ["revenue_source"]
METRICS = ["order_count", "total_amount_fen", "total_discount_fen", "net_amount_fen", "revenue_pct"]
FILTERS = ["start_date", "end_date", "store_id"]
