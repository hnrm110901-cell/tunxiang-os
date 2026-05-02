"""财务域固定报表SKU — 30个模板

覆盖：日结/P&L/现金流/预算/成本结构/应收/应付/发票/对账
"""

from __future__ import annotations
from typing import Any

_TF = "tenant_id = :tenant_id AND is_deleted = FALSE"

FINANCE_SKUS: list[dict[str, Any]] = []


def _reg(sku_id: str, name: str, desc: str, cols: list[dict], sql: str,
         params: dict | None = None, domain: str = "finance") -> dict:
    return {
        "sku_id": f"{domain}_{sku_id}", "name": name, "description": desc,
        "domain": domain, "columns": cols, "sql": sql.strip(),
        "default_params": params or {},
    }


# ── 日结汇总 (5) ──────────────────────────────────────────────────────
FINANCE_SKUS += [
    _reg("daily_settlement", "日结汇总", "各支付方式收款汇总",
         [{"name":"payment_method","label":"支付方式"},{"name":"total_fen","label":"金额(分)"},
          {"name":"order_count","label":"订单数"},{"name":"share_pct","label":"占比","format":"0.0%"}],
         """SELECT p.payment_method, COALESCE(SUM(p.amount_fen),0) AS total_fen,
            COUNT(DISTINCT p.order_id) AS order_count,
            COALESCE(SUM(p.amount_fen),0)*100.0/SUM(COALESCE(SUM(p.amount_fen),0)) OVER() AS share_pct
            FROM payments p WHERE p.{} AND p.status='confirmed'
            AND p.paid_at>=:date_start AND p.paid_at<:date_end
            GROUP BY p.payment_method ORDER BY total_fen DESC""".format(_TF),
         {"date_start":"today()","date_end":"tomorrow()"}),
    _reg("daily_cash_flow", "现金流日报", "当日收款/退款/支出/净现金流",
         [{"name":"flow_type","label":"类型"},{"name":"total_fen","label":"金额(分)"},{"name":"count","label":"笔数"}],
         """SELECT '收款' AS flow_type, COALESCE(SUM(p.amount_fen),0) AS total_fen, COUNT(*) AS count
            FROM payments p WHERE p.{} AND p.status='confirmed' AND p.paid_at>=:date_start AND p.paid_at<:date_end
            UNION ALL
            SELECT '退款', COALESCE(SUM(r.refund_fen),0), COUNT(*)
            FROM order_refunds r WHERE r.{} AND r.created_at>=:date_start AND r.created_at<:date_end
            UNION ALL
            SELECT '支出', COALESCE(SUM(po.total_fen),0), COUNT(*)
            FROM purchase_orders po WHERE po.{} AND po.created_at>=:date_start AND po.created_at<:date_end""".format(_TF,_TF,_TF),
         {"date_start":"today()","date_end":"tomorrow()"}),
]

# ── P&L报表 (5) ──────────────────────────────────────────────────────
FINANCE_SKUS += [
    _reg("pnl_daily", "P&L日报", "收入/成本/费用/利润日度汇总",
         [{"name":"line_item","label":"科目"},{"name":"amount_fen","label":"金额(分)"}],
         """SELECT '营业收入' AS line_item, COALESCE(SUM(o.total_fen),0) AS amount_fen FROM orders o WHERE o.{} AND o.created_at>=:date_start AND o.created_at<:date_end
            UNION ALL SELECT '食材成本', COALESCE(SUM(oi.cost_fen),0) FROM order_items oi WHERE oi.{} AND oi.created_at>=:date_start AND oi.created_at<:date_end
            UNION ALL SELECT '人工成本', COALESCE(SUM(pr.salary_fen),0)/30 FROM payroll_records pr WHERE pr.{} AND pr.created_at>=:date_start AND pr.created_at<:date_end
            UNION ALL SELECT '租金', COALESCE(s.daily_rent_fen,0) FROM stores s WHERE s.{} AND s.id IN (SELECT DISTINCT store_id FROM orders WHERE {} AND created_at>=:date_start AND created_at<:date_end)
            UNION ALL SELECT '折扣', COALESCE(SUM(o.discount_fen),0) FROM orders o WHERE o.{} AND o.created_at>=:date_start AND o.created_at<:date_end
            UNION ALL SELECT '退款', COALESCE(SUM(r.refund_fen),0) FROM order_refunds r WHERE r.{} AND r.created_at>=:date_start AND r.created_at<:date_end""".format(_TF,_TF,_TF,_TF,_TF,_TF,_TF),
         {"date_start":"today()","date_end":"tomorrow()"}),
    _reg("pnl_monthly", "P&L月报", "月度损益表",
         [{"name":"line_item","label":"科目"},{"name":"current_month_fen","label":"本月(分)"},
          {"name":"last_month_fen","label":"上月(分)"},{"name":"mom_change_pct","label":"环比","format":"0.0%"}],
         """SELECT '营业收入' AS line_item,
            COALESCE(SUM(CASE WHEN o.created_at>=:this_month THEN o.total_fen ELSE 0 END),0) AS current_month_fen,
            COALESCE(SUM(CASE WHEN o.created_at>=:last_month AND o.created_at<:this_month THEN o.total_fen ELSE 0 END),0) AS last_month_fen
            FROM orders o WHERE o.tenant_id=:tenant_id AND o.is_deleted=FALSE""",
         {"this_month":"month_start()","last_month":"last_month_start()"}),
]

