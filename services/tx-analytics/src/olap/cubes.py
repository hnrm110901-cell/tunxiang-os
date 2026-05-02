"""OLAP Cube 定义 — 4 个预定义多维立方体

每个 Cube 基于现有物化视图（mv_store_pnl, mv_inventory_bom, mv_member_clv），
定义度量（Measures）和维度（Dimensions），供 OLAP 引擎使用。

金额字段统一使用 分（整数），后缀 _fen。
"""

from __future__ import annotations

from typing import Any

# ─── 公共辅助维度（多个 Cube 共享） ──────────────────────────────────────────

_TIME_DIMENSIONS: list[dict[str, Any]] = [
    {
        "name": "date",
        "label": "日期",
        "source_field": "stat_date",
        "drill_level": 3,  # 最细粒度
        "parent_dim": "week",
    },
    {
        "name": "week",
        "label": "周",
        "source_field": "date_trunc('week', stat_date)",
        "drill_level": 2,
        "parent_dim": "month",
    },
    {
        "name": "month",
        "label": "月",
        "source_field": "date_trunc('month', stat_date)",
        "drill_level": 2,
        "parent_dim": "quarter",
    },
    {
        "name": "quarter",
        "label": "季度",
        "source_field": "date_trunc('quarter', stat_date)",
        "drill_level": 1,  # 最粗粒度（时间维度的根节点）
    },
]

