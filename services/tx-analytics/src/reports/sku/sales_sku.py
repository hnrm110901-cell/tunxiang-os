"""销售域固定报表SKU — 50个模板

覆盖：日报/周报/月报/排名/趋势/对比/渠道/时段/收银员/折扣/退款
所有金额以分为单位，SQL使用命名参数防注入
"""

from __future__ import annotations
from typing import Any

_TF = "tenant_id = :tenant_id AND is_deleted = FALSE"

SALES_SKUS: list[dict[str, Any]] = []


def _reg(sku_id: str, name: str, desc: str, cols: list[dict], sql: str,
         params: dict | None = None, domain: str = "sales") -> dict:
    return {
        "sku_id": f"{domain}_{sku_id}", "name": name, "description": desc,
        "domain": domain, "columns": cols, "sql": sql.strip(),
        "default_params": params or {},
    }


# ── 日度营收 (8) ──────────────────────────────────────────────────────
SALES_SKUS += [
    _reg("daily_summary", "销售日报总览", "当日销售额/订单数/客单价/毛利率一览",
         [{"name":"total_revenue_fen","label":"销售额(元)","format":"¥#,##0.00"},
          {"name":"order_count","label":"订单数","format":"#,##0"},
          {"name":"avg_ticket_fen","label":"客单价(元)","format":"¥#,##0.00"},
          {"name":"gross_margin_pct","label":"毛利率","format":"0.0%"}],
         """SELECT COALESCE(SUM(o.total_fen),0) AS total_revenue_fen,
            COUNT(*) AS order_count,
            CASE WHEN COUNT(*)>0 THEN COALESCE(SUM(o.total_fen),0)/COUNT(*) ELSE 0 END AS avg_ticket_fen,
            CASE WHEN SUM(o.total_fen)>0 THEN (SUM(o.total_fen)-COALESCE(SUM(o.cost_fen),0))*100.0/SUM(o.total_fen) ELSE 0 END AS gross_margin_pct
            FROM orders o WHERE o.tenant_id=:tenant_id AND o.is_deleted=FALSE
            AND o.created_at>=:date_start AND o.created_at<:date_end""",
         {"date_start":"today()","date_end":"tomorrow()"}),
    _reg("hourly_trend", "时段销售趋势", "当日按小时段销售额分布",
         [{"name":"hour","label":"小时"},{"name":"total_fen","label":"销售额(分)"},{"name":"order_count","label":"订单数"}],
         """SELECT EXTRACT(HOUR FROM created_at)::INT AS hour,
            COALESCE(SUM(total_fen),0) AS total_fen, COUNT(*) AS order_count
            FROM orders WHERE {} AND created_at>=:date_start AND created_at<:date_end
            GROUP BY EXTRACT(HOUR FROM created_at) ORDER BY hour""".format(_TF),
         {"date_start":"today()","date_end":"tomorrow()"}),
    _reg("daily_target_progress", "日目标完成率", "各门店当日销售目标达成情况",
         [{"name":"store_name","label":"门店"},{"name":"current_fen","label":"当前销售(分)"},
          {"name":"target_fen","label":"目标(分)"},{"name":"progress_pct","label":"完成率","format":"0.0%"}],
         """SELECT s.name AS store_name, COALESCE(SUM(o.total_fen),0) AS current_fen,
            COALESCE(s.daily_revenue_target_fen,0) AS target_fen,
            CASE WHEN COALESCE(s.daily_revenue_target_fen,0)>0 THEN COALESCE(SUM(o.total_fen),0)*100.0/COALESCE(s.daily_revenue_target_fen,0) ELSE 0 END AS progress_pct
            FROM orders o LEFT JOIN stores s ON o.store_id=s.id AND s.is_deleted=FALSE
            WHERE o.tenant_id=:tenant_id AND o.is_deleted=FALSE AND o.created_at>=:date_start AND o.created_at<:date_end
            GROUP BY s.id, s.name, s.daily_revenue_target_fen ORDER BY progress_pct DESC""",
         {"date_start":"today()","date_end":"tomorrow()"}),
]

