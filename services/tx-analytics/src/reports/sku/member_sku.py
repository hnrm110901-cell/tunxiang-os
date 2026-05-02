"""会员域固定报表SKU — 30个模板

覆盖：增长/活跃/流失/RFM/储值/积分/优惠券/生日/生命周期/私域
"""

from __future__ import annotations
from typing import Any

_TF = "tenant_id = :tenant_id AND is_deleted = FALSE"

MEMBER_SKUS: list[dict[str, Any]] = []


def _reg(sku_id: str, name: str, desc: str, cols: list[dict], sql: str,
         params: dict | None = None, domain: str = "member") -> dict:
    return {
        "sku_id": f"{domain}_{sku_id}", "name": name, "description": desc,
        "domain": domain, "columns": cols, "sql": sql.strip(),
        "default_params": params or {},
    }


# ── 会员增长 (5) ──────────────────────────────────────────────────────
MEMBER_SKUS += [
    _reg("growth_daily", "会员增长日报", "当日新增/活跃/流失会员数",
         [{"name":"new_members","label":"新注册"},{"name":"active_members","label":"活跃会员"},
          {"name":"lost_members","label":"流失会员"},{"name":"net_growth","label":"净增长"}],
         """SELECT COALESCE(SUM(CASE WHEN m.created_at>=:today_start AND m.created_at<:tomorrow_start THEN 1 ELSE 0 END),0) AS new_members,
            COUNT(DISTINCT CASE WHEN EXISTS(SELECT 1 FROM orders o WHERE o.member_id=m.id AND o.created_at>=:today_start AND o.created_at<:tomorrow_start) THEN m.id END) AS active_members,
            COALESCE(SUM(CASE WHEN m.last_order_date<:lost_threshold THEN 1 ELSE 0 END),0) AS lost_members
            FROM members m WHERE m.{}""".format(_TF.replace("tenant_id","m.tenant_id").replace("is_deleted","m.is_deleted")),
         {"today_start":"today()","tomorrow_start":"tomorrow()","lost_threshold":"90days_ago()"}),
    _reg("growth_monthly_trend", "会员增长月趋势", "近12个月每月新增/活跃/流失趋势",
         [{"name":"month","label":"月份"},{"name":"new_count","label":"新增"},{"name":"active_count","label":"活跃"},
          {"name":"lost_count","label":"流失"},{"name":"total_count","label":"总会员数"}],
         """SELECT TO_CHAR(DATE_TRUNC('month',gs.month),'YYYY-MM') AS month,
            COALESCE(SUM(CASE WHEN m.created_at>=gs.month AND m.created_at<gs.month+INTERVAL'1 month' THEN 1 ELSE 0 END),0) AS new_count,
            COUNT(DISTINCT CASE WHEN EXISTS(SELECT 1 FROM orders o WHERE o.member_id=m.id AND o.created_at>=gs.month AND o.created_at<gs.month+INTERVAL'1 month') THEN m.id END) AS active_count,
            COUNT(DISTINCT CASE WHEN m.last_order_date<gs.month-INTERVAL'90 days' THEN m.id END) AS lost_count,
            COUNT(DISTINCT CASE WHEN m.created_at<gs.month+INTERVAL'1 month' THEN m.id END) AS total_count
            FROM GENERATE_SERIES(:year_start,:year_end,INTERVAL'1 month') gs(month)
            LEFT JOIN members m ON m.tenant_id=:tenant_id AND m.is_deleted=FALSE
            GROUP BY gs.month ORDER BY month""",
         {"year_start":"year_start()","year_end":"tomorrow()"}),
]

