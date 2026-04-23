"""P2 提成报表: 厨师业绩提成表

按厨师统计出品数、出品金额、出品速度、退菜率，计算厨师提成。
关联 employees(role='chef') + order_items(kds_station/production_dept) + orders。
"""

REPORT_ID = "commission_chef"
REPORT_NAME = "厨师业绩提成表"
CATEGORY = "commission"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    e.emp_name AS chef_name,
    e.id AS employee_id,
    e.grade_level,
    COUNT(DISTINCT o.id) AS order_count,
    COALESCE(SUM(oi.quantity), 0) AS total_dishes_cooked,
    COALESCE(SUM(oi.subtotal_fen), 0) AS total_dish_revenue_fen,
    -- 出菜速度（平均出餐耗时，从 orders.serve_duration_min）
    ROUND(AVG(o.serve_duration_min) FILTER (WHERE o.serve_duration_min IS NOT NULL), 1) AS avg_serve_duration_min,
    -- 超时出餐数
    COUNT(DISTINCT o.id) FILTER (
        WHERE o.serve_duration_min IS NOT NULL
          AND o.serve_duration_min > COALESCE(s.serve_time_limit_min, 30)
    ) AS timeout_order_count,
    -- 退菜数
    SUM(oi.quantity) FILTER (WHERE oi.return_flag = TRUE) AS return_dish_qty,
    -- 退菜率
    CASE WHEN COALESCE(SUM(oi.quantity), 0) > 0
         THEN ROUND(SUM(oi.quantity) FILTER (WHERE oi.return_flag = TRUE)::NUMERIC
                     / SUM(oi.quantity) * 100, 2)
         ELSE 0
    END AS return_rate_pct,
    -- 厨师提成 = 出品金额 * 0.5%
    ROUND(COALESCE(SUM(oi.subtotal_fen), 0) * 0.005) AS commission_fen,
    RANK() OVER (PARTITION BY s.id ORDER BY COALESCE(SUM(oi.quantity), 0) DESC) AS output_rank
FROM employees e
JOIN stores s ON e.store_id = s.id AND s.tenant_id = e.tenant_id
LEFT JOIN order_items oi ON oi.kds_station = e.preferences->>'station'
    AND oi.tenant_id = e.tenant_id
    AND oi.is_deleted = FALSE
LEFT JOIN orders o ON o.id = oi.order_id
    AND o.tenant_id = oi.tenant_id
    AND o.is_deleted = FALSE
    AND o.status IN ('completed', 'paid')
    AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
    AND o.store_id = e.store_id
WHERE e.tenant_id = :tenant_id
  AND e.is_deleted = FALSE
  AND e.is_active = TRUE
  AND e.role = 'chef'
  AND (:store_id IS NULL OR e.store_id = :store_id::UUID)
GROUP BY s.store_name, s.id, e.emp_name, e.id, e.grade_level, s.serve_time_limit_min
ORDER BY total_dishes_cooked DESC
"""

DIMENSIONS = ["store_name", "chef_name", "employee_id", "grade_level"]
METRICS = [
    "order_count",
    "total_dishes_cooked",
    "total_dish_revenue_fen",
    "avg_serve_duration_min",
    "timeout_order_count",
    "return_dish_qty",
    "return_rate_pct",
    "commission_fen",
    "output_rank",
]
FILTERS = ["start_date", "end_date", "store_id"]
