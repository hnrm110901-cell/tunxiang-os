"""供应链报表: 库存台账

逐笔展示库存变动流水，按时间倒序。
"""

REPORT_ID = "scm_inventory_ledger"
REPORT_NAME = "库存台账"
CATEGORY = "supply"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    it.tx_date,
    i.name AS ingredient_name,
    i.category AS ingredient_category,
    it.tx_type,
    CASE it.tx_type
        WHEN 'purchase' THEN '采购入库'
        WHEN 'usage' THEN '消耗出库'
        WHEN 'waste' THEN '报损'
        WHEN 'transfer_out' THEN '调拨出库'
        WHEN 'transfer_in' THEN '调拨入库'
        WHEN 'stocktake' THEN '盘点调整'
        ELSE it.tx_type
    END AS tx_type_label,
    it.qty,
    it.unit,
    it.unit_price_fen,
    it.cost_fen,
    it.batch_no,
    it.supplier_name,
    it.operator_name,
    it.remark
FROM inventory_transactions it
JOIN stores s ON it.store_id = s.id AND s.tenant_id = it.tenant_id
LEFT JOIN ingredients i ON it.ingredient_id = i.id AND i.tenant_id = it.tenant_id
WHERE it.tenant_id = :tenant_id
  AND it.is_deleted = FALSE
  AND it.tx_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR it.store_id = :store_id::UUID)
  AND (:ingredient_id IS NULL OR it.ingredient_id = :ingredient_id::UUID)
ORDER BY it.tx_date DESC, it.created_at DESC
"""

DIMENSIONS = [
    "store_name",
    "tx_date",
    "ingredient_name",
    "ingredient_category",
    "tx_type",
    "tx_type_label",
    "batch_no",
    "supplier_name",
    "operator_name",
]
METRICS = ["qty", "unit_price_fen", "cost_fen"]
FILTERS = ["start_date", "end_date", "store_id", "ingredient_id"]
