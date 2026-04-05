"""P0 报表: 挂账统计

按门店统计企业挂账客户的信用额度使用情况。
关联 credit_accounts + credit_transactions + stores。
金额单位: 分(fen), int。
"""

REPORT_ID = "credit_account_stats"
REPORT_NAME = "挂账统计"
CATEGORY = "audit"

SQL_TEMPLATE = """
WITH latest_txn AS (
    SELECT
        ct.credit_account_id,
        MAX(ct.created_at) AS last_transaction_at
    FROM credit_transactions ct
    WHERE ct.tenant_id = :tenant_id
      AND ct.is_deleted = FALSE
    GROUP BY ct.credit_account_id
),
period_usage AS (
    SELECT
        ct.credit_account_id,
        SUM(CASE WHEN ct.transaction_type = 'charge' THEN ct.amount_fen ELSE 0 END) AS period_charged_fen,
        SUM(CASE WHEN ct.transaction_type = 'payment' THEN ct.amount_fen ELSE 0 END) AS period_paid_fen,
        COUNT(*) AS period_txn_count
    FROM credit_transactions ct
    WHERE ct.tenant_id = :tenant_id
      AND ct.is_deleted = FALSE
      AND DATE(ct.created_at) BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR ct.store_id = :store_id::UUID)
    GROUP BY ct.credit_account_id
)
SELECT
    s.store_name,
    s.store_code,
    ca.customer_name,
    ca.company_name,
    ca.credit_limit_fen,
    ca.used_fen,
    ca.credit_limit_fen - ca.used_fen AS balance_fen,
    CASE WHEN ca.credit_limit_fen > 0
         THEN ROUND(ca.used_fen::NUMERIC / ca.credit_limit_fen * 100, 2)
         ELSE 0
    END AS usage_rate_pct,
    COALESCE(pu.period_charged_fen, 0) AS period_charged_fen,
    COALESCE(pu.period_paid_fen, 0) AS period_paid_fen,
    COALESCE(pu.period_txn_count, 0) AS period_txn_count,
    lt.last_transaction_at
FROM credit_accounts ca
JOIN stores s ON ca.store_id = s.id AND s.tenant_id = ca.tenant_id
LEFT JOIN latest_txn lt ON lt.credit_account_id = ca.id
LEFT JOIN period_usage pu ON pu.credit_account_id = ca.id
WHERE ca.tenant_id = :tenant_id
  AND ca.is_deleted = FALSE
  AND ca.is_active = TRUE
  AND (:store_id IS NULL OR ca.store_id = :store_id::UUID)
ORDER BY ca.used_fen DESC, usage_rate_pct DESC
"""

DIMENSIONS = ["store_name", "store_code", "customer_name", "company_name"]
METRICS = [
    "credit_limit_fen", "used_fen", "balance_fen", "usage_rate_pct",
    "period_charged_fen", "period_paid_fen", "period_txn_count",
    "last_transaction_at",
]
FILTERS = ["start_date", "end_date", "store_id"]
