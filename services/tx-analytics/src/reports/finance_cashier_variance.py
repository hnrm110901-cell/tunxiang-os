"""中台财务报表: 收银差异明细/汇总

交班差异 — 系统金额 vs 实际清点金额。
用于发现收银漏洞和内控风险。
"""

REPORT_ID = "finance_cashier_variance"
REPORT_NAME = "收银差异明细表"
CATEGORY = "finance"

SQL_TEMPLATE = """
SELECT
    s.store_name,
    cs.shift_date AS biz_date,
    e.name AS cashier_name,
    e.employee_no AS cashier_no,
    cs.shift AS shift,
    cs.system_amount_fen,
    cs.actual_amount_fen,
    (cs.actual_amount_fen - cs.system_amount_fen) AS variance_fen,
    CASE WHEN cs.system_amount_fen > 0
         THEN ROUND((cs.actual_amount_fen - cs.system_amount_fen)::NUMERIC
                     / cs.system_amount_fen * 100, 2)
         ELSE 0
    END AS variance_pct,
    cs.cash_amount_fen,
    cs.wechat_amount_fen,
    cs.alipay_amount_fen,
    cs.unionpay_amount_fen,
    cs.other_amount_fen,
    cs.order_count,
    cs.remark
FROM cashier_shifts cs
JOIN stores s ON cs.store_id = s.id AND s.tenant_id = cs.tenant_id
LEFT JOIN employees e ON cs.cashier_id = e.id AND e.tenant_id = cs.tenant_id
WHERE cs.tenant_id = :tenant_id
  AND cs.is_deleted = FALSE
  AND cs.shift_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR cs.store_id = :store_id::UUID)
ORDER BY cs.shift_date DESC, s.store_name, cs.shift
"""

# 汇总查询 — 按收银员汇总差异
SQL_SUMMARY = """
SELECT
    e.name AS cashier_name,
    e.employee_no AS cashier_no,
    COUNT(*) AS shift_count,
    SUM(cs.system_amount_fen) AS total_system_fen,
    SUM(cs.actual_amount_fen) AS total_actual_fen,
    SUM(cs.actual_amount_fen - cs.system_amount_fen) AS total_variance_fen,
    COUNT(*) FILTER (WHERE ABS(cs.actual_amount_fen - cs.system_amount_fen) > 500)
        AS abnormal_shift_count,
    CASE WHEN SUM(cs.system_amount_fen) > 0
         THEN ROUND(SUM(cs.actual_amount_fen - cs.system_amount_fen)::NUMERIC
                     / SUM(cs.system_amount_fen) * 100, 2)
         ELSE 0
    END AS avg_variance_pct
FROM cashier_shifts cs
LEFT JOIN employees e ON cs.cashier_id = e.id AND e.tenant_id = cs.tenant_id
WHERE cs.tenant_id = :tenant_id
  AND cs.is_deleted = FALSE
  AND cs.shift_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR cs.store_id = :store_id::UUID)
GROUP BY e.name, e.employee_no
ORDER BY ABS(SUM(cs.actual_amount_fen - cs.system_amount_fen)) DESC
"""

DIMENSIONS = ["store_name", "biz_date", "cashier_name", "cashier_no", "shift"]
METRICS = [
    "system_amount_fen",
    "actual_amount_fen",
    "variance_fen",
    "variance_pct",
    "cash_amount_fen",
    "wechat_amount_fen",
    "alipay_amount_fen",
    "unionpay_amount_fen",
    "other_amount_fen",
    "order_count",
]
FILTERS = ["start_date", "end_date", "store_id"]
