"""供应链报表: 收发结存表

按原料统计期初、入库、出库、期末数量和金额。
"""

REPORT_ID = "scm_receipt_balance"
REPORT_NAME = "收发结存表"
CATEGORY = "supply"

SQL_TEMPLATE = """
WITH period_in AS (
    SELECT ingredient_id, store_id,
           SUM(qty) AS in_qty, SUM(cost_fen) AS in_cost_fen
    FROM inventory_transactions
    WHERE tenant_id = :tenant_id AND is_deleted = FALSE
      AND tx_type IN ('purchase', 'transfer_in')
      AND tx_date BETWEEN :start_date AND :end_date
    GROUP BY ingredient_id, store_id
),
period_out AS (
    SELECT ingredient_id, store_id,
           SUM(qty) AS out_qty, SUM(cost_fen) AS out_cost_fen
    FROM inventory_transactions
    WHERE tenant_id = :tenant_id AND is_deleted = FALSE
      AND tx_type IN ('usage', 'waste', 'transfer_out')
      AND tx_date BETWEEN :start_date AND :end_date
    GROUP BY ingredient_id, store_id
)
SELECT
    s.store_name,
    i.name AS ingredient_name,
    i.category AS ingredient_category,
    i.unit,
    COALESCE(inv.current_qty
             - COALESCE(pi.in_qty, 0) + COALESCE(po.out_qty, 0), 0) AS opening_qty,
    COALESCE(pi.in_qty, 0) AS in_qty,
    COALESCE(pi.in_cost_fen, 0) AS in_cost_fen,
    COALESCE(po.out_qty, 0) AS out_qty,
    COALESCE(po.out_cost_fen, 0) AS out_cost_fen,
    inv.current_qty AS closing_qty,
    ROUND(inv.current_qty * inv.avg_cost_fen) AS closing_balance_fen
FROM inventory inv
JOIN stores s ON inv.store_id = s.id AND s.tenant_id = inv.tenant_id
JOIN ingredients i ON inv.ingredient_id = i.id AND i.tenant_id = inv.tenant_id
LEFT JOIN period_in pi ON pi.ingredient_id = inv.ingredient_id AND pi.store_id = inv.store_id
LEFT JOIN period_out po ON po.ingredient_id = inv.ingredient_id AND po.store_id = inv.store_id
WHERE inv.tenant_id = :tenant_id
  AND inv.is_deleted = FALSE
  AND (:store_id IS NULL OR inv.store_id = :store_id::UUID)
ORDER BY closing_balance_fen DESC
"""

DIMENSIONS = ["store_name", "ingredient_name", "ingredient_category", "unit"]
METRICS = ["opening_qty", "in_qty", "in_cost_fen", "out_qty", "out_cost_fen", "closing_qty", "closing_balance_fen"]
FILTERS = ["start_date", "end_date", "store_id"]
