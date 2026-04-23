"""P2 提成报表: 切配员业绩提成表

按切配员统计处理菜品数、处理重量、效率，计算切配提成。
关联 employees(role 含 'cutter'/技能含切配) + order_items(kds_station) + orders。
切配员按出品数量和效率计提成。
"""

REPORT_ID = "commission_cutter"
REPORT_NAME = "切配员业绩提成表"
CATEGORY = "commission"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    e.emp_name AS cutter_name,
    e.id AS employee_id,
    e.grade_level,
    -- 关联切配员的出品（通过 kds_station 和档口匹配）
    COUNT(DISTINCT o.id) AS order_count,
    COALESCE(SUM(oi.quantity), 0) AS total_dishes_cut,
    COALESCE(SUM(oi.subtotal_fen), 0) AS total_dish_value_fen,
    -- 称重菜品处理量
    COALESCE(SUM(oi.weight_value), 0) AS total_weight_kg,
    -- 退菜关联数
    SUM(oi.quantity) FILTER (WHERE oi.return_flag = TRUE) AS return_dish_qty,
    -- 切配提成 = 出品数 * 单品提成（暂按每份0.5元=50分估算）
    COALESCE(SUM(oi.quantity), 0) * 50 AS commission_fen,
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
  AND (e.role = 'chef' AND 'cutting' = ANY(e.skills))
  AND (:store_id IS NULL OR e.store_id = :store_id::UUID)
GROUP BY s.store_name, s.id, e.emp_name, e.id, e.grade_level
ORDER BY total_dishes_cut DESC
"""

DIMENSIONS = ["store_name", "cutter_name", "employee_id", "grade_level"]
METRICS = [
    "order_count",
    "total_dishes_cut",
    "total_dish_value_fen",
    "total_weight_kg",
    "return_dish_qty",
    "commission_fen",
    "output_rank",
]
FILTERS = ["start_date", "end_date", "store_id"]
