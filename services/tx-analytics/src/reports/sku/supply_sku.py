"""供应链域固定报表SKU — 40个模板

覆盖：库存/采购/损耗/BOM成本/供应商/效期/入库出库
"""

from __future__ import annotations
from typing import Any

_TF = "tenant_id = :tenant_id AND is_deleted = FALSE"

SUPPLY_SKUS: list[dict[str, Any]] = []


def _reg(sku_id: str, name: str, desc: str, cols: list[dict], sql: str,
         params: dict | None = None, domain: str = "supply") -> dict:
    return {
        "sku_id": f"{domain}_{sku_id}", "name": name, "description": desc,
        "domain": domain, "columns": cols, "sql": sql.strip(),
        "default_params": params or {},
    }


# ── 库存日报 (5) ──────────────────────────────────────────────────────
SUPPLY_SKUS += [
    _reg("inventory_daily", "库存日报", "当日库存量/金额/周转率",
         [{"name":"ingredient_name","label":"食材"},{"name":"quantity","label":"库存量"},
          {"name":"unit","label":"单位"},{"name":"value_fen","label":"库存金额(分)"},
          {"name":"days_on_hand","label":"在库天数"}],
         """SELECT i.ingredient_name, i.quantity, i.unit,
            i.quantity*i.unit_cost_fen AS value_fen,
            CASE WHEN COALESCE(i.daily_usage,0)>0 THEN i.quantity*1.0/i.daily_usage ELSE 0 END AS days_on_hand
            FROM inventory i WHERE i.{} AND i.quantity>0
            ORDER BY value_fen DESC""".format(_TF)),
    _reg("inventory_turnover", "库存周转分析", "各类食材周转天数排名",
         [{"name":"category","label":"品类"},{"name":"avg_value_fen","label":"均库存(分)"},
          {"name":"total_usage_fen","label":"月消耗(分)"},{"name":"turnover_days","label":"周转天数"},
          {"name":"turnover_rate","label":"月周转率"}],
         """SELECT COALESCE(i.category,'其他') AS category,
            ROUND(AVG(i.quantity*i.unit_cost_fen)) AS avg_value_fen,
            COALESCE(SUM(it.quantity*it.unit_cost_fen),0) AS total_usage_fen,
            CASE WHEN COALESCE(SUM(it.quantity*it.unit_cost_fen),0)>0 THEN ROUND(AVG(i.quantity*i.unit_cost_fen))*30/COALESCE(SUM(it.quantity*it.unit_cost_fen),0) ELSE 0 END AS turnover_days,
            CASE WHEN ROUND(AVG(i.quantity*i.unit_cost_fen))>0 THEN COALESCE(SUM(it.quantity*it.unit_cost_fen),0)*1.0/ROUND(AVG(i.quantity*i.unit_cost_fen)) ELSE 0 END AS turnover_rate
            FROM inventory i LEFT JOIN ingredient_transactions it ON i.ingredient_id=it.ingredient_id
            AND it.type='consume' AND it.created_at>=:month_start AND it.created_at<:month_end
            WHERE i.tenant_id=:tenant_id AND i.is_deleted=FALSE
            GROUP BY i.category ORDER BY turnover_days DESC""",
         {"month_start":"month_start()","month_end":"tomorrow()"}),
]

