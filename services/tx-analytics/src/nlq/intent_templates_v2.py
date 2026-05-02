"""NLQ V2 意图模板 — 200+ 模板，分域模块化（BI-1.3 升级）

每个模板结构：
{
    "id": str,           # 唯一标识
    "patterns": [str],   # 正则表达式（支持多种中文表达）
    "intent": str,       # 意图标识符
    "category": str,     # 业务域
    "sub_category": str, # 子分类
    "sql": str,          # 参数化 SQL 模板
    "answer_tpl": str,   # 自然语言回答模板
    "chart_type": str,   # metric|bar|line|pie|table|heatmap|scatter|comparison|gauge
    "required_params": [str],  # 必选参数
    "suggested_followups": [str],  # 推荐追问
}

SQL 规范：
- 金额单位：分（整数），后缀 _fen
- 所有查询强制过滤 tenant_id + is_deleted
- 使用 :named 参数，禁止字符串拼接
- 聚合使用 COALESCE(SUM(...), 0)
"""

from __future__ import annotations

import re
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════
# 模板定义：200 个模板，10 大业务域
# ═══════════════════════════════════════════════════════════════════════════

# ── 辅助：表引用常量 ─────────────────────────────────────────────────────
_T = {
    "orders": "orders",
    "order_items": "order_items",
    "order_item_returns": "order_item_returns",
    "dishes": "dishes",
    "members": "members",
    "member_transactions": "member_transactions",
    "stores": "stores",
    "tables": "tables",
    "inventory": "inventory",
    "employees": "employees",
    "schedules": "schedules",
    "coupons": "coupons",
    "coupon_records": "coupon_records",
    "daily_settlements": "daily_settlements",
    "payroll_records": "payroll_records",
    "suppliers": "suppliers",
    "purchase_orders": "purchase_orders",
    "campaigns": "campaigns",
    "gift_cards": "gift_cards",
}

# ── 辅助：物化视图引用 ──────────────────────────────────────────────────
_MV = {
    "store_pnl": "mv_store_pnl",
    "member_clv": "mv_member_clv",
    "inventory_bom": "mv_inventory_bom",
    "discount_health": "mv_discount_health",
    "channel_margin": "mv_channel_margin",
    "daily_settlement": "mv_daily_settlement",
    "safety_compliance": "mv_safety_compliance",
    "energy_efficiency": "mv_energy_efficiency",
}

# ── 辅助：通用 SQL 片段 ──────────────────────────────────────────────────
_TENANT_FILTER = "tenant_id = :tenant_id AND is_deleted = FALSE"
_TIME_TODAY = "created_at >= :today_start AND created_at < :tomorrow_start"
_TIME_YESTERDAY = "created_at >= :yesterday_start AND created_at < :today_start"
_TIME_WEEK = "created_at >= :week_start AND created_at < :tomorrow_start"
_TIME_MONTH = "created_at >= :month_start AND created_at < :tomorrow_start"

INTENT_TEMPLATES_V2: list[dict[str, Any]] = []


