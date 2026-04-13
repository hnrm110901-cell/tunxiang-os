"""P0 报表种子数据 — 25张核心经营报表

分类：
  财务(7): 营业汇总/营业明细/支付对账/收银员统计/CRM对账/押金统计/日结监控
  经营(6): 门店对比/时段分析/菜品排行/菜品毛利/折扣统计/退单分析
  会员(4): 新增会员/消费排行/储值余额/复购率
  人力(3): 考勤汇总/薪资明细/人效分析
  补全(5): 经营指标走势/月营业汇总/存酒台账/挂账对账单/供应链库存

SQL模板均基于已有数据库表结构（orders/order_items/payments/customers/employees/
store_daily_settlements/refunds/daily_attendance/payroll_items 等）。
"""
from __future__ import annotations

from typing import Any

P0_REPORTS: list[dict[str, Any]] = [
    # ════════════════════════ 财务(7) ════════════════════════
    {
        "id": "p0_fin_biz_summary",
        "name": "营业汇总报表",
        "description": "按门店/日期汇总营业额、订单数、客单价、折扣、退款",
        "category": "finance",
        "sql_template": """
SELECT
    s.store_name,
    d.biz_date,
    d.total_orders,
    d.completed_orders,
    d.total_guests,
    d.gross_revenue_fen,
    d.total_discount_fen,
    d.total_refund_fen,
    d.net_revenue_fen,
    d.avg_per_guest_fen,
    d.gross_profit_fen,
    d.gross_margin_rate
FROM store_daily_settlements d
JOIN stores s ON s.id = d.store_id
WHERE d.biz_date BETWEEN :start_date AND :end_date
  AND d.is_deleted = FALSE
ORDER BY d.biz_date DESC, d.net_revenue_fen DESC
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "store_name", "label": "门店"},
            {"name": "biz_date", "label": "营业日期"},
        ],
        "metrics": [
            {"name": "gross_revenue_fen", "label": "总营收(分)", "unit": "fen", "is_money_fen": True},
            {"name": "net_revenue_fen", "label": "净营收(分)", "unit": "fen", "is_money_fen": True},
            {"name": "total_orders", "label": "订单数", "unit": "笔", "is_money_fen": False},
            {"name": "avg_per_guest_fen", "label": "客单价(分)", "unit": "fen", "is_money_fen": True},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },
    {
        "id": "p0_fin_biz_detail",
        "name": "营业明细报表",
        "description": "按单笔订单列出营业明细，含支付方式、折扣、菜品数",
        "category": "finance",
        "sql_template": """
SELECT
    o.order_no,
    s.store_name,
    o.order_time,
    o.total_amount_fen,
    o.discount_amount_fen,
    o.final_amount_fen,
    o.status,
    o.sales_channel,
    (SELECT COUNT(*) FROM order_items oi WHERE oi.order_id = o.id AND oi.is_deleted = FALSE) AS item_count
FROM orders o
JOIN stores s ON s.id = o.store_id
WHERE o.order_time >= :start_date::timestamptz
  AND o.order_time < (:end_date::date + 1)::timestamptz
  AND o.is_deleted = FALSE
ORDER BY o.order_time DESC
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "order_no", "label": "订单号"},
            {"name": "store_name", "label": "门店"},
            {"name": "order_time", "label": "下单时间"},
        ],
        "metrics": [
            {"name": "total_amount_fen", "label": "原价(分)", "unit": "fen", "is_money_fen": True},
            {"name": "final_amount_fen", "label": "实付(分)", "unit": "fen", "is_money_fen": True},
            {"name": "item_count", "label": "菜品数", "unit": "道", "is_money_fen": False},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },
    {
        "id": "p0_fin_payment_recon",
        "name": "支付对账报表",
        "description": "按支付方式汇总已支付金额，用于对账",
        "category": "finance",
        "sql_template": """
SELECT
    p.method,
    COUNT(*) AS pay_count,
    SUM(p.amount_fen) AS total_amount_fen,
    SUM(CASE WHEN p.is_actual_revenue THEN p.amount_fen ELSE 0 END) AS actual_revenue_fen
FROM payments p
JOIN orders o ON o.id = p.order_id
WHERE p.status = 'paid'
  AND p.paid_at >= :start_date::timestamptz
  AND p.paid_at < (:end_date::date + 1)::timestamptz
  AND p.is_deleted = FALSE
GROUP BY p.method
ORDER BY total_amount_fen DESC
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "method", "label": "支付方式"},
        ],
        "metrics": [
            {"name": "pay_count", "label": "笔数", "unit": "笔", "is_money_fen": False},
            {"name": "total_amount_fen", "label": "支付总额(分)", "unit": "fen", "is_money_fen": True},
            {"name": "actual_revenue_fen", "label": "实收(分)", "unit": "fen", "is_money_fen": True},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },
    {
        "id": "p0_fin_cashier_stats",
        "name": "收银员统计报表",
        "description": "按收银员汇总收款笔数、金额、退款",
        "category": "finance",
        "sql_template": """
SELECT
    e.emp_name AS cashier_name,
    COUNT(DISTINCT o.id) AS order_count,
    SUM(o.final_amount_fen) AS total_revenue_fen,
    SUM(o.discount_amount_fen) AS total_discount_fen,
    COUNT(DISTINCT CASE WHEN o.status = 'cancelled' THEN o.id END) AS cancel_count
FROM orders o
JOIN employees e ON e.id::text = o.waiter_id
WHERE o.order_time >= :start_date::timestamptz
  AND o.order_time < (:end_date::date + 1)::timestamptz
  AND o.is_deleted = FALSE
GROUP BY e.emp_name
ORDER BY total_revenue_fen DESC
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "cashier_name", "label": "收银员"},
        ],
        "metrics": [
            {"name": "order_count", "label": "订单数", "unit": "笔", "is_money_fen": False},
            {"name": "total_revenue_fen", "label": "收款(分)", "unit": "fen", "is_money_fen": True},
            {"name": "cancel_count", "label": "取消单数", "unit": "笔", "is_money_fen": False},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },
    {
        "id": "p0_fin_crm_recon",
        "name": "CRM会员对账报表",
        "description": "会员支付金额汇总，用于储值/积分核销对账",
        "category": "finance",
        "sql_template": """
SELECT
    p.method,
    p.payment_category,
    COUNT(*) AS pay_count,
    SUM(p.amount_fen) AS total_fen
FROM payments p
WHERE p.method IN ('member_balance', 'points', 'coupon')
  AND p.status = 'paid'
  AND p.paid_at >= :start_date::timestamptz
  AND p.paid_at < (:end_date::date + 1)::timestamptz
  AND p.is_deleted = FALSE
GROUP BY p.method, p.payment_category
ORDER BY total_fen DESC
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "method", "label": "支付方式"},
            {"name": "payment_category", "label": "支付类别"},
        ],
        "metrics": [
            {"name": "pay_count", "label": "笔数", "unit": "笔", "is_money_fen": False},
            {"name": "total_fen", "label": "金额(分)", "unit": "fen", "is_money_fen": True},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },
    {
        "id": "p0_fin_deposit",
        "name": "押金统计报表",
        "description": "挂账/押金类支付记录统计",
        "category": "finance",
        "sql_template": """
SELECT
    p.credit_account_name,
    COUNT(*) AS tx_count,
    SUM(p.amount_fen) AS total_fen,
    MIN(p.paid_at) AS first_at,
    MAX(p.paid_at) AS last_at
FROM payments p
WHERE p.method = 'credit'
  AND p.status = 'paid'
  AND p.paid_at >= :start_date::timestamptz
  AND p.paid_at < (:end_date::date + 1)::timestamptz
  AND p.is_deleted = FALSE
GROUP BY p.credit_account_name
ORDER BY total_fen DESC
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "credit_account_name", "label": "挂账单位"},
        ],
        "metrics": [
            {"name": "tx_count", "label": "笔数", "unit": "笔", "is_money_fen": False},
            {"name": "total_fen", "label": "押金总额(分)", "unit": "fen", "is_money_fen": True},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },
    {
        "id": "p0_fin_daily_settlement_monitor",
        "name": "日结监控报表",
        "description": "监控各门店日结单状态，发现未提交/异常日结",
        "category": "finance",
        "sql_template": """
SELECT
    s.store_name,
    d.biz_date,
    d.settlement_no,
    d.status,
    d.net_revenue_fen,
    d.cash_expected_fen,
    d.cash_actual_fen,
    d.cash_diff_fen,
    d.operator_name,
    d.submitted_at,
    d.reviewed_at
FROM store_daily_settlements d
JOIN stores s ON s.id = d.store_id
WHERE d.biz_date BETWEEN :start_date AND :end_date
  AND d.is_deleted = FALSE
ORDER BY d.biz_date DESC, d.status ASC
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "store_name", "label": "门店"},
            {"name": "biz_date", "label": "营业日期"},
            {"name": "status", "label": "日结状态"},
        ],
        "metrics": [
            {"name": "net_revenue_fen", "label": "净营收(分)", "unit": "fen", "is_money_fen": True},
            {"name": "cash_diff_fen", "label": "现金差异(分)", "unit": "fen", "is_money_fen": True},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },

    # ════════════════════════ 经营(6) ════════════════════════
    {
        "id": "p0_ops_store_compare",
        "name": "门店对比报表",
        "description": "多门店核心指标横向对比",
        "category": "operation",
        "sql_template": """
SELECT
    s.store_name,
    SUM(d.net_revenue_fen) AS net_revenue_fen,
    SUM(d.total_orders) AS total_orders,
    AVG(d.avg_per_guest_fen)::int AS avg_guest_fen,
    AVG(d.gross_margin_rate)::numeric(6,4) AS avg_margin_rate,
    SUM(d.total_guests) AS total_guests
FROM store_daily_settlements d
JOIN stores s ON s.id = d.store_id
WHERE d.biz_date BETWEEN :start_date AND :end_date
  AND d.is_deleted = FALSE
GROUP BY s.store_name
ORDER BY net_revenue_fen DESC
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "store_name", "label": "门店"},
        ],
        "metrics": [
            {"name": "net_revenue_fen", "label": "净营收(分)", "unit": "fen", "is_money_fen": True},
            {"name": "total_orders", "label": "订单数", "unit": "笔", "is_money_fen": False},
            {"name": "avg_guest_fen", "label": "客单价(分)", "unit": "fen", "is_money_fen": True},
            {"name": "avg_margin_rate", "label": "平均毛利率", "unit": "%", "is_money_fen": False},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },
    {
        "id": "p0_ops_time_period",
        "name": "时段分析报表",
        "description": "按小时段分析订单量、营收分布，定位高峰低谷",
        "category": "operation",
        "sql_template": """
SELECT
    EXTRACT(HOUR FROM o.order_time)::int AS hour_of_day,
    COUNT(*) AS order_count,
    SUM(o.final_amount_fen) AS revenue_fen,
    AVG(o.final_amount_fen)::int AS avg_order_fen
FROM orders o
WHERE o.order_time >= :start_date::timestamptz
  AND o.order_time < (:end_date::date + 1)::timestamptz
  AND o.status NOT IN ('cancelled')
  AND o.is_deleted = FALSE
GROUP BY EXTRACT(HOUR FROM o.order_time)
ORDER BY hour_of_day
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "hour_of_day", "label": "小时"},
        ],
        "metrics": [
            {"name": "order_count", "label": "订单数", "unit": "笔", "is_money_fen": False},
            {"name": "revenue_fen", "label": "营收(分)", "unit": "fen", "is_money_fen": True},
            {"name": "avg_order_fen", "label": "均单价(分)", "unit": "fen", "is_money_fen": True},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },
    {
        "id": "p0_ops_dish_rank",
        "name": "菜品排行报表",
        "description": "菜品销量/销售额排行榜",
        "category": "operation",
        "sql_template": """
SELECT
    oi.item_name AS dish_name,
    SUM(oi.quantity) AS total_qty,
    SUM(oi.subtotal_fen) AS total_revenue_fen,
    COUNT(DISTINCT oi.order_id) AS order_count
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
WHERE o.order_time >= :start_date::timestamptz
  AND o.order_time < (:end_date::date + 1)::timestamptz
  AND o.status NOT IN ('cancelled')
  AND oi.is_deleted = FALSE
GROUP BY oi.item_name
ORDER BY total_revenue_fen DESC
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "dish_name", "label": "菜品名称"},
        ],
        "metrics": [
            {"name": "total_qty", "label": "销量", "unit": "份", "is_money_fen": False},
            {"name": "total_revenue_fen", "label": "销售额(分)", "unit": "fen", "is_money_fen": True},
            {"name": "order_count", "label": "点单次数", "unit": "次", "is_money_fen": False},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },
    {
        "id": "p0_ops_dish_margin",
        "name": "菜品毛利报表",
        "description": "按菜品分析毛利率，定位高/低利润菜品",
        "category": "operation",
        "sql_template": """
SELECT
    oi.item_name AS dish_name,
    SUM(oi.quantity) AS total_qty,
    SUM(oi.subtotal_fen) AS revenue_fen,
    SUM(oi.food_cost_fen) AS cost_fen,
    SUM(oi.subtotal_fen) - COALESCE(SUM(oi.food_cost_fen), 0) AS profit_fen,
    CASE WHEN SUM(oi.subtotal_fen) > 0
         THEN ROUND((SUM(oi.subtotal_fen) - COALESCE(SUM(oi.food_cost_fen), 0))::numeric
                     / SUM(oi.subtotal_fen) * 100, 2)
         ELSE 0 END AS margin_pct
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
WHERE o.order_time >= :start_date::timestamptz
  AND o.order_time < (:end_date::date + 1)::timestamptz
  AND o.status NOT IN ('cancelled')
  AND oi.is_deleted = FALSE
GROUP BY oi.item_name
ORDER BY profit_fen DESC
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "dish_name", "label": "菜品名称"},
        ],
        "metrics": [
            {"name": "revenue_fen", "label": "销售额(分)", "unit": "fen", "is_money_fen": True},
            {"name": "cost_fen", "label": "成本(分)", "unit": "fen", "is_money_fen": True},
            {"name": "profit_fen", "label": "毛利(分)", "unit": "fen", "is_money_fen": True},
            {"name": "margin_pct", "label": "毛利率(%)", "unit": "%", "is_money_fen": False},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },
    {
        "id": "p0_ops_discount_stats",
        "name": "折扣统计报表",
        "description": "按日期汇总折扣金额、折扣订单占比",
        "category": "operation",
        "sql_template": """
SELECT
    o.biz_date,
    COUNT(*) AS total_orders,
    COUNT(CASE WHEN o.discount_amount_fen > 0 THEN 1 END) AS discount_orders,
    ROUND(COUNT(CASE WHEN o.discount_amount_fen > 0 THEN 1 END)::numeric
          / NULLIF(COUNT(*), 0) * 100, 2) AS discount_order_pct,
    SUM(o.discount_amount_fen) AS total_discount_fen,
    SUM(o.final_amount_fen) AS total_revenue_fen
FROM orders o
WHERE o.biz_date BETWEEN :start_date AND :end_date
  AND o.status NOT IN ('cancelled')
  AND o.is_deleted = FALSE
GROUP BY o.biz_date
ORDER BY o.biz_date DESC
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "biz_date", "label": "营业日期"},
        ],
        "metrics": [
            {"name": "total_orders", "label": "订单数", "unit": "笔", "is_money_fen": False},
            {"name": "discount_orders", "label": "折扣订单", "unit": "笔", "is_money_fen": False},
            {"name": "discount_order_pct", "label": "折扣占比(%)", "unit": "%", "is_money_fen": False},
            {"name": "total_discount_fen", "label": "折扣总额(分)", "unit": "fen", "is_money_fen": True},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },
    {
        "id": "p0_ops_refund_analysis",
        "name": "退单分析报表",
        "description": "退款/取消单汇总，定位异常退单",
        "category": "operation",
        "sql_template": """
SELECT
    r.refund_type,
    r.reason,
    COUNT(*) AS refund_count,
    SUM(r.amount_fen) AS refund_fen,
    MIN(r.created_at) AS earliest,
    MAX(r.created_at) AS latest
FROM refunds r
WHERE r.created_at >= :start_date::timestamptz
  AND r.created_at < (:end_date::date + 1)::timestamptz
  AND r.is_deleted = FALSE
GROUP BY r.refund_type, r.reason
ORDER BY refund_fen DESC
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "refund_type", "label": "退款类型"},
            {"name": "reason", "label": "退款原因"},
        ],
        "metrics": [
            {"name": "refund_count", "label": "退单数", "unit": "笔", "is_money_fen": False},
            {"name": "refund_fen", "label": "退款金额(分)", "unit": "fen", "is_money_fen": True},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },

    # ════════════════════════ 会员(4) ════════════════════════
    {
        "id": "p0_mbr_new_members",
        "name": "新增会员报表",
        "description": "按日期统计新增会员数、来源渠道分布",
        "category": "member",
        "sql_template": """
SELECT
    c.created_at::date AS join_date,
    c.source,
    COUNT(*) AS new_count
FROM customers c
WHERE c.created_at >= :start_date::timestamptz
  AND c.created_at < (:end_date::date + 1)::timestamptz
  AND c.is_deleted = FALSE
  AND c.is_merged = FALSE
GROUP BY c.created_at::date, c.source
ORDER BY join_date DESC, new_count DESC
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "join_date", "label": "入会日期"},
            {"name": "source", "label": "来源渠道"},
        ],
        "metrics": [
            {"name": "new_count", "label": "新增数", "unit": "人", "is_money_fen": False},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },
    {
        "id": "p0_mbr_consume_rank",
        "name": "会员消费排行报表",
        "description": "按会员累计消费金额排行",
        "category": "member",
        "sql_template": """
SELECT
    c.id::text AS customer_id,
    c.rfm_level,
    c.total_order_count,
    c.total_order_amount_fen,
    c.rfm_recency_days,
    c.rfm_frequency,
    c.last_order_at
FROM customers c
WHERE c.is_deleted = FALSE
  AND c.is_merged = FALSE
  AND c.total_order_amount_fen > 0
ORDER BY c.total_order_amount_fen DESC
""",
        "default_params": {},
        "dimensions": [
            {"name": "customer_id", "label": "会员ID"},
            {"name": "rfm_level", "label": "RFM等级"},
        ],
        "metrics": [
            {"name": "total_order_count", "label": "消费次数", "unit": "次", "is_money_fen": False},
            {"name": "total_order_amount_fen", "label": "累计消费(分)", "unit": "fen", "is_money_fen": True},
            {"name": "rfm_recency_days", "label": "最近消费(天)", "unit": "天", "is_money_fen": False},
        ],
        "filters": [],
    },
    {
        "id": "p0_mbr_stored_balance",
        "name": "储值余额报表",
        "description": "会员余额支付汇总（通过支付记录中member_balance方式统计）",
        "category": "member",
        "sql_template": """
SELECT
    o.biz_date,
    COUNT(DISTINCT p.order_id) AS balance_pay_orders,
    SUM(p.amount_fen) AS balance_consumed_fen
FROM payments p
JOIN orders o ON o.id = p.order_id
WHERE p.method = 'member_balance'
  AND p.status = 'paid'
  AND o.biz_date BETWEEN :start_date AND :end_date
  AND p.is_deleted = FALSE
GROUP BY o.biz_date
ORDER BY o.biz_date DESC
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "biz_date", "label": "日期"},
        ],
        "metrics": [
            {"name": "balance_pay_orders", "label": "储值支付单数", "unit": "笔", "is_money_fen": False},
            {"name": "balance_consumed_fen", "label": "储值消费(分)", "unit": "fen", "is_money_fen": True},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },
    {
        "id": "p0_mbr_repurchase_rate",
        "name": "复购率报表",
        "description": "统计指定时间段内的会员复购率（消费>=2次的会员占比）",
        "category": "member",
        "sql_template": """
WITH member_orders AS (
    SELECT
        o.customer_id,
        COUNT(*) AS order_count
    FROM orders o
    WHERE o.customer_id IS NOT NULL
      AND o.order_time >= :start_date::timestamptz
      AND o.order_time < (:end_date::date + 1)::timestamptz
      AND o.status NOT IN ('cancelled')
      AND o.is_deleted = FALSE
    GROUP BY o.customer_id
)
SELECT
    COUNT(*) AS total_members,
    COUNT(CASE WHEN order_count >= 2 THEN 1 END) AS repeat_members,
    ROUND(COUNT(CASE WHEN order_count >= 2 THEN 1 END)::numeric
          / NULLIF(COUNT(*), 0) * 100, 2) AS repurchase_rate_pct
FROM member_orders
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [],
        "metrics": [
            {"name": "total_members", "label": "有消费会员数", "unit": "人", "is_money_fen": False},
            {"name": "repeat_members", "label": "复购会员数", "unit": "人", "is_money_fen": False},
            {"name": "repurchase_rate_pct", "label": "复购率(%)", "unit": "%", "is_money_fen": False},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },

    # ════════════════════════ 人力(3) ════════════════════════
    {
        "id": "p0_hr_attendance_summary",
        "name": "考勤汇总报表",
        "description": "按员工汇总出勤天数、迟到/早退次数、加班时长",
        "category": "hr",
        "sql_template": """
SELECT
    e.emp_name,
    e.role,
    s.store_name,
    COUNT(*) AS work_days,
    SUM(CASE WHEN da.status = 'late' THEN 1 ELSE 0 END) AS late_count,
    SUM(CASE WHEN da.status = 'early_leave' THEN 1 ELSE 0 END) AS early_leave_count,
    SUM(COALESCE(da.overtime_minutes, 0)) AS total_overtime_min
FROM daily_attendance da
JOIN employees e ON e.id::text = da.employee_id
JOIN stores s ON s.id = e.store_id
WHERE da.work_date BETWEEN :start_date AND :end_date
  AND da.is_deleted = FALSE
GROUP BY e.emp_name, e.role, s.store_name
ORDER BY late_count DESC, work_days DESC
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "emp_name", "label": "员工姓名"},
            {"name": "role", "label": "岗位"},
            {"name": "store_name", "label": "门店"},
        ],
        "metrics": [
            {"name": "work_days", "label": "出勤天数", "unit": "天", "is_money_fen": False},
            {"name": "late_count", "label": "迟到次数", "unit": "次", "is_money_fen": False},
            {"name": "total_overtime_min", "label": "加班(分钟)", "unit": "分钟", "is_money_fen": False},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },
    {
        "id": "p0_hr_payroll_detail",
        "name": "薪资明细报表",
        "description": "员工薪资明细，含基本工资、绩效、扣款",
        "category": "hr",
        "sql_template": """
SELECT
    e.emp_name,
    e.role,
    pi.base_salary_fen,
    pi.commission_fen,
    pi.overtime_fen,
    pi.bonus_fen,
    pi.deduction_fen,
    pi.tax_fen,
    pi.net_salary_fen
FROM payroll_items pi
JOIN employees e ON e.id::text = pi.employee_id
JOIN payroll_batches pb ON pb.id = pi.batch_id
WHERE pb.pay_month = :pay_month
  AND pi.is_deleted = FALSE
ORDER BY pi.net_salary_fen DESC
""",
        "default_params": {
            "pay_month": "2026-03",
        },
        "dimensions": [
            {"name": "emp_name", "label": "员工姓名"},
            {"name": "role", "label": "岗位"},
        ],
        "metrics": [
            {"name": "base_salary_fen", "label": "基本工资(分)", "unit": "fen", "is_money_fen": True},
            {"name": "commission_fen", "label": "提成(分)", "unit": "fen", "is_money_fen": True},
            {"name": "net_salary_fen", "label": "实发(分)", "unit": "fen", "is_money_fen": True},
        ],
        "filters": [
            {"name": "pay_month", "label": "薪资月份", "field_type": "text", "required": True, "default": "2026-03"},
        ],
    },
    {
        "id": "p0_hr_labor_efficiency",
        "name": "人效分析报表",
        "description": "门店人效 = 净营收 / 在岗员工数",
        "category": "hr",
        "sql_template": """
SELECT
    s.store_name,
    SUM(d.net_revenue_fen) AS net_revenue_fen,
    (SELECT COUNT(*) FROM employees e2
     WHERE e2.store_id = s.id AND e2.is_active = TRUE AND e2.is_deleted = FALSE) AS staff_count,
    CASE WHEN (SELECT COUNT(*) FROM employees e3
               WHERE e3.store_id = s.id AND e3.is_active = TRUE AND e3.is_deleted = FALSE) > 0
         THEN SUM(d.net_revenue_fen) / (SELECT COUNT(*) FROM employees e4
               WHERE e4.store_id = s.id AND e4.is_active = TRUE AND e4.is_deleted = FALSE)
         ELSE 0 END AS revenue_per_staff_fen
FROM store_daily_settlements d
JOIN stores s ON s.id = d.store_id
WHERE d.biz_date BETWEEN :start_date AND :end_date
  AND d.is_deleted = FALSE
GROUP BY s.id, s.store_name
ORDER BY revenue_per_staff_fen DESC
""",
        "default_params": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-09",
        },
        "dimensions": [
            {"name": "store_name", "label": "门店"},
        ],
        "metrics": [
            {"name": "net_revenue_fen", "label": "净营收(分)", "unit": "fen", "is_money_fen": True},
            {"name": "staff_count", "label": "在岗人数", "unit": "人", "is_money_fen": False},
            {"name": "revenue_per_staff_fen", "label": "人效(分)", "unit": "fen", "is_money_fen": True},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-09"},
        ],
    },
    # ════════════════════════ 补全(5) — 对标天财25张P0清单 ════════════════════════
    {
        "id": "p0_ops_trend",
        "name": "经营指标走势",
        "description": "近30天营收/客单价/订单量趋势折线图数据",
        "category": "operations",
        "sql_template": """
SELECT
    d.biz_date,
    d.gross_revenue_fen,
    d.net_revenue_fen,
    d.total_orders,
    CASE WHEN d.total_guests > 0
         THEN d.gross_revenue_fen / d.total_guests
         ELSE 0 END AS avg_per_guest_fen
FROM store_daily_settlements d
JOIN stores s ON s.id = d.store_id
WHERE d.tenant_id = :tenant_id
  AND d.biz_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR d.store_id = :store_id::UUID)
ORDER BY d.biz_date ASC
""",
        "default_params": {"start_date": "2026-03-13", "end_date": "2026-04-12"},
        "dimensions": [{"name": "biz_date", "label": "日期"}],
        "metrics": [
            {"name": "gross_revenue_fen", "label": "总营收(分)", "unit": "fen", "is_money_fen": True},
            {"name": "total_orders", "label": "订单数", "unit": "笔", "is_money_fen": False},
            {"name": "avg_per_guest_fen", "label": "客单价(分)", "unit": "fen", "is_money_fen": True},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-03-13"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-12"},
            {"name": "store_id", "label": "门店", "field_type": "store_select", "required": False},
        ],
    },
    {
        "id": "p0_fin_monthly_summary",
        "name": "月营业汇总",
        "description": "按月汇总各门店营收、折扣、订单量，对标天财#53",
        "category": "finance",
        "sql_template": """
SELECT
    TO_CHAR(d.biz_date, 'YYYY-MM') AS biz_month,
    s.store_name,
    SUM(d.gross_revenue_fen) AS gross_revenue_fen,
    SUM(d.net_revenue_fen) AS net_revenue_fen,
    SUM(d.total_orders) AS total_orders,
    SUM(d.total_guests) AS total_guests,
    SUM(d.discount_amount_fen) AS discount_amount_fen
FROM store_daily_settlements d
JOIN stores s ON s.id = d.store_id
WHERE d.tenant_id = :tenant_id
  AND d.biz_date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR d.store_id = :store_id::UUID)