# ── 采购分析 (5) ──────────────────────────────────────────────────────
SUPPLY_SKUS += [
    _reg("purchase_summary", "采购汇总", "采购金额/量/供应商排名",
         [{"name":"supplier_name","label":"供应商"},{"name":"total_fen","label":"采购金额(分)"},
          {"name":"order_count","label":"采购次数"},{"name":"avg_delivery_days","label":"均到货天"}],
         """SELECT s.name AS supplier_name, COALESCE(SUM(po.total_fen),0) AS total_fen,
            COUNT(DISTINCT po.id) AS order_count,
            ROUND(AVG(EXTRACT(DAY FROM po.delivered_at-po.created_at)))) AS avg_delivery_days
            FROM purchase_orders po JOIN suppliers s ON po.supplier_id=s.id AND s.is_deleted=FALSE
            WHERE po.tenant_id=:tenant_id AND po.is_deleted=FALSE
            AND po.created_at>=:date_start AND po.created_at<:date_end
            GROUP BY s.id, s.name ORDER BY total_fen DESC""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
    _reg("purchase_price_trend", "采购价趋势", "核心食材采购价走势",
         [{"name":"ingredient_name","label":"食材"},{"name":"month","label":"月份"},
          {"name":"avg_unit_price_fen","label":"均价(分)"},{"name":"quantity","label":"采购量"}],
         """SELECT i.name AS ingredient_name, TO_CHAR(DATE_TRUNC('month',po.created_at),'YYYY-MM') AS month,
            ROUND(AVG(poi.unit_price_fen)) AS avg_unit_price_fen,
            COALESCE(SUM(poi.quantity),0) AS quantity
            FROM purchase_order_items poi JOIN purchase_orders po ON poi.purchase_order_id=po.id
            JOIN ingredients i ON poi.ingredient_id=i.id AND i.is_deleted=FALSE
            WHERE po.tenant_id=:tenant_id AND po.is_deleted=FALSE AND po.created_at>=:period_start
            GROUP BY i.id, i.name, DATE_TRUNC('month',po.created_at) ORDER BY i.name, month""",
         {"period_start":"year_start()"}),
]

# ── 损耗分析 (5) ──────────────────────────────────────────────────────
SUPPLY_SKUS += [
    _reg("waste_summary", "损耗分析", "损耗率/原因/金额排行",
         [{"name":"waste_reason","label":"损耗原因"},{"name":"total_fen","label":"损耗金额(分)"},
          {"name":"occurrence_count","label":"次数"},{"name":"share_pct","label":"占比","format":"0.0%"}],
         """SELECT COALESCE(reason,'未分类') AS waste_reason, COALESCE(SUM(amount_fen),0) AS total_fen,
            COUNT(*) AS occurrence_count,
            COALESCE(SUM(amount_fen),0)*100.0/SUM(COALESCE(SUM(amount_fen),0)) OVER() AS share_pct
            FROM inventory_waste WHERE {} AND created_at>=:date_start AND created_at<:date_end
            GROUP BY reason ORDER BY total_fen DESC""".format(_TF),
         {"date_start":"month_start()","date_end":"tomorrow()"}),
    _reg("waste_rate_by_ingredient", "食材损耗率排行", "各食材损耗率排名",
         [{"name":"ingredient_name","label":"食材"},{"name":"waste_qty","label":"损耗量"},
          {"name":"usage_qty","label":"用量"},{"name":"waste_rate","label":"损耗率","format":"0.0%"}],
         """SELECT i.name AS ingredient_name,
            COALESCE(SUM(iw.quantity),0) AS waste_qty, COALESCE(SUM(it.quantity),0) AS usage_qty,
            CASE WHEN COALESCE(SUM(it.quantity),0)>0 THEN COALESCE(SUM(iw.quantity),0)*100.0/COALESCE(SUM(it.quantity),0) ELSE 0 END AS waste_rate
            FROM ingredients i LEFT JOIN inventory_waste iw ON i.id=iw.ingredient_id AND iw.created_at>=:date_start
            LEFT JOIN ingredient_transactions it ON i.id=it.ingredient_id AND it.type='consume' AND it.created_at>=:date_start
            WHERE i.tenant_id=:tenant_id AND i.is_deleted=FALSE
            GROUP BY i.id, i.name HAVING COALESCE(SUM(iw.quantity),0)>0 ORDER BY waste_rate DESC""",
         {"date_start":"month_start()"}),
]

# ── BOM成本分析 (5) ────────────────────────────────────────────────────
SUPPLY_SKUS += [
    _reg("bom_cost_breakdown", "BOM成本构成", "各菜品BOM理论成本vs实际成本",
         [{"name":"dish_name","label":"菜品"},{"name":"theoretical_cost_fen","label":"理论成本(分)"},
          {"name":"actual_cost_fen","label":"实际成本(分)"},{"name":"variance_pct","label":"偏差率","format":"0.0%"}],
         """SELECT d.name AS dish_name,
            COALESCE(SUM(bom.quantity*ing.unit_cost_fen),0) AS theoretical_cost_fen,
            COALESCE(AVG(oi.cost_fen),0) AS actual_cost_fen,
            CASE WHEN COALESCE(SUM(bom.quantity*ing.unit_cost_fen),0)>0 THEN (COALESCE(AVG(oi.cost_fen),0)-COALESCE(SUM(bom.quantity*ing.unit_cost_fen),0))*100.0/COALESCE(SUM(bom.quantity*ing.unit_cost_fen),0) ELSE 0 END AS variance_pct
            FROM dishes d LEFT JOIN dish_bom bom ON d.id=bom.dish_id AND bom.is_deleted=FALSE
            LEFT JOIN ingredients ing ON bom.ingredient_id=ing.id AND ing.is_deleted=FALSE
            LEFT JOIN order_items oi ON d.id=oi.dish_id AND oi.created_at>=:date_start
            WHERE d.tenant_id=:tenant_id AND d.is_deleted=FALSE
            GROUP BY d.id, d.name ORDER BY variance_pct DESC""",
         {"date_start":"month_start()"}),
]

# ── 供应商绩效 (5) ─────────────────────────────────────────────────────
SUPPLY_SKUS += [
    _reg("supplier_scorecard", "供应商绩效评分", "多维度供应商评价",
         [{"name":"supplier_name","label":"供应商"},{"name":"on_time_pct","label":"准时率","format":"0.0%"},
          {"name":"quality_score","label":"质量分"},{"name":"price_index","label":"价格指数"},
          {"name":"total_score","label":"综合评分"}],
         """SELECT s.name AS supplier_name,
            CASE WHEN COUNT(po.id)>0 THEN COUNT(CASE WHEN po.delivered_at<=po.expected_at THEN 1 END)*100.0/COUNT(po.id) ELSE 0 END AS on_time_pct,
            ROUND(AVG(COALESCE(po.quality_score,0))) AS quality_score,
            ROUND(AVG(COALESCE(po.price_index,100))) AS price_index,
            (CASE WHEN COUNT(po.id)>0 THEN COUNT(CASE WHEN po.delivered_at<=po.expected_at THEN 1 END)*100.0/COUNT(po.id) ELSE 0 END)*0.3 + ROUND(AVG(COALESCE(po.quality_score,0)))*0.5 + (200-ROUND(AVG(COALESCE(po.price_index,100))))*0.2 AS total_score
            FROM suppliers s LEFT JOIN purchase_orders po ON s.id=po.supplier_id AND po.created_at>=:date_start
            WHERE s.tenant_id=:tenant_id AND s.is_deleted=FALSE
            GROUP BY s.id, s.name ORDER BY total_score DESC""",
         {"date_start":"quarter_start()"}),
]

# ── 效期预警 (5) ──────────────────────────────────────────────────────
SUPPLY_SKUS += [
    _reg("expiry_alert", "效期预警", "临期食材清单及处理建议",
         [{"name":"ingredient_name","label":"食材"},{"name":"batch","label":"批次"},
          {"name":"quantity","label":"库存量"},{"name":"expiry_date","label":"效期"},
          {"name":"days_left","label":"剩余天数"},{"name":"value_fen","label":"金额(分)"}],
         """SELECT i.ingredient_name, ib.batch_no AS batch, ib.quantity,
            ib.expiry_date, EXTRACT(DAY FROM ib.expiry_date-NOW())::INT AS days_left,
            ib.quantity*i.unit_cost_fen AS value_fen
            FROM inventory_batches ib JOIN inventory i ON ib.inventory_id=i.id AND i.is_deleted=FALSE
            WHERE ib.tenant_id=:tenant_id AND ib.is_deleted=FALSE AND ib.status='active'
            AND ib.expiry_date<=NOW()+INTERVAL'{} days'
            ORDER BY days_left ASC""".format(":expiry_window"),
         {"expiry_window":"7"}),
    _reg("safety_stock_alert", "安全库存预警", "低于安全库存的食材",
         [{"name":"ingredient_name","label":"食材"},{"name":"current_qty","label":"当前库存"},
          {"name":"safety_qty","label":"安全库存"},{"name":"shortage","label":"缺口"}],
         """SELECT i.ingredient_name, i.quantity AS current_qty, i.safety_stock AS safety_qty,
            i.safety_stock-i.quantity AS shortage
            FROM inventory i WHERE i.{} AND i.quantity<i.safety_stock
            ORDER BY shortage DESC""".format(_TF)),
]

# ── 入库/出库汇总 (5) ─────────────────────────────────────────────────
SUPPLY_SKUS += [
    _reg("inbound_summary", "入库汇总", "按品类/供应商入库统计",
         [{"name":"category","label":"品类"},{"name":"inbound_qty","label":"入库量"},
          {"name":"inbound_fen","label":"入库金额(分)"},{"name":"supplier_count","label":"供应商数"}],
         """SELECT COALESCE(i.category,'其他') AS category,
            COALESCE(SUM(it.quantity),0) AS inbound_qty,
            COALESCE(SUM(it.quantity*it.unit_cost_fen),0) AS inbound_fen,
            COUNT(DISTINCT it.supplier_id) AS supplier_count
            FROM ingredient_transactions it JOIN inventory i ON it.inventory_id=i.id AND i.is_deleted=FALSE
            WHERE it.tenant_id=:tenant_id AND it.is_deleted=FALSE AND it.type='inbound'
            AND it.created_at>=:date_start AND it.created_at<:date_end
            GROUP BY i.category ORDER BY inbound_fen DESC""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
    _reg("outbound_summary", "出库汇总", "按品类/用途出库统计",
         [{"name":"category","label":"品类"},{"name":"outbound_qty","label":"出库量"},
          {"name":"outbound_fen","label":"出库金额(分)"}],
         """SELECT COALESCE(i.category,'其他') AS category,
            COALESCE(SUM(it.quantity),0) AS outbound_qty,
            COALESCE(SUM(it.quantity*it.unit_cost_fen),0) AS outbound_fen
            FROM ingredient_transactions it JOIN inventory i ON it.inventory_id=i.id AND i.is_deleted=FALSE
            WHERE it.tenant_id=:tenant_id AND it.is_deleted=FALSE AND it.type IN ('consume','waste','transfer_out')
            AND it.created_at>=:date_start AND it.created_at<:date_end
            GROUP BY i.category ORDER BY outbound_fen DESC""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
]

# ── 食安/能耗 (5) ──────────────────────────────────────────────────────
SUPPLY_SKUS += [
    _reg("food_safety_log", "食安检查日志", "食材温度/抽样/巡检记录",
         [{"name":"check_date","label":"日期"},{"name":"check_type","label":"检查类型"},
          {"name":"result","label":"结果"},{"name":"item_count","label":"检查项数"},
          {"name":"fail_count","label":"不合格项"}],
         """SELECT DATE(fs.created_at) AS check_date, fs.check_type,
            CASE WHEN COUNT(CASE WHEN fs.result='fail' THEN 1 END)>0 THEN '不合格' ELSE '合格' END AS result,
            COUNT(*) AS item_count, COUNT(CASE WHEN fs.result='fail' THEN 1 END) AS fail_count
            FROM food_safety_checks fs WHERE fs.{} AND fs.created_at>=:date_start
            GROUP BY DATE(fs.created_at), fs.check_type ORDER BY check_date DESC""".format(_TF),
         {"date_start":"month_start()"}),
    _reg("temperature_log", "温度监控日志", "冷藏/冷冻设备温度记录",
         [{"name":"device_name","label":"设备"},{"name":"record_time","label":"记录时间"},
          {"name":"temp_c","label":"温度(°C)"},{"name":"is_normal","label":"是否正常"}],
         """SELECT d.name AS device_name, tr.recorded_at AS record_time,
            tr.temperature AS temp_c,
            CASE WHEN tr.temperature BETWEEN d.temp_min AND d.temp_max THEN '正常' ELSE '异常' END AS is_normal
            FROM temperature_records tr JOIN cold_devices d ON tr.device_id=d.id AND d.is_deleted=FALSE
            WHERE tr.tenant_id=:tenant_id AND tr.is_deleted=FALSE
            AND tr.recorded_at>=:date_start AND tr.recorded_at<:date_end
            ORDER BY tr.recorded_at DESC""",
         {"date_start":"today()","date_end":"tomorrow()"}),
]