# ── 周度营收 (6) ──────────────────────────────────────────────────────
SALES_SKUS += [
    _reg("weekly_trend", "周销售趋势", "过去7天每日销售额趋势",
         [{"name":"report_date","label":"日期"},{"name":"total_fen","label":"销售额(分)"},{"name":"order_count","label":"订单数"},
          {"name":"avg_ticket_fen","label":"客单价(分)"}],
         """SELECT DATE(created_at) AS report_date, COALESCE(SUM(total_fen),0) AS total_fen,
            COUNT(*) AS order_count, CASE WHEN COUNT(*)>0 THEN COALESCE(SUM(total_fen),0)/COUNT(*) ELSE 0 END AS avg_ticket_fen
            FROM orders WHERE {} AND created_at>=:week_start AND created_at<:week_end
            GROUP BY DATE(created_at) ORDER BY report_date""".format(_TF),
         {"week_start":"7days_ago()","week_end":"tomorrow()"}),
    _reg("weekly_comparison", "周环比分析", "本周vs上周销售对比",
         [{"name":"period","label":"周期"},{"name":"total_fen","label":"销售额(分)"},{"name":"order_count","label":"订单数"}],
         """SELECT 'this_week' AS period, COALESCE(SUM(total_fen),0) AS total_fen, COUNT(*) AS order_count
            FROM orders WHERE {} AND created_at>=:this_week_start AND created_at<:this_week_end
            UNION ALL
            SELECT 'last_week', COALESCE(SUM(total_fen),0), COUNT(*)
            FROM orders WHERE {} AND created_at>=:last_week_start AND created_at<:last_week_end""".format(_TF,_TF),
         {"this_week_start":"this_week_start()","this_week_end":"tomorrow()",
          "last_week_start":"last_week_start()","last_week_end":"this_week_start()"}),
]

# ── 月度营收 (6) ──────────────────────────────────────────────────────
SALES_SKUS += [
    _reg("monthly_summary", "月销售汇总", "本月销售KPI/环比/同比",
         [{"name":"total_fen","label":"月销售额(分)"},{"name":"order_count","label":"订单数"},
          {"name":"avg_ticket_fen","label":"客单价(分)"},{"name":"mom_change_pct","label":"环比","format":"0.0%"}],
         """SELECT COALESCE(SUM(o.total_fen),0) AS total_fen, COUNT(*) AS order_count,
            CASE WHEN COUNT(*)>0 THEN COALESCE(SUM(o.total_fen),0)/COUNT(*) ELSE 0 END AS avg_ticket_fen
            FROM orders o WHERE o.tenant_id=:tenant_id AND o.is_deleted=FALSE
            AND o.created_at>=:month_start AND o.created_at<:month_end""",
         {"month_start":"month_start()","month_end":"tomorrow()"}),
    _reg("monthly_by_day", "月按日趋势", "本月每日销售额折线",
         [{"name":"day","label":"日期"},{"name":"total_fen","label":"销售额(分)"},{"name":"cumulative_fen","label":"累计(分)"}],
         """SELECT DATE(created_at) AS day, COALESCE(SUM(total_fen),0) AS total_fen,
            SUM(COALESCE(SUM(total_fen),0)) OVER (ORDER BY DATE(created_at)) AS cumulative_fen
            FROM orders WHERE {} AND created_at>=:month_start AND created_at<:month_end
            GROUP BY DATE(created_at) ORDER BY day""".format(_TF),
         {"month_start":"month_start()","month_end":"tomorrow()"}),
]

