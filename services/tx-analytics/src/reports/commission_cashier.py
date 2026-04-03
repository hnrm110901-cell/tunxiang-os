"""P2 提成报表: 收银员业绩统计表

按收银员统计收银笔数、金额、退款、差异，用于收银绩效评估。
关联 employees(role='cashier') + orders + order_items。
"""

REPORT_ID = "commission_cashier"
REPORT_NAME = "收银员业绩统计表"
CATEGORY = "commission"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    e.emp_name AS cashier_name,
    e.id AS employee_id,
    e.grade_level,
    COUNT(DISTINCT o.id) AS order_count,
    SUM(o.total_amount_fen) AS total_amount_fen,
    COALESCE(SUM(o.discount_amount_fen), 0) AS discount_fen,
    SUM(COALESCE(o.final_amount_fen, o.total_amount_fen)) AS actual_fen,
    -- 退款统计
    COUNT(DISTINCT o.id) FILTER (WHERE o.status = 'cancelled') AS cancel_count,
    -- 手工折扣次数
    COUNT(DISTINCT o.id) FILTER (WHERE o.discount_type = 'manual') AS manual_discount_count,
    -- 均单金额
    CASE WHEN COUNT(DISTINCT o.id) > 0
         THEN SUM(COALESCE(o.final_amount_fen, o.total_amount_fen)) / COUNT(DISTINCT o.id)
         ELSE 0
    END AS avg_ticket_fen,
    -- 异常单数（折扣超50% 或 毛利告警）
    COUNT(DISTINCT o.id) FILTER (
        WHERE o.abnormal_flag = TRUE OR o.margin_alert_flag = TRUE
    ) AS anomaly_count,
    -- 收银提成 = 收银笔数 * 单价（暂按每单1元=100分估算）
    COUNT(DISTINCT o.id) * 100 AS commission_fen,
    RANK() OVER (PARTITION BY s.id ORDER BY COUNT(DISTINCT o.id) DESC) AS output_rank
FROM employees e
JOIN stores s ON e.store_id = s.id AND s.tenant_id = e.tenant_id
LEFT JOIN orders o ON o.store_id = e.store_id
    AND o.tenant_id = e.tenant_id
    AND o.is_deleted = FALSE
    AND o.status IN ('completed', 'paid', 'cancelled')
    AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
WHERE e.tenant_id = :tenant_id
  AND e.is_deleted = FALSE
  AND e.is_active = TRUE
  AND e.role = 'cashier'
  AND (:store_id IS NULL OR e.store_id = :store_id::UUID)
GROUP BY s.store_name, s.id, e.emp_name, e.id, e.grade_level
ORDER BY actual_fen DESC
"""

DIMENSIONS = ["store_name", "cashier_name", "employee_id", "grade_level"]
METRICS = [
    "order_count", "total_amount_fen", "discount_fen", "actual_fen",
    "cancel_count", "manual_discount_count", "avg_ticket_fen",
    "anomaly_count", "commission_fen", "output_rank",
]
FILTERS = ["start_date", "end_date", "store_id"]
