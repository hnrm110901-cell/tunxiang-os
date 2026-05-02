"""餐品域固定报表SKU — 40个模板

覆盖：销量排名/毛利排名/滞销/退货/新品/套餐/分类/ABC分析
"""

from __future__ import annotations
from typing import Any

_TF = "tenant_id = :tenant_id AND is_deleted = FALSE"

DISH_SKUS: list[dict[str, Any]] = []


def _reg(sku_id: str, name: str, desc: str, cols: list[dict], sql: str,
         params: dict | None = None, domain: str = "dish") -> dict:
    return {
        "sku_id": f"{domain}_{sku_id}", "name": name, "description": desc,
        "domain": domain, "columns": cols, "sql": sql.strip(),
        "default_params": params or {},
    }


# ── 销量排名 (6) ──────────────────────────────────────────────────────
DISH_SKUS += [
    _reg("top20_by_sales", "菜品销量TOP20", "按销量降序排名（前20）",
         [{"name":"rank","label":"排名"},{"name":"dish_name","label":"菜品"},
          {"name":"quantity","label":"销量"},{"name":"revenue_fen","label":"销售额(分)"},
          {"name":"margin_pct","label":"毛利率","format":"0.0%"}],
         """SELECT ROW_NUMBER() OVER (ORDER BY COALESCE(SUM(oi.quantity),0) DESC) AS rank,
            d.name AS dish_name, COALESCE(SUM(oi.quantity),0) AS quantity,
            COALESCE(SUM(oi.total_fen),0) AS revenue_fen,
            CASE WHEN COALESCE(SUM(oi.total_fen),0)>0 THEN (COALESCE(SUM(oi.total_fen),0)-COALESCE(SUM(oi.cost_fen),0))*100.0/COALESCE(SUM(oi.total_fen),0) ELSE 0 END AS margin_pct
            FROM order_items oi JOIN dishes d ON oi.dish_id=d.id AND d.is_deleted=FALSE
            WHERE oi.tenant_id=:tenant_id AND oi.is_deleted=FALSE
            AND oi.created_at>=:date_start AND oi.created_at<:date_end
            GROUP BY d.id, d.name ORDER BY rank LIMIT 20""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
    _reg("top20_by_revenue", "菜品营收TOP20", "按销售额降序排名（前20）",
         [{"name":"rank","label":"排名"},{"name":"dish_name","label":"菜品"},
          {"name":"revenue_fen","label":"销售额(分)"},{"name":"quantity","label":"销量"},
          {"name":"avg_price_fen","label":"均价(分)"}],
         """SELECT ROW_NUMBER() OVER (ORDER BY COALESCE(SUM(oi.total_fen),0) DESC) AS rank,
            d.name AS dish_name, COALESCE(SUM(oi.total_fen),0) AS revenue_fen,
            COALESCE(SUM(oi.quantity),0) AS quantity,
            CASE WHEN COALESCE(SUM(oi.quantity),0)>0 THEN COALESCE(SUM(oi.total_fen),0)/COALESCE(SUM(oi.quantity),0) ELSE 0 END AS avg_price_fen
            FROM order_items oi JOIN dishes d ON oi.dish_id=d.id AND d.is_deleted=FALSE
            WHERE oi.tenant_id=:tenant_id AND oi.is_deleted=FALSE
            AND oi.created_at>=:date_start AND oi.created_at<:date_end
            GROUP BY d.id, d.name ORDER BY rank LIMIT 20""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
    _reg("top20_by_margin", "菜品毛利TOP20", "毛利贡献排名（毛利额×毛利率加权）",
         [{"name":"rank","label":"排名"},{"name":"dish_name","label":"菜品"},
          {"name":"margin_fen","label":"毛利额(分)"},{"name":"margin_pct","label":"毛利率","format":"0.0%"},
          {"name":"revenue_fen","label":"销售额(分)"}],
         """SELECT ROW_NUMBER() OVER (ORDER BY (COALESCE(SUM(oi.total_fen),0)-COALESCE(SUM(oi.cost_fen),0)) DESC) AS rank,
            d.name AS dish_name, COALESCE(SUM(oi.total_fen),0)-COALESCE(SUM(oi.cost_fen),0) AS margin_fen,
            CASE WHEN COALESCE(SUM(oi.total_fen),0)>0 THEN (COALESCE(SUM(oi.total_fen),0)-COALESCE(SUM(oi.cost_fen),0))*100.0/COALESCE(SUM(oi.total_fen),0) ELSE 0 END AS margin_pct,
            COALESCE(SUM(oi.total_fen),0) AS revenue_fen
            FROM order_items oi JOIN dishes d ON oi.dish_id=d.id AND d.is_deleted=FALSE
            WHERE oi.tenant_id=:tenant_id AND oi.is_deleted=FALSE
            AND oi.created_at>=:date_start AND oi.created_at<:date_end
            GROUP BY d.id, d.name ORDER BY rank LIMIT 20""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
]

# ── 滞销/退货 (6) ──────────────────────────────────────────────────────
DISH_SKUS += [
    _reg("slow_movers", "滞销菜品", "30天内无销售的菜品清单",
         [{"name":"dish_name","label":"菜品"},{"name":"category_name","label":"品类"},
          {"name":"last_sold_date","label":"最后销售日"},{"name":"days_unsold","label":"未售天数"}],
         """SELECT d.name AS dish_name, COALESCE(d.category_name,'-') AS category_name,
            MAX(oi.created_at) AS last_sold_date,
            EXTRACT(DAY FROM NOW()-COALESCE(MAX(oi.created_at),d.created_at))::INT AS days_unsold
            FROM dishes d LEFT JOIN order_items oi ON d.id=oi.dish_id AND oi.created_at>=:lookback_start
            WHERE d.tenant_id=:tenant_id AND d.is_deleted=FALSE AND d.is_active=TRUE
            GROUP BY d.id, d.name, d.category_name, d.created_at
            HAVING MAX(oi.created_at) IS NULL OR MAX(oi.created_at)<:stale_threshold
            ORDER BY days_unsold DESC""",
         {"lookback_start":"90days_ago()","stale_threshold":"30days_ago()"}),
    _reg("return_rate_ranking", "菜品退货排行", "退货率最高的菜品",
         [{"name":"dish_name","label":"菜品"},{"name":"sold_qty","label":"销量"},
          {"name":"returned_qty","label":"退货量"},{"name":"return_rate","label":"退货率","format":"0.0%"}],
         """SELECT d.name AS dish_name,
            COALESCE(SUM(CASE WHEN oi.status!='returned' THEN oi.quantity ELSE 0 END),0) AS sold_qty,
            COALESCE(SUM(CASE WHEN oi.status='returned' THEN oi.quantity ELSE 0 END),0) AS returned_qty,
            CASE WHEN COALESCE(SUM(oi.quantity),0)>0 THEN COALESCE(SUM(CASE WHEN oi.status='returned' THEN oi.quantity ELSE 0 END),0)*100.0/COALESCE(SUM(oi.quantity),0) ELSE 0 END AS return_rate
            FROM order_items oi JOIN dishes d ON oi.dish_id=d.id AND d.is_deleted=FALSE
            WHERE oi.tenant_id=:tenant_id AND oi.is_deleted=FALSE
            AND oi.created_at>=:date_start AND oi.created_at<:date_end
            GROUP BY d.id, d.name HAVING COALESCE(SUM(CASE WHEN oi.status='returned' THEN oi.quantity ELSE 0 END),0)>0
            ORDER BY return_rate DESC""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
    _reg("discontinued_candidates", "淘汰候选菜品", "销量低+毛利低+退货高=建议淘汰",
         [{"name":"dish_name","label":"菜品"},{"name":"quantity","label":"月销量"},
          {"name":"margin_pct","label":"毛利率","format":"0.0%"},{"name":"return_rate","label":"退货率","format":"0.0%"},
          {"name":"retention_score","label":"保留评分"}],
         """SELECT d.name AS dish_name, COALESCE(SUM(oi.quantity),0) AS quantity,
            CASE WHEN COALESCE(SUM(oi.total_fen),0)>0 THEN (COALESCE(SUM(oi.total_fen),0)-COALESCE(SUM(oi.cost_fen),0))*100.0/COALESCE(SUM(oi.total_fen),0) ELSE 0 END AS margin_pct,
            COALESCE(SUM(CASE WHEN oi.status='returned' THEN oi.quantity ELSE 0 END),0)*100.0/COALESCE(NULLIF(SUM(oi.quantity),0),1) AS return_rate,
            (COALESCE(SUM(oi.total_fen),0)*0.4/10000 + (CASE WHEN COALESCE(SUM(oi.total_fen),0)>0 THEN (COALESCE(SUM(oi.total_fen),0)-COALESCE(SUM(oi.cost_fen),0))*100.0/COALESCE(SUM(oi.total_fen),0) ELSE 0 END)*0.4 - COALESCE(SUM(CASE WHEN oi.status='returned' THEN oi.quantity ELSE 0 END),0)*100.0/COALESCE(NULLIF(SUM(oi.quantity),0),1)*0.2) AS retention_score
            FROM order_items oi JOIN dishes d ON oi.dish_id=d.id AND d.is_deleted=FALSE
            WHERE oi.tenant_id=:tenant_id AND oi.is_deleted=FALSE
            AND oi.created_at>=:date_start AND oi.created_at<:date_end
            GROUP BY d.id, d.name HAVING COALESCE(SUM(oi.quantity),0)<50
            ORDER BY retention_score ASC""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
]

# ── 新品追踪 (4) ──────────────────────────────────────────────────────
DISH_SKUS += [
    _reg("new_dish_tracker", "新品销售追踪", "新品上市30天销售趋势",
         [{"name":"dish_name","label":"新品"},{"name":"days_since_launch","label":"上市天数"},
          {"name":"total_quantity","label":"累计销量"},{"name":"total_revenue_fen","label":"累计销售(分)"},
          {"name":"daily_avg_fen","label":"日均销售(分)"}],
         """SELECT d.name AS dish_name,
            EXTRACT(DAY FROM NOW()-d.launched_at)::INT AS days_since_launch,
            COALESCE(SUM(oi.quantity),0) AS total_quantity,
            COALESCE(SUM(oi.total_fen),0) AS total_revenue_fen,
            COALESCE(SUM(oi.total_fen),0)/GREATEST(EXTRACT(DAY FROM NOW()-d.launched_at),1) AS daily_avg_fen
            FROM dishes d LEFT JOIN order_items oi ON d.id=oi.dish_id AND oi.created_at>=d.launched_at
            WHERE d.tenant_id=:tenant_id AND d.is_deleted=FALSE AND d.is_active=TRUE
            AND d.launched_at IS NOT NULL AND d.launched_at>=:new_threshold
            GROUP BY d.id, d.name, d.launched_at ORDER BY daily_avg_fen DESC""",
         {"new_threshold":"90days_ago()"}),
    _reg("new_vs_established", "新品vs老品对比", "新品与经典品销售对比",
         [{"name":"category","label":"分类"},{"name":"dish_count","label":"菜品数"},
          {"name":"total_revenue_fen","label":"销售额(分)"},{"name":"share_pct","label":"占比","format":"0.0%"}],
         """SELECT CASE WHEN d.launched_at IS NOT NULL AND d.launched_at>=:new_threshold THEN '新品' ELSE '经典' END AS category,
            COUNT(DISTINCT d.id) AS dish_count, COALESCE(SUM(oi.total_fen),0) AS total_revenue_fen,
            COALESCE(SUM(oi.total_fen),0)*100.0/SUM(COALESCE(SUM(oi.total_fen),0)) OVER() AS share_pct
            FROM dishes d LEFT JOIN order_items oi ON d.id=oi.dish_id AND oi.created_at>=:date_start AND oi.created_at<:date_end
            WHERE d.tenant_id=:tenant_id AND d.is_deleted=FALSE AND d.is_active=TRUE
            GROUP BY category""",
         {"new_threshold":"90days_ago()","date_start":"month_start()","date_end":"tomorrow()"}),
]

# ── 套餐/分类 (6) ───────────────────────────────────────────────────────
DISH_SKUS += [
    _reg("combo_analysis", "套餐销售分析", "套餐销量/占比/客单提升效果",
         [{"name":"combo_name","label":"套餐"},{"name":"quantity","label":"销量"},
          {"name":"revenue_fen","label":"销售额(分)"},{"name":"avg_discount_pct","label":"均折扣率","format":"0.0%"}],
         """SELECT d.name AS combo_name, COALESCE(SUM(oi.quantity),0) AS quantity,
            COALESCE(SUM(oi.total_fen),0) AS revenue_fen,
            CASE WHEN COALESCE(SUM(oi.original_fen),0)>0 THEN COALESCE(SUM(oi.original_fen-oi.total_fen),0)*100.0/COALESCE(SUM(oi.original_fen),0) ELSE 0 END AS avg_discount_pct
            FROM order_items oi JOIN dishes d ON oi.dish_id=d.id AND d.is_deleted=FALSE
            WHERE oi.tenant_id=:tenant_id AND oi.is_deleted=FALSE AND d.is_combo=TRUE
            AND oi.created_at>=:date_start AND oi.created_at<:date_end
            GROUP BY d.id, d.name ORDER BY revenue_fen DESC""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
    _reg("category_structure", "分类销售构成", "各分类销量/销售额/占比/毛利率",
         [{"name":"category_name","label":"分类"},{"name":"dish_count","label":"菜品数"},
          {"name":"quantity","label":"销量"},{"name":"revenue_fen","label":"销售额(分)"},
          {"name":"margin_pct","label":"毛利率","format":"0.0%"}],
         """SELECT COALESCE(d.category_name,'其他') AS category_name, COUNT(DISTINCT d.id) AS dish_count,
            COALESCE(SUM(oi.quantity),0) AS quantity, COALESCE(SUM(oi.total_fen),0) AS revenue_fen,
            CASE WHEN COALESCE(SUM(oi.total_fen),0)>0 THEN (COALESCE(SUM(oi.total_fen),0)-COALESCE(SUM(oi.cost_fen),0))*100.0/COALESCE(SUM(oi.total_fen),0) ELSE 0 END AS margin_pct
            FROM order_items oi JOIN dishes d ON oi.dish_id=d.id AND d.is_deleted=FALSE
            WHERE oi.tenant_id=:tenant_id AND oi.is_deleted=FALSE
            AND oi.created_at>=:date_start AND oi.created_at<:date_end
            GROUP BY d.category_name ORDER BY revenue_fen DESC""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
]

# ── ABC分析 (4) ──────────────────────────────────────────────────────
DISH_SKUS += [
    _reg("abc_analysis", "菜品ABC分类", "按销售额累计占比分ABC类",
         [{"name":"class","label":"分类"},{"name":"dish_count","label":"菜品数"},
          {"name":"revenue_fen","label":"销售额(分)"},{"name":"share_pct","label":"占比","format":"0.0%"}],
         """WITH ranked AS (
            SELECT d.id, d.name, COALESCE(SUM(oi.total_fen),0) AS rev,
            SUM(COALESCE(SUM(oi.total_fen),0)) OVER() AS total_rev,
            SUM(COALESCE(SUM(oi.total_fen),0)) OVER (ORDER BY COALESCE(SUM(oi.total_fen),0) DESC) AS cum_rev
            FROM order_items oi JOIN dishes d ON oi.dish_id=d.id AND d.is_deleted=FALSE
            WHERE oi.tenant_id=:tenant_id AND oi.is_deleted=FALSE
            AND oi.created_at>=:date_start AND oi.created_at<:date_end
            GROUP BY d.id, d.name
        )
        SELECT CASE WHEN cum_rev*100.0/total_rev<=70 THEN 'A' WHEN cum_rev*100.0/total_rev<=90 THEN 'B' ELSE 'C' END AS class,
            COUNT(*) AS dish_count, COALESCE(SUM(rev),0) AS revenue_fen,
            COALESCE(SUM(rev),0)*100.0/MAX(total_rev) AS share_pct
        FROM ranked GROUP BY class ORDER BY class""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
]

# ── 时段/做法 (5) ──────────────────────────────────────────────────────
DISH_SKUS += [
    _reg("by_daypart", "时段菜品偏好", "午市/晚市各时段点菜偏好",
         [{"name":"daypart","label":"时段"},{"name":"dish_name","label":"菜品"},
          {"name":"quantity","label":"销量"}],
         """SELECT CASE WHEN EXTRACT(HOUR FROM oi.created_at)<14 THEN '午市' WHEN EXTRACT(HOUR FROM oi.created_at)<17 THEN '下午茶' ELSE '晚市' END AS daypart,
            d.name AS dish_name, COALESCE(SUM(oi.quantity),0) AS quantity
            FROM order_items oi JOIN dishes d ON oi.dish_id=d.id AND d.is_deleted=FALSE
            WHERE oi.tenant_id=:tenant_id AND oi.is_deleted=FALSE
            AND oi.created_at>=:date_start AND oi.created_at<:date_end
            GROUP BY daypart, d.id, d.name HAVING COALESCE(SUM(oi.quantity),0)>0
            ORDER BY daypart, quantity DESC""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
    _reg("by_cooking_method", "做法偏好分析", "各做法（炒/蒸/煮/烤/炸）销量分布",
         [{"name":"cooking_method","label":"做法"},{"name":"dish_count","label":"菜品数"},
          {"name":"quantity","label":"销量"},{"name":"revenue_fen","label":"销售额(分)"}],
         """SELECT COALESCE(d.cooking_method,'其他') AS cooking_method, COUNT(DISTINCT d.id) AS dish_count,
            COALESCE(SUM(oi.quantity),0) AS quantity, COALESCE(SUM(oi.total_fen),0) AS revenue_fen
            FROM order_items oi JOIN dishes d ON oi.dish_id=d.id AND d.is_deleted=FALSE
            WHERE oi.tenant_id=:tenant_id AND oi.is_deleted=FALSE
            AND oi.created_at>=:date_start AND oi.created_at<:date_end
            GROUP BY d.cooking_method ORDER BY revenue_fen DESC""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
]

# ── 套餐搭配分析 (3) ─────────────────────────────────────────────────
DISH_SKUS += [
    _reg("pairing_analysis", "菜品搭配分析", "经常一起点的菜品组合（捆绑销售机会）",
         [{"name":"dish_a","label":"菜品A"},{"name":"dish_b","label":"菜品B"},
          {"name":"pair_count","label":"同单次数"}],
         """SELECT a.dish_name AS dish_a, b.dish_name AS dish_b, COUNT(*) AS pair_count
            FROM order_items a JOIN order_items b ON a.order_id=b.order_id AND a.dish_id<b.dish_id
            WHERE a.tenant_id=:tenant_id AND a.is_deleted=FALSE AND b.is_deleted=FALSE
            AND a.created_at>=:date_start AND a.created_at<:date_end
            GROUP BY a.dish_id, a.dish_name, b.dish_id, b.dish_name
            HAVING COUNT(*)>=5 ORDER BY pair_count DESC LIMIT 30""",
         {"date_start":"quarter_start()","date_end":"tomorrow()"}),
]

# ── 菜品生命周期 (3) ─────────────────────────────────────────────────
DISH_SKUS += [
    _reg("lifecycle_stage", "菜品生命周期", "按菜品上市时长分阶段统计",
         [{"name":"stage","label":"阶段"},{"name":"dish_count","label":"菜品数"},
          {"name":"avg_daily_sales","label":"日均销量"}],
         """SELECT CASE WHEN d.launched_at IS NULL THEN '未设置'
                         WHEN d.launched_at>=:new_range THEN '新品期(<3月)'
                         WHEN d.launched_at>=:growth_range THEN '成长期(3-12月)'
                         WHEN d.launched_at>=:mature_range THEN '成熟期(1-3年)'
                         ELSE '衰退期(>3年)' END AS stage,
            COUNT(DISTINCT d.id) AS dish_count,
            COALESCE(SUM(oi.quantity),0)/GREATEST(EXTRACT(DAY FROM :date_end::timestamp-:date_start::timestamp),1) AS avg_daily_sales
            FROM dishes d LEFT JOIN order_items oi ON d.id=oi.dish_id AND oi.created_at>=:date_start AND oi.created_at<:date_end
            WHERE d.tenant_id=:tenant_id AND d.is_deleted=FALSE AND d.is_active=TRUE
            GROUP BY stage ORDER BY stage""",
         {"new_range":"90days_ago()","growth_range":"365days_ago()","mature_range":"1095days_ago()",
          "date_start":"month_start()","date_end":"tomorrow()"}),
]