# ── RFM分析 (5) ──────────────────────────────────────────────────────
MEMBER_SKUS += [
    _reg("rfm_summary", "RFM分层汇总", "各RFM层级人数/消费/占比",
         [{"name":"rfm_tier","label":"RFM层级"},{"name":"member_count","label":"人数"},
          {"name":"total_spend_fen","label":"总消费(分)"},{"name":"avg_spend_fen","label":"人均消费(分)"},
          {"name":"share_pct","label":"人数占比","format":"0.0%"}],
         """SELECT m.rfm_tier, COUNT(*) AS member_count,
            COALESCE(SUM(m.total_spend_fen),0) AS total_spend_fen,
            CASE WHEN COUNT(*)>0 THEN COALESCE(SUM(m.total_spend_fen),0)/COUNT(*) ELSE 0 END AS avg_spend_fen,
            COUNT(*)*100.0/SUM(COUNT(*)) OVER() AS share_pct
            FROM members m WHERE m.tenant_id=:tenant_id AND m.is_deleted=FALSE
            GROUP BY m.rfm_tier ORDER BY total_spend_fen DESC"""),
    _reg("rfm_composition", "RFM构成分析", "高价值/中价值/低价值会员各维度均值",
         [{"name":"rfm_tier","label":"层级"},{"name":"member_count","label":"人数"},
          {"name":"avg_recency_days","label":"均最近消费(天)"},{"name":"avg_frequency","label":"均消费频次"},
          {"name":"avg_monetary_fen","label":"均消费额(分)"}],
         """SELECT m.rfm_tier, COUNT(*) AS member_count,
            ROUND(AVG(EXTRACT(DAY FROM NOW()-m.last_order_date))) AS avg_recency_days,
            ROUND(AVG(m.order_count),1) AS avg_frequency,
            ROUND(AVG(m.total_spend_fen)) AS avg_monetary_fen
            FROM members m WHERE m.tenant_id=:tenant_id AND m.is_deleted=FALSE AND m.rfm_tier IS NOT NULL
            GROUP BY m.rfm_tier ORDER BY avg_monetary_fen DESC"""),
]

# ── 复购分析 (4) ──────────────────────────────────────────────────────
MEMBER_SKUS += [
    _reg("repurchase_rate", "会员复购率", "月度复购率趋势",
         [{"name":"month","label":"月份"},{"name":"total_active","label":"活跃会员"},
          {"name":"repurchase_count","label":"复购会员"},{"name":"repurchase_rate","label":"复购率","format":"0.0%"}],
         """WITH member_orders AS (
            SELECT m.id, DATE_TRUNC('month',o.created_at) AS mon, COUNT(*) AS cnt
            FROM members m JOIN orders o ON m.id=o.member_id
            WHERE m.tenant_id=:tenant_id AND m.is_deleted=FALSE AND o.created_at>=:period_start
            GROUP BY m.id, DATE_TRUNC('month',o.created_at)
        )
        SELECT TO_CHAR(mon,'YYYY-MM') AS month, COUNT(DISTINCT id) AS total_active,
            COUNT(DISTINCT CASE WHEN cnt>=2 THEN id END) AS repurchase_count,
            CASE WHEN COUNT(DISTINCT id)>0 THEN COUNT(DISTINCT CASE WHEN cnt>=2 THEN id END)*100.0/COUNT(DISTINCT id) ELSE 0 END AS repurchase_rate
        FROM member_orders GROUP BY mon ORDER BY month""",
         {"period_start":"year_start()"}),
    _reg("member_visit_frequency", "会员消费频次分布", "各消费频次段会员人数",
         [{"name":"visit_range","label":"消费次数"},{"name":"member_count","label":"人数"},{"name":"share_pct","label":"占比","format":"0.0%"}],
         """SELECT CASE WHEN m.order_count=1 THEN '1次' WHEN m.order_count<=3 THEN '2-3次'
                         WHEN m.order_count<=6 THEN '4-6次' WHEN m.order_count<=12 THEN '7-12次' ELSE '12次以上' END AS visit_range,
            COUNT(*) AS member_count, COUNT(*)*100.0/SUM(COUNT(*)) OVER() AS share_pct
            FROM members m WHERE m.tenant_id=:tenant_id AND m.is_deleted=FALSE AND m.order_count>0
            GROUP BY visit_range ORDER BY MIN(m.order_count)"""),
]

