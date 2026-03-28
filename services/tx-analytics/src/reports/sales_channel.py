"""销售渠道统计表 — 按渠道(POS/小程序/美团/饿了么/抖音)汇总

P1 每周分析报表 #10
金额单位: 分(fen), int
"""

REPORT_ID = "sales_channel"
REPORT_NAME = "销售渠道统计表"
CATEGORY = "channel"

SQL_TEMPLATE = """
SELECT
    COALESCE(o.channel, 'pos') AS channel,
    COUNT(o.id) AS order_count,
    COALESCE(SUM(o.guest_count), 0) AS guest_count,
    COALESCE(SUM(o.total_amount_fen), 0) AS total_amount_fen,
    CASE WHEN COUNT(*) > 0
         THEN SUM(o.total_amount_fen) / COUNT(*)
         ELSE 0
    END AS avg_ticket_fen,
    ROUND(
        SUM(o.total_amount_fen)::numeric * 100.0
        / NULLIF(SUM(SUM(o.total_amount_fen)) OVER (), 0),
        2
    ) AS channel_pct
FROM orders o
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND o.status = 'paid'
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY COALESCE(o.channel, 'pos')
ORDER BY total_amount_fen DESC
"""

DIMENSIONS = ["channel"]
METRICS = ["order_count", "guest_count", "total_amount_fen", "avg_ticket_fen", "channel_pct"]
FILTERS = ["start_date", "end_date", "store_id"]
