"""供应链报表: 入库明细表

逐笔展示入库记录，含批次号、供应商、数量、单价、金额。
"""

REPORT_ID = "scm_receiving_detail"
REPORT_NAME = "入库明细表"
CATEGORY = "supply"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    it.tx_date,
    i.name AS ingredient_name,
    i.category AS ingredient_category,
    it.batch_no,
    it.supplier_name,
    it.qty,
    it.unit,
    it.unit_price_fen,
    it.cost_fen,
    it.operator_name,
    it.remark
FROM inventory_transactions it
JOIN stores s ON it.store_id = s.id AND s.tenant_id = it.tenant_id
LEFT JOIN ingredients i ON it.ingredient_id = i.id AND i.tenant_id = it.tenant_id
WHERE it.tenant_id = :tenant_id
  AND it.is_deleted = FALSE
  AND it.tx_type = 'purchase'
  AND it.tx_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR it.store_id = :store_id::UUID)
ORDER BY it.tx_date DESC, it.created_at DESC
"""

DIMENSIONS = ["store_name", "tx_date", "ingredient_name", "ingredient_category",
              "batch_no", "supplier_name", "operator_name"]
METRICS = ["qty", "unit_price_fen", "cost_fen"]
FILTERS = ["start_date", "end_date", "store_id"]