def _t(category: str, sub: str, intent: str, patterns: list[str],
       sql: str, answer: str, chart: str = "metric",
       params: list[str] | None = None,
       followups: list[str] | None = None) -> dict[str, Any]:
    """构建模板对象的工厂函数"""
    return {
        "id": f"nlq_v2_{intent}",
        "patterns": patterns,
        "intent": intent,
        "category": category,
        "sub_category": sub,
        "sql": sql.strip(),
        "answer_tpl": answer,
        "chart_type": chart,
        "required_params": params or ["tenant_id"],
        "suggested_followups": followups or [],
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1. 营收域 (Revenue) — 30 模板
# ═══════════════════════════════════════════════════════════════════════════

# 1.1 日度营收 (8)
INTENT_TEMPLATES_V2 += [
    _t("revenue", "daily", "revenue_today",
       [r"今天.*营业额", r"今日.*营收", r"今天.*卖了多少", r"今天.*收入", r"今日.*流水"],
       """SELECT COALESCE(SUM(total_fen), 0) AS total_fen,
          COUNT(*) AS order_count
          FROM orders WHERE {tenant} AND {time_today}""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日营业额 {revenue}，共 {order_count} 笔订单。", "metric",
       followups=["环比昨天呢", "哪个门店最高", "客单价多少"]),

    _t("revenue", "daily", "revenue_yesterday",
       [r"昨天.*营业", r"昨日.*营收", r"昨天.*卖了多少", r"昨日.*收入", r"昨天.*流水"],
       """SELECT COALESCE(SUM(total_fen), 0) AS total_fen,
          COUNT(*) AS order_count
          FROM orders WHERE {tenant} AND {time_yesterday}""".format(tenant=_TENANT_FILTER, time_yesterday=_TIME_YESTERDAY),
       "昨日营业额 {revenue}，共 {order_count} 笔订单。", "metric",
       followups=["前天呢", "和今天比怎么样", "哪个门店最高"]),

    _t("revenue", "daily", "revenue_day_ago",
       [r"前天.*营业", r"前天.*收入", r"前一天.*营收"],
       """SELECT COALESCE(SUM(total_fen), 0) AS total_fen,
          COUNT(*) AS order_count
          FROM orders WHERE {tenant}
          AND created_at >= :day_ago_start AND created_at < :yesterday_start""".format(tenant=_TENANT_FILTER),
       "前天营业额 {revenue}，共 {order_count} 笔订单。", "metric"),

    _t("revenue", "daily", "revenue_comparison",
       [r"环比|同比|对比.*昨天|和昨天比|昨天今天.*对比"],
       """SELECT
          (SELECT COALESCE(SUM(total_fen),0) FROM orders WHERE {tenant} AND {time_today}) AS today_fen,
          (SELECT COALESCE(SUM(total_fen),0) FROM orders WHERE {tenant} AND {time_yesterday}) AS yesterday_fen""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY, time_yesterday=_TIME_YESTERDAY),
       "今日营业额 {today}，昨日 {yesterday}，环比 {change}。", "comparison",
       followups=["这周趋势怎么样", "客单价有变化吗"]),

    _t("revenue", "daily", "revenue_target_progress",
       [r"目标.*完成|完成.*目标|达标|KPI.*完成|业绩.*达成"],
       """SELECT
          COALESCE(SUM(o.total_fen), 0) AS current_fen,
          s.daily_revenue_target_fen
          FROM orders o, stores s
          WHERE o.tenant_id = :tenant_id AND o.is_deleted = FALSE
          AND o.created_at >= :today_start AND o.created_at < :tomorrow_start
          AND o.store_id = s.id AND s.is_deleted = FALSE
          GROUP BY s.id, s.daily_revenue_target_fen""",
       "今日目标完成度 {progress}（{current} / {target}）。", "gauge",
       followups=["哪家店还没达标", "本月累计完成多少"]),

    _t("revenue", "daily", "revenue_by_hour",
       [r"每小时.*营收|分时段.*收入|每个小时.*卖|营业额.*小时"],
       """SELECT EXTRACT(HOUR FROM created_at)::INT AS hour,
          COALESCE(SUM(total_fen), 0) AS total_fen,
          COUNT(*) AS order_count
          FROM orders WHERE {tenant} AND {time_today}
          GROUP BY EXTRACT(HOUR FROM created_at)
          ORDER BY hour""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日分时段营收：{hourly_data}。", "line",
       followups=["哪个时段最忙", "和昨天同一时段比呢"]),

    _t("revenue", "daily", "revenue_lunch_vs_dinner",
       [r"午市.*晚市|午市.*营收|晚市.*营收|午餐.*晚餐.*对比"],
       """SELECT
          CASE WHEN EXTRACT(HOUR FROM created_at) < 15 THEN '午市' ELSE '晚市' END AS meal_period,
          COALESCE(SUM(total_fen), 0) AS total_fen,
          COUNT(*) AS order_count
          FROM orders WHERE {tenant} AND {time_today}
          GROUP BY CASE WHEN EXTRACT(HOUR FROM created_at) < 15 THEN '午市' ELSE '晚市' END
          ORDER BY meal_period""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日午市/晚市营收：{meal_data}。", "bar",
       followups=["午市客单价多少", "晚市哪个菜最畅销"]),

    _t("revenue", "daily", "revenue_per_table",
       [r"单桌.*消费|桌均.*营收|每桌.*消费|桌均.*收入"],
       """SELECT
          CASE WHEN COUNT(DISTINCT table_id) > 0
          THEN COALESCE(SUM(total_fen), 0) / COUNT(DISTINCT table_id) ELSE 0 END AS avg_table_fen,
          COUNT(DISTINCT table_id) AS table_count,
          COUNT(*) AS order_count
          FROM orders WHERE {tenant} AND {time_today} AND table_id IS NOT NULL""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日桌均消费 {avg_table}，共 {table_count} 桌用餐，{order_count} 笔订单。", "metric"),
]

# 1.2 周度营收 (5)
INTENT_TEMPLATES_V2 += [
    _t("revenue", "weekly", "revenue_this_week",
       [r"本周.*营收", r"这周.*营业", r"本周.*收入", r"这周.*流水"],
       """SELECT COALESCE(SUM(total_fen), 0) AS total_fen,
          COUNT(*) AS order_count
          FROM orders WHERE {tenant} AND {time_week}""".format(tenant=_TENANT_FILTER, time_week=_TIME_WEEK),
       "本周累计营业额 {revenue}，共 {order_count} 笔订单。", "metric",
       followups=["和上周比呢", "日均多少", "趋势怎么样"]),

    _t("revenue", "weekly", "revenue_last_week",
       [r"上周.*营收|上周.*营业|上周.*收入|上一周.*流水"],
       """SELECT COALESCE(SUM(total_fen), 0) AS total_fen,
          COUNT(*) AS order_count
          FROM orders WHERE {tenant}
          AND created_at >= :last_week_start AND created_at < :week_start""".format(tenant=_TENANT_FILTER),
       "上周营业额 {revenue}，共 {order_count} 笔订单。", "metric",
       followups=["环比涨跌", "哪个门店表现好"]),

    _t("revenue", "weekly", "revenue_week_comparison",
       [r"本周.*上周.*对比|这周.*上周.*比|周环比"],
       """SELECT
          (SELECT COALESCE(SUM(total_fen),0) FROM orders WHERE {tenant} AND {time_week}) AS this_week_fen,
          (SELECT COALESCE(SUM(total_fen),0) FROM orders WHERE {tenant}
           AND created_at >= :last_week_start AND created_at < :week_start) AS last_week_fen""".format(tenant=_TENANT_FILTER, time_week=_TIME_WEEK),
       "本周 {this_week}，上周 {last_week}，环比 {change}。", "comparison",
       followups=["客单价变化", "哪个时段增长快"]),

    _t("revenue", "weekly", "revenue_week_trend",
       [r"周.*趋势|每日.*营业.*走势|一周.*收入.*走势"],
       """SELECT DATE(created_at) AS biz_date,
          COALESCE(SUM(total_fen), 0) AS total_fen
          FROM orders WHERE {tenant} AND {time_week}
          GROUP BY DATE(created_at) ORDER BY biz_date""".format(tenant=_TENANT_FILTER, time_week=_TIME_WEEK),
       "本周每日营业额趋势：{trend_data}。", "line",
       followups=["周末和平时比怎么样"]),

    _t("revenue", "weekly", "revenue_weekday_vs_weekend",
       [r"周末.*平时|工作日.*周末|周末.*平日.*对比"],
       """SELECT
          CASE WHEN EXTRACT(DOW FROM created_at) IN (0,6) THEN '周末' ELSE '工作日' END AS day_type,
          COALESCE(SUM(total_fen),0) / NULLIF(COUNT(DISTINCT DATE(created_at)),0) AS avg_daily_fen
          FROM orders WHERE {tenant} AND {time_week}
          GROUP BY CASE WHEN EXTRACT(DOW FROM created_at) IN (0,6) THEN '周末' ELSE '工作日' END""".format(tenant=_TENANT_FILTER, time_week=_TIME_WEEK),
       "本周工作日/周末日均营收对比：{day_type_data}。", "bar"),
]

# 1.3 月度营收 (8)
INTENT_TEMPLATES_V2 += [
    _t("revenue", "monthly", "revenue_this_month",
       [r"本月.*营收", r"这个月.*营业", r"本月.*收入", r"这个月.*流水"],
       """SELECT COALESCE(SUM(total_fen), 0) AS total_fen,
          COUNT(*) AS order_count
          FROM orders WHERE {tenant} AND {time_month}""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月累计营业额 {revenue}，共 {order_count} 笔订单。", "metric",
       followups=["和上个月比", "日均多少", "能完成月目标吗"]),

    _t("revenue", "monthly", "revenue_last_month",
       [r"上个月.*营收|上月.*营业|上个月.*收入"],
       """SELECT COALESCE(SUM(total_fen), 0) AS total_fen,
          COUNT(*) AS order_count
          FROM orders WHERE {tenant}
          AND created_at >= :last_month_start AND created_at < :month_start""".format(tenant=_TENANT_FILTER),
       "上月营业额 {revenue}，共 {order_count} 笔订单。", "metric",
       followups=["环比呢", "哪个门店贡献大"]),

    _t("revenue", "monthly", "revenue_month_comparison",
       [r"月环比|本月.*上月.*对比|和上个月比|月增长"],
       """SELECT
          (SELECT COALESCE(SUM(total_fen),0) FROM orders WHERE {tenant} AND {time_month}) AS this_month_fen,
          (SELECT COALESCE(SUM(total_fen),0) FROM orders WHERE {tenant}
           AND created_at >= :last_month_start AND created_at < :month_start) AS last_month_fen""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月 {this_month}，上月 {last_month}，月环比 {change}。", "comparison"),

    _t("revenue", "monthly", "revenue_month_trend",
       [r"月度.*趋势|每月.*营业.*走势|月份.*收入.*变化"],
       """SELECT TO_CHAR(DATE_TRUNC('month', created_at), 'YYYY-MM') AS month_label,
          COALESCE(SUM(total_fen), 0) AS total_fen,
          COUNT(*) AS order_count
          FROM orders WHERE {tenant}
          AND created_at >= :six_months_start AND created_at < :tomorrow_start
          GROUP BY DATE_TRUNC('month', created_at)
          ORDER BY month_label""".format(tenant=_TENANT_FILTER),
       "近6个月营收趋势：{trend_data}。", "line",
       followups=["哪个月最高", "客单价趋势呢"]),

    _t("revenue", "monthly", "revenue_monthly_avg",
       [r"日均.*营业|平均.*每天.*收入|日均.*营收"],
       """SELECT COALESCE(AVG(daily_total), 0) AS avg_fen FROM (
          SELECT DATE(created_at) AS d, SUM(total_fen) AS daily_total
          FROM orders WHERE {tenant} AND {time_month}
          GROUP BY DATE(created_at)
       ) sub""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月日均营业额 {revenue}。", "metric"),

    _t("revenue", "monthly", "revenue_same_month_last_year",
       [r"同比|去年.*这个月|去年同期|同比.*增长"],
       """SELECT
          COALESCE(SUM(CASE WHEN created_at >= :month_start AND created_at < :tomorrow_start THEN total_fen ELSE 0 END),0) AS this_year_fen,
          COALESCE(SUM(CASE WHEN created_at >= :last_year_month_start AND created_at < :last_year_month_end THEN total_fen ELSE 0 END),0) AS last_year_fen
          FROM orders WHERE {tenant}
          AND ((created_at >= :month_start AND created_at < :tomorrow_start)
               OR (created_at >= :last_year_month_start AND created_at < :last_year_month_end))""".format(tenant=_TENANT_FILTER),
       "本月 {this_year}，去年同期 {last_year}，同比 {change}。", "comparison"),

    _t("revenue", "monthly", "revenue_month_target",
       [r"本月.*目标.*完成|月.*KPI|月.*业绩.*进度"],
       """SELECT COALESCE(SUM(o.total_fen), 0) AS current_fen,
          s.monthly_revenue_target_fen
          FROM orders o, stores s
          WHERE o.tenant_id = :tenant_id AND o.is_deleted = FALSE
          AND o.created_at >= :month_start AND o.created_at < :tomorrow_start
          AND o.store_id = s.id AND s.is_deleted = FALSE
          GROUP BY s.monthly_revenue_target_fen""",
       "本月目标完成度 {progress}（{current} / {target}），剩余 {days_left} 天。", "gauge"),

    _t("revenue", "monthly", "revenue_seasonal_pattern",
       [r"季节性|旺季.*淡季|哪个.*月份.*好|淡旺季"],
       """SELECT EXTRACT(MONTH FROM created_at)::INT AS month_num,
          COALESCE(SUM(total_fen), 0) AS total_fen
          FROM orders WHERE {tenant}
          AND created_at >= :twelve_months_start AND created_at < :tomorrow_start
          GROUP BY EXTRACT(MONTH FROM created_at)
          ORDER BY month_num""".format(tenant=_TENANT_FILTER),
       "近12个月营收季节分布：{seasonal_data}。", "line"),
]

# 1.4 营收排行 (4)
INTENT_TEMPLATES_V2 += [
    _t("revenue", "ranking", "top_store",
       [r"哪个门店.*最好|门店.*最高|最好.*门店|营业额.*排名|门店.*营收.*高"],
       """SELECT s.name AS store_name,
          COALESCE(SUM(o.total_fen), 0) AS total_fen
          FROM orders o JOIN stores s ON o.store_id = s.id
          WHERE o.{tenant} AND o.{time_today}
          AND s.is_deleted = FALSE
          GROUP BY s.name ORDER BY total_fen DESC LIMIT 5""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日营业额最高的门店：{top_list}。", "bar",
       followups=["最差的是哪家", "客单价排名呢"]),

    _t("revenue", "ranking", "bottom_store",
       [r"哪个门店.*最差|门店.*最低|最差.*门店|业绩.*最低|营收.*低.*门店"],
       """SELECT s.name AS store_name,
          COALESCE(SUM(o.total_fen), 0) AS total_fen
          FROM orders o JOIN stores s ON o.store_id = s.id
          WHERE o.{tenant} AND o.{time_today}
          AND s.is_deleted = FALSE
          GROUP BY s.name ORDER BY total_fen ASC LIMIT 5""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日营业额最低的门店：{bottom_list}。", "bar",
       followups=["为什么这么低", "最近一周都这么低吗"]),

    _t("revenue", "ranking", "store_revenue_rank_month",
       [r"本月.*门店.*排名|月.*门店.*榜单|各门店.*月.*营收"],
       """SELECT s.name AS store_name,
          COALESCE(SUM(o.total_fen), 0) AS total_fen,
          COUNT(*) AS order_count
          FROM orders o JOIN stores s ON o.store_id = s.id
          WHERE o.{tenant} AND o.{time_month}
          AND s.is_deleted = FALSE
          GROUP BY s.name ORDER BY total_fen DESC""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月门店营收排行：{rank_list}。", "bar",
       followups=["各门店客单价", "各门店毛利率"]),

    _t("revenue", "ranking", "store_growth_rank",
       [r"增长.*最快.*门店|门店.*增速|哪家.*增长.*快|环比.*增长.*门店"],
       """SELECT s.name AS store_name,
          COALESCE(SUM(CASE WHEN o.created_at >= :today_start AND o.created_at < :tomorrow_start THEN o.total_fen ELSE 0 END), 0) AS today_fen,
          COALESCE(SUM(CASE WHEN o.created_at >= :yesterday_start AND o.created_at < :today_start THEN o.total_fen ELSE 0 END), 0) AS yesterday_fen
          FROM orders o JOIN stores s ON o.store_id = s.id
          WHERE o.tenant_id = :tenant_id AND o.is_deleted = FALSE AND s.is_deleted = FALSE
          AND o.created_at >= :yesterday_start AND o.created_at < :tomorrow_start
          GROUP BY s.name ORDER BY (COALESCE(SUM(CASE WHEN o.created_at >= :today_start AND o.created_at < :tomorrow_start THEN o.total_fen ELSE 0 END), 0) - COALESCE(SUM(CASE WHEN o.created_at >= :yesterday_start AND o.created_at < :today_start THEN o.total_fen ELSE 0 END), 0)) DESC LIMIT 5""",
       "今日环比增速最快的门店：{growth_list}。", "bar"),
]

# 1.5 客单价与消费分析 (5)
INTENT_TEMPLATES_V2 += [
    _t("revenue", "arpu", "avg_order_value",
       [r"客单价|人均消费|平均.*订单|每单.*平均"],
       """SELECT CASE WHEN COUNT(*) > 0
          THEN COALESCE(SUM(total_fen),0)/COUNT(*) ELSE 0 END AS avg_fen,
          COUNT(*) AS order_count
          FROM orders WHERE {tenant} AND {time_today}""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日客单价 {avg_price}，共 {order_count} 笔订单。", "metric",
       followups=["昨天多少", "哪个门店客单价最高", "午市晚市对比"]),

    _t("revenue", "arpu", "avg_order_value_trend",
       [r"客单价.*趋势|客单.*走势|人均.*变化"],
       """SELECT DATE(created_at) AS biz_date,
          COALESCE(SUM(total_fen),0)/GREATEST(COUNT(*),1) AS avg_fen
          FROM orders WHERE {tenant} AND {time_week}
          GROUP BY DATE(created_at) ORDER BY biz_date""".format(tenant=_TENANT_FILTER, time_week=_TIME_WEEK),
       "近7日客单价趋势：{trend_data}。", "line"),

    _t("revenue", "arpu", "avg_order_value_by_store",
       [r"各门店.*客单价|门店.*客单.*对比|哪家.*客单.*高"],
       """SELECT s.name AS store_name,
          COALESCE(SUM(o.total_fen),0)/GREATEST(COUNT(*),1) AS avg_fen,
          COUNT(*) AS order_count
          FROM orders o JOIN stores s ON o.store_id = s.id
          WHERE o.{tenant} AND o.{time_today} AND s.is_deleted = FALSE
          GROUP BY s.name ORDER BY avg_fen DESC""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "各门店客单价：{store_avg_list}。", "bar"),

    _t("revenue", "arpu", "revenue_per_guest",
       [r"人均消费.*趋势|人均.*客单|每人.*消费"],
       """SELECT DATE(created_at) AS biz_date,
          COALESCE(SUM(total_fen),0)/GREATEST(SUM(guest_count),1) AS per_guest_fen
          FROM orders WHERE {tenant} AND {time_week}
          GROUP BY DATE(created_at) ORDER BY biz_date""".format(tenant=_TENANT_FILTER, time_week=_TIME_WEEK),
       "近7日人均消费趋势：{trend_data}。", "line"),

    _t("revenue", "arpu", "ticket_size_distribution",
       [r"消费.*分布|客单.*区间|平均.*消费.*段"],
       """SELECT
          CASE WHEN total_fen < 5000 THEN '50元以下' WHEN total_fen < 10000 THEN '50-100元'
               WHEN total_fen < 20000 THEN '100-200元' WHEN total_fen < 50000 THEN '200-500元'
               ELSE '500元以上' END AS price_range,
          COUNT(*) AS order_count
          FROM orders WHERE {tenant} AND {time_today}
          GROUP BY CASE WHEN total_fen < 5000 THEN '50元以下' WHEN total_fen < 10000 THEN '50-100元'
               WHEN total_fen < 20000 THEN '100-200元' WHEN total_fen < 50000 THEN '200-500元'
               ELSE '500元以上' END
          ORDER BY order_count DESC""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日客单价分布：{dist_data}。", "pie"),
]

# ═══════════════════════════════════════════════════════════════════════════
# 2. 餐品域 (Dish) — 25 模板
# ═══════════════════════════════════════════════════════════════════════════

# 2.1 畅销/滞销分析 (8)
INTENT_TEMPLATES_V2 += [
    _t("dish", "popularity", "top_dishes",
       [r"最畅销|卖得最好.*菜|销量.*最高.*菜|热销|菜品.*排行"],
       """SELECT d.name AS dish_name,
          SUM(oi.quantity) AS total_qty,
          SUM(oi.subtotal_fen) AS total_fen
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_today}
          AND d.is_deleted = FALSE
          GROUP BY d.name ORDER BY total_qty DESC LIMIT 10""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日畅销菜品TOP10：{dish_list}。", "bar",
       followups=["利润率怎么样", "库存够吗"]),

    _t("dish", "popularity", "top_dishes_by_revenue",
       [r"卖钱.*最多.*菜|收入.*最高.*菜|营业.*最高.*菜品"],
       """SELECT d.name AS dish_name,
          SUM(oi.subtotal_fen) AS total_fen,
          SUM(oi.quantity) AS total_qty
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_today}
          AND d.is_deleted = FALSE
          GROUP BY d.name ORDER BY total_fen DESC LIMIT 10""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日营收贡献最高菜品：{dish_list}。", "bar"),

    _t("dish", "popularity", "worst_dishes",
       [r"卖得最差|滞销.*菜|没人点|点单.*最少|销量.*最低"],
       """SELECT d.name AS dish_name,
          COALESCE(SUM(oi.quantity), 0) AS total_qty
          FROM dishes d LEFT JOIN order_items oi ON d.id = oi.dish_id
          LEFT JOIN orders o ON oi.order_id = o.id
          AND o.{time_today} AND o.is_deleted = FALSE
          WHERE d.{tenant}
          GROUP BY d.name ORDER BY total_qty ASC LIMIT 10""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日销量最低的菜品：{dish_list}。", "bar",
       followups=["是不是毛利问题", "看看是不是该下架"]),

    _t("dish", "popularity", "dish_sales_trend",
       [r"菜品.*销量.*趋势|某道菜.*走势|哪个.*菜.*涨|哪个.*菜.*跌"],
       """SELECT d.name AS dish_name,
          DATE(o.created_at) AS biz_date,
          SUM(oi.quantity) AS daily_qty
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_week} AND d.is_deleted = FALSE
          GROUP BY d.name, DATE(o.created_at)
          ORDER BY d.name, biz_date""".format(tenant=_TENANT_FILTER, time_week=_TIME_WEEK),
       "近7日菜品销量趋势：{trend_data}。", "line"),

    _t("dish", "popularity", "dish_turnover_days",
       [r"菜品.*周转|菜.*卖.*多少天|出品.*频率"],
       """SELECT d.name AS dish_name,
          COUNT(DISTINCT DATE(o.created_at)) AS active_days,
          COALESCE(SUM(oi.quantity),0) AS total_qty
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_week} AND d.is_deleted = FALSE
          GROUP BY d.name ORDER BY active_days DESC, total_qty DESC LIMIT 10""".format(tenant=_TENANT_FILTER, time_week=_TIME_WEEK),
       "近7日出品频率最高的菜品：{dish_list}。", "bar"),

    _t("dish", "popularity", "combo_sales",
       [r"套餐.*销量|套餐.*情况|组合.*菜|套餐.*表现"],
       """SELECT d.name AS dish_name, SUM(oi.quantity) AS total_qty,
          SUM(oi.subtotal_fen) AS total_fen
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_today}
          AND d.category = 'combo' AND d.is_deleted = FALSE AND o.is_deleted = FALSE
          GROUP BY d.name ORDER BY total_qty DESC LIMIT 10""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日套餐销售情况：{dish_list}。", "bar"),

    _t("dish", "popularity", "new_dish_performance",
       [r"新菜.*表现|上新.*销量|新品.*如何|新菜.*数据"],
       """SELECT d.name AS dish_name,
          COALESCE(SUM(oi.quantity), 0) AS total_qty,
          COALESCE(SUM(oi.subtotal_fen), 0) AS total_fen
          FROM dishes d LEFT JOIN order_items oi ON d.id = oi.dish_id
          LEFT JOIN orders o ON oi.order_id = o.id
          AND o.{time_week} AND o.is_deleted = FALSE
          WHERE d.{tenant}
          AND d.created_at >= :thirty_days_ago
          GROUP BY d.name ORDER BY total_qty DESC LIMIT 10""".format(tenant=_TENANT_FILTER, time_week=_TIME_WEEK),
       "近30天新菜表现：{dish_list}。", "bar"),

    _t("dish", "popularity", "seasonal_dish",
       [r"时令.*菜|季节.*菜|应季.*菜.*销量|当季.*菜品"],
       """SELECT d.name AS dish_name,
          COALESCE(SUM(oi.quantity), 0) AS total_qty,
          COALESCE(SUM(oi.subtotal_fen), 0) AS total_fen
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_month}
          AND d.is_seasonal = TRUE AND d.is_deleted = FALSE AND o.is_deleted = FALSE
          GROUP BY d.name ORDER BY total_qty DESC LIMIT 10""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月应季菜品销售表现：{dish_list}。", "bar"),
]

# 2.2 毛利分析 (6)
INTENT_TEMPLATES_V2 += [
    _t("dish", "margin", "most_profitable_dish",
       [r"毛利.*最高.*菜|最赚钱.*菜|利润.*最高.*菜|高毛利.*菜"],
       """SELECT d.name AS dish_name,
          COALESCE(d.margin_rate, 0) AS margin_rate,
          SUM(oi.subtotal_fen) AS total_fen
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_today}
          AND d.is_deleted = FALSE AND o.is_deleted = FALSE
          GROUP BY d.name, d.margin_rate
          ORDER BY margin_rate DESC LIMIT 10""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "毛利率最高的菜品：{dish_list}。", "bar"),

    _t("dish", "margin", "low_margin_dishes",
       [r"毛利率.*低于|毛利.*不达标|低毛利.*菜|毛利.*差.*菜"],
       """SELECT name AS dish_name, COALESCE(margin_rate, 0) AS margin_rate
          FROM dishes
          WHERE {tenant}
          AND COALESCE(margin_rate, 0) < 0.30
          ORDER BY margin_rate ASC LIMIT 20""".format(tenant=_TENANT_FILTER),
       "毛利率低于30%的菜品共{count}个：{dish_list}。", "table",
       followups=["建议怎么调整", "对比同行水平"]),

    _t("dish", "margin", "dish_margin_contribution",
       [r"毛利.*贡献|哪道菜.*毛利.*多|菜品.*利润.*贡献"],
       """SELECT d.name AS dish_name,
          SUM(oi.subtotal_fen * COALESCE(d.margin_rate, 0)) AS margin_contribution_fen,
          SUM(oi.subtotal_fen) AS total_fen,
          COALESCE(d.margin_rate, 0) AS margin_rate
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_today}
          AND d.is_deleted = FALSE AND o.is_deleted = FALSE
          GROUP BY d.name, d.margin_rate
          ORDER BY margin_contribution_fen DESC LIMIT 10""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日毛利贡献TOP10菜品：{dish_list}。", "bar"),

    _t("dish", "margin", "dish_margin_trend",
       [r"菜品.*毛利.*趋势|某道.*菜.*毛利.*变化"],
       """SELECT d.name AS dish_name,
          DATE(o.created_at) AS biz_date,
          AVG(COALESCE(d.margin_rate, 0)) AS avg_margin
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_month}
          AND d.is_deleted = FALSE AND o.is_deleted = FALSE
          GROUP BY d.name, DATE(o.created_at) HAVING COUNT(*) >= 5
          ORDER BY d.name, biz_date""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月菜品毛利趋势（日均>=5单）：{trend_data}。", "line"),

    _t("dish", "margin", "combo_margin_vs_single",
       [r"套餐.*毛利.*单品|套餐.*对比.*单点|组合.*划算"],
       """SELECT CASE WHEN d.category = 'combo' THEN '套餐' ELSE '单品' END AS dish_type,
          AVG(COALESCE(d.margin_rate, 0)) AS avg_margin_rate,
          SUM(oi.subtotal_fen) AS total_fen
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_month}
          AND d.is_deleted = FALSE AND o.is_deleted = FALSE
          GROUP BY CASE WHEN d.category = 'combo' THEN '套餐' ELSE '单品' END""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "套餐vs单品毛利率对比：{compare_data}。", "bar",
       followups=["套餐占比多少"]),

    _t("dish", "margin", "bcg_matrix",
       [r"四象限|BCG.*矩阵|菜品.*分析.*矩阵|菜品.*分类"],
       """SELECT d.name, COALESCE(d.margin_rate, 0) AS margin,
          COALESCE(SUM(oi.quantity), 0) AS qty
          FROM dishes d LEFT JOIN order_items oi ON d.id = oi.dish_id
          LEFT JOIN orders o ON oi.order_id = o.id
          AND o.{time_month} AND o.is_deleted = FALSE
          WHERE d.{tenant}
          GROUP BY d.name, d.margin_rate""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "菜品四象限分析：明星{star}、金牛{cash_cow}、问号{question}、瘦狗{dog}。", "scatter"),
]

