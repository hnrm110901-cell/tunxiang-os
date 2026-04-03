"""中台财务报表: 库存分析/采购明细/盘点明细/调拨明细

基于 inventory_transactions 表按交易类型汇总。
覆盖采购入库、消耗出库、盘点调整、门店调拨四大场景。
"""

REPORT_ID = "finance_inventory"
REPORT_NAME = "库存分析/采购/盘点/调拨明细表"
CATEGORY = "finance"

# 库存交易汇总 — 按类型
SQL_SUMMARY_BY_TYPE = """
SELECT
    it.tx_type,
    COUNT(*) AS tx_count,
    SUM(it.qty) AS total_qty,
    SUM(it.cost_fen) AS total_cost_fen,
    COUNT(DISTINCT it.ingredient_id) AS ingredient_count
FROM inventory_transactions it
WHERE it.tenant_id = :tenant_id
  AND it.is_deleted = FALSE
  AND it.tx_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR it.store_id = :store_id::UUID)
GROUP BY it.tx_type
ORDER BY total_cost_fen DESC
"""

# 采购明细
SQL_PURCHASE_DETAIL = """
SELECT
    s.store_name,
    it.tx_date,
    i.name AS ingredient_name,
    i.category AS ingredient_category,
    it.qty,
    it.unit,
    it.unit_price_fen,
    it.cost_fen,
    it.supplier_name,
    it.batch_no,
    it.remark
FROM inventory_transactions it
JOIN stores s ON it.store_id = s.id AND s.tenant_id = it.tenant_id
LEFT JOIN ingredients i ON it.ingredient_id = i.id AND i.tenant_id = it.tenant_id
WHERE it.tenant_id = :tenant_id
  AND it.is_deleted = FALSE
  AND it.tx_type = 'purchase'
  AND it.tx_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR it.store_id = :store_id::UUID)
ORDER BY it.tx_date DESC, it.cost_fen DESC
"""

# 盘点明细
SQL_STOCKTAKE_DETAIL = """
SELECT
    s.store_name,
    it.tx_date,
    i.name AS ingredient_name,
    it.expected_qty,
    it.actual_qty,
    (it.actual_qty - it.expected_qty) AS variance_qty,
    it.unit,
    it.cost_fen AS variance_cost_fen,
    it.operator_name,
    it.remark
FROM inventory_transactions it
JOIN stores s ON it.store_id = s.id AND s.tenant_id = it.tenant_id
LEFT JOIN ingredients i ON it.ingredient_id = i.id AND i.tenant_id = it.tenant_id
WHERE it.tenant_id = :tenant_id
  AND it.is_deleted = FALSE
  AND it.tx_type = 'stocktake'
  AND it.tx_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR it.store_id = :store_id::UUID)
ORDER BY it.tx_date DESC, ABS(it.cost_fen) DESC
"""

# 调拨明细
SQL_TRANSFER_DETAIL = """
SELECT
    sf.store_name AS from_store,
    st.store_name AS to_store,
    it.tx_date,
    i.name AS ingredient_name,
    it.qty,
    it.unit,
    it.cost_fen,
    it.operator_name,
    it.remark
FROM inventory_transactions it
JOIN stores sf ON it.store_id = sf.id AND sf.tenant_id = it.tenant_id
LEFT JOIN stores st ON it.to_store_id = st.id AND st.tenant_id = it.tenant_id
LEFT JOIN ingredients i ON it.ingredient_id = i.id AND i.tenant_id = it.tenant_id
WHERE it.tenant_id = :tenant_id
  AND it.is_deleted = FALSE
  AND it.tx_type = 'transfer'
  AND it.tx_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL
       OR it.store_id = :store_id::UUID
       OR it.to_store_id = :store_id::UUID)
ORDER BY it.tx_date DESC
"""

DIMENSIONS = ["store_name", "tx_date", "ingredient_name", "tx_type"]
METRICS = ["tx_count", "total_qty", "total_cost_fen", "ingredient_count"]
FILTERS = ["start_date", "end_date", "store_id"]
