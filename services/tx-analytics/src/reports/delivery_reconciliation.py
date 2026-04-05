"""P0 报表: 平台外卖对账表

对比系统内外卖订单金额与平台结算金额，发现差异单据。
关联 delivery_orders(系统记录) vs delivery_reconciliations(平台数据)。
金额单位: 分(fen), int。
"""

REPORT_ID = "delivery_reconciliation"
REPORT_NAME = "平台外卖对账表"
CATEGORY = "audit"

SQL_TEMPLATE = """
WITH system_orders AS (
    SELECT
        d.id AS delivery_order_id,
        d.platform,
        d.platform_order_no,
        d.store_id,
        d.order_amount_fen AS system_amount_fen,
        d.commission_fen AS system_commission_fen,
        d.status AS system_status,
        COALESCE(d.biz_date, DATE(d.created_at)) AS biz_date
    FROM delivery_orders d
    WHERE d.tenant_id = :tenant_id
      AND d.is_deleted = FALSE
      AND COALESCE(d.biz_date, DATE(d.created_at)) BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR d.store_id = :store_id::UUID)
),
platform_data AS (
    SELECT
        dr.platform_order_no,
        dr.platform,
        dr.platform_amount_fen,
        dr.platform_commission_fen,
        dr.settlement_status
    FROM delivery_reconciliations dr
    WHERE dr.tenant_id = :tenant_id
      AND dr.is_deleted = FALSE
      AND dr.biz_date BETWEEN :start_date AND :end_date
      AND (:store_id IS NULL OR dr.store_id = :store_id::UUID)
)
SELECT
    s.store_name,
    so.biz_date,
    so.platform,
    so.platform_order_no,
    so.system_amount_fen,
    COALESCE(pd.platform_amount_fen, 0) AS platform_amount_fen,
    so.system_amount_fen - COALESCE(pd.platform_amount_fen, 0) AS amount_diff_fen,
    so.system_commission_fen,
    COALESCE(pd.platform_commission_fen, 0) AS platform_commission_fen,
    so.system_commission_fen - COALESCE(pd.platform_commission_fen, 0) AS commission_diff_fen,
    so.system_status,
    COALESCE(pd.settlement_status, 'missing') AS platform_status,
    CASE
        WHEN pd.platform_order_no IS NULL THEN 'platform_missing'
        WHEN ABS(so.system_amount_fen - pd.platform_amount_fen) > 0 THEN 'amount_mismatch'
        WHEN ABS(so.system_commission_fen - COALESCE(pd.platform_commission_fen, 0)) > 0 THEN 'commission_mismatch'
        ELSE 'matched'
    END AS reconciliation_status
FROM system_orders so
JOIN stores s ON so.store_id = s.id AND s.tenant_id = :tenant_id
LEFT JOIN platform_data pd
    ON so.platform_order_no = pd.platform_order_no
    AND so.platform = pd.platform
ORDER BY so.biz_date DESC,
    CASE WHEN pd.platform_order_no IS NULL THEN 0
         WHEN ABS(so.system_amount_fen - COALESCE(pd.platform_amount_fen, 0)) > 0 THEN 1
         ELSE 2
    END,
    ABS(so.system_amount_fen - COALESCE(pd.platform_amount_fen, 0)) DESC
"""

DIMENSIONS = ["store_name", "biz_date", "platform", "platform_order_no"]
METRICS = [
    "system_amount_fen", "platform_amount_fen", "amount_diff_fen",
    "system_commission_fen", "platform_commission_fen", "commission_diff_fen",
    "reconciliation_status",
]
FILTERS = ["start_date", "end_date", "store_id"]
