"""中台财务报表: 损益分析明细表

损益 = 营收 - 食材成本 - 人力成本 - 租金 - 其他
从 orders + expenses 表汇总，生成完整损益结构。
"""

REPORT_ID = "finance_profit_loss"
REPORT_NAME = "损益分析明细表"
CATEGORY = "finance"

# 营收汇总
SQL_REVENUE = """
SELECT
    s.store_name,
    COALESCE(o.sales_channel, 'dine_in') AS channel,
    COUNT(*) AS order_count,
    SUM(COALESCE(o.final_amount_fen,
        o.total_amount_fen - COALESCE(o.discount_amount_fen, 0))) AS revenue_fen
FROM orders o
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND o.status = 'paid'
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY s.store_name, COALESCE(o.sales_channel, 'dine_in')
ORDER BY revenue_fen DESC
"""

# 成本费用汇总（按大类）
SQL_COSTS = """
SELECT
    ex.expense_category,
    SUM(ex.amount_fen) AS amount_fen
FROM expenses ex
WHERE ex.tenant_id = :tenant_id
  AND ex.is_deleted = FALSE
  AND ex.expense_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR ex.store_id = :store_id::UUID)
GROUP BY ex.expense_category
ORDER BY amount_fen DESC
"""

# 完整损益 — 一条SQL出全貌
SQL_FULL_PNL = """
WITH rev AS (
    SELECT
        COALESCE(SUM(COALESCE(o.final_amount_fen,
            o.total_amount_fen - COALESCE(o.discount_amount_fen, 0))), 0) AS total_revenue_fen
    FROM orders o
    WHERE o.tenant_id = :tenant_id
      AND o.is_deleted = FALSE
      AND o.status = 'paid'
      AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
),
costs AS (
    SELECT
        COALESCE(SUM(CASE WHEN expense_category = 'food_material'
                     THEN amount_fen ELSE 0 END), 0) AS food_cost_fen,
        COALESCE(SUM(CASE WHEN expense_category = 'labor'
                     THEN amount_fen ELSE 0 END), 0) AS labor_cost_fen,
        COALESCE(SUM(CASE WHEN expense_category = 'rent'
                     THEN amount_fen ELSE 0 END), 0) AS rent_fen,
        COALESCE(SUM(CASE WHEN expense_category = 'utilities'
                     THEN amount_fen ELSE 0 END), 0) AS utilities_fen,
        COALESCE(SUM(CASE WHEN expense_category NOT IN
                     ('food_material', 'labor', 'rent', 'utilities')
                     THEN amount_fen ELSE 0 END), 0) AS other_cost_fen,
        COALESCE(SUM(amount_fen), 0) AS total_cost_fen
    FROM expenses
    WHERE tenant_id = :tenant_id
      AND is_deleted = FALSE
      AND expense_date BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR store_id = :store_id::UUID)
)
SELECT
    rev.total_revenue_fen,
    costs.food_cost_fen,
    costs.labor_cost_fen,
    costs.rent_fen,
    costs.utilities_fen,
    costs.other_cost_fen,
    costs.total_cost_fen,
    (rev.total_revenue_fen - costs.food_cost_fen) AS gross_profit_fen,
    (rev.total_revenue_fen - costs.total_cost_fen) AS net_profit_fen,
    CASE WHEN rev.total_revenue_fen > 0
         THEN ROUND((rev.total_revenue_fen - costs.food_cost_fen)::NUMERIC
                     / rev.total_revenue_fen * 100, 2)
         ELSE 0
    END AS gross_margin_pct,
    CASE WHEN rev.total_revenue_fen > 0
         THEN ROUND((rev.total_revenue_fen - costs.total_cost_fen)::NUMERIC
                     / rev.total_revenue_fen * 100, 2)
         ELSE 0
    END AS net_margin_pct,
    CASE WHEN rev.total_revenue_fen > 0
         THEN ROUND(costs.food_cost_fen::NUMERIC
                     / rev.total_revenue_fen * 100, 2)
         ELSE 0
    END AS food_cost_ratio_pct,
    CASE WHEN rev.total_revenue_fen > 0
         THEN ROUND(costs.labor_cost_fen::NUMERIC
                     / rev.total_revenue_fen * 100, 2)
         ELSE 0
    END AS labor_cost_ratio_pct
FROM rev, costs
"""

DIMENSIONS = ["store_name", "channel"]
METRICS = [
    "total_revenue_fen", "food_cost_fen", "labor_cost_fen", "rent_fen",
    "utilities_fen", "other_cost_fen", "total_cost_fen",
    "gross_profit_fen", "net_profit_fen",
    "gross_margin_pct", "net_margin_pct",
    "food_cost_ratio_pct", "labor_cost_ratio_pct",
]
FILTERS = ["start_date", "end_date", "store_id"]