GROUP BY biz_month, s.store_name
ORDER BY biz_month DESC, s.store_name
""",
        "default_params": {"start_date": "2026-01-01", "end_date": "2026-04-30"},
        "dimensions": [{"name": "biz_month", "label": "月份"}, {"name": "store_name", "label": "门店"}],
        "metrics": [
            {"name": "gross_revenue_fen", "label": "总营收(分)", "unit": "fen", "is_money_fen": True},
            {"name": "total_orders", "label": "订单数", "unit": "笔", "is_money_fen": False},
            {"name": "discount_amount_fen", "label": "折扣金额(分)", "unit": "fen", "is_money_fen": True},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-01-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-30"},
            {"name": "store_id", "label": "门店", "field_type": "store_select", "required": False},
        ],
    },
    {
        "id": "p0_wine_ledger",
        "name": "存酒台账",
        "description": "会员存酒记录：存入/支取/剩余/有效期，对标天财存酒模块",
        "category": "finance",
        "sql_template": """
SELECT
    wb.id,
    m.name AS member_name,
    m.phone,
    wb.wine_name,
    wb.spec,
    wb.quantity_in,
    wb.quantity_out,
    (wb.quantity_in - wb.quantity_out) AS quantity_remain,
    wb.registered_at,
    wb.expires_at,
    wb.status,
    s.store_name
