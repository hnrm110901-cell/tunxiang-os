"""P0 报表: 最低消费补齐报表

按门店按日期统计设有最低消费的桌台订单，计算实际消费与最低消费的差额补齐情况。
关联 tables(min_consume_fen) + orders + stores。
金额单位: 分(fen), int。
"""

REPORT_ID = "min_spend_supplement"
REPORT_NAME = "最低消费补齐报表"
CATEGORY = "revenue"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    s.store_code,
    COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
    t.table_label,
    t.table_type,
    t.min_consume_fen,
    o.order_no,
    COALESCE(o.final_amount_fen, o.total_amount_fen - COALESCE(o.discount_amount_fen, 0)) AS actual_fen,
    GREATEST(
        t.min_consume_fen
        - COALESCE(o.final_amount_fen, o.total_amount_fen - COALESCE(o.discount_amount_fen, 0)),
        0
    ) AS supplement_fen,
    CASE
        WHEN COALESCE(o.final_amount_fen, o.total_amount_fen - COALESCE(o.discount_amount_fen, 0))
             >= t.min_consume_fen THEN 'met'
        ELSE 'supplemented'
    END AS status
FROM orders o
JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
JOIN tables t ON o.table_id = t.id AND t.tenant_id = o.tenant_id
WHERE o.tenant_id = :tenant_id
  AND o.is_deleted = FALSE
  AND o.status IN ('paid', 'completed')
  AND t.min_consume_fen > 0
  AND t.is_deleted = FALSE
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
ORDER BY biz_date DESC, supplement_fen DESC
"""

DIMENSIONS = ["store_name", "store_code", "biz_date", "table_label", "table_type", "order_no"]
METRICS = ["min_consume_fen", "actual_fen", "supplement_fen"]
FILTERS = ["start_date", "end_date", "store_id"]
