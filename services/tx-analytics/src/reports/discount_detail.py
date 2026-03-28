"""P2 稽核报表: 折扣统计表

按门店/折扣类型/日期汇总折扣明细，识别异常折扣行为。
关联 orders + order_items + stores + employees。
"""

REPORT_ID = "discount_detail"
REPORT_NAME = "折扣统计表"
CATEGORY = "audit"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
    COALESCE(o.discount_type, '无折扣') AS discount_type,
    CASE o.discount_type
        WHEN 'coupon' THEN '优惠券'
        WHEN 'vip' THEN '会员折扣'
        WHEN 'manager' THEN '店长特批'
        WHEN 'promotion' THEN '促销活动'
        WHEN 'manual' THEN '手工折扣'
        ELSE COALESCE(o.discount_type, '无折扣')
    END AS discount_type_label,
    COUNT(*) AS order_count,
    SUM(o.total_amount_fen) AS total_amount_fen,
    COALESCE(SUM(o.discount_amount_fen), 0) AS discount_fen,
    SUM(COALESCE(o.final_amount_fen, o.total_amount_fen)) AS actual_fen,
    -- 折扣率
    CASE WHEN SUM(o.total_amount_fen) > 0
         THEN ROUND(COALESCE(SUM(o.discount_amount_fen), 0)::NUMERIC
                     / SUM(o.total_amount_fen) * 100, 2)
         ELSE 0
    END AS discount_rate_pct,
    -- 折扣订单占比
    CASE WHEN SUM(COUNT(*)) OVER (PARTITION BY s.store_name, COALESCE(o.biz_date, DATE(o.created_at))) > 0
         THEN ROUND(COUNT(*)::NUMERIC
                     / SUM(COUNT(*)) OVER (PARTITION BY s.store_name, COALESCE(o.biz_date, DATE(o.created_at))) * 100, 2)
         ELSE 0
    END AS order_share_pct,
    -- 高折扣订单数(折扣超50%)
    COUNT(*) FILTER (
        WHERE o.total_amount_fen > 0
          AND COALESCE(o.discount_amount_fen, 0)::NUMERIC / o.total_amount_fen > 0.5
    ) AS high_discount_count,
    -- 毛利告警数
    COUNT(*) FILTER (WHERE o.margin_alert_flag = TRUE) AS margin_alert_count,
    -- 均单折扣额
    CASE WHEN COUNT(*) > 0
         THEN COALESCE(SUM(o.discount_amount_fen), 0) / COUNT(*)
         ELSE 0
    END AS avg_discount_fen
FROM orders o
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND o.status IN ('completed', 'paid')
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY s.store_name, COALESCE(o.biz_date, DATE(o.created_at)), o.discount_type
ORDER BY biz_date DESC, discount_fen DESC
"""

DIMENSIONS = ["store_name", "biz_date", "discount_type", "discount_type_label"]
METRICS = [
    "order_count", "total_amount_fen", "discount_fen", "actual_fen",
    "discount_rate_pct", "order_share_pct",
    "high_discount_count", "margin_alert_count", "avg_discount_fen",
]
FILTERS = ["start_date", "end_date", "store_id"]
