"""P2 提成报表: 服务员业绩提成表

按服务员统计关联订单数、营收、客数，计算服务提成。
关联 employees(role='waiter') + orders(waiter_id) + order_items。
"""

REPORT_ID = "commission_waiter"
REPORT_NAME = "服务员业绩提成表"
CATEGORY = "commission"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    e.emp_name AS waiter_name,
    e.id AS employee_id,
    e.grade_level,
    COUNT(DISTINCT o.id) AS order_count,
    COALESCE(SUM(o.guest_count), 0) AS guest_count,
    SUM(o.final_amount_fen) AS revenue_fen,
    CASE WHEN COUNT(DISTINCT o.id) > 0
         THEN SUM(o.final_amount_fen) / COUNT(DISTINCT o.id)
         ELSE 0
    END AS avg_ticket_fen,
    COALESCE(SUM(o.discount_amount_fen), 0) AS discount_fen,
    -- 退菜笔数
    COUNT(DISTINCT o.id) FILTER (WHERE EXISTS (
        SELECT 1 FROM order_items oi2
        WHERE oi2.order_id = o.id AND oi2.return_flag = TRUE AND oi2.is_deleted = FALSE
    )) AS return_order_count,
    -- 服务提成 = 营收 * 提成比例（暂按0.5%估算，实际由门店配置）
    ROUND(SUM(o.final_amount_fen) * 0.005) AS commission_fen,
    RANK() OVER (PARTITION BY s.id ORDER BY SUM(o.final_amount_fen) DESC) AS revenue_rank
FROM employees e
JOIN stores s ON e.store_id = s.id AND s.tenant_id = e.tenant_id
LEFT JOIN orders o ON o.waiter_id = e.id::TEXT
    AND o.tenant_id = e.tenant_id
    AND o.is_deleted = FALSE
    AND o.status IN ('completed', 'paid')
    AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
WHERE e.tenant_id = :tenant_id
  AND e.is_deleted = FALSE
  AND e.is_active = TRUE
  AND e.role = 'waiter'
  AND (:store_id IS NULL OR e.store_id = :store_id::UUID)
GROUP BY s.store_name, s.id, e.emp_name, e.id, e.grade_level
ORDER BY revenue_fen DESC
"""

DIMENSIONS = ["store_name", "waiter_name", "employee_id", "grade_level"]
METRICS = [
    "order_count", "guest_count", "revenue_fen", "avg_ticket_fen",
    "discount_fen", "return_order_count", "commission_fen", "revenue_rank",
]
FILTERS = ["start_date", "end_date", "store_id"]