# ── 生命周期 (4) ──────────────────────────────────────────────────────
MEMBER_SKUS += [
    _reg("lifecycle_stages", "会员生命周期分布", "新客/活跃/沉睡/流失各阶段人数",
         [{"name":"stage","label":"阶段"},{"name":"member_count","label":"人数"},
          {"name":"share_pct","label":"占比","format":"0.0%"},{"name":"avg_spend_fen","label":"人均消费(分)"}],
         """SELECT CASE WHEN m.created_at>=:new_threshold THEN '新客'
                         WHEN m.last_order_date>=:active_threshold THEN '活跃'
                         WHEN m.last_order_date>=:dormant_threshold THEN '沉睡' ELSE '流失' END AS stage,
            COUNT(*) AS member_count, COUNT(*)*100.0/SUM(COUNT(*)) OVER() AS share_pct,
            ROUND(AVG(COALESCE(m.total_spend_fen,0))) AS avg_spend_fen
            FROM members m WHERE m.tenant_id=:tenant_id AND m.is_deleted=FALSE
            GROUP BY stage ORDER BY MIN(m.created_at)""",
         {"new_threshold":"30days_ago()","active_threshold":"30days_ago()","dormant_threshold":"90days_ago()"}),
    _reg("churn_risk", "流失预警名单", "90天未消费且高价值的会员",
         [{"name":"member_name","label":"会员"},{"name":"phone","label":"手机号"},
          {"name":"last_order_date","label":"最后消费日"},{"name":"total_spend_fen","label":"历史消费(分)"},
          {"name":"days_inactive","label":"未消费天数"}],
         """SELECT m.name AS member_name, m.phone,
            m.last_order_date, m.total_spend_fen,
            EXTRACT(DAY FROM NOW()-m.last_order_date)::INT AS days_inactive
            FROM members m WHERE m.tenant_id=:tenant_id AND m.is_deleted=FALSE
            AND m.last_order_date<:churn_threshold AND m.total_spend_fen>:min_spend
            ORDER BY m.total_spend_fen DESC LIMIT 100""",
         {"churn_threshold":"90days_ago()","min_spend":"100000"}),
]

# ── 储值/积分 (4) ──────────────────────────────────────────────────────
MEMBER_SKUS += [
    _reg("stored_value_summary", "储值分析", "储值金额/消耗/余额趋势",
         [{"name":"month","label":"月份"},{"name":"recharge_fen","label":"充值(分)"},
          {"name":"consume_fen","label":"消耗(分)"},{"name":"balance_fen","label":"余额(分)"}],
         """SELECT TO_CHAR(DATE_TRUNC('month',mt.created_at),'YYYY-MM') AS month,
            COALESCE(SUM(CASE WHEN mt.type='recharge' THEN mt.amount_fen ELSE 0 END),0) AS recharge_fen,
            COALESCE(SUM(CASE WHEN mt.type='consume' THEN mt.amount_fen ELSE 0 END),0) AS consume_fen,
            COALESCE(SUM(CASE WHEN mt.type='recharge' THEN mt.amount_fen ELSE -mt.amount_fen END),0) AS balance_fen
            FROM member_transactions mt WHERE mt.tenant_id=:tenant_id AND mt.is_deleted=FALSE
            AND mt.created_at>=:period_start
            GROUP BY DATE_TRUNC('month',mt.created_at) ORDER BY month""",
         {"period_start":"year_start()"}),
    _reg("points_summary", "积分分析", "积分获取/兑换/过期统计",
         [{"name":"month","label":"月份"},{"name":"earned","label":"获取"},{"name":"redeemed","label":"兑换"},
          {"name":"expired","label":"过期"},{"name":"net","label":"净增"}],
         """SELECT TO_CHAR(DATE_TRUNC('month',created_at),'YYYY-MM') AS month,
            COALESCE(SUM(CASE WHEN type='earn' THEN points ELSE 0 END),0) AS earned,
            COALESCE(SUM(CASE WHEN type='redeem' THEN points ELSE 0 END),0) AS redeemed,
            COALESCE(SUM(CASE WHEN type='expire' THEN points ELSE 0 END),0) AS expired,
            COALESCE(SUM(CASE WHEN type='earn' THEN points ELSE -points END),0) AS net
            FROM member_points_log WHERE {} AND created_at>=:period_start
            GROUP BY DATE_TRUNC('month',created_at) ORDER BY month""".format(_TF),
         {"period_start":"year_start()"}),
]

