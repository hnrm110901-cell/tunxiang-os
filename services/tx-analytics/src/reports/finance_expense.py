"""中台财务报表: 费用分析（主要/超预算/同比）

按费用类别（食材/人力/租金/水电/其他）汇总，支持同比计算（去年同期）。
用于费用监控、预算管控和成本优化决策。
"""

REPORT_ID = "finance_expense"
REPORT_NAME = "费用分析表"
CATEGORY = "finance"

# 费用明细 — 按类别汇总
SQL_TEMPLATE = """
SELECT
    s.store_name,
    ex.expense_category,
    ex.expense_subcategory,
    SUM(ex.amount_fen) AS amount_fen,
    SUM(ex.budget_fen) AS budget_fen,
    CASE WHEN SUM(ex.budget_fen) > 0
         THEN ROUND(SUM(ex.amount_fen)::NUMERIC
                     / SUM(ex.budget_fen) * 100, 2)
         ELSE 0
    END AS budget_usage_pct,
    CASE WHEN SUM(ex.amount_fen) > SUM(ex.budget_fen)
              AND SUM(ex.budget_fen) > 0
         THEN SUM(ex.amount_fen) - SUM(ex.budget_fen)
         ELSE 0
    END AS over_budget_fen,
    COUNT(*) AS entry_count
FROM expenses ex
JOIN stores s ON ex.store_id = s.id AND s.tenant_id = ex.tenant_id
WHERE ex.tenant_id = :tenant_id
  AND ex.is_deleted = FALSE
  AND ex.expense_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR ex.store_id = :store_id::UUID)
GROUP BY s.store_name, ex.expense_category, ex.expense_subcategory
ORDER BY amount_fen DESC
"""

# 同比查询 — 去年同期
SQL_YEAR_OVER_YEAR = """
WITH current_period AS (
    SELECT
        ex.expense_category,
        SUM(ex.amount_fen) AS current_amount_fen
    FROM expenses ex
    WHERE ex.tenant_id = :tenant_id
      AND ex.is_deleted = FALSE
      AND ex.expense_date BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR ex.store_id = :store_id::UUID)
    GROUP BY ex.expense_category
),
last_year_period AS (
    SELECT
        ex.expense_category,
        SUM(ex.amount_fen) AS last_year_amount_fen
    FROM expenses ex
    WHERE ex.tenant_id = :tenant_id
      AND ex.is_deleted = FALSE
      AND ex.expense_date BETWEEN (:start_date::DATE - INTERVAL '1 year')
                              AND (:end_date::DATE - INTERVAL '1 year')
      AND (:store_id IS NULL OR ex.store_id = :store_id::UUID)
    GROUP BY ex.expense_category
)
SELECT
    COALESCE(c.expense_category, l.expense_category) AS expense_category,
    COALESCE(c.current_amount_fen, 0) AS current_amount_fen,
    COALESCE(l.last_year_amount_fen, 0) AS last_year_amount_fen,
    COALESCE(c.current_amount_fen, 0) - COALESCE(l.last_year_amount_fen, 0)
        AS yoy_change_fen,
    CASE WHEN COALESCE(l.last_year_amount_fen, 0) > 0
         THEN ROUND((COALESCE(c.current_amount_fen, 0)
                     - COALESCE(l.last_year_amount_fen, 0))::NUMERIC
                     / l.last_year_amount_fen * 100, 2)
         ELSE NULL
    END AS yoy_change_pct
FROM current_period c
FULL OUTER JOIN last_year_period l ON c.expense_category = l.expense_category
ORDER BY COALESCE(c.current_amount_fen, 0) DESC
"""

# 超预算项目列表
SQL_OVER_BUDGET = """
SELECT
    s.store_name,
    ex.expense_category,
    ex.expense_subcategory,
    SUM(ex.amount_fen) AS amount_fen,
    SUM(ex.budget_fen) AS budget_fen,
    SUM(ex.amount_fen) - SUM(ex.budget_fen) AS over_budget_fen,
    ROUND((SUM(ex.amount_fen) - SUM(ex.budget_fen))::NUMERIC
          / NULLIF(SUM(ex.budget_fen), 0) * 100, 2) AS over_budget_pct
FROM expenses ex
JOIN stores s ON ex.store_id = s.id AND s.tenant_id = ex.tenant_id
WHERE ex.tenant_id = :tenant_id
  AND ex.is_deleted = FALSE
  AND ex.expense_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR ex.store_id = :store_id::UUID)
GROUP BY s.store_name, ex.expense_category, ex.expense_subcategory
HAVING SUM(ex.amount_fen) > SUM(ex.budget_fen) AND SUM(ex.budget_fen) > 0
ORDER BY over_budget_fen DESC
"""

EXPENSE_CATEGORIES = ["food_material", "labor", "rent", "utilities", "other"]

DIMENSIONS = ["store_name", "expense_category", "expense_subcategory"]
METRICS = [
    "amount_fen",
    "budget_fen",
    "budget_usage_pct",
    "over_budget_fen",
    "entry_count",
]
FILTERS = ["start_date", "end_date", "store_id"]
