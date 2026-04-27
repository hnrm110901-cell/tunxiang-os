"""供应链报表: 应收账户挂账明细表

展示客户/企业挂账明细及余额，支持按门店和时间范围筛选。
"""

REPORT_ID = "scm_ar_ledger"
REPORT_NAME = "应收账户挂账明细表"
CATEGORY = "supply"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    ar.account_name,
    ar.account_type,
    COALESCE(ar.biz_date, DATE(ar.created_at)) AS biz_date,
    ar.order_no,
    ar.debit_fen,
    ar.credit_fen,
    SUM(ar.debit_fen - ar.credit_fen)
        OVER (PARTITION BY ar.account_name ORDER BY COALESCE(ar.biz_date, DATE(ar.created_at)), ar.created_at) AS running_balance_fen,
    ar.remark,
    ar.operator_name
FROM ar_ledger_entries ar
JOIN stores s ON ar.store_id = s.id AND s.tenant_id = ar.tenant_id
WHERE ar.tenant_id = :tenant_id
  AND ar.is_deleted = FALSE
  AND COALESCE(ar.biz_date, DATE(ar.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR ar.store_id = :store_id::UUID)
ORDER BY ar.account_name, COALESCE(ar.biz_date, DATE(ar.created_at)), ar.created_at
"""

DIMENSIONS = ["store_name", "account_name", "account_type", "biz_date", "order_no", "operator_name"]
METRICS = ["debit_fen", "credit_fen", "running_balance_fen"]
FILTERS = ["start_date", "end_date", "store_id"]
