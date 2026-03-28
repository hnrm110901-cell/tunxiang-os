"""P2 稽核报表: 销售转出库结转状况表

对比销售消耗（按BOM理论用量）与实际出库，分析结转差异。
关联 orders + order_items(BOM成本) + ingredient_transactions(实际出库) + ingredients。
"""

REPORT_ID = "sales_transfer"
REPORT_NAME = "销售转出库结转状况表"
CATEGORY = "audit"

SQL_TEMPLATE = """
WITH sales_bom AS (
    -- 按菜品汇总BOM理论消耗成本
    SELECT
        o.store_id,
        COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
        SUM(oi.quantity) AS total_dish_qty,
        SUM(COALESCE(oi.food_cost_fen, 0) * oi.quantity) AS bom_cost_fen
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.id AND oi.tenant_id = o.tenant_id
    WHERE o.tenant_id = :tenant_id
      AND o.is_deleted = FALSE
      AND oi.is_deleted = FALSE
      AND o.status IN ('completed', 'paid')
      AND oi.food_cost_fen IS NOT NULL
      AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
    GROUP BY o.store_id, COALESCE(o.biz_date, DATE(o.created_at))
),
actual_outbound AS (
    -- 实际出库成本（usage类型流水）
    SELECT
        it.store_id,
        DATE(it.transaction_time) AS biz_date,
        COUNT(*) AS txn_count,
        COALESCE(SUM(ABS(it.total_cost_fen)), 0) AS actual_outbound_fen
    FROM ingredient_transactions it
    WHERE it.tenant_id = :tenant_id
      AND it.is_deleted = FALSE
      AND it.transaction_type = 'usage'
      AND DATE(it.transaction_time) BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR it.store_id = :store_id::UUID)
    GROUP BY it.store_id, DATE(it.transaction_time)
)
SELECT
    s.store_name,
    s.store_code,
    sb.biz_date,
    sb.total_dish_qty,
    sb.bom_cost_fen,
    COALESCE(ao.actual_outbound_fen, 0) AS actual_outbound_fen,
    COALESCE(ao.txn_count, 0) AS txn_count,
    -- 结转差异 = 实际出库 - BOM理论
    COALESCE(ao.actual_outbound_fen, 0) - sb.bom_cost_fen AS variance_fen,
    -- 差异率
    CASE WHEN sb.bom_cost_fen > 0
         THEN ROUND((COALESCE(ao.actual_outbound_fen, 0) - sb.bom_cost_fen)::NUMERIC
                     / sb.bom_cost_fen * 100, 2)
         ELSE 0
    END AS variance_rate_pct,
    -- 差异状态
    CASE
        WHEN ABS(COALESCE(ao.actual_outbound_fen, 0) - sb.bom_cost_fen) <= sb.bom_cost_fen * 0.05
            THEN 'ok'
        WHEN ABS(COALESCE(ao.actual_outbound_fen, 0) - sb.bom_cost_fen) <= sb.bom_cost_fen * 0.10
            THEN 'warning'
        ELSE 'critical'
    END AS variance_status
FROM sales_bom sb
JOIN stores s ON sb.store_id = s.id AND s.tenant_id = :tenant_id
LEFT JOIN actual_outbound ao ON ao.store_id = sb.store_id AND ao.biz_date = sb.biz_date
ORDER BY sb.biz_date DESC, variance_rate_pct DESC
"""

DIMENSIONS = ["store_name", "store_code", "biz_date", "variance_status"]
METRICS = [
    "total_dish_qty", "bom_cost_fen", "actual_outbound_fen",
    "txn_count", "variance_fen", "variance_rate_pct",
]
FILTERS = ["start_date", "end_date", "store_id"]