_STORE_DIMENSIONS: list[dict[str, Any]] = [
    {
        "name": "store_id",
        "label": "门店",
        "source_field": "store_id",
        "drill_level": 1,
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Cube 1: sales_cube — 销售分析立方体（基于 mv_store_pnl）
# ═══════════════════════════════════════════════════════════════════════════════

_SALES_MEASURES: list[dict[str, Any]] = [
    {
        "name": "revenue",
        "label": "销售额",
        "aggregation": "SUM",
        "source_expression": "COALESCE(gross_revenue_fen, 0)",
        "format": "¥#,##0.00",
        "unit": "分",
    },
    {
        "name": "net_revenue",
        "label": "净收入",
        "aggregation": "SUM",
        "source_expression": "COALESCE(net_revenue_fen, 0)",
        "format": "¥#,##0.00",
        "unit": "分",
    },
    {
        "name": "gross_profit",
        "label": "毛利额",
        "aggregation": "SUM",
        "source_expression": "COALESCE(gross_profit_fen, 0)",
        "format": "¥#,##0.00",
        "unit": "分",
    },
    {
        "name": "order_count",
        "label": "订单数",
        "aggregation": "SUM",
        "source_expression": "COALESCE(order_count, 0)",
        "format": "#,##0",
    },
    {
        "name": "customer_count",
        "label": "消费人次",
        "aggregation": "SUM",
        "source_expression": "COALESCE(customer_count, 0)",
        "format": "#,##0",
    },
    {
        "name": "avg_ticket",
        "label": "客单价",
        "aggregation": "AVG",
        "source_expression": "COALESCE(avg_check_fen, 0)",
        "format": "¥#,##0.00",
        "unit": "分",
    },
    {
        "name": "gross_margin_rate",
        "label": "毛利率",
        "aggregation": "AVG",
        "source_expression": "COALESCE(gross_margin_rate, 0)",
        "format": "0.00%",
    },
    {
        "name": "stored_value_new",
        "label": "新增储值额",
        "aggregation": "SUM",
        "source_expression": "COALESCE(stored_value_new_fen, 0)",
        "format": "¥#,##0.00",
        "unit": "分",
    },
    {
        "name": "stored_value_consumed",
        "label": "储值消费额",
        "aggregation": "SUM",
        "source_expression": "COALESCE(stored_value_consumed_fen, 0)",
        "format": "¥#,##0.00",
        "unit": "分",
    },
]

_SALES_DIMENSIONS: list[dict[str, Any]] = [
    *_TIME_DIMENSIONS,
    *_STORE_DIMENSIONS,
    {
        "name": "brand_id",
        "label": "品牌",
        "source_field": "brand_id",
        "drill_level": 2,
        "parent_dim": "store_id",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Cube 2: dish_cube — 菜品分析立方体（基于 mv_store_pnl，按品类/菜品维度）
# ═══════════════════════════════════════════════════════════════════════════════

_DISH_MEASURES: list[dict[str, Any]] = [
    {
        "name": "dish_revenue",
        "label": "菜品销售额",
        "aggregation": "SUM",
        "source_expression": "COALESCE(gross_revenue_fen, 0)",
        "format": "¥#,##0.00",
        "unit": "分",
    },
    {
        "name": "dish_order_count",
        "label": "出品份数",
        "aggregation": "SUM",
        "source_expression": "COALESCE(order_count, 0)",
        "format": "#,##0",
    },
    {
        "name": "dish_gross_profit",
        "label": "毛利额",
        "aggregation": "SUM",
        "source_expression": "COALESCE(gross_profit_fen, 0)",
        "format": "¥#,##0.00",
        "unit": "分",
    },
    {
        "name": "dish_margin_rate",
        "label": "毛利率",
        "aggregation": "AVG",
        "source_expression": "COALESCE(gross_margin_rate, 0)",
        "format": "0.00%",
    },
    {
        "name": "dish_avg_check",
        "label": "客单价",
        "aggregation": "AVG",
        "source_expression": "COALESCE(avg_check_fen, 0)",
        "format": "¥#,##0.00",
        "unit": "分",
    },
]

_DISH_DIMENSIONS: list[dict[str, Any]] = [
    *_TIME_DIMENSIONS,
    *_STORE_DIMENSIONS,
    {
        "name": "dish_category",
        "label": "菜品品类",
        "source_field": "category_name",
        "drill_level": 1,
    },
    {
        "name": "dish_name",
        "label": "菜品名称",
        "source_field": "dish_name",
        "drill_level": 3,
        "parent_dim": "dish_category",
    },
    {
        "name": "channel_type",
        "label": "销售渠道",
        "source_field": "channel_type",
        "drill_level": 1,
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Cube 3: inventory_cube — 库存成本分析立方体（基于 mv_inventory_bom）
# ═══════════════════════════════════════════════════════════════════════════════

_INVENTORY_MEASURES: list[dict[str, Any]] = [
    {
        "name": "theoretical_usage",
        "label": "BOM理论耗用（克）",
        "aggregation": "SUM",
        "source_expression": "COALESCE(theoretical_usage_g, 0)",
        "format": "#,##0.0",
        "unit": "克",
    },
    {
        "name": "actual_usage",
        "label": "实际使用量（克）",
        "aggregation": "SUM",
        "source_expression": "COALESCE(actual_usage_g, 0)",
        "format": "#,##0.0",
        "unit": "克",
    },
    {
        "name": "waste",
        "label": "登记损耗（克）",
        "aggregation": "SUM",
        "source_expression": "COALESCE(waste_g, 0)",
        "format": "#,##0.0",
        "unit": "克",
    },
    {
        "name": "unexplained_loss",
        "label": "未解释损耗（克）",
        "aggregation": "SUM",
        "source_expression": "COALESCE(unexplained_loss_g, 0)",
        "format": "#,##0.0",
        "unit": "克",
    },
    {
        "name": "loss_rate",
        "label": "损耗率",
        "aggregation": "AVG",
        "source_expression": "COALESCE(loss_rate, 0)",
        "format": "0.00%",
    },
    {
        "name": "ingredient_count",
        "label": "原料品种数",
        "aggregation": "COUNT_DISTINCT",
        "source_expression": "ingredient_id",
    },
]

_INVENTORY_DIMENSIONS: list[dict[str, Any]] = [
    *_TIME_DIMENSIONS,
    *_STORE_DIMENSIONS,
    {
        "name": "ingredient_id",
        "label": "原料",
        "source_field": "ingredient_id",
        "drill_level": 1,
    },
    {
        "name": "ingredient_name",
        "label": "原料名称",
        "source_field": "ingredient_name",
        "drill_level": 2,
        "parent_dim": "ingredient_id",
    },
    {
        "name": "ingredient_category",
        "label": "原料品类",
        "source_field": "ingredient_category",
        "drill_level": 1,
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Cube 4: member_cube — 会员分析立方体（基于 mv_member_clv）
# ═══════════════════════════════════════════════════════════════════════════════

_MEMBER_MEASURES: list[dict[str, Any]] = [
    {
        "name": "total_spend",
        "label": "累计消费额",
        "aggregation": "SUM",
        "source_expression": "COALESCE(total_spend_fen, 0)",
        "format": "¥#,##0.00",
        "unit": "分",
    },
    {
        "name": "clv",
        "label": "生命周期价值（CLV）",
        "aggregation": "SUM",
        "source_expression": "COALESCE(clv_fen, 0)",
        "format": "¥#,##0.00",
        "unit": "分",
    },
    {
        "name": "visit_count",
        "label": "到店次数",
        "aggregation": "SUM",
        "source_expression": "COALESCE(visit_count, 0)",
        "format": "#,##0",
    },
    {
        "name": "member_count",
        "label": "会员数",
        "aggregation": "COUNT_DISTINCT",
        "source_expression": "customer_id",
    },
    {
        "name": "stored_balance",
        "label": "储值余额",
        "aggregation": "SUM",
        "source_expression": "COALESCE(stored_value_balance_fen, 0)",
        "format": "¥#,##0.00",
        "unit": "分",
    },
    {
        "name": "voucher_used_count",
        "label": "券核销数",
        "aggregation": "SUM",
        "source_expression": "COALESCE(voucher_used_count, 0)",
        "format": "#,##0",
    },
    {
        "name": "voucher_cost",
        "label": "券成本",
        "aggregation": "SUM",
        "source_expression": "COALESCE(voucher_cost_fen, 0)",
        "format": "¥#,##0.00",
        "unit": "分",
    },
    {
        "name": "avg_churn_probability",
        "label": "平均流失概率",
        "aggregation": "AVG",
        "source_expression": "COALESCE(churn_probability, 0)",
        "format": "0.00%",
    },
    {
        "name": "avg_next_visit_days",
        "label": "平均回访天数",
        "aggregation": "AVG",
        "source_expression": "COALESCE(next_visit_days, 0)",
        "format": "#,##0.0",
        "unit": "天",
    },
]

_MEMBER_DIMENSIONS: list[dict[str, Any]] = [
    {
        "name": "register_month",
        "label": "注册月份",
        "source_field": "date_trunc('month', registered_at)",
        "drill_level": 1,
    },
    {
        "name": "last_visit_month",
        "label": "最近到店月份",
        "source_field": "date_trunc('month', last_visit_at)",
        "drill_level": 1,
    },
    {
        "name": "member_tier",
        "label": "会员等级",
        "source_field": "member_tier",
        "drill_level": 1,
    },
    {
        "name": "member_source",
        "label": "注册渠道",
        "source_field": "member_source",
        "drill_level": 1,
    },
    {
        "name": "churn_risk",
        "label": "流失风险",
        "source_field": "CASE WHEN churn_probability >= 0.7 THEN 'high' WHEN churn_probability >= 0.4 THEN 'medium' ELSE 'low' END",
        "drill_level": 1,
    },
    {
        "name": "store_id",
        "label": "归属门店",
        "source_field": "store_id",
        "drill_level": 1,
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# 汇总 CUBES 字典
# ═══════════════════════════════════════════════════════════════════════════════

CUBES: dict[str, dict[str, Any]] = {
    "sales_cube": {
        "name": "sales_cube",
        "label": "销售分析立方体",
        "description": "按时间/门店/品牌的销售多维分析。支持钻取（日→周→月）、切片（筛选门店/日期范围）、切块（交叉维度分组）。数据来源：mv_store_pnl。",
        "source": "mv_store_pnl",
        "measures": _SALES_MEASURES,
        "dimensions": _SALES_DIMENSIONS,
    },
    "dish_cube": {
        "name": "dish_cube",
        "label": "菜品分析立方体",
        "description": "按品类/菜品/渠道的菜品销售与毛利多维分析。支持钻取（品类→菜品）、跨维度切块（门店×品类×渠道）。数据来源：mv_store_pnl（可关联 dish 表获取菜品维）。",
        "source": "mv_store_pnl",
        "measures": _DISH_MEASURES,
        "dimensions": _DISH_DIMENSIONS,
    },
    "inventory_cube": {
        "name": "inventory_cube",
        "label": "库存成本分析立方体",
        "description": "按时间/门店/原料品类的库存 BOM 差异多维分析。支持钻取（日期→周→月、门店→原料）、切片（筛选原料/日期）。核心指标：理论耗用 vs 实际使用 vs 损耗。数据来源：mv_inventory_bom。",
        "source": "mv_inventory_bom",
        "measures": _INVENTORY_MEASURES,
        "dimensions": _INVENTORY_DIMENSIONS,
    },
    "member_cube": {
        "name": "member_cube",
        "label": "会员分析立方体",
        "description": "按注册月份/会员等级/流失风险/归属门店的会员 CLV 多维分析。支持钻取（等级→门店）、切片（高流失风险会员）、切块（等级×注册渠道）。数据来源：mv_member_clv。",
        "source": "mv_member_clv",
        "measures": _MEMBER_MEASURES,
        "dimensions": _MEMBER_DIMENSIONS,
    },
}
