"""P2 提成报表: 点单员业绩提成表

按点单员统计点单数、点单金额、菜品推荐成功率，计算点单提成。
关联 employees + orders(waiter_id 兼点单员) + order_items。
点单员通常与服务员同一角色，但侧重点单环节的菜品推荐和高毛利菜品占比。
"""

REPORT_ID = "commission_orderer"
REPORT_NAME = "点单员业绩提成表"
CATEGORY = "commission"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    e.emp_name AS orderer_name,
    e.id AS employee_id,
    e.grade_level,
    COUNT(DISTINCT o.id) AS order_count,
    SUM(oi.quantity) AS total_dishes,
    SUM(oi.subtotal_fen) AS total_dish_revenue_fen,
    -- 高毛利菜品占比（毛利率>=60%的菜品数量占比）
    CASE WHEN SUM(oi.quantity) > 0
         THEN ROUND(
             SUM(oi.quantity) FILTER (
                 WHERE oi.food_cost_fen IS NOT NULL
                   AND oi.subtotal_fen > 0
                   AND (oi.subtotal_fen - oi.food_cost_fen * oi.quantity)::NUMERIC / oi.subtotal_fen >= 0.60
             )::NUMERIC / SUM(oi.quantity) * 100, 2)
         ELSE 0
    END AS high_margin_dish_pct,
    -- 推荐菜品数（is_recommended 标记）
    SUM(oi.quantity) FILTER (WHERE d.is_recommended = TRUE) AS recommended_dish_qty,
    -- 赠菜数
    SUM(oi.quantity) FILTER (WHERE oi.gift_flag = TRUE) AS gift_dish_qty,
    -- 点单提成 = 总菜品营收 * 0.3%
    ROUND(SUM(oi.subtotal_fen) * 0.003) AS commission_fen,
    RANK() OVER (PARTITION BY s.id ORDER BY SUM(oi.subtotal_fen) DESC) AS revenue_rank
FROM employees e
JOIN stores s ON e.store_id = s.id AND s.tenant_id = e.tenant_id
LEFT JOIN orders o ON o.waiter_id = e.id::TEXT
    AND o.tenant_id = e.tenant_id
    AND o.is_deleted = FALSE
    AND o.status IN ('completed', 'paid')
    AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
LEFT JOIN order_items oi ON oi.order_id = o.id
    AND oi.tenant_id = o.tenant_id
    AND oi.is_deleted = FALSE
LEFT JOIN dishes d ON oi.dish_id = d.id AND d.tenant_id = oi.tenant_id
WHERE e.tenant_id = :tenant_id
  AND e.is_deleted = FALSE
  AND e.is_active = TRUE
  AND e.role IN ('waiter', 'manager')
  AND (:store_id IS NULL OR e.store_id = :store_id::UUID)
GROUP BY s.store_name, s.id, e.emp_name, e.id, e.grade_level
ORDER BY total_dish_revenue_fen DESC
"""

DIMENSIONS = ["store_name", "orderer_name", "employee_id", "grade_level"]
METRICS = [
    "order_count", "total_dishes", "total_dish_revenue_fen",
    "high_margin_dish_pct", "recommended_dish_qty", "gift_dish_qty",
    "commission_fen", "revenue_rank",
]
FILTERS = ["start_date", "end_date", "store_id"]