FROM wine_bottles wb
JOIN members m ON m.id = wb.member_id
JOIN stores s ON s.id = wb.store_id
WHERE wb.tenant_id = :tenant_id
  AND (:store_id IS NULL OR wb.store_id = :store_id::UUID)
  AND wb.registered_at::date BETWEEN :start_date AND :end_date
  AND wb.is_deleted = FALSE
ORDER BY wb.registered_at DESC
""",
        "default_params": {"start_date": "2026-04-01", "end_date": "2026-04-30"},
        "dimensions": [
            {"name": "member_name", "label": "会员姓名"},
            {"name": "wine_name", "label": "酒品名称"},
            {"name": "store_name", "label": "门店"},
        ],
        "metrics": [
            {"name": "quantity_in", "label": "存入数量", "unit": "瓶", "is_money_fen": False},
            {"name": "quantity_out", "label": "支取数量", "unit": "瓶", "is_money_fen": False},
            {"name": "quantity_remain", "label": "剩余数量", "unit": "瓶", "is_money_fen": False},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-30"},
            {"name": "store_id", "label": "门店", "field_type": "store_select", "required": False},
        ],
    },
    {
        "id": "p0_credit_statement",
        "name": "挂账对账单",
        "description": "协议单位挂账明细：签单人/金额/状态/还款进度，对标天财协议挂账",
        "category": "finance",
        "sql_template": """