# ── 成本结构 (5) ──────────────────────────────────────────────────────
FINANCE_SKUS += [
    _reg("cost_structure", "成本结构分析", "食材/人工/租金/水电/其他占比",
         [{"name":"cost_category","label":"成本类别"},{"name":"amount_fen","label":"金额(分)"},
          {"name":"share_pct","label":"占比","format":"0.0%"},{"name":"revenue_ratio","label":"费用率","format":"0.0%"}],
         """WITH total_rev AS (SELECT COALESCE(SUM(total_fen),0) AS rev FROM orders WHERE {} AND created_at>=:date_start AND created_at<:date_end)
            SELECT '食材成本' AS cost_category, COALESCE(SUM(oi.cost_fen),0) AS amount_fen,
            COALESCE(SUM(oi.cost_fen),0)*100.0/(SELECT rev FROM total_rev) AS revenue_ratio
            FROM order_items oi WHERE oi.{} AND oi.created_at>=:date_start AND oi.created_at<:date_end""".format(_TF,_TF),
         {"date_start":"month_start()","date_end":"tomorrow()"}),
    _reg("food_cost_ratio_trend", "食材成本率趋势", "12个月食材成本率走势",
         [{"name":"month","label":"月份"},{"name":"food_cost_fen","label":"食材成本(分)"},
          {"name":"revenue_fen","label":"营收(分)"},{"name":"cost_ratio","label":"成本率","format":"0.0%"}],
         """SELECT TO_CHAR(gs.month,'YYYY-MM') AS month,
            COALESCE(SUM(oi.cost_fen),0) AS food_cost_fen, COALESCE(SUM(o.total_fen),0) AS revenue_fen,
            CASE WHEN COALESCE(SUM(o.total_fen),0)>0 THEN COALESCE(SUM(oi.cost_fen),0)*100.0/COALESCE(SUM(o.total_fen),0) ELSE 0 END AS cost_ratio
            FROM GENERATE_SERIES(:year_start,:year_end,INTERVAL'1 month') gs(month)
            LEFT JOIN orders o ON o.created_at>=gs.month AND o.created_at<gs.month+INTERVAL'1 month' AND o.tenant_id=:tenant_id AND o.is_deleted=FALSE
            LEFT JOIN order_items oi ON o.id=oi.order_id AND oi.tenant_id=:tenant_id AND oi.is_deleted=FALSE
            GROUP BY gs.month ORDER BY month""",
         {"year_start":"year_start()","year_end":"tomorrow()"}),
]

# ── 预算执行 (5) ──────────────────────────────────────────────────────
FINANCE_SKUS += [
    _reg("budget_vs_actual", "预算执行分析", "月度预算vs实际偏差",
         [{"name":"category","label":"科目"},{"name":"budget_fen","label":"预算(分)"},
          {"name":"actual_fen","label":"实际(分)"},{"name":"variance_fen","label":"偏差(分)"},
          {"name":"execution_rate","label":"执行率","format":"0.0%"}],
         """SELECT b.category, COALESCE(SUM(b.amount_fen),0) AS budget_fen,
            COALESCE(SUM(b.actual_fen),0) AS actual_fen,
            COALESCE(SUM(b.actual_fen),0)-COALESCE(SUM(b.amount_fen),0) AS variance_fen,
            CASE WHEN COALESCE(SUM(b.amount_fen),0)>0 THEN COALESCE(SUM(b.actual_fen),0)*100.0/COALESCE(SUM(b.amount_fen),0) ELSE 0 END AS execution_rate
            FROM budgets b WHERE b.{} AND b.period_start>=:month_start AND b.period_start<:month_end
            GROUP BY b.category ORDER BY ABS(COALESCE(SUM(b.actual_fen),0)-COALESCE(SUM(b.amount_fen),0)) DESC""".format(_TF),
         {"month_start":"month_start()","month_end":"tomorrow()"}),
]