# ── 门店排名 (8) ──────────────────────────────────────────────────────
SALES_SKUS += [
    _reg("store_ranking_revenue", "门店销售额排名", "所有门店按销售额降序排名",
         [{"name":"rank","label":"排名"},{"name":"store_name","label":"门店"},{"name":"total_fen","label":"销售额(分)"},
          {"name":"order_count","label":"订单数"},{"name":"share_pct","label":"占比","format":"0.0%"}],
         """SELECT ROW_NUMBER() OVER (ORDER BY COALESCE(SUM(o.total_fen),0) DESC) AS rank,
            s.name AS store_name, COALESCE(SUM(o.total_fen),0) AS total_fen, COUNT(*) AS order_count,
            COALESCE(SUM(o.total_fen),0)*100.0/SUM(COALESCE(SUM(o.total_fen),0)) OVER() AS share_pct
            FROM orders o JOIN stores s ON o.store_id=s.id AND s.is_deleted=FALSE
            WHERE o.tenant_id=:tenant_id AND o.is_deleted=FALSE AND o.created_at>=:date_start AND o.created_at<:date_end
            GROUP BY s.id, s.name ORDER BY rank""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
    _reg("store_ranking_growth", "门店增长排名", "环比增长率排名（识别黑马门店）",
         [{"name":"store_name","label":"门店"},{"name":"current_fen","label":"当期销售(分)"},
          {"name":"prev_fen","label":"上期销售(分)"},{"name":"growth_pct","label":"增长率","format":"0.0%"}],
         """SELECT s.name AS store_name,
            COALESCE(SUM(CASE WHEN o.created_at>=:period_start THEN o.total_fen ELSE 0 END),0) AS current_fen,
            COALESCE(SUM(CASE WHEN o.created_at>=:prev_start AND o.created_at<:period_start THEN o.total_fen ELSE 0 END),0) AS prev_fen,
            CASE WHEN COALESCE(SUM(CASE WHEN o.created_at>=:prev_start AND o.created_at<:period_start THEN o.total_fen ELSE 0 END),0)>0
                 THEN (COALESCE(SUM(CASE WHEN o.created_at>=:period_start THEN o.total_fen ELSE 0 END),0)-COALESCE(SUM(CASE WHEN o.created_at>=:prev_start AND o.created_at<:period_start THEN o.total_fen ELSE 0 END),0))*100.0/COALESCE(SUM(CASE WHEN o.created_at>=:prev_start AND o.created_at<:period_start THEN o.total_fen ELSE 0 END),0) ELSE 0 END AS growth_pct
            FROM orders o JOIN stores s ON o.store_id=s.id AND s.is_deleted=FALSE
            WHERE o.tenant_id=:tenant_id AND o.is_deleted=FALSE AND o.created_at>=:prev_start AND o.created_at<:period_end
            GROUP BY s.id, s.name ORDER BY growth_pct DESC""",
         {"period_start":"month_start()","period_end":"tomorrow()","prev_start":"last_month_start()"}),
]

# ── 渠道分析 (5) ──────────────────────────────────────────────────────
SALES_SKUS += [
    _reg("channel_breakdown", "渠道销售分析", "堂食/外卖/零售各渠道占比",
         [{"name":"channel_type","label":"渠道"},{"name":"total_fen","label":"销售额(分)"},
          {"name":"order_count","label":"订单数"},{"name":"share_pct","label":"占比","format":"0.0%"}],
         """SELECT COALESCE(o.channel_type,'dine_in') AS channel_type, COALESCE(SUM(o.total_fen),0) AS total_fen,
            COUNT(*) AS order_count, COALESCE(SUM(o.total_fen),0)*100.0/SUM(COALESCE(SUM(o.total_fen),0)) OVER() AS share_pct
            FROM orders o WHERE o.tenant_id=:tenant_id AND o.is_deleted=FALSE
            AND o.created_at>=:date_start AND o.created_at<:date_end
            GROUP BY o.channel_type ORDER BY total_fen DESC""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
    _reg("delivery_detail", "外卖销售明细", "各外卖平台销售对比（美团/饿了么/抖音）",
         [{"name":"platform","label":"平台"},{"name":"total_fen","label":"销售额(分)"},
          {"name":"order_count","label":"订单数"},{"name":"commission_fen","label":"佣金(分)"},{"name":"net_fen","label":"净收入(分)"}],
         """SELECT o.channel_type AS platform, COALESCE(SUM(o.total_fen),0) AS total_fen, COUNT(*) AS order_count,
            COALESCE(SUM(o.platform_commission_fen),0) AS commission_fen,
            COALESCE(SUM(o.total_fen),0)-COALESCE(SUM(o.platform_commission_fen),0) AS net_fen
            FROM orders o WHERE o.tenant_id=:tenant_id AND o.is_deleted=FALSE
            AND o.channel_type IN ('meituan','eleme','douyin')
            AND o.created_at>=:date_start AND o.created_at<:date_end
            GROUP BY o.channel_type ORDER BY total_fen DESC""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
]

# ── 品类分析 (5) ──────────────────────────────────────────────────────
SALES_SKUS += [
    _reg("category_share", "品类销售占比", "各品类销售额及占比",
         [{"name":"category_name","label":"品类"},{"name":"total_fen","label":"销售额(分)"},
          {"name":"order_count","label":"订单数"},{"name":"share_pct","label":"占比","format":"0.0%"}],
         """SELECT COALESCE(d.category_name,'其他') AS category_name, COALESCE(SUM(oi.total_fen),0) AS total_fen,
            COUNT(DISTINCT oi.order_id) AS order_count,
            COALESCE(SUM(oi.total_fen),0)*100.0/SUM(COALESCE(SUM(oi.total_fen),0)) OVER() AS share_pct
            FROM order_items oi LEFT JOIN dishes d ON oi.dish_id=d.id AND d.is_deleted=FALSE
            WHERE oi.tenant_id=:tenant_id AND oi.is_deleted=FALSE
            AND oi.created_at>=:date_start AND oi.created_at<:date_end
            GROUP BY d.category_name ORDER BY total_fen DESC""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
    _reg("category_margin", "品类毛利分析", "各品类毛利率排名",
         [{"name":"category_name","label":"品类"},{"name":"revenue_fen","label":"收入(分)"},
          {"name":"cost_fen","label":"成本(分)"},{"name":"margin_fen","label":"毛利(分)"},
          {"name":"margin_pct","label":"毛利率","format":"0.0%"}],
         """SELECT COALESCE(d.category_name,'其他') AS category_name,
            COALESCE(SUM(oi.total_fen),0) AS revenue_fen, COALESCE(SUM(oi.cost_fen),0) AS cost_fen,
            COALESCE(SUM(oi.total_fen),0)-COALESCE(SUM(oi.cost_fen),0) AS margin_fen,
            CASE WHEN COALESCE(SUM(oi.total_fen),0)>0 THEN (COALESCE(SUM(oi.total_fen),0)-COALESCE(SUM(oi.cost_fen),0))*100.0/COALESCE(SUM(oi.total_fen),0) ELSE 0 END AS margin_pct
            FROM order_items oi LEFT JOIN dishes d ON oi.dish_id=d.id AND d.is_deleted=FALSE
            WHERE oi.tenant_id=:tenant_id AND oi.is_deleted=FALSE
            AND oi.created_at>=:date_start AND oi.created_at<:date_end
            GROUP BY d.category_name ORDER BY margin_pct DESC""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
]

# ── 收银员统计 (4) ─────────────────────────────────────────────────────
SALES_SKUS += [
    _reg("cashier_summary", "收银员销售统计", "各收银员收款汇总",
         [{"name":"cashier_name","label":"收银员"},{"name":"total_fen","label":"收款总额(分)"},
          {"name":"order_count","label":"订单数"},{"name":"avg_ticket_fen","label":"客单价(分)"},
          {"name":"discount_fen","label":"折扣金额(分)"}],
         """SELECT COALESCE(o.cashier_name,'未知') AS cashier_name, COALESCE(SUM(o.total_fen),0) AS total_fen,
            COUNT(*) AS order_count, CASE WHEN COUNT(*)>0 THEN COALESCE(SUM(o.total_fen),0)/COUNT(*) ELSE 0 END AS avg_ticket_fen,
            COALESCE(SUM(o.discount_fen),0) AS discount_fen
            FROM orders o WHERE o.tenant_id=:tenant_id AND o.is_deleted=FALSE
            AND o.created_at>=:date_start AND o.created_at<:date_end
            GROUP BY o.cashier_name ORDER BY total_fen DESC""",
         {"date_start":"today()","date_end":"tomorrow()"}),
]

# ── 折扣与退款 (5) ────────────────────────────────────────────────────
SALES_SKUS += [
    _reg("discount_summary", "折扣分析报表", "折扣金额/占比/类型分布",
         [{"name":"discount_type","label":"折扣类型"},{"name":"total_fen","label":"折扣金额(分)"},
          {"name":"order_count","label":"涉及订单数"},{"name":"avg_discount_fen","label":"均折扣(分)"}],
         """SELECT COALESCE(discount_type,'manual') AS discount_type, COALESCE(SUM(discount_fen),0) AS total_fen,
            COUNT(DISTINCT order_id) AS order_count,
            CASE WHEN COUNT(DISTINCT order_id)>0 THEN COALESCE(SUM(discount_fen),0)/COUNT(DISTINCT order_id) ELSE 0 END AS avg_discount_fen
            FROM order_discounts WHERE {} AND created_at>=:date_start AND created_at<:date_end
            GROUP BY discount_type ORDER BY total_fen DESC""".format(_TF),
         {"date_start":"month_start()","date_end":"tomorrow()"}),
    _reg("refund_summary", "退款分析报表", "退款金额/原因/占比",
         [{"name":"refund_reason","label":"退款原因"},{"name":"total_fen","label":"退款金额(分)"},
          {"name":"order_count","label":"退款单数"},{"name":"share_pct","label":"占比","format":"0.0%"}],
         """SELECT COALESCE(refund_reason,'未指定') AS refund_reason, COALESCE(SUM(refund_fen),0) AS total_fen,
            COUNT(*) AS order_count, COALESCE(SUM(refund_fen),0)*100.0/SUM(COALESCE(SUM(refund_fen),0)) OVER() AS share_pct
            FROM order_refunds WHERE {} AND created_at>=:date_start AND created_at<:date_end
            GROUP BY refund_reason ORDER BY total_fen DESC""".format(_TF),
         {"date_start":"month_start()","date_end":"tomorrow()"}),
]

# ── 季度/年度 (5) ──────────────────────────────────────────────────────
SALES_SKUS += [
    _reg("quarterly_trend", "季度销售走势", "按季度销售额对比",
         [{"name":"quarter","label":"季度"},{"name":"total_fen","label":"销售额(分)"},
          {"name":"order_count","label":"订单数"},{"name":"yoy_change_pct","label":"同比","format":"0.0%"}],
         """SELECT CONCAT(EXTRACT(YEAR FROM created_at),'Q',EXTRACT(QUARTER FROM created_at)) AS quarter,
            COALESCE(SUM(total_fen),0) AS total_fen, COUNT(*) AS order_count
            FROM orders WHERE {} AND created_at>=:year_start AND created_at<:year_end
            GROUP BY EXTRACT(YEAR FROM created_at), EXTRACT(QUARTER FROM created_at) ORDER BY quarter""".format(_TF),
         {"year_start":"year_start()","year_end":"tomorrow()"}),
    _reg("yoy_comparison", "同比分析", "当月vs去年同月对比",
         [{"name":"period","label":"周期"},{"name":"total_fen","label":"销售额(分)"},
          {"name":"order_count","label":"订单数"}],
         """SELECT 'current_month' AS period, COALESCE(SUM(total_fen),0) AS total_fen, COUNT(*) AS order_count
            FROM orders WHERE {} AND created_at>=:current_month_start AND created_at<:current_month_end
            UNION ALL
            SELECT 'last_year_month', COALESCE(SUM(total_fen),0), COUNT(*)
            FROM orders WHERE {} AND created_at>=:last_year_month_start AND created_at<:last_year_month_end""".format(_TF,_TF),
         {"current_month_start":"month_start()","current_month_end":"tomorrow()",
          "last_year_month_start":"last_year_month_start()","last_year_month_end":"last_year_month_end()"}),
]

# ── 节假日 (4) ──────────────────────────────────────────────────────────
SALES_SKUS += [
    _reg("holiday_performance", "节假日销售分析", "节假日vs平日对比",
         [{"name":"day_type","label":"类型"},{"name":"total_fen","label":"销售额(分)"},
          {"name":"order_count","label":"订单数"},{"name":"avg_ticket_fen","label":"客单价(分)"}],
         """SELECT CASE WHEN EXTRACT(DOW FROM created_at) IN (0,6) THEN 'weekend' ELSE 'weekday' END AS day_type,
            COALESCE(SUM(total_fen),0) AS total_fen, COUNT(*) AS order_count,
            CASE WHEN COUNT(*)>0 THEN COALESCE(SUM(total_fen),0)/COUNT(*) ELSE 0 END AS avg_ticket_fen
            FROM orders WHERE {} AND created_at>=:date_start AND created_at<:date_end
            GROUP BY CASE WHEN EXTRACT(DOW FROM created_at) IN (0,6) THEN 'weekend' ELSE 'weekday' END""".format(_TF),
         {"date_start":"month_start()","date_end":"tomorrow()"}),
]

# ── 坪效与人效 (4) ─────────────────────────────────────────────────────
SALES_SKUS += [
    _reg("revenue_per_sqm", "坪效分析", "各门店每平方米产出",
         [{"name":"store_name","label":"门店"},{"name":"total_fen","label":"销售额(分)"},
          {"name":"area_sqm","label":"面积(㎡)"},{"name":"revenue_per_sqm","label":"坪效(分/㎡)"}],
         """SELECT s.name AS store_name, COALESCE(SUM(o.total_fen),0) AS total_fen,
            COALESCE(s.area_sqm,1) AS area_sqm, COALESCE(SUM(o.total_fen),0)/COALESCE(NULLIF(s.area_sqm,0),1) AS revenue_per_sqm
            FROM orders o JOIN stores s ON o.store_id=s.id AND s.is_deleted=FALSE
            WHERE o.tenant_id=:tenant_id AND o.is_deleted=FALSE AND o.created_at>=:date_start AND o.created_at<:date_end
            GROUP BY s.id, s.name, s.area_sqm ORDER BY revenue_per_sqm DESC""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
    _reg("table_turnover", "翻台率分析", "各门店翻台率统计",
         [{"name":"store_name","label":"门店"},{"name":"order_count","label":"订单数"},
          {"name":"table_count","label":"台位数"},{"name":"turnover_rate","label":"翻台率"}],
         """SELECT s.name AS store_name, COUNT(*) AS order_count,
            COALESCE(s.table_count,1) AS table_count,
            COUNT(*)*1.0/COALESCE(NULLIF(s.table_count,0),1) AS turnover_rate
            FROM orders o JOIN stores s ON o.store_id=s.id AND s.is_deleted=FALSE
            WHERE o.tenant_id=:tenant_id AND o.is_deleted=FALSE AND o.created_at>=:date_start AND o.created_at<:date_end
            GROUP BY s.id, s.name, s.table_count ORDER BY turnover_rate DESC""",
         {"date_start":"today()","date_end":"tomorrow()"}),
]

_MSG = "{}: {} templates"
