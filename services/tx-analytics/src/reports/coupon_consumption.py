"""P0 报表: 团购券消费分析

按团购券类型和来源平台统计核销量、面值总额、实际成本、盈亏。
关联 coupon_redemptions + stores。
金额单位: 分(fen), int。
"""

REPORT_ID = "coupon_consumption"
REPORT_NAME = "团购券消费分析"
CATEGORY = "revenue"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    s.store_code,
    COALESCE(cr.biz_date, DATE(cr.created_at)) AS biz_date,
    cr.coupon_type,
    cr.platform,
    COUNT(*) AS redeemed_count,
    SUM(COALESCE(cr.face_value_fen, 0)) AS face_value_total_fen,
    SUM(COALESCE(cr.actual_cost_fen, 0)) AS actual_cost_total_fen,
    SUM(COALESCE(cr.settlement_fen, 0)) AS settlement_total_fen,
    -- 盈亏 = 平台结算 - 实际成本
    SUM(COALESCE(cr.settlement_fen, 0))
        - SUM(COALESCE(cr.actual_cost_fen, 0)) AS profit_loss_fen,
    -- 核销率
    CASE WHEN SUM(cr.issued_count) > 0
         THEN ROUND(COUNT(*)::NUMERIC / SUM(cr.issued_count) * 100, 2)
         ELSE NULL
    END AS redemption_rate_pct,
    -- 平均面值
    CASE WHEN COUNT(*) > 0
         THEN SUM(COALESCE(cr.face_value_fen, 0)) / COUNT(*)
         ELSE 0
    END AS avg_face_value_fen,
    -- 平均结算价
    CASE WHEN COUNT(*) > 0
         THEN SUM(COALESCE(cr.settlement_fen, 0)) / COUNT(*)
         ELSE 0
    END AS avg_settlement_fen
FROM coupon_redemptions cr
JOIN stores s ON cr.store_id = s.id AND s.tenant_id = cr.tenant_id
WHERE cr.tenant_id = :tenant_id
  AND cr.is_deleted = FALSE
  AND COALESCE(cr.biz_date, DATE(cr.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR cr.store_id = :store_id::UUID)
GROUP BY s.store_name, s.store_code,
    COALESCE(cr.biz_date, DATE(cr.created_at)), cr.coupon_type, cr.platform
ORDER BY biz_date DESC, redeemed_count DESC
"""

DIMENSIONS = ["store_name", "store_code", "biz_date", "coupon_type", "platform"]
METRICS = [
    "redeemed_count", "face_value_total_fen", "actual_cost_total_fen",
    "settlement_total_fen", "profit_loss_fen", "redemption_rate_pct",
    "avg_face_value_fen", "avg_settlement_fen",
]
FILTERS = ["start_date", "end_date", "store_id"]