# ── 应收账款 (5) ──────────────────────────────────────────────────────
FINANCE_SKUS += [
    _reg("receivable_aging", "应收账款账龄", "挂账金额/账龄/催收优先级",
         [{"name":"customer_name","label":"客户"},{"name":"total_due_fen","label":"欠款(分)"},
          {"name":"aging_days","label":"账龄(天)"},{"name":"aging_bucket","label":"账龄段"}],
         """SELECT COALESCE(c.name,'未知') AS customer_name, COALESCE(SUM(ar.amount_fen),0) AS total_due_fen,
            ROUND(AVG(EXTRACT(DAY FROM NOW()-ar.due_date))) AS aging_days,
            CASE WHEN AVG(EXTRACT(DAY FROM NOW()-ar.due_date))<=30 THEN '<30天'
                 WHEN AVG(EXTRACT(DAY FROM NOW()-ar.due_date))<=90 THEN '30-90天'
                 WHEN AVG(EXTRACT(DAY FROM NOW()-ar.due_date))<=180 THEN '90-180天' ELSE '>180天' END AS aging_bucket
            FROM accounts_receivable ar LEFT JOIN customers c ON ar.customer_id=c.id AND c.is_deleted=FALSE
            WHERE ar.{} AND ar.status='open' GROUP BY c.name ORDER BY total_due_fen DESC""".format(_TF)),
]

# ── 发票/对账 (5) ──────────────────────────────────────────────────────
FINANCE_SKUS += [
    _reg("invoice_summary", "发票统计", "开票金额/类型/数量汇总",
         [{"name":"invoice_type","label":"发票类型"},{"name":"count","label":"开票数"},
          {"name":"total_fen","label":"金额(分)"},{"name":"avg_fen","label":"均金额(分)"}],
         """SELECT COALESCE(invoice_type,'普票') AS invoice_type, COUNT(*) AS count,
            COALESCE(SUM(total_fen),0) AS total_fen, ROUND(AVG(COALESCE(total_fen,0))) AS avg_fen
            FROM invoices WHERE {} AND created_at>=:date_start AND created_at<:date_end
            GROUP BY invoice_type ORDER BY total_fen DESC""".format(_TF),
         {"date_start":"month_start()","date_end":"tomorrow()"}),
    _reg("reconciliation", "对账差异报告", "系统vs渠道对账差异明细",
         [{"name":"channel","label":"渠道"},{"name":"system_fen","label":"系统金额(分)"},
          {"name":"channel_fen","label":"渠道金额(分)"},{"name":"diff_fen","label":"差异(分)"}],
         """SELECT rs.channel, COALESCE(SUM(rs.system_amount_fen),0) AS system_fen,
            COALESCE(SUM(rs.channel_amount_fen),0) AS channel_fen,
            COALESCE(SUM(rs.system_amount_fen),0)-COALESCE(SUM(rs.channel_amount_fen),0) AS diff_fen
            FROM reconciliation_summary rs WHERE rs.{} AND rs.recon_date>=:date_start AND rs.recon_date<:date_end
            GROUP BY rs.channel HAVING ABS(COALESCE(SUM(rs.system_amount_fen),0)-COALESCE(SUM(rs.channel_amount_fen),0))>0""".format(_TF),
         {"date_start":"month_start()","date_end":"tomorrow()"}),
]

# ── 税务 (3) ───────────────────────────────────────────────────────────
FINANCE_SKUS += [
    _reg("tax_summary", "税务汇总", "增值税/所得税/附加税汇总",
         [{"name":"tax_type","label":"税种"},{"name":"tax_base_fen","label":"税基(分)"},
          {"name":"tax_amount_fen","label":"税额(分)"}],
         """SELECT '增值税' AS tax_type, COALESCE(SUM(taxable_amount_fen),0) AS tax_base_fen,
            COALESCE(SUM(tax_amount_fen),0) AS tax_amount_fen
            FROM tax_records WHERE {} AND tax_period>=:period_start AND tax_period<:period_end
            GROUP BY tax_type ORDER BY tax_amount_fen DESC""".format(_TF),
         {"period_start":"quarter_start()","period_end":"quarter_end()"}),
]
