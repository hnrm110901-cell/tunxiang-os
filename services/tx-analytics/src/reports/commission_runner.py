"""P2 提成报表: 传菜员业绩提成表

按传菜员统计传菜单数、传菜速度、超时率，计算传菜提成。
关联 employees(role 含 runner/技能含传菜) + orders(served_at) + order_items。
"""

REPORT_ID = "commission_runner"
REPORT_NAME = "传菜员业绩提成表"
CATEGORY = "commission"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    e.emp_name AS runner_name,
    e.id AS employee_id,
    e.grade_level,
    COUNT(DISTINCT o.id) AS order_count,
    COALESCE(SUM(oi.quantity), 0) AS total_dishes_served,
    -- 平均传菜耗时（从厨房到桌台）
    ROUND(AVG(o.serve_duration_min) FILTER (WHERE o.serve_duration_min IS NOT NULL), 1) AS avg_serve_duration_min,
    -- 超时传菜数
    COUNT(DISTINCT o.id) FILTER (
        WHERE o.serve_duration_min IS NOT NULL
          AND o.serve_duration_min > COALESCE(s.serve_time_limit_min, 30)
    ) AS timeout_order_count,
    -- 超时率
    CASE WHEN COUNT(DISTINCT o.id) > 0
         THEN ROUND(
             COUNT(DISTINCT o.id) FILTER (
                 WHERE o.serve_duration_min IS NOT NULL
                   AND o.serve_duration_min > COALESCE(s.serve_time_limit_min, 30)
             )::NUMERIC / COUNT(DISTINCT o.id) * 100, 2)
         ELSE 0
    END AS timeout_rate_pct,
    -- 传菜提成 = 传菜单数 * 单价（暂按每单2元=200分估算）
    COUNT(DISTINCT o.id) * 200 AS commission_fen,
    RANK() OVER (PARTITION BY s.id ORDER BY COUNT(DISTINCT o.id) DESC) AS output_rank
FROM employees e
JOIN stores s ON e.store_id = s.id AND s.tenant_id = e.tenant_id
LEFT JOIN orders o ON o.store_id = e.store_id
    AND o.tenant_id = e.tenant_id
    AND o.is_deleted = FALSE
    AND o.status IN ('completed', 'paid')
    AND o.served_at IS NOT NULL
    AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
LEFT JOIN order_items oi ON oi.order_id = o.id
    AND oi.tenant_id = o.tenant_id
    AND oi.is_deleted = FALSE
    AND oi.sent_to_kds_flag = TRUE
WHERE e.tenant_id = :tenant_id
  AND e.is_deleted = FALSE
  AND e.is_active = TRUE
  AND (e.role = 'waiter' AND 'runner' = ANY(e.skills))
  AND (:store_id IS NULL OR e.store_id = :store_id::UUID)
GROUP BY s.store_name, s.id, e.emp_name, e.id, e.grade_level, s.serve_time_limit_min
ORDER BY total_dishes_served DESC
"""

DIMENSIONS = ["store_name", "runner_name", "employee_id", "grade_level"]
METRICS = [
    "order_count",
    "total_dishes_served",
    "avg_serve_duration_min",
    "timeout_order_count",
    "timeout_rate_pct",
    "commission_fen",
    "output_rank",
]
FILTERS = ["start_date", "end_date", "store_id"]
