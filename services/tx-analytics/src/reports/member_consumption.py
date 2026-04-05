"""P0 报表: 会员消费分析

按会员维度汇总消费频次、总消费额、客单价、最近到店日期等。
关联 customers + orders + stores。
金额单位: 分(fen), int。
"""

REPORT_ID = "member_consumption"
REPORT_NAME = "会员消费分析"
CATEGORY = "member"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    c.id AS member_id,
    c.member_no,
    c.customer_name,
    c.phone_masked,
    c.member_level,
    COUNT(o.id) AS visit_count,
    SUM(COALESCE(o.final_amount_fen, o.total_amount_fen - COALESCE(o.discount_amount_fen, 0))) AS total_spend_fen,
    CASE WHEN COUNT(o.id) > 0
         THEN SUM(COALESCE(o.final_amount_fen, o.total_amount_fen - COALESCE(o.discount_amount_fen, 0)))
              / COUNT(o.id)
         ELSE 0
    END AS avg_per_visit_fen,
    SUM(COALESCE(o.discount_amount_fen, 0)) AS total_discount_fen,
    MAX(COALESCE(o.biz_date, DATE(o.created_at))) AS last_visit_date,
    MIN(COALESCE(o.biz_date, DATE(o.created_at))) AS first_visit_date,
    -- 消费频率（天/次）
    CASE WHEN COUNT(o.id) > 1
         THEN ROUND(
             (MAX(COALESCE(o.biz_date, DATE(o.created_at)))
              - MIN(COALESCE(o.biz_date, DATE(o.created_at))))::NUMERIC
             / (COUNT(o.id) - 1), 1
         )
         ELSE NULL
    END AS avg_days_between_visits
FROM customers c
JOIN orders o ON o.customer_id = c.id AND o.tenant_id = c.tenant_id
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
WHERE c.tenant_id = :tenant_id
  AND c.is_deleted = FALSE
  AND o.is_deleted = FALSE
  AND o.status IN ('paid', 'completed')
  AND c.is_member = TRUE
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY s.store_name, c.id, c.member_no, c.customer_name, c.phone_masked, c.member_level
ORDER BY total_spend_fen DESC, visit_count DESC
"""

DIMENSIONS = ["store_name", "member_id", "member_no", "customer_name", "phone_masked", "member_level"]
METRICS = [
    "visit_count", "total_spend_fen", "avg_per_visit_fen",
    "total_discount_fen", "last_visit_date", "first_visit_date",
    "avg_days_between_visits",
]
FILTERS = ["start_date", "end_date", "store_id"]