SELECT
    au.name AS unit_name,
    ab.id AS bill_id,
    asn.name AS signer_name,
    ab.amount_fen,
    ab.repaid_amount_fen,
    (ab.amount_fen - ab.repaid_amount_fen) AS outstanding_fen,
    ab.status,
    ab.created_at::date AS sign_date,
    s.store_name
FROM agreement_bills ab
JOIN agreement_units au ON au.id = ab.unit_id
LEFT JOIN agreement_signers asn ON asn.id = ab.signer_id
JOIN stores s ON s.id = ab.store_id
WHERE ab.tenant_id = :tenant_id
  AND ab.created_at::date BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR ab.store_id = :store_id::UUID)
  AND ab.is_deleted = FALSE
ORDER BY ab.created_at DESC
""",
        "default_params": {"start_date": "2026-04-01", "end_date": "2026-04-30"},
        "dimensions": [
            {"name": "unit_name", "label": "协议单位"},
            {"name": "signer_name", "label": "签单人"},
            {"name": "store_name", "label": "门店"},
        ],
        "metrics": [
            {"name": "amount_fen", "label": "挂账金额(分)", "unit": "fen", "is_money_fen": True},
            {"name": "repaid_amount_fen", "label": "已还金额(分)", "unit": "fen", "is_money_fen": True},
            {"name": "outstanding_fen", "label": "待还金额(分)", "unit": "fen", "is_money_fen": True},
        ],
        "filters": [
            {"name": "start_date", "label": "开始日期", "field_type": "date", "required": True, "default": "2026-04-01"},
            {"name": "end_date", "label": "结束日期", "field_type": "date", "required": True, "default": "2026-04-30"},
            {"name": "store_id", "label": "门店", "field_type": "store_select", "required": False},
        ],
    },
    {
        "id": "p0_supply_inventory",
        "name": "供应链库存报表",
        "description": "库存盘点/进货/损耗综合报表，覆盖天财#70/71/72三张表",
        "category": "supply",
        "sql_template": """