# ── 优惠券/生日 (4) ────────────────────────────────────────────────────
MEMBER_SKUS += [
    _reg("coupon_usage", "优惠券使用分析", "发放量/使用率/核销金额",
         [{"name":"coupon_name","label":"券名称"},{"name":"issued","label":"发放量"},
          {"name":"used","label":"使用量"},{"name":"usage_rate","label":"使用率","format":"0.0%"},
          {"name":"redeemed_fen","label":"核销金额(分)"}],
         """SELECT c.name AS coupon_name, COUNT(cr.id) AS issued,
            COUNT(CASE WHEN cr.status='used' THEN 1 END) AS used,
            CASE WHEN COUNT(cr.id)>0 THEN COUNT(CASE WHEN cr.status='used' THEN 1 END)*100.0/COUNT(cr.id) ELSE 0 END AS usage_rate,
            COALESCE(SUM(CASE WHEN cr.status='used' THEN cr.redeemed_fen ELSE 0 END),0) AS redeemed_fen
            FROM coupons c LEFT JOIN coupon_records cr ON c.id=cr.coupon_id AND cr.tenant_id=:tenant_id
            WHERE c.tenant_id=:tenant_id AND c.is_deleted=FALSE AND cr.created_at>=:date_start
            GROUP BY c.id, c.name ORDER BY usage_rate DESC""",
         {"date_start":"quarter_start()"}),
    _reg("birthday_members", "生日会员清单", "本月生日会员及消费统计",
         [{"name":"member_name","label":"会员"},{"name":"birthday","label":"生日"},
          {"name":"total_spend_fen","label":"累计消费(分)"},{"name":"last_order_date","label":"最后消费日"}],
         """SELECT m.name AS member_name, m.birthday, m.total_spend_fen, m.last_order_date
            FROM members m WHERE m.tenant_id=:tenant_id AND m.is_deleted=FALSE
            AND EXTRACT(MONTH FROM m.birthday)=EXTRACT(MONTH FROM CURRENT_DATE)
            ORDER BY m.total_spend_fen DESC"""),
]

# ── 会员消费习惯 (4) ───────────────────────────────────────────────────
MEMBER_SKUS += [
    _reg("preferred_dish", "会员菜品偏好", "各RFM层级偏好菜品",
         [{"name":"rfm_tier","label":"层级"},{"name":"dish_name","label":"偏好菜品"},
          {"name":"order_count","label":"点单次数"}],
         """SELECT m.rfm_tier, d.name AS dish_name, COUNT(*) AS order_count
            FROM orders o JOIN members m ON o.member_id=m.id AND m.is_deleted=FALSE
            JOIN order_items oi ON o.id=oi.order_id JOIN dishes d ON oi.dish_id=d.id AND d.is_deleted=FALSE
            WHERE o.tenant_id=:tenant_id AND o.is_deleted=FALSE AND o.created_at>=:date_start AND m.rfm_tier IS NOT NULL
            GROUP BY m.rfm_tier, d.id, d.name HAVING COUNT(*)>=3 ORDER BY m.rfm_tier, order_count DESC""",
         {"date_start":"quarter_start()"}),
    _reg("preferred_daypart", "会员消费时段", "会员偏好消费时段分布",
         [{"name":"daypart","label":"时段"},{"name":"order_count","label":"订单数"},
          {"name":"avg_ticket_fen","label":"均客单价(分)"}],
         """SELECT CASE WHEN EXTRACT(HOUR FROM o.created_at)<11 THEN '早餐'
                         WHEN EXTRACT(HOUR FROM o.created_at)<14 THEN '午餐'
                         WHEN EXTRACT(HOUR FROM o.created_at)<17 THEN '下午茶' ELSE '晚餐' END AS daypart,
            COUNT(*) AS order_count,
            ROUND(AVG(o.total_fen)) AS avg_ticket_fen
            FROM orders o WHERE o.tenant_id=:tenant_id AND o.is_deleted=FALSE
            AND o.member_id IS NOT NULL AND o.created_at>=:date_start AND o.created_at<:date_end
            GROUP BY daypart ORDER BY order_count DESC""",
         {"date_start":"quarter_start()","date_end":"tomorrow()"}),
]
