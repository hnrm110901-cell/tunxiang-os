"""中台财务报表: 储值卡充值汇总（电子+实体）

按储值卡类型（电子/实体）、充值方式、门店汇总充值交易。
用于监控储值业务和预收款管理。
"""

REPORT_ID = "finance_stored_value"
REPORT_NAME = "储值卡充值汇总表"
CATEGORY = "finance"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    COALESCE(sv.biz_date, DATE(sv.created_at)) AS biz_date,
    sv.card_type,
    sv.tx_type,
    COUNT(*) AS tx_count,
    SUM(sv.charge_amount_fen) AS charge_amount_fen,
    SUM(sv.gift_amount_fen) AS gift_amount_fen,
    SUM(sv.charge_amount_fen + sv.gift_amount_fen) AS total_amount_fen,
    COUNT(DISTINCT sv.member_id) AS member_count,
    CASE WHEN SUM(sv.charge_amount_fen) > 0
         THEN ROUND(SUM(sv.gift_amount_fen)::NUMERIC
                     / SUM(sv.charge_amount_fen) * 100, 2)
         ELSE 0
    END AS gift_rate_pct
FROM stored_value_transactions sv
JOIN stores s ON sv.store_id = s.id AND s.tenant_id = sv.tenant_id
WHERE sv.tenant_id = :tenant_id
  AND sv.is_deleted = FALSE
  AND sv.status = 'success'
  AND COALESCE(sv.biz_date, DATE(sv.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR sv.store_id = :store_id::UUID)
GROUP BY s.store_name,
         COALESCE(sv.biz_date, DATE(sv.created_at)),
         sv.card_type, sv.tx_type
ORDER BY biz_date DESC, charge_amount_fen DESC
"""

# 汇总 — 按卡类型汇总
SQL_BY_CARD_TYPE = """
SELECT
    sv.card_type,
    COUNT(*) AS tx_count,
    SUM(sv.charge_amount_fen) AS charge_amount_fen,
    SUM(sv.gift_amount_fen) AS gift_amount_fen,
    SUM(sv.charge_amount_fen + sv.gift_amount_fen) AS total_amount_fen,
    COUNT(DISTINCT sv.member_id) AS unique_members
FROM stored_value_transactions sv
WHERE sv.tenant_id = :tenant_id
  AND sv.is_deleted = FALSE
  AND sv.status = 'success'
  AND COALESCE(sv.biz_date, DATE(sv.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR sv.store_id = :store_id::UUID)
GROUP BY sv.card_type
ORDER BY charge_amount_fen DESC
"""

DIMENSIONS = ["store_name", "biz_date", "card_type", "tx_type"]
METRICS = [
    "tx_count", "charge_amount_fen", "gift_amount_fen",
    "total_amount_fen", "member_count", "gift_rate_pct",
]
FILTERS = ["start_date", "end_date", "store_id"]