SELECT
    i.ingredient_name,
    i.unit,
    i.current_stock_qty,
    i.safety_stock_qty,
    CASE WHEN i.current_stock_qty < i.safety_stock_qty THEN TRUE ELSE FALSE END AS is_below_safety,
    i.last_purchase_price_fen,
    i.updated_at::date AS as_of_date,
    s.store_name
FROM ingredient_inventory i
JOIN stores s ON s.id = i.store_id
WHERE i.tenant_id = :tenant_id
  AND (:store_id IS NULL OR i.store_id = :store_id::UUID)
  AND i.is_deleted = FALSE
ORDER BY is_below_safety DESC, i.ingredient_name
""",
        "default_params": {},
        "dimensions": [
            {"name": "ingredient_name", "label": "食材名称"},
            {"name": "store_name", "label": "门店"},
        ],
        "metrics": [
            {"name": "current_stock_qty", "label": "当前库存", "unit": "单位", "is_money_fen": False},
            {"name": "safety_stock_qty", "label": "安全库存", "unit": "单位", "is_money_fen": False},
            {"name": "last_purchase_price_fen", "label": "最近进价(分)", "unit": "fen", "is_money_fen": True},
        ],
        "filters": [
            {"name": "store_id", "label": "门店", "field_type": "store_select", "required": False},
        ],
    },
]