# 2.3 品类分析 (5)
INTENT_TEMPLATES_V2 += [
    _t("dish", "category", "dish_category_breakdown",
       [r"菜品.*分类|各分类.*销量|品类.*占比|类别.*分布"],
       """SELECT d.category, SUM(oi.quantity) AS total_qty,
          SUM(oi.subtotal_fen) AS total_fen
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_today}
          AND d.is_deleted = FALSE AND o.is_deleted = FALSE
          GROUP BY d.category ORDER BY total_fen DESC""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日各品类销售：{category_list}。", "pie",
       followups=["哪个品类毛利高", "荤菜占比多少"]),

    _t("dish", "category", "dish_category_by_revenue",
       [r"各品类.*营收|分类.*销售额|品类.*贡献.*金额"],
       """SELECT d.category,
          COALESCE(SUM(oi.subtotal_fen), 0) AS total_fen,
          COUNT(DISTINCT d.id) AS dish_count
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_today}
          AND d.is_deleted = FALSE AND o.is_deleted = FALSE
          GROUP BY d.category ORDER BY total_fen DESC""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日各品类营收贡献：{category_list}。", "bar"),

    _t("dish", "category", "dish_category_profit",
       [r"各品类.*毛利|分类.*利润|品类.*赚钱"],
       """SELECT d.category,
          SUM(oi.subtotal_fen * COALESCE(d.margin_rate,0)) AS margin_fen,
          AVG(COALESCE(d.margin_rate,0)) AS avg_margin_rate
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_month}
          AND d.is_deleted = FALSE AND o.is_deleted = FALSE
          GROUP BY d.category ORDER BY margin_fen DESC""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月各品类毛利贡献：{category_list}。", "bar"),

    _t("dish", "category", "dish_category_trend",
       [r"品类.*趋势|某类.*菜.*走势|分类.*销量.*变化"],
       """SELECT d.category,
          DATE(o.created_at) AS biz_date,
          SUM(oi.quantity) AS daily_qty
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_week}
          AND d.is_deleted = FALSE AND o.is_deleted = FALSE
          GROUP BY d.category, DATE(o.created_at)
          ORDER BY d.category, biz_date""".format(tenant=_TENANT_FILTER, time_week=_TIME_WEEK),
       "近7日各品类销量趋势：{trend_data}。", "line"),

    _t("dish", "category", "dish_cooking_method",
       [r"做法.*排行|烹饪.*方式|不同.*做法.*销量"],
       """SELECT d.cooking_method, SUM(oi.quantity) AS total_qty,
          SUM(oi.subtotal_fen) AS total_fen
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_today}
          AND d.is_deleted = FALSE AND o.is_deleted = FALSE
          GROUP BY d.cooking_method ORDER BY total_qty DESC""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日各做法（烹饪方式）销量：{method_data}。", "pie"),
]

