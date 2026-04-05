"""P0 报表: 预定明细统计

按门店按日期统计预定量，按状态(confirmed/seated/cancelled/no_show)和时段分布。
关联 reservations + stores。
"""

REPORT_ID = "reservation_detail"
REPORT_NAME = "预定明细统计"
CATEGORY = "operation"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    s.store_code,
    DATE(r.reservation_date) AS biz_date,
    COUNT(*) AS total_reservations,
    COUNT(*) FILTER (WHERE r.status = 'confirmed') AS confirmed_count,
    COUNT(*) FILTER (WHERE r.status = 'seated') AS seated_count,
    COUNT(*) FILTER (WHERE r.status = 'cancelled') AS cancelled_count,
    COUNT(*) FILTER (WHERE r.status = 'no_show') AS no_show_count,
    -- 到店率
    CASE WHEN COUNT(*) > 0
         THEN ROUND(
             COUNT(*) FILTER (WHERE r.status = 'seated')::NUMERIC / COUNT(*) * 100, 2
         )
         ELSE 0
    END AS seated_pct,
    -- 按时段分布
    COUNT(*) FILTER (WHERE r.time_slot = 'lunch') AS lunch_count,
    COUNT(*) FILTER (WHERE r.time_slot = 'dinner') AS dinner_count,
    COUNT(*) FILTER (WHERE r.time_slot NOT IN ('lunch', 'dinner')) AS other_slot_count,
    -- 按来源分布
    COUNT(*) FILTER (WHERE r.source = 'phone') AS source_phone,
    COUNT(*) FILTER (WHERE r.source = 'wechat') AS source_wechat,
    COUNT(*) FILTER (WHERE r.source = 'app') AS source_app,
    COUNT(*) FILTER (WHERE r.source NOT IN ('phone', 'wechat', 'app')) AS source_other,
    -- 预定人数汇总
    COALESCE(SUM(r.guest_count), 0) AS total_guests
FROM reservations r
JOIN stores s ON r.store_id = s.id AND s.tenant_id = r.tenant_id
WHERE r.tenant_id = :tenant_id
  AND r.is_deleted = FALSE
  AND DATE(r.reservation_date) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR r.store_id = :store_id::UUID)
GROUP BY s.store_name, s.store_code, DATE(r.reservation_date)
ORDER BY biz_date DESC, total_reservations DESC
"""

DIMENSIONS = ["store_name", "store_code", "biz_date"]
METRICS = [
    "total_reservations", "confirmed_count", "seated_count",
    "cancelled_count", "no_show_count", "seated_pct",
    "lunch_count", "dinner_count", "other_slot_count",
    "source_phone", "source_wechat", "source_app", "source_other",
    "total_guests",
]
FILTERS = ["start_date", "end_date", "store_id"]
