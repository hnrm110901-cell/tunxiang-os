"""P2 提成报表: 业绩提成分门店汇总

按门店汇总各岗位业绩提成总额，含服务员/点单员/厨师/切配/传菜/收银。
关联 employees + orders + order_items。
"""

REPORT_ID = "commission_summary"
REPORT_NAME = "业绩提成分门店汇总"
CATEGORY = "commission"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    s.store_code,
    COUNT(DISTINCT e.id) AS employee_count,
    COUNT(DISTINCT o.id) AS total_orders,
    SUM(o.final_amount_fen) AS total_revenue_fen,
    -- 按岗位统计人数
    COUNT(DISTINCT e.id) FILTER (WHERE e.role = 'waiter') AS waiter_count,
    COUNT(DISTINCT e.id) FILTER (WHERE e.role = 'chef') AS chef_count,
    COUNT(DISTINCT e.id) FILTER (WHERE e.role = 'cashier') AS cashier_count,
    -- 按岗位关联的营收（用于提成基数）
    SUM(o.final_amount_fen) FILTER (WHERE e.role = 'waiter') AS waiter_revenue_fen,
    SUM(o.final_amount_fen) FILTER (WHERE e.role = 'chef') AS chef_revenue_fen,
    SUM(o.final_amount_fen) FILTER (WHERE e.role = 'cashier') AS cashier_revenue_fen,
    -- 人均产值
    CASE WHEN COUNT(DISTINCT e.id) > 0
         THEN SUM(o.final_amount_fen) / COUNT(DISTINCT e.id)
         ELSE 0
    END AS avg_revenue_per_emp_fen
FROM stores s
LEFT JOIN employees e ON e.store_id = s.id
    AND e.tenant_id = s.tenant_id
    AND e.is_active = TRUE
    AND e.is_deleted = FALSE
LEFT JOIN orders o ON o.store_id = s.id
    AND o.tenant_id = s.tenant_id
    AND o.is_deleted = FALSE
    AND o.status IN ('completed', 'paid')
    AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
    AND o.waiter_id = e.id::TEXT
WHERE s.tenant_id = :tenant_id
  AND s.is_deleted = FALSE
  AND s.store_type = 'physical'
  AND (:store_id IS NULL OR s.id = :store_id::UUID)
GROUP BY s.store_name, s.store_code
ORDER BY total_revenue_fen DESC
"""

DIMENSIONS = ["store_name", "store_code"]
METRICS = [
    "employee_count", "total_orders", "total_revenue_fen",
    "waiter_count", "chef_count", "cashier_count",
    "waiter_revenue_fen", "chef_revenue_fen", "cashier_revenue_fen",
    "avg_revenue_per_emp_fen",
]
FILTERS = ["start_date", "end_date", "store_id"]