# 2.4 退菜/差评 (3)
INTENT_TEMPLATES_V2 += [
    _t("dish", "returns", "dish_return_ranking",
       [r"退菜.*多|退菜.*排名|退菜.*原因|哪个.*菜.*退菜"],
       """SELECT d.name AS dish_name, COUNT(*) AS return_count
          FROM order_item_returns oir
          JOIN order_items oi ON oir.order_item_id = oi.id
          JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant}
          AND oir.created_at >= :today_start AND oir.created_at < :tomorrow_start
          AND d.is_deleted = FALSE
          GROUP BY d.name ORDER BY return_count DESC LIMIT 10""".format(tenant=_TENANT_FILTER),
       "今日退菜最多的菜品：{dish_list}。", "bar",
       followups=["原因是什么", "哪个门店退菜多"]),

    _t("dish", "returns", "dish_return_reason",
       [r"退菜.*原因.*分析|为什么.*退菜|退菜.*理由"],
       """SELECT oir.reason, COUNT(*) AS return_count
          FROM order_item_returns oir
          JOIN order_items oi ON oir.order_item_id = oi.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant}
          AND oir.created_at >= :today_start AND oir.created_at < :tomorrow_start
          GROUP BY oir.reason ORDER BY return_count DESC""".format(tenant=_TENANT_FILTER),
       "今日退菜原因分布：{reason_data}。", "pie"),

    _t("dish", "returns", "dish_return_by_store",
       [r"哪个.*门店.*退菜.*多|门店.*退菜.*率"],
       """SELECT s.name AS store_name,
          COUNT(oir.id) AS return_count,
          COUNT(o.id) AS total_order_count
          FROM stores s LEFT JOIN orders o ON s.id = o.store_id
          AND o.{time_today} AND o.is_deleted = FALSE
          LEFT JOIN order_item_returns oir ON EXISTS (
            SELECT 1 FROM order_items oi WHERE oir.order_item_id = oi.id AND oi.order_id = o.id)
          WHERE s.{tenant}
          GROUP BY s.name ORDER BY return_count DESC""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日各门店退菜情况：{store_return_data}。", "bar"),
]

# 2.5 菜品推荐 (3)
INTENT_TEMPLATES_V2 += [
    _t("dish", "recommendation", "dish_recommendation",
       [r"菜品.*推荐|今天.*推什么|推荐.*主推|今天.*做什么.*菜"],
       """SELECT d.name AS dish_name, d.margin_rate,
          COALESCE(SUM(oi.quantity), 0) AS recent_qty
          FROM dishes d LEFT JOIN order_items oi ON d.id = oi.dish_id
          LEFT JOIN orders o ON oi.order_id = o.id
          AND o.{time_week} AND o.is_deleted = FALSE
          WHERE d.{tenant}
          AND d.is_deleted = FALSE AND d.is_available = TRUE
          AND d.margin_rate > 0.3
          GROUP BY d.name, d.margin_rate ORDER BY recent_qty DESC LIMIT 10""".format(tenant=_TENANT_FILTER, time_week=_TIME_WEEK),
       "基于近期销量和毛利，建议主推：{recommendations}。", "table"),

    _t("dish", "recommendation", "cross_sell_suggestion",
       [r"搭配.*推荐|关联.*菜品|一起.*点.*多|搭配.*卖"],
       """SELECT di1.name AS dish_a, di2.name AS dish_b,
          COUNT(*) AS pair_count
          FROM order_items oi1 JOIN order_items oi2
          ON oi1.order_id = oi2.order_id AND oi1.dish_id < oi2.dish_id
          JOIN dishes di1 ON oi1.dish_id = di1.id
          JOIN dishes di2 ON oi2.dish_id = di2.id
          JOIN orders o ON oi1.order_id = o.id
          WHERE o.{tenant} AND o.{time_month}
          AND di1.is_deleted = FALSE AND di2.is_deleted = FALSE
          GROUP BY di1.name, di2.name
          ORDER BY pair_count DESC LIMIT 10""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月热门菜品搭配：{pair_data}。可据此设计套餐或推荐搭配。", "table"),

    _t("dish", "recommendation", "menu_gap_analysis",
       [r"菜单.*缺失|缺.*什么.*菜|菜单.*空白|菜单.*不全"],
       """SELECT d.category,
          COUNT(*) AS dish_count,
          AVG(COALESCE(d.margin_rate, 0)) AS avg_margin
          FROM dishes d WHERE d.{tenant}
          AND d.is_deleted = FALSE AND d.is_available = TRUE
          GROUP BY d.category ORDER BY dish_count ASC""".format(tenant=_TENANT_FILTER),
       "各品类菜品数量分布（用于识别菜单空白）：{gap_data}。", "bar"),
]

# ═══════════════════════════════════════════════════════════════════════════
# 3. 会员域 (Member) — 25 模板
# ═══════════════════════════════════════════════════════════════════════════

# 3.1 会员增长 (6)
INTENT_TEMPLATES_V2 += [
    _t("member", "growth", "new_members_today",
       [r"新增会员|今天.*会员|今日.*注册|新.*会员.*多少"],
       """SELECT COUNT(*) AS new_count FROM members
          WHERE {tenant}
          AND created_at >= :today_start AND created_at < :tomorrow_start""".format(tenant=_TENANT_FILTER),
       "今日新增会员 {count} 人。", "metric",
       followups=["本周新增多少", "这些新会员消费了吗"]),

    _t("member", "growth", "new_members_week",
       [r"本周.*新增.*会员|这周.*注册.*会员|一周.*新会员"],
       """SELECT COUNT(*) AS new_count FROM members
          WHERE {tenant}
          AND created_at >= :week_start AND created_at < :tomorrow_start""".format(tenant=_TENANT_FILTER),
       "本周新增会员 {count} 人。", "metric"),

    _t("member", "growth", "new_members_month",
       [r"本月.*新增.*会员|这个月.*注册.*会员|月.*新会员"],
       """SELECT COUNT(*) AS new_count FROM members
          WHERE {tenant}
          AND created_at >= :month_start AND created_at < :tomorrow_start""".format(tenant=_TENANT_FILTER),
       "本月新增会员 {count} 人。", "metric"),

    _t("member", "growth", "member_growth_trend",
       [r"会员.*增长.*趋势|会员.*数量.*走势|新增.*会员.*趋势"],
       """SELECT DATE(created_at) AS biz_date,
          COUNT(*) AS new_count
          FROM members WHERE {tenant}
          AND created_at >= :month_start AND created_at < :tomorrow_start
          GROUP BY DATE(created_at) ORDER BY biz_date""".format(tenant=_TENANT_FILTER),
       "本月每日新增会员趋势：{trend_data}。", "line"),

    _t("member", "growth", "member_source_channel",
       [r"会员.*来源|哪.*渠道.*会员|注册.*渠道.*分布"],
       """SELECT COALESCE(source_channel, '未知') AS channel,
          COUNT(*) AS member_count
          FROM members WHERE {tenant}
          GROUP BY COALESCE(source_channel, '未知')
          ORDER BY member_count DESC""".format(tenant=_TENANT_FILTER),
       "会员来源渠道分布：{channel_data}。", "pie"),

    _t("member", "growth", "member_conversion_rate",
       [r"会员.*转化|注册.*率|到店.*办卡|引流.*转化"],
       """SELECT
          COUNT(DISTINCT CASE WHEN member_id IS NOT NULL THEN member_id END) AS member_orders,
          COUNT(DISTINCT CASE WHEN member_id IS NULL THEN id END) AS non_member_orders
          FROM orders WHERE {tenant} AND {time_month}""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月会员转化率 {rate}（{member_count} 会员单 / {total_count} 总单）。", "metric"),
]

# 3.2 复购率 (4)
INTENT_TEMPLATES_V2 += [
    _t("member", "repurchase", "repurchase_rate",
       [r"复购率|回头客|老客.*比例|重复.*消费.*率"],
       """SELECT
          COUNT(DISTINCT CASE WHEN order_cnt > 1 THEN member_id END) AS repeat_count,
          COUNT(DISTINCT member_id) AS total_count
          FROM (
             SELECT member_id, COUNT(*) AS order_cnt FROM orders
             WHERE {tenant} AND member_id IS NOT NULL
             AND {time_month}
             GROUP BY member_id
          ) sub""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月会员复购率 {rate}（{repeat}/{total}）。", "metric",
       followups=["上月复购率呢", "哪些会员复购最高"]),

    _t("member", "repurchase", "repurchase_by_store",
       [r"各门店.*复购率|门店.*回头客|哪家.*回头客.*多"],
       """SELECT s.name AS store_name,
          COUNT(DISTINCT o.member_id) AS total_members,
          COUNT(DISTINCT CASE WHEN sub.order_cnt > 1 THEN o.member_id END) AS repeat_members
          FROM orders o JOIN stores s ON o.store_id = s.id
          LEFT JOIN (
             SELECT member_id, COUNT(*) AS order_cnt FROM orders
             WHERE {tenant} AND {time_month} AND member_id IS NOT NULL
             GROUP BY member_id
          ) sub ON o.member_id = sub.member_id
          WHERE o.{tenant} AND o.{time_month} AND o.member_id IS NOT NULL
          AND s.is_deleted = FALSE
          GROUP BY s.name ORDER BY repeat_members DESC""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月各门店复购率：{store_data}。", "bar"),

    _t("member", "repurchase", "repurchase_interval",
       [r"复购.*间隔|多久.*再来|回头.*周期"],
       """SELECT AVG(EXTRACT(DAY FROM (next_visit - created_at))) AS avg_interval_days
          FROM (
             SELECT member_id, created_at,
             LEAD(created_at) OVER (PARTITION BY member_id ORDER BY created_at) AS next_visit
             FROM orders WHERE {tenant} AND member_id IS NOT NULL
             AND {time_month}
          ) sub WHERE next_visit IS NOT NULL""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月会员平均复购间隔 {days} 天。", "metric"),

    _t("member", "repurchase", "high_freq_members",
       [r"高频.*会员|常客|经常.*来.*会员|消费.*频繁.*会员"],
       """SELECT m.name, m.phone, COUNT(o.id) AS visit_count,
          COALESCE(SUM(o.total_fen),0) AS total_spend
          FROM members m JOIN orders o ON m.id = o.member_id
          WHERE m.{tenant} AND o.{time_month} AND o.is_deleted = FALSE
          GROUP BY m.id, m.name, m.phone
          ORDER BY visit_count DESC LIMIT 20""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月高频消费会员TOP20：{member_list}。", "table"),
]

# 3.3 RFM分层 (3)
INTENT_TEMPLATES_V2 += [
    _t("member", "rfm", "member_rfm_distribution",
       [r"RFM|会员.*分层|会员.*等级.*分布|会员.*分类.*占比"],
       """SELECT
          CASE WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN '高价值'
               WHEN r_score >= 4 AND f_score >= 2 THEN '活跃'
               WHEN r_score >= 2 AND m_score >= 4 THEN '潜力'
               WHEN r_score = 1 THEN '流失风险' ELSE '一般' END AS segment,
          COUNT(*) AS member_count
          FROM mv_member_clv WHERE tenant_id = :tenant_id
          GROUP BY CASE WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN '高价值'
               WHEN r_score >= 4 AND f_score >= 2 THEN '活跃'
               WHEN r_score >= 2 AND m_score >= 4 THEN '潜力'
               WHEN r_score = 1 THEN '流失风险' ELSE '一般' END""",
       "会员RFM分层：{segment_data}。", "pie",
       followups=["高价值会员有多少", "流失风险会员怎么召回"]),

    _t("member", "rfm", "vip_members",
       [r"VIP.*会员|高价值.*会员|大客户|贵宾.*客户"],
       """SELECT m.name, m.phone, COALESCE(SUM(o.total_fen), 0) AS total_spend,
          COUNT(o.id) AS visit_count
          FROM members m JOIN orders o ON m.id = o.member_id
          WHERE m.{tenant} AND o.{time_month} AND o.is_deleted = FALSE
          GROUP BY m.id, m.name, m.phone
          ORDER BY total_spend DESC LIMIT 20""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月消费最高的VIP会员：{member_list}。", "table",
       followups=["他们最爱点哪些菜", "给他们发专属优惠吗"]),

    _t("member", "rfm", "member_tier_distribution",
       [r"会员.*等级|会员.*级别.*分布|各级.*会员.*数量"],
       """SELECT COALESCE(tier, '普通') AS tier,
          COUNT(*) AS member_count,
          AVG(COALESCE(balance_fen, 0)) AS avg_balance_fen
          FROM members WHERE {tenant}
          GROUP BY COALESCE(tier, '普通') ORDER BY member_count DESC""".format(tenant=_TENANT_FILTER),
       "会员等级分布：{tier_data}。", "bar"),
]

# 3.4 储值/支付 (4)
INTENT_TEMPLATES_V2 += [
    _t("member", "stored_value", "stored_value_balance",
       [r"储值.*余额|充值.*总额|储值.*统计|卡里.*余额"],
       """SELECT COALESCE(SUM(balance_fen), 0) AS total_balance,
          COUNT(*) AS member_count
          FROM members WHERE {tenant}
          AND balance_fen > 0""".format(tenant=_TENANT_FILTER),
       "当前储值余额合计 {balance}，涉及 {count} 位会员。", "metric",
       followups=["最近充值多少", "储值消费占比"]),

    _t("member", "stored_value", "stored_value_recharge_trend",
       [r"充值.*趋势|储值.*变化|最近.*充值.*多少"],
       """SELECT DATE(created_at) AS biz_date,
          COALESCE(SUM(amount_fen), 0) AS daily_recharge_fen,
          COUNT(*) AS recharge_count
          FROM member_transactions WHERE {tenant}
          AND transaction_type = 'recharge'
          AND created_at >= :week_start AND created_at < :tomorrow_start
          GROUP BY DATE(created_at) ORDER BY biz_date""".format(tenant=_TENANT_FILTER),
       "近7日储值充值趋势：{trend_data}。", "line"),

    _t("member", "stored_value", "member_revenue_share",
       [r"会员.*消费|会员.*贡献|会员.*占比|会员.*收入"],
       """SELECT
          COALESCE(SUM(CASE WHEN member_id IS NOT NULL THEN total_fen ELSE 0 END), 0) AS member_fen,
          COALESCE(SUM(total_fen), 0) AS total_fen
          FROM orders WHERE {tenant} AND {time_today}""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日会员消费占比 {share}（{member_rev} / {total_rev}）。", "pie"),

    _t("member", "stored_value", "stored_value_consumption",
       [r"储值.*消费|余额.*支付.*占比|储值.*支付.*比"],
       """SELECT
          COALESCE(SUM(CASE WHEN pay_method = 'stored_value' THEN total_fen ELSE 0 END), 0) AS stored_pay_fen,
          COALESCE(SUM(total_fen), 0) AS total_fen
          FROM orders WHERE {tenant} AND {time_today}""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日储值支付占比 {share}（{stored_pay} / {total_rev}）。", "pie"),
]

# 3.5 流失/沉睡 (4)
INTENT_TEMPLATES_V2 += [
    _t("member", "churn", "churned_members",
       [r"流失.*会员|沉睡.*会员|多久没来|休眠.*客户"],
       """SELECT COUNT(*) AS churned_count FROM members m
          WHERE m.{tenant}
          AND NOT EXISTS (
             SELECT 1 FROM orders o WHERE o.member_id = m.id
             AND o.created_at >= :sixty_days_ago
             AND o.is_deleted = FALSE
          )""".format(tenant=_TENANT_FILTER),
       "近60天未消费的沉睡会员共 {count} 人，建议启动召回计划。", "metric",
       followups=["怎么召回", "他们人均消费多少"]),

    _t("member", "churn", "churn_rate_trend",
       [r"流失.*率.*趋势|沉睡.*率.*变化|会员.*流失.*走势"],
       """SELECT
          DATE_TRUNC('month', last_order_date) AS month_label,
          COUNT(*) AS churned_count
          FROM (
             SELECT m.id, MAX(o.created_at) AS last_order_date
             FROM members m LEFT JOIN orders o ON m.id = o.member_id
             AND o.is_deleted = FALSE
             WHERE m.{tenant}
             GROUP BY m.id
             HAVING MAX(o.created_at) < :sixty_days_ago OR MAX(o.created_at) IS NULL
          ) sub GROUP BY DATE_TRUNC('month', last_order_date)
          ORDER BY month_label""".format(tenant=_TENANT_FILTER),
       "会员流失趋势：{trend_data}。", "line"),

    _t("member", "churn", "at_risk_members",
       [r"流失.*风险|快.*流失.*会员|预警.*会员"],
       """SELECT m.name, m.phone,
          MAX(o.created_at) AS last_visit_date,
          COALESCE(SUM(o.total_fen), 0) AS lifetime_spend
          FROM members m JOIN orders o ON m.id = o.member_id
          WHERE m.{tenant} AND o.is_deleted = FALSE
          GROUP BY m.id, m.name, m.phone
          HAVING MAX(o.created_at) < :thirty_days_ago
          AND MAX(o.created_at) >= :sixty_days_ago
          ORDER BY last_visit_date LIMIT 20""".format(tenant=_TENANT_FILTER),
       "近30-60天未消费的高风险流失会员{count}人：{member_list}。", "table"),

    _t("member", "churn", "winback_candidates",
       [r"召回.*目标|可.*召回.*会员|流失.*回来"],
       """SELECT m.name, m.phone,
          COALESCE(SUM(o.total_fen), 0) AS lifetime_spend,
          COUNT(o.id) AS historical_visits
          FROM members m JOIN orders o ON m.id = o.member_id
          WHERE m.{tenant} AND o.is_deleted = FALSE
          GROUP BY m.id, m.name, m.phone
          HAVING COUNT(o.id) >= 5
          AND MAX(o.created_at) < :sixty_days_ago
          ORDER BY lifetime_spend DESC LIMIT 20""".format(tenant=_TENANT_FILTER),
       "高价值可召回会员（历史>=5次、超60天未到店）：{member_list}。", "table"),
]

# 3.6 生日/特殊 (2)
INTENT_TEMPLATES_V2 += [
    _t("member", "birthday", "birthday_members",
       [r"会员.*生日|本月.*生日|生日.*提醒|即将.*生日.*会员"],
       """SELECT name, phone, birthday FROM members
          WHERE {tenant}
          AND EXTRACT(MONTH FROM birthday) = EXTRACT(MONTH FROM CURRENT_DATE)
          AND EXTRACT(DAY FROM birthday) BETWEEN
          EXTRACT(DAY FROM CURRENT_DATE) AND EXTRACT(DAY FROM CURRENT_DATE) + 7
          LIMIT 20""".format(tenant=_TENANT_FILTER),
       "未来7天过生日的会员有{count}位：{member_list}。", "table",
       followups=["给他们发券", "去年生日的消费了多少"]),

    _t("member", "birthday", "member_anniversary",
       [r"入会.*周年|注册.*纪念|会员.*周年"],
       """SELECT name, phone, created_at AS join_date
          FROM members WHERE {tenant}
          AND EXTRACT(MONTH FROM created_at) = EXTRACT(MONTH FROM CURRENT_DATE)
          AND EXTRACT(DAY FROM created_at) BETWEEN
          EXTRACT(DAY FROM CURRENT_DATE) AND EXTRACT(DAY FROM CURRENT_DATE) + 7
          AND created_at < CURRENT_DATE - INTERVAL '1 year'
          LIMIT 20""".format(tenant=_TENANT_FILTER),
       "未来7天入会周年的会员有{count}位：{member_list}。", "table"),
]

# 3.7 优惠券 (2)
INTENT_TEMPLATES_V2 += [
    _t("member", "coupon", "coupon_usage",
       [r"优惠券.*核销|券.*使用|优惠券.*效果|发券.*效果"],
       """SELECT c.name AS coupon_name,
          COUNT(CASE WHEN cr.status = 'redeemed' THEN 1 END) AS used,
          COUNT(*) AS total
          FROM coupon_records cr JOIN coupons c ON cr.coupon_id = c.id
          WHERE cr.{tenant}
          AND cr.created_at >= :month_start
          AND c.is_deleted = FALSE
          GROUP BY c.name ORDER BY used DESC LIMIT 10""".format(tenant=_TENANT_FILTER),
       "本月优惠券核销情况：{coupon_list}。", "bar",
       followups=["核销带动了多少消费"]),

    _t("member", "coupon", "coupon_roi",
       [r"券.*ROI|券.*投入产出|发券.*回报"],
       """SELECT c.name AS coupon_name,
          COUNT(CASE WHEN cr.status = 'redeemed' THEN 1 END) AS redeemed,
          COALESCE(SUM(CASE WHEN cr.status = 'redeemed' THEN cr.order_total_fen ELSE 0 END), 0) AS order_revenue_fen
          FROM coupon_records cr JOIN coupons c ON cr.coupon_id = c.id
          WHERE cr.{tenant}
          AND cr.created_at >= :month_start
          AND c.is_deleted = FALSE
          GROUP BY c.name ORDER BY order_revenue_fen DESC LIMIT 10""".format(tenant=_TENANT_FILTER),
       "本月各优惠券带动的订单收入：{coupon_roi_list}。", "bar"),
]

# ═══════════════════════════════════════════════════════════════════════════
# 4. 成本域 (Cost) — 20 模板
# ═══════════════════════════════════════════════════════════════════════════

INTENT_TEMPLATES_V2 += [
    # 4.1 食材成本 (6)
    _t("cost", "food", "food_cost_rate",
       [r"食材.*成本|成本率|成本.*占比|食材.*费用"],
       """SELECT COALESCE(SUM(total_fen), 0) AS revenue_fen,
          COALESCE(SUM(cost_fen), 0) AS cost_fen
          FROM orders WHERE {tenant} AND {time_month}""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月食材成本率 {cost_rate}（{cost} / {revenue}）。", "metric",
       followups=["成本率比上月高吗", "哪个门店成本最高"]),

    _t("cost", "food", "food_cost_by_category",
       [r"各类.*食材.*成本|原料.*分类.*成本|食材.*类别.*成本"],
       """SELECT d.category,
          COALESCE(SUM(o.cost_fen), 0) AS total_cost_fen,
          COALESCE(SUM(o.total_fen), 0) AS total_revenue_fen
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_month}
          AND d.is_deleted = FALSE AND o.is_deleted = FALSE
          GROUP BY d.category ORDER BY total_cost_fen DESC""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月各品类食材成本：{category_cost}。", "bar"),

    _t("cost", "food", "food_cost_trend",
       [r"食材.*成本.*趋势|成本.*走势|成本.*率.*变化"],
       """SELECT DATE(created_at) AS biz_date,
          COALESCE(SUM(cost_fen), 0) AS daily_cost_fen,
          COALESCE(SUM(total_fen), 0) AS daily_revenue_fen
          FROM orders WHERE {tenant} AND {time_week}
          GROUP BY DATE(created_at) ORDER BY biz_date""".format(tenant=_TENANT_FILTER, time_week=_TIME_WEEK),
       "近7日食材成本趋势：{trend_data}。", "line"),

    _t("cost", "food", "food_cost_by_store",
       [r"各门店.*成本率|门店.*食材.*成本.*对比|哪家.*成本.*高"],
       """SELECT s.name AS store_name,
          COALESCE(SUM(o.cost_fen), 0) AS cost_fen,
          COALESCE(SUM(o.total_fen), 0) AS revenue_fen
          FROM orders o JOIN stores s ON o.store_id = s.id
          WHERE o.{tenant} AND o.{time_month}
          AND s.is_deleted = FALSE
          GROUP BY s.name ORDER BY cost_fen DESC""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月各门店食材成本：{store_cost}。", "bar"),

    _t("cost", "food", "cost_anomaly_dish",
       [r"成本.*异常.*菜|哪道.*菜.*成本.*高|成本.*超.*预期"],
       """SELECT d.name AS dish_name,
          COALESCE(AVG(o.cost_fen), 0) AS avg_cost_fen,
          COALESCE(AVG(o.total_fen), 0) AS avg_price_fen
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_month}
          AND d.is_deleted = FALSE AND o.is_deleted = FALSE
          GROUP BY d.name
          HAVING COALESCE(AVG(o.cost_fen), 0) > :threshold_fen
          ORDER BY avg_cost_fen DESC""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月成本异常菜品（均成本>{threshold_fen}分）：{dish_list}。", "table"),

    _t("cost", "food", "food_cost_vs_revenue",
       [r"食材.*成本.*营收.*比|料率|原料.*占比"],
       """SELECT
          COALESCE(SUM(CASE WHEN created_at >= :today_start AND created_at < :tomorrow_start THEN cost_fen ELSE 0 END), 0) AS today_cost,
          COALESCE(SUM(CASE WHEN created_at >= :today_start AND created_at < :tomorrow_start THEN total_fen ELSE 0 END), 0) AS today_revenue
          FROM orders WHERE {tenant}
          AND created_at >= :today_start AND created_at < :tomorrow_start""".format(tenant=_TENANT_FILTER),
       "今日食材成本率 {cost_rate}。", "metric"),
]

# 4.2 人力成本 (5)
INTENT_TEMPLATES_V2 += [
    _t("cost", "labor", "labor_cost",
       [r"人力.*成本|工资.*占比|人效|人工.*成本"],
       """SELECT COALESCE(SUM(salary_fen), 0) AS salary_fen,
          COUNT(DISTINCT employee_id) AS headcount
          FROM payroll_records WHERE {tenant}
          AND pay_month = TO_CHAR(:today_date, 'YYYY-MM')""".format(tenant=_TENANT_FILTER),
       "本月人力成本 {salary}，共 {headcount} 人。", "metric",
       followups=["营收占比多少", "和上月比"]),

    _t("cost", "labor", "labor_revenue_ratio",
       [r"人效.*比|人工.*占比|人力.*成本.*率|人工.*费率"],
       """SELECT
          COALESCE((SELECT SUM(salary_fen) FROM payroll_records
           WHERE tenant_id=:tenant_id AND pay_month=TO_CHAR(:today_date,'YYYY-MM')), 0) AS labor_fen,
          COALESCE((SELECT SUM(total_fen) FROM orders
           WHERE tenant_id=:tenant_id AND {time_month}), 0) AS revenue_fen""".format(time_month=_TIME_MONTH),
       "本月人工费率 {rate}（{labor} / {revenue}）。", "metric"),

    _t("cost", "labor", "labor_cost_by_store",
       [r"各门店.*人力.*成本|门店.*工资.*对比"],
       """SELECT s.name AS store_name,
          COALESCE(SUM(pr.salary_fen), 0) AS labor_fen,
          COUNT(DISTINCT pr.employee_id) AS headcount
          FROM payroll_records pr JOIN employees e ON pr.employee_id = e.id
          JOIN stores s ON e.store_id = s.id
          WHERE pr.{tenant} AND pr.pay_month = TO_CHAR(:today_date, 'YYYY-MM')
          AND s.is_deleted = FALSE
          GROUP BY s.name ORDER BY labor_fen DESC""".format(tenant=_TENANT_FILTER),
       "本月各门店人力成本：{store_labor}。", "bar"),

    _t("cost", "labor", "overtime_cost",
       [r"加班.*成本|加班.*费|加班.*工时"],
       """SELECT e.name,
          COALESCE(SUM(s.overtime_hours), 0) AS overtime_hours,
          COALESCE(SUM(s.overtime_hours * e.hourly_rate_fen), 0) AS overtime_cost_fen
          FROM schedules s JOIN employees e ON s.employee_id = e.id
          WHERE s.{tenant} AND s.shift_date >= :month_start
          AND s.overtime_hours > 0
          AND e.is_deleted = FALSE
          GROUP BY e.id, e.name ORDER BY overtime_cost_fen DESC LIMIT 10""".format(tenant=_TENANT_FILTER),
       "本月加班成本TOP10员工：{overtime_list}。", "table"),

    _t("cost", "labor", "revenue_per_employee",
       [r"人效.*产出|每个.*员工.*产出|人均.*创收"],
       """SELECT
          COALESCE(SUM(o.total_fen), 0) / NULLIF(COUNT(DISTINCT e.id), 0) AS per_employee_revenue_fen,
          COUNT(DISTINCT e.id) AS headcount
          FROM orders o, employees e
          WHERE o.tenant_id = :tenant_id AND o.{time_month} AND o.is_deleted = FALSE
          AND e.tenant_id = :tenant_id AND e.is_deleted = FALSE AND e.status = 'active'""".format(time_month=_TIME_MONTH),
       "本月人均创收 {revenue}，在岗 {headcount} 人。", "metric"),
]

# 4.3 运营/其他成本 (5)
INTENT_TEMPLATES_V2 += [
    _t("cost", "overhead", "overhead_cost",
       [r"运营.*成本|管理.*费用|固定.*成本|房租"],
       """SELECT
          COALESCE(SUM(rent_fen), 0) AS rent_fen,
          COALESCE(SUM(utility_fen), 0) AS utility_fen,
          COALESCE(SUM(other_overhead_fen), 0) AS other_fen
          FROM mv_store_pnl WHERE tenant_id = :tenant_id""",
       "当前运营费用：租金 {rent}、水电 {utility}、其他 {other}。", "metric"),

    _t("cost", "overhead", "energy_cost",
       [r"能耗|电费|水费|用电|能源.*成本"],
       """SELECT * FROM mv_energy_efficiency WHERE tenant_id = :tenant_id LIMIT 5""",
       "能耗概览：{energy_summary}。", "bar"),

    _t("cost", "overhead", "total_cost_breakdown",
       [r"总成本.*构成|成本.*结构|各项.*成本.*占比"],
       """SELECT
          '食材' AS cost_type, COALESCE(SUM(cost_fen), 0) AS amount_fen FROM orders WHERE {tenant} AND {time_month}
          UNION ALL SELECT '人力', COALESCE(SUM(salary_fen), 0) FROM payroll_records WHERE {tenant} AND pay_month=TO_CHAR(:today_date,'YYYY-MM')
          UNION ALL SELECT '能耗', COALESCE(SUM(total_fen), 0) FROM mv_energy_efficiency WHERE tenant_id = :tenant_id""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月成本构成：{breakdown}。", "pie"),

    _t("cost", "overhead", "cost_change_drivers",
       [r"成本.*为什么.*涨|成本.*上涨.*原因|哪项.*成本.*涨"],
       """SELECT
          CASE WHEN current - prev > 0 THEN '上涨' ELSE '下降' END AS direction,
          ABS(current - prev) AS change_amount_fen
          FROM (
             SELECT
             (SELECT COALESCE(SUM(cost_fen), 0) FROM orders WHERE {tenant} AND {time_month}) AS current,
             (SELECT COALESCE(SUM(cost_fen), 0) FROM orders WHERE {tenant}
              AND created_at >= :last_month_start AND created_at < :month_start) AS prev
          ) sub""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月食材成本较上月 {direction} {amount}，变动 {change_percent}。", "comparison"),

    _t("cost", "overhead", "cost_per_dish",
       [r"每道.*菜.*成本|菜品.*单位成本|单菜.*成本"],
       """SELECT d.name AS dish_name,
          COALESCE(AVG(o.cost_fen / NULLIF(oi.quantity, 0)), 0) AS avg_unit_cost_fen,
          SUM(oi.quantity) AS total_qty
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND o.{time_month}
          AND d.is_deleted = FALSE AND o.is_deleted = FALSE
          GROUP BY d.name ORDER BY avg_unit_cost_fen DESC LIMIT 15""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月单菜成本TOP15：{dish_cost_list}。", "bar"),

    _t("cost", "overhead", "waste_cost",
       [r"损耗.*成本|浪费.*金额|消耗.*费用"],
       """SELECT
          COALESCE(SUM(waste_qty * unit_cost_fen), 0) AS waste_cost_fen,
          COUNT(DISTINCT ingredient_name) AS wasted_sku_count
          FROM inventory WHERE {tenant}
          AND waste_qty > 0 AND {time_month}""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月损耗成本 {waste_cost}，涉及 {wasted_sku_count} 种食材。", "metric"),

    _t("cost", "overhead", "utility_cost_anomaly",
       [r"水电.*异常|能耗.*异常|水电.*为什么.*高"],
       """SELECT store_name,
          total_fen AS current_month_fen,
          prev_month_fen
          FROM mv_energy_efficiency WHERE tenant_id = :tenant_id
          AND total_fen > prev_month_fen * 1.2
          ORDER BY total_fen - prev_month_fen DESC""",
       "能耗异常增长的门店（环比超20%）：{anomaly_stores}。", "bar"),

    _t("cost", "overhead", "procurement_cost_trend",
       [r"采购.*成本.*趋势|进货.*费用.*走势|采购.*金额.*变化"],
       """SELECT DATE(created_at) AS biz_date,
          COALESCE(SUM(total_fen), 0) AS daily_purchase_fen,
          COUNT(*) AS po_count
          FROM purchase_orders WHERE {tenant}
          AND created_at >= :month_start AND created_at < :tomorrow_start
          GROUP BY DATE(created_at) ORDER BY biz_date""".format(tenant=_TENANT_FILTER),
       "本月每日采购成本趋势：{trend_data}。", "line"),

    _t("cost", "overhead", "packaging_cost_rate",
       [r"包装.*成本|打包.*费用|外卖.*包装.*占比"],
       """SELECT
          COALESCE(SUM(packaging_fen), 0) AS packaging_fen,
          COALESCE(SUM(total_fen), 0) AS delivery_revenue_fen
          FROM orders WHERE {tenant} AND {time_month}
          AND channel IN ('meituan', 'eleme', 'douyin')""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月外卖包装成本 {packaging}，占外卖营收 {rate}。", "metric"),
]

# ═══════════════════════════════════════════════════════════════════════════
# 5. 门店域 (Store) — 25 模板
# ═══════════════════════════════════════════════════════════════════════════

INTENT_TEMPLATES_V2 += [
    # 5.1 经营效率 (6)
    _t("store", "efficiency", "table_turnover",
       [r"翻台率|桌台.*利用|翻台.*次数|翻桌.*率"],
       """SELECT COUNT(DISTINCT o.id)::FLOAT /
          GREATEST((SELECT COUNT(*) FROM tables WHERE store_id = :store_id AND is_deleted = FALSE), 1) AS turnover_rate
          FROM orders o WHERE o.{tenant} AND o.{time_today}
          AND o.table_id IS NOT NULL""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日翻台率 {rate} 次/桌。", "metric",
       followups=["午市翻台率呢", "和昨天比"]),

    _t("store", "efficiency", "table_turnover_by_store",
       [r"各门店.*翻台率|哪家.*翻台.*高|门店.*翻桌"],
       """SELECT s.name AS store_name,
          COALESCE(COUNT(DISTINCT o.id)::FLOAT / NULLIF(COUNT(DISTINCT t.id), 0), 0) AS turnover_rate
          FROM stores s LEFT JOIN tables t ON s.id = t.store_id AND t.is_deleted = FALSE
          LEFT JOIN orders o ON t.id = o.table_id
          AND o.{time_today} AND o.is_deleted = FALSE
          WHERE s.{tenant}
          GROUP BY s.name ORDER BY turnover_rate DESC""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日各门店翻台率：{store_turnover}。", "bar"),

    _t("store", "efficiency", "avg_dining_duration",
       [r"平均.*用餐.*时间|顾客.*吃.*多久|用餐.*时长"],
       """SELECT AVG(EXTRACT(EPOCH FROM (updated_at - created_at))/60) AS avg_minutes
          FROM orders WHERE {tenant} AND {time_today}
          AND status IN ('paid', 'completed')""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日平均用餐时长 {minutes} 分钟。", "metric"),

    _t("store", "efficiency", "peak_hours",
       [r"高峰.*时段|忙.*时间|客流.*分布|什么.*时候.*忙"],
       """SELECT EXTRACT(HOUR FROM created_at)::INT AS hour,
          COUNT(*) AS order_count,
          COALESCE(SUM(total_fen), 0) AS total_fen
          FROM orders WHERE {tenant} AND {time_today}
          GROUP BY EXTRACT(HOUR FROM created_at)
          ORDER BY order_count DESC""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日客流高峰时段：{peak_hours}。", "bar",
       followups=["高峰时段出品速度怎么样"]),

    _t("store", "efficiency", "seat_utilization",
       [r"座位.*利用|上座率|座位.*占用"],
       """SELECT COUNT(DISTINCT table_id)::FLOAT /
          GREATEST((SELECT COUNT(*) FROM tables WHERE store_id = :store_id AND is_deleted = FALSE), 1) AS seat_rate
          FROM orders WHERE {tenant} AND {time_today}
          AND table_id IS NOT NULL AND status IN ('paid', 'completed', 'serving')""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日上座率 {rate}。", "metric"),

    _t("store", "efficiency", "wait_time_avg",
       [r"等位.*时间|排队.*时间|等.*多久|排队.*多长"],
       """SELECT
          COALESCE(AVG(EXTRACT(EPOCH FROM (seated_at - queued_at))/60), 0) AS avg_wait_min,
          COUNT(*) AS queue_count
          FROM orders WHERE {tenant} AND {time_today}
          AND queued_at IS NOT NULL AND seated_at IS NOT NULL""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日平均等位时间 {minutes} 分钟，共 {queue_count} 组排队。", "metric"),
]

# 5.2 门店健康度 (7)
INTENT_TEMPLATES_V2 += [
    _t("store", "health", "store_health",
       [r"经营.*健康|整体.*状况|门店.*评分|健康度|门店.*诊断"],
       """SELECT * FROM mv_store_pnl WHERE tenant_id = :tenant_id LIMIT 5""",
       "门店经营健康度评分：{score}/100。{summary}", "gauge",
       followups=["哪项指标扣分了", "怎么改善"]),

    _t("store", "health", "store_daily_settlement",
       [r"日结|今天.*结算|日清|打烊.*结算"],
       """SELECT status, revenue_fen, cost_fen, cash_actual_fen, cash_expected_fen
          FROM daily_settlements
          WHERE {tenant} AND biz_date = :today_date LIMIT 1""".format(tenant=_TENANT_FILTER),
       "今日日结状态：{status}，营收 {revenue}，成本 {cost}。", "metric",
       followups=["现金差异多少"]),

    _t("store", "health", "store_cash_discrepancy",
       [r"现金.*差异|长短款|现金.*对不上|钱箱.*不符"],
       """SELECT COALESCE(cash_expected_fen, 0) - COALESCE(cash_actual_fen, 0) AS discrepancy_fen,
          cash_actual_fen, cash_expected_fen
          FROM daily_settlements
          WHERE {tenant} AND biz_date = :today_date LIMIT 1""".format(tenant=_TENANT_FILTER),
       "今日现金差异 {discrepancy}（实收 {actual} / 应�� {expected}）。", "metric"),

    _t("store", "health", "store_void_orders",
       [r"废单|作废.*订单|取消.*订单|作废.*多少"],
       """SELECT COUNT(*) AS void_count,
          COALESCE(SUM(total_fen), 0) AS void_fen
          FROM orders WHERE {tenant}
          AND {time_today}
          AND status = 'voided'""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日废单 {count} 笔，合计 {amount}。", "metric",
       followups=["哪个收银员废单最多"]),

    _t("store", "health", "store_void_by_cashier",
       [r"哪个.*收银.*废单.*多|收银员.*作废"],
       """SELECT e.name AS cashier_name, COUNT(*) AS void_count,
          COALESCE(SUM(o.total_fen), 0) AS void_fen
          FROM orders o JOIN employees e ON o.cashier_id = e.id
          WHERE o.{tenant} AND o.{time_today}
          AND o.status = 'voided' AND e.is_deleted = FALSE
          GROUP BY e.name ORDER BY void_count DESC LIMIT 10""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日废单最多的收银员：{cashier_list}。", "bar"),

    _t("store", "health", "discount_total",
       [r"折扣.*多少|折扣.*总额|今天.*打折|优免.*多少"],
       """SELECT COALESCE(SUM(discount_fen), 0) AS discount_fen,
          COUNT(CASE WHEN discount_fen > 0 THEN 1 END) AS discount_count,
          COUNT(*) AS total_count
          FROM orders WHERE {tenant} AND {time_today}""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日折扣合计 {amount}，{discount_count}/{total_count} 笔订单享受折扣。", "metric",
       followups=["折扣率正常吗", "谁折扣最多"]),

    _t("store", "health", "store_seating_capacity",
       [r"门店.*容量|每店.*多少.*桌|各门店.*座位"],
       """SELECT s.name AS store_name,
          COUNT(t.id) AS table_count,
          SUM(t.seats) AS total_seats
          FROM stores s JOIN tables t ON s.id = t.store_id
          WHERE s.{tenant} AND t.is_deleted = FALSE
          GROUP BY s.name ORDER BY total_seats DESC""".format(tenant=_TENANT_FILTER),
       "各门店席位容量：{capacity_list}。", "bar"),
]

# 5.3 门店对比 (5)
INTENT_TEMPLATES_V2 += [
    _t("store", "comparison", "multi_store_compare",
       [r"门店.*对比|多家.*门店.*比较|门店.*横向.*对比"],
       """SELECT s.name AS store_name,
          COALESCE(SUM(o.total_fen), 0) AS total_fen,
          COUNT(*) AS order_count,
          COALESCE(SUM(o.discount_fen), 0) AS discount_fen
          FROM orders o JOIN stores s ON o.store_id = s.id
          WHERE o.{tenant} AND o.{time_today} AND s.is_deleted = FALSE
          GROUP BY s.name ORDER BY total_fen DESC""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日各门店核心指标对比：{compare_data}。", "bar"),

    _t("store", "comparison", "store_performance_bm",
       [r"门店.*对标|门店.*基准.*对比|和.*平均.*比.*门店"],
       """SELECT s.name AS store_name,
          COALESCE(SUM(o.total_fen), 0) AS total_fen,
          COALESCE(SUM(o.total_fen), 0) - (SELECT AVG(store_total) FROM (
             SELECT SUM(total_fen) AS store_total FROM orders
             WHERE {tenant} AND {time_today}
             GROUP BY store_id) avg_sub) AS vs_average_fen
          FROM orders o JOIN stores s ON o.store_id = s.id
          WHERE o.{tenant} AND o.{time_today} AND s.is_deleted = FALSE
          GROUP BY s.name ORDER BY vs_average_fen DESC""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "各门店vs平均表现：{benchmark_data}。", "bar"),

    _t("store", "comparison", "store_type_compare",
       [r"不同.*业态.*对比|大店.*小店.*对比|业态.*比较"],
       """SELECT s.store_type,
          COUNT(DISTINCT s.id) AS store_count,
          AVG(COALESCE(store_revenue, 0)) AS avg_revenue_fen
          FROM stores s LEFT JOIN (
             SELECT store_id, SUM(total_fen) AS store_revenue
             FROM orders WHERE {tenant} AND {time_month}
             GROUP BY store_id) rev ON s.id = rev.store_id
          WHERE s.{tenant}
          GROUP BY s.store_type""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "不同业态表现对比：{type_compare}。", "bar"),

    _t("store", "comparison", "new_store_ramp",
       [r"新店.*爬坡|新开业.*门店|新店.*表现"],
       """SELECT s.name AS store_name,
          s.opened_at,
          DATE_TRUNC('week', o.created_at) AS week_start,
          COALESCE(SUM(o.total_fen), 0) AS weekly_revenue_fen
          FROM stores s JOIN orders o ON s.id = o.store_id
          WHERE s.{tenant} AND s.is_deleted = FALSE
          AND s.opened_at >= :six_months_ago AND o.is_deleted = FALSE
          GROUP BY s.name, s.opened_at, DATE_TRUNC('week', o.created_at)
          ORDER BY s.opened_at, week_start""".format(tenant=_TENANT_FILTER),
       "新店爬坡表现：{ramp_data}。", "line"),

    _t("store", "comparison", "profit_center_ranking",
       [r"利润.*中心.*排名|哪个.*门店.*最.*赚钱|利润.*排行"],
       """SELECT s.name AS store_name,
          COALESCE(SUM(o.total_fen - o.cost_fen - o.discount_fen), 0) AS net_profit_fen
          FROM orders o JOIN stores s ON o.store_id = s.id
          WHERE o.{tenant} AND o.{time_month} AND s.is_deleted = FALSE
          GROUP BY s.name ORDER BY net_profit_fen DESC""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月利润中心排行：{profit_rank}。", "bar"),
]

# 5.4 出餐效率 (4) — moved from old ops category
INTENT_TEMPLATES_V2 += [
    _t("store", "ops", "avg_serve_time",
       [r"出餐.*时间|等餐.*时间|平均.*出餐|出品.*速度"],
       """SELECT AVG(EXTRACT(EPOCH FROM (served_at - created_at))/60) AS avg_minutes,
          COUNT(*) AS item_count
          FROM order_items WHERE {tenant} AND {time_today}
          AND served_at IS NOT NULL""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日平均出餐时间 {minutes} 分钟。", "metric",
       followups=["哪个菜最慢", "晚高峰出餐速度"]),

    _t("store", "ops", "slow_dishes",
       [r"出餐.*慢.*菜|哪个.*菜.*慢|等.*最久.*菜"],
       """SELECT d.name AS dish_name,
          AVG(EXTRACT(EPOCH FROM (oi.served_at - oi.created_at))/60) AS avg_minutes,
          COUNT(*) AS order_count
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          WHERE oi.{tenant} AND oi.{time_today}
          AND oi.served_at IS NOT NULL AND d.is_deleted = FALSE
          GROUP BY d.name ORDER BY avg_minutes DESC LIMIT 10""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日出餐最慢的菜品：{dish_list}。", "bar"),

    _t("store", "ops", "serve_time_trend",
       [r"出餐.*趋势|出品.*变化|上菜.*速度.*趋势"],
       """SELECT DATE(created_at) AS biz_date,
          AVG(EXTRACT(EPOCH FROM (served_at - created_at))/60) AS avg_minutes
          FROM order_items WHERE {tenant}
          AND created_at >= :week_start AND created_at < :tomorrow_start
          AND served_at IS NOT NULL
          GROUP BY DATE(created_at) ORDER BY biz_date""".format(tenant=_TENANT_FILTER),
       "近7日出餐时间趋势：{trend_data}。", "line"),

    _t("store", "ops", "kds_queue_length",
       [r"KDS.*队列|厨房.*积压|后厨.*待做.*多少"],
       """SELECT COUNT(*) AS pending_items,
          COUNT(DISTINCT order_id) AS pending_orders
          FROM order_items WHERE {tenant}
          AND status = 'pending' AND is_deleted = FALSE""".format(tenant=_TENANT_FILTER),
       "当前待出品 {items} 道菜，涉及 {orders} 笔订单。", "metric"),
]

# 5.5 门店排班 (3)
INTENT_TEMPLATES_V2 += [
    _t("store", "schedule", "staff_schedule",
       [r"员工.*排班|今天.*上班|谁.*值班|今日.*排班"],
       """SELECT e.name, s.shift_type, s.start_time, s.end_time
          FROM schedules s JOIN employees e ON s.employee_id = e.id
          WHERE s.{tenant} AND s.shift_date = :today_date
          AND e.is_deleted = FALSE AND s.is_deleted = FALSE
          ORDER BY s.start_time""".format(tenant=_TENANT_FILTER),
       "今日排班：{schedule_list}。", "table",
       followups=["人手够吗", "哪个时段人最紧"]),

    _t("store", "schedule", "staffing_gap",
       [r"人手.*不够|缺.*人|排班.*缺口|人手.*不足"],
       """SELECT s.name AS store_name,
          COUNT(e.id) AS on_duty,
          s.required_staff
          FROM stores s LEFT JOIN schedules sch ON s.id = sch.store_id
          AND sch.shift_date = :today_date AND sch.is_deleted = FALSE
          LEFT JOIN employees e ON sch.employee_id = e.id AND e.is_deleted = FALSE
          WHERE s.{tenant}
          GROUP BY s.name, s.required_staff
          HAVING COUNT(e.id) < s.required_staff""".format(tenant=_TENANT_FILTER),
       "今日人手不足的门店：{gap_list}。", "table"),

    _t("store", "schedule", "labor_efficiency_period",
       [r"排班.*效率|排班.*合理|高峰期.*人手.*够"],
       """SELECT sch.shift_type,
          EXTRACT(HOUR FROM sch.start_time)::INT AS start_hour,
          COUNT(e.id) AS staff_count,
          (SELECT COUNT(*) FROM orders o WHERE o.tenant_id = :tenant_id
           AND o.{time_today}
           AND EXTRACT(HOUR FROM o.created_at)::INT BETWEEN
           EXTRACT(HOUR FROM sch.start_time)::INT AND EXTRACT(HOUR FROM sch.end_time)::INT
          ) AS order_count
          FROM schedules sch JOIN employees e ON sch.employee_id = e.id
          WHERE sch.{tenant} AND sch.shift_date = :today_date
          AND e.is_deleted = FALSE AND sch.is_deleted = FALSE
          GROUP BY sch.shift_type, EXTRACT(HOUR FROM sch.start_time)
          ORDER BY start_hour""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "各时段排班与客流对比：{efficiency_data}。", "table"),
]

# ═══════════════════════════════════════════════════════════════════════════
# 6. 渠道域 (Channel) — 15 模板
# ═══════════════════════════════════════════════════════════════════════════

INTENT_TEMPLATES_V2 += [
    _t("channel", "breakdown", "channel_breakdown",
       [r"堂食.*外卖|渠道.*占比|线上.*线下|渠道.*分布|堂食.*对比"],
       """SELECT COALESCE(channel, 'dine_in') AS channel,
          COUNT(*) AS order_count,
          COALESCE(SUM(total_fen), 0) AS total_fen
          FROM orders WHERE {tenant} AND {time_today}
          GROUP BY COALESCE(channel, 'dine_in')""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日渠道分布：{channel_list}。", "pie",
       followups=["外卖占比变化", "哪个平台外卖最多"]),

    _t("channel", "breakdown", "channel_month_breakdown",
       [r"月度.*渠道|本月.*渠道.*占比|月.*各渠道"],
       """SELECT COALESCE(channel, 'dine_in') AS channel,
          COUNT(*) AS order_count,
          COALESCE(SUM(total_fen), 0) AS total_fen
          FROM orders WHERE {tenant} AND {time_month}
          GROUP BY COALESCE(channel, 'dine_in')""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月各渠道营收：{channel_list}。", "pie"),

    _t("channel", "breakdown", "channel_trend",
       [r"渠道.*趋势|堂食.*外卖.*走势|各渠道.*变化"],
       """SELECT DATE(created_at) AS biz_date,
          COALESCE(channel, 'dine_in') AS channel,
          COALESCE(SUM(total_fen), 0) AS total_fen
          FROM orders WHERE {tenant} AND {time_week}
          GROUP BY DATE(created_at), COALESCE(channel, 'dine_in')
          ORDER BY biz_date, channel""".format(tenant=_TENANT_FILTER, time_week=_TIME_WEEK),
       "近7日各渠道营收趋势：{trend_data}。", "line"),

    _t("channel", "delivery", "delivery_top_stores",
       [r"外卖.*最好的.*门店|哪个.*门店.*外卖.*多|外卖.*排行"],
       """SELECT s.name AS store_name,
          COUNT(*) AS delivery_count,
          COALESCE(SUM(o.total_fen), 0) AS delivery_fen
          FROM orders o JOIN stores s ON o.store_id = s.id
          WHERE o.{tenant} AND o.{time_today}
          AND o.channel IN ('meituan', 'eleme', 'douyin')
          AND s.is_deleted = FALSE
          GROUP BY s.name ORDER BY delivery_count DESC LIMIT 10""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日外卖订单最多的门店：{store_list}。", "bar"),

    _t("channel", "delivery", "delivery_avg_time",
       [r"外卖.*送达.*时间|配送.*多久|外卖.*速度"],
       """SELECT COALESCE(channel, 'unknown') AS platform,
          AVG(EXTRACT(EPOCH FROM (delivered_at - created_at))/60) AS avg_delivery_min,
          COUNT(*) AS order_count
          FROM orders WHERE {tenant} AND {time_today}
          AND channel IN ('meituan', 'eleme', 'douyin')
          AND delivered_at IS NOT NULL
          GROUP BY COALESCE(channel, 'unknown')""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日各平台外卖平均送达时间：{delivery_data}。", "bar"),

    _t("channel", "delivery", "delivery_cancellation_rate",
       [r"外卖.*退单.*率|外卖.*取消|外卖.*拒单"],
       """SELECT COALESCE(channel, 'unknown') AS platform,
          COUNT(CASE WHEN status = 'cancelled' THEN 1 END) AS cancelled,
          COUNT(*) AS total
          FROM orders WHERE {tenant} AND {time_today}
          AND channel IN ('meituan', 'eleme', 'douyin')
          GROUP BY COALESCE(channel, 'unknown')""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日各平台外卖退单率：{cancel_data}。", "bar"),

    _t("channel", "platform", "platform_comparison",
       [r"美团.*饿了么.*对比|各平台.*对比|平台.*比较"],
       """SELECT COALESCE(channel, 'unknown') AS platform,
          COUNT(*) AS order_count,
          COALESCE(SUM(total_fen), 0) AS total_fen,
          AVG(total_fen) AS avg_fen
          FROM orders WHERE {tenant} AND {time_month}
          AND channel IN ('meituan', 'eleme', 'douyin')
          GROUP BY COALESCE(channel, 'unknown')""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月各外卖平台对比：{platform_compare}。", "bar"),

    _t("channel", "platform", "channel_margin",
       [r"渠道.*毛利|哪个.*渠道.*赚钱|平台.*抽佣.*对比"],
       """SELECT * FROM mv_channel_margin WHERE tenant_id = :tenant_id LIMIT 20""",
       "各渠道毛利率对比：{channel_margin_data}。", "bar"),

    _t("channel", "platform", "meituan_commission",
       [r"美团.*抽佣|美团.*佣金|美团.*扣点"],
       """SELECT COALESCE(SUM(total_fen), 0) AS gross_fen,
          COALESCE(SUM(commission_fen), 0) AS commission_fen,
          COUNT(*) AS order_count
          FROM orders WHERE {tenant} AND {time_month}
          AND channel = 'meituan'""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月美团抽佣合计 {commission}（{rate}），订单 {count} 笔。", "metric"),

    _t("channel", "platform", "eleme_commission",
       [r"饿了么.*抽佣|饿了么.*佣金|饿了么.*扣点"],
       """SELECT COALESCE(SUM(total_fen), 0) AS gross_fen,
          COALESCE(SUM(commission_fen), 0) AS commission_fen,
          COUNT(*) AS order_count
          FROM orders WHERE {tenant} AND {time_month}
          AND channel = 'eleme'""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月饿了么抽佣合计 {commission}（{rate}），订单 {count} 笔。", "metric"),

    _t("channel", "self", "self_delivery_vs_platform",
       [r"自配送.*平台|自营.*外卖.*对比|私域.*外卖"],
       """SELECT CASE WHEN channel = 'private' THEN '自营' ELSE '平台' END AS delivery_type,
          COUNT(*) AS order_count,
          COALESCE(SUM(total_fen), 0) AS total_fen
          FROM orders WHERE {tenant} AND {time_month}
          AND channel IN ('meituan', 'eleme', 'douyin', 'private')
          GROUP BY CASE WHEN channel = 'private' THEN '自营' ELSE '平台' END""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月自营vs平台外卖对比：{compare_data}。", "bar"),

    _t("channel", "self", "mini_program_orders",
       [r"小程序.*订单|微信.*点餐|小程序.*营收"],
       """SELECT COUNT(*) AS order_count,
          COALESCE(SUM(total_fen), 0) AS total_fen
          FROM orders WHERE {tenant} AND {time_month}
          AND channel = 'miniapp'""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月小程序订单 {count} 笔，营收 {revenue}。", "metric"),

    _t("channel", "self", "scan_to_order",
       [r"扫码.*点餐|桌边.*扫码|扫码.*下单"],
       """SELECT COUNT(*) AS scan_count,
          COALESCE(SUM(total_fen), 0) AS scan_fen
          FROM orders WHERE {tenant} AND {time_today}
          AND order_source = 'scan_to_order'""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日扫码点餐 {count} 笔，营收 {revenue}。", "metric"),

    _t("channel", "self", "takeout_vs_dinein_arppu",
       [r"外卖.*客单.*对比.*堂食|外卖.*人均.*堂食"],
       """SELECT CASE WHEN channel IN ('meituan','eleme','douyin') THEN '外卖' ELSE '堂食' END AS type,
          COALESCE(SUM(total_fen),0)/NULLIF(COUNT(*),0) AS avg_fen
          FROM orders WHERE {tenant} AND {time_today}
          GROUP BY CASE WHEN channel IN ('meituan','eleme','douyin') THEN '外卖' ELSE '堂食' END""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日外卖vs堂食客单价：{compare_data}。", "bar"),

    _t("channel", "self", "douyin_delivery",
       [r"抖音.*外卖|抖音.*团购.*外卖|抖音.*到店"],
       """SELECT product_type,
          COUNT(*) AS order_count,
          COALESCE(SUM(total_fen), 0) AS total_fen
          FROM orders WHERE {tenant} AND {time_month}
          AND channel = 'douyin'
          GROUP BY product_type""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月抖音渠道（团购/外卖）表现：{douyin_data}。", "bar"),
]

# ═══════════════════════════════════════════════════════════════════════════
# 7. 供应链域 (Supply) — 20 模板
# ═══════════════════════════════════════════════════════════════════════════

INTENT_TEMPLATES_V2 += [
    _t("supply", "inventory", "inventory_alert",
       [r"库存.*预警|快.*断货|缺货|库存.*不足|库存.*低"],
       """SELECT ingredient_name, current_qty, unit, min_qty
          FROM inventory WHERE {tenant}
          AND current_qty <= min_qty
          ORDER BY (current_qty::FLOAT / NULLIF(min_qty, 1)) ASC LIMIT 10""".format(tenant=_TENANT_FILTER),
       "当前库存预警食材{count}种：{ingredient_list}。", "table",
       followups=["一键采购", "哪些菜品受影响"]),

    _t("supply", "inventory", "expiry_alert",
       [r"临期|过期|食材.*效期|保质期|快要.*过期"],
       """SELECT ingredient_name, current_qty, unit, expiry_date
          FROM inventory WHERE {tenant}
          AND expiry_date <= CURRENT_DATE + INTERVAL '3 days'
          AND expiry_date >= CURRENT_DATE
          ORDER BY expiry_date ASC LIMIT 10""".format(tenant=_TENANT_FILTER),
       "临期食材（3天内）{count}种：{ingredient_list}。请立即处理！", "table",
       followups=["哪些菜品要用这些食材"]),

    _t("supply", "inventory", "inventory_turnover",
       [r"库存.*周转|库存.*天数|食材.*消耗.*速度"],
       """SELECT ingredient_name,
          COALESCE(SUM(daily_consumption), 0) AS total_consumed,
          current_qty,
          CASE WHEN SUM(daily_consumption) > 0
          THEN current_qty / (SUM(daily_consumption) / NULLIF(COUNT(DISTINCT biz_date), 0))
          ELSE 999 END AS turnover_days
          FROM inventory WHERE {tenant}
          GROUP BY ingredient_name, current_qty
          ORDER BY turnover_days ASC LIMIT 10""".format(tenant=_TENANT_FILTER),
       "库存周转最快的食材（周转天数）：{turnover_list}。", "table"),

    _t("supply", "inventory", "inventory_value",
       [r"库存.*金额|库存.*价值|存货.*总值"],
       """SELECT COALESCE(SUM(current_qty * unit_cost_fen), 0) AS total_value_fen,
          COUNT(DISTINCT ingredient_name) AS sku_count
          FROM inventory WHERE {tenant}""".format(tenant=_TENANT_FILTER),
       "当前库存总价值 {value}，共 {sku_count} 种食材。", "metric"),

    _t("supply", "inventory", "inventory_by_category",
       [r"库存.*分类|各类.*食材.*库存|库存.*品类"],
       """SELECT COALESCE(category, '未分类') AS category,
          COALESCE(SUM(current_qty * unit_cost_fen), 0) AS value_fen,
          COUNT(DISTINCT ingredient_name) AS sku_count
          FROM inventory WHERE {tenant}
          GROUP BY COALESCE(category, '未分类')""".format(tenant=_TENANT_FILTER),
       "各类别库存价值分布：{category_data}。", "pie"),

    _t("supply", "inventory", "slow_moving_inventory",
       [r"滞销.*库存|呆滞.*食材|用.*不.*完.*的.*食材"],
       """SELECT ingredient_name, current_qty, unit,
          COALESCE(SUM(daily_consumption), 0) AS consumed_past_week
          FROM inventory WHERE {tenant}
          GROUP BY ingredient_name, current_qty, unit
          HAVING COALESCE(SUM(daily_consumption), 0) = 0
          ORDER BY current_qty DESC LIMIT 10""".format(tenant=_TENANT_FILTER),
       "滞销库存（近7天零消耗）：{slow_list}。", "table"),

    _t("supply", "procurement", "procurement_by_supplier",
       [r"采购.*供应商|哪个.*供应商.*最.*多|供应商.*采购.*排行"],
       """SELECT s.name AS supplier_name,
          COUNT(po.id) AS po_count,
          COALESCE(SUM(po.total_fen), 0) AS total_fen
          FROM purchase_orders po JOIN suppliers s ON po.supplier_id = s.id
          WHERE po.{tenant} AND po.{time_month}
          AND s.is_deleted = FALSE
          GROUP BY s.name ORDER BY total_fen DESC LIMIT 10""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月按供应商采购金额排行：{supplier_list}。", "bar"),

    _t("supply", "procurement", "procurement_price_trend",
       [r"采购.*价格.*趋势|原料.*价格.*变化|进货.*价格.*涨"],
       """SELECT ingredient_name,
          DATE_TRUNC('week', created_at) AS week_start,
          AVG(unit_price_fen) AS avg_price_fen
          FROM purchase_orders WHERE {tenant}
          AND created_at >= :three_months_ago
          GROUP BY ingredient_name, DATE_TRUNC('week', created_at)
          ORDER BY ingredient_name, week_start""".format(tenant=_TENANT_FILTER),
       "近3个月主要原料采购价格趋势：{price_trend}。", "line"),

    _t("supply", "procurement", "purchase_order_status",
       [r"采购.*订单.*状态|采购.*进度|未.*到货.*采购"],
       """SELECT status, COUNT(*) AS count,
          COALESCE(SUM(total_fen), 0) AS total_fen
          FROM purchase_orders WHERE {tenant}
          GROUP BY status""".format(tenant=_TENANT_FILTER),
       "当前采购订单状态分布：{status_data}。", "pie"),

    _t("supply", "waste", "waste_tracking",
       [r"损耗|浪费|丢弃|报废.*食材|损耗.*统计"],
       """SELECT ingredient_name,
          COALESCE(SUM(waste_qty), 0) AS total_waste,
          COALESCE(SUM(waste_qty * unit_cost_fen), 0) AS waste_value_fen
          FROM inventory WHERE {tenant} AND {time_month}
          AND waste_qty > 0
          GROUP BY ingredient_name ORDER BY waste_value_fen DESC LIMIT 10""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月食材损耗TOP10：{waste_list}。", "bar"),

    _t("supply", "waste", "waste_rate",
       [r"损耗率|损耗.*占比|报废.*率"],
       """SELECT
          COALESCE(SUM(waste_qty * unit_cost_fen), 0) AS waste_fen,
          COALESCE(SUM(purchased_qty * unit_cost_fen), 0) AS purchased_fen
          FROM inventory WHERE {tenant} AND {time_month}""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月食材损耗率 {rate}（{waste} / {purchased}）。", "metric"),

    _t("supply", "waste", "waste_by_store",
       [r"各门店.*损耗|哪家.*门店.*浪费.*多|门店.*损耗.*对比"],
       """SELECT s.name AS store_name,
          SUM(i.waste_qty * i.unit_cost_fen) AS waste_fen
          FROM inventory i JOIN stores s ON i.store_id = s.id
          WHERE i.{tenant} AND i.{time_month}
          AND i.waste_qty > 0 AND s.is_deleted = FALSE
          GROUP BY s.name ORDER BY waste_fen DESC""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月各门店食材损耗：{store_waste}。", "bar"),
]

INTENT_TEMPLATES_V2 += [
    _t("supply", "supplier", "supplier_performance",
       [r"供应商.*表现|供应商.*评分|供应商.*评价"],
       """SELECT s.name AS supplier_name,
          AVG(po.quality_score) AS avg_quality,
          AVG(EXTRACT(EPOCH FROM (po.delivered_at - po.ordered_at))/3600) AS avg_delivery_hours,
          COUNT(CASE WHEN po.status = 'delayed' THEN 1 END) AS delay_count
          FROM purchase_orders po JOIN suppliers s ON po.supplier_id = s.id
          WHERE po.{tenant} AND po.{time_month}
          AND s.is_deleted = FALSE
          GROUP BY s.name ORDER BY avg_quality DESC""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月供应商表现评估：{supplier_data}。", "table"),

    _t("supply", "supplier", "supplier_price_compare",
       [r"供应商.*价格.*对比|哪个.*供应商.*便宜|比价"],
       """SELECT ingredient_name, s.name AS supplier_name,
          AVG(po.unit_price_fen) AS avg_price_fen
          FROM purchase_orders po JOIN suppliers s ON po.supplier_id = s.id
          WHERE po.{tenant} AND po.{time_month} AND s.is_deleted = FALSE
          GROUP BY ingredient_name, s.name
          ORDER BY ingredient_name, avg_price_fen""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月各供应商相同品类价格对比：{compare_data}。", "table"),

    _t("supply", "food_safety", "safety_check",
       [r"食安.*检查|食品安全|溯源.*记录"],
       """SELECT * FROM mv_safety_compliance WHERE tenant_id = :tenant_id LIMIT 10""",
       "食安合规最新记录：{safety_data}。", "table",
       followups=["有违规记录吗"]),

    _t("supply", "food_safety", "temperature_log",
       [r"温度.*记录|冷藏.*温度|冷链.*温度"],
       """SELECT store_name, equipment_name,
          AVG(temperature_celsius) AS avg_temp,
          COUNT(CASE WHEN temperature_celsius > threshold_celsius THEN 1 END) AS alert_count
          FROM temperature_logs WHERE tenant_id = :tenant_id
          AND recorded_at >= :today_start
          GROUP BY store_name, equipment_name
          HAVING COUNT(CASE WHEN temperature_celsius > threshold_celsius THEN 1 END) > 0""",
       "今日温度超标的设备：{temp_data}。", "table"),

    _t("supply", "live_seafood", "live_seafood_status",
       [r"活鲜.*状态|海鲜.*存活.*率|活鲜.*损耗"],
       """SELECT species_name, current_qty, unit, mortality_rate,
          last_feed_time, water_temp_celsius
          FROM live_seafood_inventory WHERE {tenant}
          ORDER BY mortality_rate DESC""".format(tenant=_TENANT_FILTER),
       "当前活鲜状态：{seafood_data}。", "table"),

    _t("supply", "live_seafood", "seafood_mortality_alert",
       [r"海鲜.*死亡.*多|活鲜.*损耗.*高|海鲜.*死.*多少"],
       """SELECT species_name, current_qty, dead_today_qty,
          CASE WHEN current_qty > 0 THEN dead_today_qty::FLOAT / current_qty ELSE 0 END AS mortality_rate
          FROM live_seafood_inventory WHERE {tenant}
          AND dead_today_qty > 0
          ORDER BY mortality_rate DESC""".format(tenant=_TENANT_FILTER),
       "今日活鲜死亡记录：{mortality_data}。", "table"),

    _t("supply", "bom", "bom_explosion",
       [r"BOM|配方.*展开|标准.*用量|配方.*成本"],
       """SELECT d.name AS dish_name,
          i.ingredient_name,
          bi.qty_per_serving,
          i.unit_cost_fen,
          bi.qty_per_serving * i.unit_cost_fen AS cost_per_serving_fen
          FROM bom_items bi JOIN dishes d ON bi.dish_id = d.id
          JOIN inventory i ON bi.ingredient_id = i.id
          WHERE d.{tenant}
          ORDER BY d.name, cost_per_serving_fen DESC""".format(tenant=_TENANT_FILTER),
       "BOM配方成本明细：{bom_data}。", "table"),

    _t("supply", "bom", "bom_cost_change",
       [r"配方.*成本.*变化|BOM.*成本.*上涨|菜品.*成本.*变了"],
       """SELECT d.name AS dish_name,
          COALESCE(SUM(bi.qty_per_serving * i.unit_cost_fen), 0) AS current_cost_fen,
          COALESCE(AVG(bi_last.qty_per_serving * i_last.unit_cost_fen), 0) AS last_month_cost_fen
          FROM bom_items bi JOIN dishes d ON bi.dish_id = d.id
          JOIN inventory i ON bi.ingredient_id = i.id
          LEFT JOIN inventory i_last ON bi.ingredient_id = i_last.id
          WHERE d.{tenant}
          GROUP BY d.name
          HAVING COALESCE(SUM(bi.qty_per_serving * i.unit_cost_fen), 0) >
                 COALESCE(AVG(bi_last.qty_per_serving * i_last.unit_cost_fen), 0) * 1.1
          ORDER BY current_cost_fen DESC""".format(tenant=_TENANT_FILTER),
       "本月BOM成本上涨超10%的菜品：{bom_cost_list}。", "table"),
]

# ═══════════════════════════════════════════════════════════════════════════
# 8. 财务域 (Finance) — 20 模板
# ═══════════════════════════════════════════════════════════════════════════

INTENT_TEMPLATES_V2 += [
    _t("finance", "pnl", "gross_margin",
       [r"毛利|利润率|今天.*赚|毛利.*多少|经营利润"],
       """SELECT COALESCE(SUM(total_fen), 0) AS revenue_fen,
          COALESCE(SUM(cost_fen), 0) AS cost_fen
          FROM orders WHERE {tenant} AND {time_today}""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日营收 {revenue}，成本 {cost}，毛利率 {margin_rate}。", "metric",
       followups=["净利润多少", "同行毛利率对比"]),

    _t("finance", "pnl", "pnl_summary",
       [r"P&?L|损益|盈亏|利润表|利润.*汇总"],
       """SELECT * FROM mv_store_pnl WHERE tenant_id = :tenant_id LIMIT 20""",
       "门店P&L概览：{pnl_summary}。", "table"),

    _t("finance", "pnl", "pnl_monthly",
       [r"月度.*损益|月.*盈亏|这个月.*赚了多少|月利润"],
       """SELECT
          COALESCE(SUM(total_fen), 0) AS revenue_fen,
          COALESCE(SUM(cost_fen), 0) AS cost_fen,
          COALESCE(SUM(discount_fen), 0) AS discount_fen,
          COALESCE(SUM(total_fen) - SUM(cost_fen) - SUM(discount_fen), 0) AS net_fen
          FROM orders WHERE {tenant} AND {time_month}""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月利润：营收 {revenue} - 成本 {cost} - 折扣 {discount} = 净利 {net}。", "metric"),

    _t("finance", "pnl", "net_profit_margin",
       [r"净利润.*率|净利.*率|纯利|净利润.*多少"],
       """SELECT
          COALESCE(SUM(total_fen), 0) AS revenue_fen,
          COALESCE(SUM(total_fen) - SUM(cost_fen) - SUM(discount_fen), 0) AS net_fen
          FROM orders WHERE {tenant} AND {time_month}""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月净利润率 {rate}（净利 {net} / 营收 {revenue}）。", "metric"),

    _t("finance", "pnl", "profit_by_store",
       [r"各门店.*利润|门店.*赚钱.*排行|哪家.*利润.*高"],
       """SELECT s.name AS store_name,
          COALESCE(SUM(o.total_fen - o.cost_fen - o.discount_fen), 0) AS net_fen
          FROM orders o JOIN stores s ON o.store_id = s.id
          WHERE o.{tenant} AND o.{time_month} AND s.is_deleted = FALSE
          GROUP BY s.name ORDER BY net_fen DESC""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月各门店净利润排行：{profit_rank}。", "bar"),

    _t("finance", "cashflow", "daily_cashflow",
       [r"现金.*流|今天.*现金.*多少|收银.*统计"],
       """SELECT
          COALESCE(SUM(CASE WHEN pay_method = 'cash' THEN total_fen ELSE 0 END), 0) AS cash_fen,
          COALESCE(SUM(CASE WHEN pay_method = 'wechat' THEN total_fen ELSE 0 END), 0) AS wechat_fen,
          COALESCE(SUM(CASE WHEN pay_method = 'alipay' THEN total_fen ELSE 0 END), 0) AS alipay_fen,
          COALESCE(SUM(CASE WHEN pay_method = 'stored_value' THEN total_fen ELSE 0 END), 0) AS stored_fen,
          COALESCE(SUM(CASE WHEN pay_method = 'bank_card' THEN total_fen ELSE 0 END), 0) AS card_fen
          FROM orders WHERE {tenant} AND {time_today}""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日现金流：现金 {cash} / 微信 {wechat} / 支付宝 {alipay} / 储值 {stored} / 刷卡 {card}。", "bar"),

    _t("finance", "cashflow", "payment_method_trend",
       [r"支付.*方式.*趋势|支付.*占比.*变化"],
       """SELECT DATE(created_at) AS biz_date,
          COALESCE(SUM(CASE WHEN pay_method = 'wechat' THEN total_fen ELSE 0 END), 0) AS wechat_fen,
          COALESCE(SUM(CASE WHEN pay_method = 'alipay' THEN total_fen ELSE 0 END), 0) AS alipay_fen
          FROM orders WHERE {tenant} AND {time_week}
          GROUP BY DATE(created_at) ORDER BY biz_date""".format(tenant=_TENANT_FILTER, time_week=_TIME_WEEK),
       "近7日微信/支付宝支付趋势：{trend_data}。", "line"),

    _t("finance", "budget", "budget_variance",
       [r"预算.*差异|预算.*偏差|实际.*预算.*对比"],
       """SELECT
          (SELECT COALESCE(SUM(total_fen), 0) FROM orders WHERE {tenant} AND {time_month}) AS actual_fen,
          (SELECT COALESCE(SUM(monthly_revenue_target_fen), 0) FROM stores WHERE {tenant}) AS budget_fen""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月营收预算完成度 {progress}（实际 {actual} / 预算 {budget}）。", "gauge"),

    _t("finance", "budget", "budget_by_category",
       [r"各.*费.*预算|预算.*执行|费用.*预算"],
       """SELECT budget_category,
          COALESCE(SUM(budget_fen), 0) AS budget_fen,
          COALESCE(SUM(actual_fen), 0) AS actual_fen
          FROM budgets WHERE {tenant} AND budget_month = TO_CHAR(:today_date, 'YYYY-MM')
          GROUP BY budget_category""".format(tenant=_TENANT_FILTER),
       "本月各项预算执行：{budget_data}。", "bar"),

    _t("finance", "invoice", "invoice_summary",
       [r"开票.*统计|发票.*汇总|发票.*多少"],
       """SELECT
          COUNT(*) AS invoice_count,
          COALESCE(SUM(amount_fen), 0) AS total_fen,
          COALESCE(SUM(tax_fen), 0) AS total_tax_fen
          FROM invoices WHERE {tenant} AND {time_today}""".format(tenant=_TENANT_FILTER, time_today=_TIME_TODAY),
       "今日开票 {count} 张，合计 {amount}，税额 {tax}。", "metric"),

    _t("finance", "invoice", "invoice_digital_tax",
       [r"全电.*发票|金税|电子.*发票.*进度"],
       """SELECT
          COUNT(CASE WHEN invoice_type = 'digital_full' THEN 1 END) AS digital_count,
          COUNT(CASE WHEN invoice_type = 'paper' THEN 1 END) AS paper_count
          FROM invoices WHERE {tenant} AND {time_month}""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月全电发票 {digital_count} 张，纸质 {paper_count} 张。全电化率 {rate}。", "metric"),
]

INTENT_TEMPLATES_V2 += [
    _t("finance", "anomaly", "margin_attribution",
       [r"为什么.*下降|毛利.*低|利润.*降|利润.*为什么.*差"],
       """SELECT
          (SELECT COALESCE(SUM(total_fen), 0) FROM orders WHERE {tenant} AND {time_month}) AS current_revenue,
          (SELECT COALESCE(SUM(total_fen), 0) FROM orders WHERE {tenant}
           AND created_at >= :last_month_start AND created_at < :month_start) AS prev_revenue,
          (SELECT COALESCE(SUM(cost_fen), 0) FROM orders WHERE {tenant} AND {time_month}) AS current_cost,
          (SELECT COALESCE(SUM(cost_fen), 0) FROM orders WHERE {tenant}
           AND created_at >= :last_month_start AND created_at < :month_start) AS prev_cost,
          (SELECT COALESCE(SUM(discount_fen), 0) FROM orders WHERE {tenant} AND {time_month}) AS current_discount,
          (SELECT COALESCE(SUM(discount_fen), 0) FROM orders WHERE {tenant}
           AND created_at >= :last_month_start AND created_at < :month_start) AS prev_discount""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "毛利变动归因分析：{attribution_analysis}。", "comparison"),

    _t("finance", "anomaly", "cost_root_cause",
       [r"成本.*为什么.*涨|成本.*上升.*原因|什么.*导致.*成本"],
       """SELECT d.category,
          COALESCE(SUM(o.cost_fen), 0) AS current_cost,
          LAG(COALESCE(SUM(o.cost_fen), 0)) OVER (ORDER BY d.category) AS prev_cost
          FROM order_items oi JOIN dishes d ON oi.dish_id = d.id
          JOIN orders o ON oi.order_id = o.id
          WHERE o.{tenant} AND (o.{time_month} OR (o.created_at >= :last_month_start AND o.created_at < :month_start))
          AND d.is_deleted = FALSE AND o.is_deleted = FALSE
          GROUP BY d.category""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "成本变动根因分析：{root_cause}。", "table"),

    _t("finance", "anomaly", "discount_anomaly",
       [r"折扣.*异常|折扣.*可疑|折扣.*守护|折扣.*监控"],
       """SELECT * FROM mv_discount_health WHERE tenant_id = :tenant_id LIMIT 20""",
       "折扣健康状况：{health_summary}。", "table"),

    _t("finance", "tax", "tax_summary",
       [r"税务.*汇总|税金.*统计|税负.*情况"],
       """SELECT
          COALESCE(SUM(vat_output_fen), 0) AS vat_output,
          COALESCE(SUM(vat_input_fen), 0) AS vat_input,
          COALESCE(SUM(income_tax_fen), 0) AS income_tax
          FROM tax_records WHERE {tenant}
          AND tax_period = TO_CHAR(:today_date, 'YYYY-MM')""".format(tenant=_TENANT_FILTER),
       "本月税务汇总：销项 {vat_out} / 进项 {vat_in} / 所得税 {income_tax}。", "metric"),

    _t("finance", "tax", "invoice_send_status",
       [r"发票.*发送|发票.*推送|开票.*状态"],
       """SELECT status, COUNT(*) AS count
          FROM invoices WHERE {tenant} AND {time_month}
          GROUP BY status""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月发票状态分布：{status_data}。", "pie"),
]

INTENT_TEMPLATES_V2 += [
    _t("finance", "receivable", "receivable_aging",
       [r"应收.*账龄|挂账.*多久|应收账款.*分析"],
       """SELECT
          CASE WHEN days_overdue <= 0 THEN '未到期' WHEN days_overdue <= 30 THEN '1-30天'
               WHEN days_overdue <= 60 THEN '31-60天' WHEN days_overdue <= 90 THEN '61-90天'
               ELSE '90天以上' END AS aging_bucket,
          COALESCE(SUM(amount_fen), 0) AS total_fen
          FROM receivables WHERE {tenant}
          GROUP BY CASE WHEN days_overdue <= 0 THEN '未到期' WHEN days_overdue <= 30 THEN '1-30天'
               WHEN days_overdue <= 60 THEN '31-60天' WHEN days_overdue <= 90 THEN '61-90天'
               ELSE '90天以上' END""".format(tenant=_TENANT_FILTER),
       "应收账款账龄分析：{aging_data}。", "pie"),

    _t("finance", "receivable", "top_receivables",
       [r"最大.*应收.*客户|欠款.*最多.*客户|挂账.*排行"],
       """SELECT customer_name,
          COALESCE(SUM(amount_fen), 0) AS outstanding_fen,
          MAX(days_overdue) AS max_days_overdue
          FROM receivables WHERE {tenant} AND status = 'open'
          GROUP BY customer_name
          ORDER BY outstanding_fen DESC LIMIT 10""".format(tenant=_TENANT_FILTER),
       "当前应收账款TOP10：{receivable_list}。", "table"),

    _t("finance", "receivable", "corp_account_settlement",
       [r"协议.*挂账.*结算|公司.*挂账|企业.*客户.*结算"],
       """SELECT c.name AS corp_name,
          COALESCE(SUM(o.total_fen), 0) AS total_fen,
          COUNT(o.id) AS order_count,
          MAX(o.created_at) AS last_dine_date
          FROM orders o JOIN corporate_accounts c ON o.corp_account_id = c.id
          WHERE o.{tenant} AND o.{time_month}
          AND o.pay_method = 'corp_account'
          AND c.is_deleted = FALSE
          GROUP BY c.name ORDER BY total_fen DESC""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月协议挂账客户排行：{corp_list}。", "table"),

    _t("finance", "receivable", "daily_settlement_verify",
       [r"日结.*校验|日结.*审核|结算.*是否.*正确"],
       """SELECT * FROM mv_daily_settlement WHERE tenant_id = :tenant_id
          AND biz_date = :today_date LIMIT 5""",
       "今日日结校验结果：{verify_result}。", "table"),
]

# ═══════════════════════════════════════════════════════════════════════════
# 9. 人效域 (HR) — 10 模板
# ═══════════════════════════════════════════════════════════════════════════

INTENT_TEMPLATES_V2 += [
    _t("hr", "headcount", "headcount_summary",
       [r"员工.*人数|总共.*多少人|在岗.*人数|全公司.*多少人"],
       """SELECT COUNT(*) AS total_count,
          COUNT(CASE WHEN status = 'active' THEN 1 END) AS active_count
          FROM employees WHERE {tenant}""".format(tenant=_TENANT_FILTER),
       "当前员工 {active_count} 人在岗（共 {total_count} 人）。", "metric",
       followups=["哪个门店人最多"]),

    _t("hr", "headcount", "headcount_by_store",
       [r"各门店.*人数|每个.*店.*多少人|门店.*员工.*数量"],
       """SELECT s.name AS store_name,
          COUNT(e.id) AS headcount
          FROM stores s LEFT JOIN employees e ON s.id = e.store_id
          AND e.status = 'active' AND e.is_deleted = FALSE
          WHERE s.{tenant}
          GROUP BY s.name ORDER BY headcount DESC""".format(tenant=_TENANT_FILTER),
       "各门店在岗人数：{headcount_data}。", "bar"),

    _t("hr", "efficiency", "revenue_per_headcount",
       [r"人效|人均.*产出|人均.*营收|每.*人.*产出"],
       """SELECT s.name AS store_name,
          COALESCE(SUM(o.total_fen), 0) / NULLIF(COUNT(DISTINCT e.id), 0) AS per_capita_fen,
          COUNT(DISTINCT e.id) AS headcount
          FROM stores s LEFT JOIN orders o ON s.id = o.store_id
          AND o.{time_month} AND o.is_deleted = FALSE
          LEFT JOIN employees e ON s.id = e.store_id
          AND e.status = 'active' AND e.is_deleted = FALSE
          WHERE s.{tenant}
          GROUP BY s.name ORDER BY per_capita_fen DESC""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月各门店人均创收：{efficiency_data}。", "bar"),

    _t("hr", "efficiency", "staff_turnover",
       [r"员工.*离职|流失.*率|员工.*流动"],
       """SELECT
          COUNT(CASE WHEN status = 'resigned' AND updated_at >= :month_start AND updated_at < :tomorrow_start THEN 1 END) AS resigned,
          COUNT(*) AS total
          FROM employees WHERE {tenant}""".format(tenant=_TENANT_FILTER),
       "本月员工离职 {resigned} 人，离职率 {rate}。", "metric"),

    _t("hr", "scheduling", "schedule_overview",
       [r"排班.*总览|今天.*排班.*情况|上班.*人数"],
       """SELECT COUNT(DISTINCT e.id) AS on_duty_count,
          COUNT(DISTINCT s.shift_type) AS shift_types
          FROM schedules s JOIN employees e ON s.employee_id = e.id
          WHERE s.{tenant} AND s.shift_date = :today_date
          AND e.status = 'active'
          AND s.is_deleted = FALSE AND e.is_deleted = FALSE""".format(tenant=_TENANT_FILTER),
       "今日排班 {on_duty_count} 人在岗，{shift_types} 种班次。", "metric"),

    _t("hr", "scheduling", "overtime_analysis",
       [r"加班.*分析|加班.*排行|谁.*加班.*多"],
       """SELECT e.name,
          COALESCE(SUM(s.overtime_hours), 0) AS overtime_hours,
          COUNT(DISTINCT s.shift_date) AS overtime_days
          FROM schedules s JOIN employees e ON s.employee_id = e.id
          WHERE s.{tenant}
          AND s.shift_date >= :month_start AND s.shift_date < :tomorrow_start
          AND s.overtime_hours > 0
          AND e.is_deleted = FALSE AND s.is_deleted = FALSE
          GROUP BY e.name ORDER BY overtime_hours DESC LIMIT 10""".format(tenant=_TENANT_FILTER),
       "本月加班TOP10员工：{overtime_list}。", "bar"),

    _t("hr", "performance", "top_performers",
       [r"优秀.*员工|销售.*冠军|业绩.*最好.*员工|表现.*最好"],
       """SELECT e.name, s.name AS store_name,
          COALESCE(SUM(o.total_fen), 0) AS sales_fen,
          COUNT(o.id) AS order_count
          FROM orders o JOIN employees e ON o.server_id = e.id
          JOIN stores s ON e.store_id = s.id
          WHERE o.{tenant} AND o.{time_month}
          AND e.is_deleted = FALSE
          GROUP BY e.id, e.name, s.name
          ORDER BY sales_fen DESC LIMIT 10""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月销售业绩最好的员工：{performer_list}。", "table"),

    _t("hr", "performance", "employee_attendance",
       [r"考勤|出勤.*率|迟到|缺勤"],
       """SELECT
          COUNT(CASE WHEN status = 'on_time' THEN 1 END) AS on_time,
          COUNT(CASE WHEN status = 'late' THEN 1 END) AS late,
          COUNT(CASE WHEN status = 'absent' THEN 1 END) AS absent,
          COUNT(*) AS total
          FROM attendances WHERE {tenant}
          AND attendance_date = :today_date""".format(tenant=_TENANT_FILTER),
       "今日考勤：准时 {on_time} / 迟到 {late} / 缺勤 {absent}。出勤率 {rate}。", "metric"),

    _t("hr", "performance", "training_completion",
       [r"培训.*完成|员工.*培训.*进度|培训.*统计"],
       """SELECT training_name,
          COUNT(CASE WHEN status = 'completed' THEN 1 END) AS completed,
          COUNT(*) AS total
          FROM training_records WHERE {tenant}
          AND due_date <= :today_date
          GROUP BY training_name""".format(tenant=_TENANT_FILTER),
       "培训完成情况：{training_data}。", "bar"),

    _t("hr", "performance", "employee_satisfaction",
       [r"员工.*满意度|员工.*投诉|员工.*反馈"],
       """SELECT
          AVG(satisfaction_score) AS avg_score,
          COUNT(CASE WHEN satisfaction_score < 3 THEN 1 END) AS low_count,
          COUNT(*) AS total
          FROM employee_surveys WHERE {tenant}
          AND survey_date >= :month_start""".format(tenant=_TENANT_FILTER),
       "本月员工满意度平均 {score}/5，{low_count} 人打分低于3。", "metric"),
]

# ═══════════════════════════════════════════════════════════════════════════
# 10. 营销域 (Marketing) — 10 模板
# ═══════════════════════════════════════════════════════════════════════════

INTENT_TEMPLATES_V2 += [
    _t("marketing", "campaign", "campaign_performance",
       [r"营销.*效果|活动.*效果|活动.*数据|活动.*ROI"],
       """SELECT c.name AS campaign_name,
          COUNT(CASE WHEN cr.status = 'redeemed' THEN 1 END) AS redeemed,
          COALESCE(SUM(CASE WHEN cr.status = 'redeemed' THEN cr.order_total_fen ELSE 0 END), 0) AS order_revenue_fen,
          c.budget_fen
          FROM campaigns c LEFT JOIN coupon_records cr ON c.id = cr.campaign_id
          AND cr.status = 'redeemed'
          WHERE c.{tenant} AND c.{time_month}
          AND c.is_deleted = FALSE
          GROUP BY c.name, c.budget_fen ORDER BY order_revenue_fen DESC""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月营销活动效果：{campaign_data}。", "bar",
       followups=["哪个活动ROI最高"]),

    _t("marketing", "campaign", "campaign_roi",
       [r"活动.*ROI|营销.*投入产出|活动.*回报.*率"],
       """SELECT c.name AS campaign_name,
          c.budget_fen,
          COALESCE(SUM(CASE WHEN cr.status = 'redeemed' THEN cr.order_total_fen ELSE 0 END), 0) AS revenue_fen,
          CASE WHEN c.budget_fen > 0 THEN
          COALESCE(SUM(CASE WHEN cr.status = 'redeemed' THEN cr.order_total_fen ELSE 0 END), 0)::FLOAT / c.budget_fen
          ELSE 0 END AS roi
          FROM campaigns c LEFT JOIN coupon_records cr ON c.id = cr.campaign_id
          WHERE c.{tenant} AND c.start_date >= :month_start
          AND c.is_deleted = FALSE
          GROUP BY c.name, c.budget_fen ORDER BY roi DESC""".format(tenant=_TENANT_FILTER),
       "本月营销活动ROI排行：{roi_list}。", "bar"),

    _t("marketing", "coupon", "coupon_distribution",
       [r"发券.*统计|发了.*多少.*券|优惠券.*发放"],
       """SELECT c.name AS coupon_name,
          COUNT(*) AS total_sent,
          COUNT(CASE WHEN cr.status = 'redeemed' THEN 1 END) AS redeemed,
          COUNT(CASE WHEN cr.status = 'expired' THEN 1 END) AS expired
          FROM coupon_records cr JOIN coupons c ON cr.coupon_id = c.id
          WHERE cr.{tenant} AND cr.created_at >= :month_start
          AND c.is_deleted = FALSE
          GROUP BY c.name""".format(tenant=_TENANT_FILTER),
       "本月优惠券发放/核销/过期统计：{coupon_data}。", "bar"),

    _t("marketing", "coupon", "most_effective_coupon_type",
       [r"什么.*券.*最.*有效|哪种.*优惠券.*好|券.*类型.*效果"],
       """SELECT c.type AS coupon_type,
          COUNT(CASE WHEN cr.status = 'redeemed' THEN 1 END) AS redeemed,
          COUNT(*) AS total_sent,
          COUNT(CASE WHEN cr.status = 'redeemed' THEN 1 END)::FLOAT / NULLIF(COUNT(*), 0) AS redemption_rate
          FROM coupon_records cr JOIN coupons c ON cr.coupon_id = c.id
          WHERE cr.{tenant} AND cr.created_at >= :month_start
          AND c.is_deleted = FALSE
          GROUP BY c.type ORDER BY redemption_rate DESC""".format(tenant=_TENANT_FILTER),
       "各类型优惠券核销率对比：{coupon_type_data}。", "bar"),

    _t("marketing", "gift_card", "gift_card_sales",
       [r"礼品卡.*销售|礼品卡.*情况|送礼.*卡"],
       """SELECT
          COUNT(*) AS sold_count,
          COALESCE(SUM(face_value_fen), 0) AS total_face_value,
          COALESCE(SUM(redeemed_fen), 0) AS redeemed_fen
          FROM gift_cards WHERE {tenant}
          AND sold_at >= :month_start AND sold_at < :tomorrow_start""".format(tenant=_TENANT_FILTER),
       "本月礼品卡售出 {count} 张，面值 {face_value}，已消费 {redeemed}。", "metric"),

    _t("marketing", "gift_card", "gift_card_redemption_rate",
       [r"礼品卡.*核销.*率|送礼.*卡.*使用.*率"],
       """SELECT
          COUNT(CASE WHEN redeemed_fen > 0 THEN 1 END) AS redeemed,
          COUNT(*) AS total
          FROM gift_cards WHERE {tenant}
          AND sold_at >= :six_months_ago""".format(tenant=_TENANT_FILTER),
       "近6个月礼品卡核销率 {rate}（{redeemed}/{total}）。", "metric"),

    _t("marketing", "loyalty", "loyalty_points_balance",
       [r"积分.*余额|会员.*积分|积分.*统计"],
       """SELECT COALESCE(SUM(points_balance), 0) AS total_points,
          COUNT(CASE WHEN points_balance > 0 THEN 1 END) AS members_with_points
          FROM members WHERE {tenant}""".format(tenant=_TENANT_FILTER),
       "当前会员积分总余额 {points} 分，涉及 {count} 位会员。", "metric"),

    _t("marketing", "loyalty", "points_redemption",
       [r"积分.*兑换|积分.*核销|积分.*消耗"],
       """SELECT redemption_item,
          COUNT(*) AS redemption_count,
          COALESCE(SUM(points_cost), 0) AS total_points_cost
          FROM point_redemptions WHERE {tenant}
          AND created_at >= :month_start AND created_at < :tomorrow_start
          GROUP BY redemption_item ORDER BY redemption_count DESC""".format(tenant=_TENANT_FILTER),
       "本月积分兑换排行：{redemption_data}。", "bar"),

    _t("marketing", "private_domain", "wecom_followers",
       [r"企微.*粉丝|企业微信.*好友|私域.*人数"],
       """SELECT COUNT(*) AS follower_count,
          COUNT(CASE WHEN is_member = TRUE THEN 1 END) AS member_followers
          FROM wecom_contacts WHERE {tenant}""".format(tenant=_TENANT_FILTER),
       "当前企业微信好友 {count} 人，其中已注册会员 {member_count} 人。", "metric"),

    _t("marketing", "private_domain", "private_domain_order_rate",
       [r"私域.*订单.*率|企微.*转化|社群.*下单"],
       """SELECT
          COUNT(CASE WHEN source IN ('wecom', 'wechat_group') THEN 1 END) AS private_orders,
          COUNT(*) AS total_orders
          FROM orders WHERE {tenant} AND {time_month}""".format(tenant=_TENANT_FILTER, time_month=_TIME_MONTH),
       "本月私域订单占比 {rate}（{private}/{total}）。", "metric"),
]

# ═══════════════════════════════════════════════════════════════════════════
# 模板计数和预编译
# ═══════════════════════════════════════════════════════════════════════════

TEMPLATE_COUNT: int = len(INTENT_TEMPLATES_V2)

# 为每个模板的每个 pattern 预编译正则
_COMPILED_V2: list[dict[str, Any]] = []
for _tpl in INTENT_TEMPLATES_V2:
    for _i, _pat in enumerate(_tpl["patterns"]):
        _COMPILED_V2.append({
            "re": re.compile(_pat, re.IGNORECASE),
            "template": _tpl,
            "pattern_index": _i,
        })


def match_intent_v2(question: str) -> dict[str, Any] | None:
    """在 200+ 模板中匹配第一个命中，返回模板字典或 None"""
    q = question.strip()
    for entry in _COMPILED_V2:
        if entry["re"].search(q):
            return entry["template"]
    return None


def match_intent_v2_topk(question: str, k: int = 3) -> list[dict[str, Any]]:
    """返回置信度最高的 top-k 个匹配模板（用于模糊意图确认）"""
    matches: list[tuple[int, dict[str, Any]]] = []
    q = question.strip()
    for entry in _COMPILED_V2:
        m = entry["re"].search(q)
        if m:
            # 匹配质量评分：pattern 越长越精确
            score = len(entry["re"].pattern)
            matches.append((score, entry["template"]))
    # 去重 & 排序
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for _, tpl in sorted(matches, key=lambda x: x[0], reverse=True):
        if tpl["id"] not in seen:
            seen.add(tpl["id"])
            unique.append(tpl)
        if len(unique) >= k:
            break
    return unique


def get_templates_by_category(category: str) -> list[dict[str, Any]]:
    """返回指定业务域的所有模板"""
    return [t for t in INTENT_TEMPLATES_V2 if t["category"] == category]


def get_template_by_id(template_id: str) -> dict[str, Any] | None:
    """根据 ID 获取模板"""
    for t in INTENT_TEMPLATES_V2:
        if t["id"] == template_id:
            return t
    return None


def get_category_counts() -> dict[str, int]:
    """返回各业务域模板数量统计"""
    counts: dict[str, int] = {}
    for t in INTENT_TEMPLATES_V2:
        cat = t["category"]
        counts[cat] = counts.get(cat, 0) + 1
    return counts
