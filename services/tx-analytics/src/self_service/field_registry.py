"""可用字段注册表 — 从数据仓库表结构自动发现可查询字段

每个 QueryField 定义了一个可供业务用户拖拽使用的分析字段。
字段来源于物化视图（mv_*）和基础表（orders/dishes/customers 等）。

金额字段统一以 _fen 结尾（单位：分），显示时自动除以 100 转为元。
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class FieldType(str, Enum):
    DIMENSION = "dimension"       # 维度 — 用于 GROUP BY 的行/列
    MEASURE = "measure"           # 度量 — 用于聚合的值
    DATE_DIM = "date_dim"         # 日期维度 — 特殊处理（支持粒度切换）
    FILTER_ONLY = "filter_only"   # 仅用于筛选


class DataType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    MONEY = "money"       # 单位分，显示时自动除以 100
    PERCENT = "percent"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"


class QueryField:
    """可查询字段定义"""

    def __init__(
        self,
        field_id: str,
        label: str,
        description: str = "",
        field_type: FieldType = FieldType.DIMENSION,
        data_type: DataType = DataType.STRING,
        domain: str = "",
        source_table: str = "",
        source_expression: str = "",
        aggregation: Optional[str] = None,
        format: Optional[str] = None,
        drillable: bool = False,
        filterable: bool = True,
        sortable: bool = True,
        allowed_operators: Optional[list[str]] = None,
    ):
        self.field_id = field_id
        self.label = label
        self.description = description
        self.field_type = field_type
        self.data_type = data_type
        self.domain = domain
        self.source_table = source_table
        self.source_expression = source_expression
        self.aggregation = aggregation
        self.format = format
        self.drillable = drillable
        self.filterable = filterable
        self.sortable = sortable
        self.allowed_operators = allowed_operators or [
            "eq", "neq", "gt", "gte", "lt", "lte", "in", "between", "is_null",
        ]

    def to_dict(self) -> dict:
        return {
            "field_id": self.field_id,
            "label": self.label,
            "description": self.description,
            "field_type": self.field_type.value if isinstance(self.field_type, FieldType) else self.field_type,
            "data_type": self.data_type.value if isinstance(self.data_type, DataType) else self.data_type,
            "domain": self.domain,
            "source_table": self.source_table,
            "source_expression": self.source_expression,
            "aggregation": self.aggregation,
            "format": self.format,
            "drillable": self.drillable,
            "filterable": self.filterable,
            "sortable": self.sortable,
            "allowed_operators": self.allowed_operators,
        }


# ═══════════════════════════════════════════════════════════════════
# 销售域 (sales) — 从 orders / order_items / mv_store_pnl
# ═══════════════════════════════════════════════════════════════════

_SALES_DIMS: list[QueryField] = [
    QueryField("sale_store_id", "门店", "下单门店", FieldType.DIMENSION, DataType.STRING,
               "sales", "orders", "orders.store_id", drillable=True),
    QueryField("sale_store_name", "门店名称", "门店名称（关联查询）", FieldType.DIMENSION, DataType.STRING,
               "sales", "stores", "stores.store_name", drillable=True),
    QueryField("sale_brand_id", "品牌", "所属品牌", FieldType.DIMENSION, DataType.STRING,
               "sales", "stores", "stores.brand_id", drillable=True),
    QueryField("sale_region", "区域", "门店所在区域", FieldType.DIMENSION, DataType.STRING,
               "sales", "stores", "stores.region"),
    QueryField("sale_order_type", "订单类型", "堂食/外卖/零售/宴席", FieldType.DIMENSION, DataType.STRING,
               "sales", "orders", "orders.order_type"),
    QueryField("sale_channel_type", "销售渠道", "美团/饿了么/抖音/堂食", FieldType.DIMENSION, DataType.STRING,
               "sales", "orders", "orders.sales_channel_id"),
    QueryField("sale_cashier_id", "收银员ID", "", FieldType.DIMENSION, DataType.STRING,
               "sales", "orders", "orders.cashier_id"),
    QueryField("sale_waiter_id", "服务员ID", "", FieldType.DIMENSION, DataType.STRING,
               "sales", "orders", "orders.waiter_id"),
    QueryField("sale_report_date", "营业日期", "按日期聚合", FieldType.DATE_DIM, DataType.DATE,
               "sales", "orders", "orders.order_time::date"),
    QueryField("sale_day_of_week", "星期几", "ISO 星期编号 1-7", FieldType.DIMENSION, DataType.NUMBER,
               "sales", "orders", "EXTRACT(ISODOW FROM orders.order_time)"),
    QueryField("sale_hour_of_day", "营业时段", "小时 0-23", FieldType.DIMENSION, DataType.NUMBER,
               "sales", "orders", "EXTRACT(HOUR FROM orders.order_time)"),
    QueryField("sale_month", "月份", "YYYY-MM 格式", FieldType.DIMENSION, DataType.STRING,
               "sales", "orders", "TO_CHAR(orders.order_time, 'YYYY-MM')"),
    QueryField("sale_quarter", "季度", "YYYY-Q 格式", FieldType.DIMENSION, DataType.STRING,
               "sales", "orders", "TO_CHAR(orders.order_time, 'YYYY-\"Q\"Q')"),
    QueryField("sale_order_status", "订单状态", "pending/paid/cancelled/refunded/closed", FieldType.DIMENSION, DataType.STRING,
               "sales", "orders", "orders.status"),
    QueryField("sale_discount_type", "折扣类型", "coupon/vip/manager/promotion", FieldType.DIMENSION, DataType.STRING,
               "sales", "orders", "orders.discount_type"),
    QueryField("sale_guest_count", "就餐人数", "", FieldType.DIMENSION, DataType.NUMBER,
               "sales", "orders", "orders.guest_count"),
    QueryField("sale_table_number", "桌号", "", FieldType.DIMENSION, DataType.STRING,
               "sales", "orders", "orders.table_number"),
]

_SALES_MEASURES: list[QueryField] = [
    QueryField("sale_total_revenue_fen", "总营收", "订单总金额（分）", FieldType.MEASURE, DataType.MONEY,
               "sales", "orders", "orders.total_amount_fen", aggregation="SUM", format="money"),
    QueryField("sale_final_revenue_fen", "实收金额", "折扣后实收金额（分）", FieldType.MEASURE, DataType.MONEY,
               "sales", "orders", "orders.final_amount_fen", aggregation="SUM", format="money"),
    QueryField("sale_order_count", "订单数", "", FieldType.MEASURE, DataType.NUMBER,
               "sales", "orders", "orders.id", aggregation="COUNT", format="integer"),
    QueryField("sale_discount_amount_fen", "折扣金额", "折扣总额（分）", FieldType.MEASURE, DataType.MONEY,
               "sales", "orders", "orders.discount_amount_fen", aggregation="SUM", format="money"),
    QueryField("sale_avg_ticket_fen", "客单价", "平均每单金额（分）", FieldType.MEASURE, DataType.MONEY,
               "sales", "orders", "orders.final_amount_fen / NULLIF(COUNT(orders.id), 0)", aggregation="AVG", format="money"),
    QueryField("sale_customer_count", "消费人数", "去重顾客数", FieldType.MEASURE, DataType.NUMBER,
               "sales", "orders", "orders.customer_id", aggregation="COUNT_DISTINCT", format="integer"),
    QueryField("sale_refund_amount_fen", "退款金额", "退款总额（分）", FieldType.MEASURE, DataType.MONEY,
               "sales", "orders", "CASE WHEN orders.status = 'refunded' THEN orders.final_amount_fen ELSE 0 END",
               aggregation="SUM", format="money"),
    QueryField("sale_refund_count", "退款单数", "", FieldType.MEASURE, DataType.NUMBER,
               "sales", "orders", "CASE WHEN orders.status = 'refunded' THEN 1 ELSE 0 END",
               aggregation="SUM", format="integer"),
    QueryField("sale_gross_margin_pct", "毛利率", "毛利率百分比", FieldType.MEASURE, DataType.PERCENT,
               "sales", "mv_store_pnl",
               "CASE WHEN mv_store_pnl.gross_revenue_fen > 0 "
               "THEN mv_store_pnl.gross_profit_fen::float / mv_store_pnl.gross_revenue_fen * 100 ELSE 0 END",
               aggregation="AVG", format="percent"),
    QueryField("sale_net_revenue_fen", "净营收", "净营收（分）", FieldType.MEASURE, DataType.MONEY,
               "sales", "mv_store_pnl", "mv_store_pnl.net_revenue_fen", aggregation="SUM", format="money"),
    QueryField("sale_gross_revenue_fen", "毛营收", "毛营收（分）", FieldType.MEASURE, DataType.MONEY,
               "sales", "mv_store_pnl", "mv_store_pnl.gross_revenue_fen", aggregation="SUM", format="money"),
    QueryField("sale_turnover_rate", "翻台率", "翻台次数", FieldType.MEASURE, DataType.NUMBER,
               "sales", "mv_store_pnl",
               "CASE WHEN stores.seats > 0 THEN mv_store_pnl.order_count::float / stores.seats ELSE 0 END",
               aggregation="AVG", format="decimal"),
    QueryField("sale_service_charge_fen", "服务费", "服务费总额（分）", FieldType.MEASURE, DataType.MONEY,
               "sales", "orders", "orders.service_charge_fen", aggregation="SUM", format="money"),
]

# ═══════════════════════════════════════════════════════════════════
# 菜品域 (dish) — 从 dishes / dish_categories / order_items
# ═══════════════════════════════════════════════════════════════════

_DISH_DIMS: list[QueryField] = [
    QueryField("dish_id", "菜品ID", "", FieldType.DIMENSION, DataType.STRING,
               "dish", "dishes", "dishes.id"),
    QueryField("dish_name", "菜品名称", "", FieldType.DIMENSION, DataType.STRING,
               "dish", "dishes", "dishes.dish_name", drillable=True),
    QueryField("dish_code", "菜品编码", "通用菜品编码", FieldType.DIMENSION, DataType.STRING,
               "dish", "dishes", "dishes.dish_code"),
    QueryField("dish_category_name", "菜品分类", "分类名称", FieldType.DIMENSION, DataType.STRING,
               "dish", "dish_categories", "dish_categories.name", drillable=True),
    QueryField("dish_cooking_method", "烹饪方式", "炒/蒸/煮/烤/炸", FieldType.DIMENSION, DataType.STRING,
               "dish", "dishes", "dishes.cooking_method"),
    QueryField("dish_kitchen_station", "出品档口", "", FieldType.DIMENSION, DataType.STRING,
               "dish", "dishes", "dishes.kitchen_station"),
    QueryField("dish_spicy_level", "辣度", "0-5", FieldType.DIMENSION, DataType.NUMBER,
               "dish", "dishes", "dishes.spicy_level"),
    QueryField("dish_tags", "菜品标签", "招牌/新品/特价/素食", FieldType.DIMENSION, DataType.STRING,
               "dish", "dishes", "UNNEST(dishes.tags)"),
    QueryField("dish_is_recommended", "是否推荐菜", "", FieldType.DIMENSION, DataType.BOOLEAN,
               "dish", "dishes", "dishes.is_recommended"),
    QueryField("dish_is_seasonal", "是否时令菜", "", FieldType.DIMENSION, DataType.BOOLEAN,
               "dish", "dishes", "dishes.is_seasonal"),
    QueryField("dish_season", "季节", "春/夏/秋/冬", FieldType.DIMENSION, DataType.STRING,
               "dish", "dishes", "dishes.season"),
]

_DISH_MEASURES: list[QueryField] = [
    QueryField("dish_price_fen", "售价", "菜品售价（分）", FieldType.MEASURE, DataType.MONEY,
               "dish", "dishes", "dishes.price_fen", aggregation="AVG", format="money"),
    QueryField("dish_cost_fen", "成本", "菜品成本（分）", FieldType.MEASURE, DataType.MONEY,
               "dish", "dishes", "dishes.cost_fen", aggregation="AVG", format="money"),
    QueryField("dish_profit_margin", "毛利率", "菜品毛利率(%)", FieldType.MEASURE, DataType.PERCENT,
               "dish", "dishes", "dishes.profit_margin", aggregation="AVG", format="percent"),
    QueryField("dish_sales_count", "销量", "菜品销售份数", FieldType.MEASURE, DataType.NUMBER,
               "dish", "order_items", "order_items.quantity", aggregation="SUM", format="integer"),
    QueryField("dish_revenue_fen", "菜品营收", "菜品总营收（分）", FieldType.MEASURE, DataType.MONEY,
               "dish", "order_items", "order_items.subtotal_fen", aggregation="SUM", format="money"),
    QueryField("dish_return_count", "退菜数", "退菜份数", FieldType.MEASURE, DataType.NUMBER,
               "dish", "order_items",
               "CASE WHEN order_items.return_flag THEN order_items.quantity ELSE 0 END",
               aggregation="SUM", format="integer"),
    QueryField("dish_return_rate_pct", "退菜率", "退菜占比(%)", FieldType.MEASURE, DataType.PERCENT,
               "dish", "order_items",
               "CASE WHEN order_items.return_flag THEN 1 ELSE 0 END::float / NULLIF(COUNT(*), 0) * 100",
               aggregation="AVG", format="percent"),
    QueryField("dish_rating", "评分", "菜品平均评分", FieldType.MEASURE, DataType.NUMBER,
               "dish", "dishes", "dishes.rating", aggregation="AVG", format="decimal"),
    QueryField("dish_review_count", "评价数", "评价总数量", FieldType.MEASURE, DataType.NUMBER,
               "dish", "dishes", "dishes.review_count", aggregation="SUM", format="integer"),
    QueryField("dish_gift_count", "赠菜数", "赠送份数", FieldType.MEASURE, DataType.NUMBER,
               "dish", "order_items",
               "CASE WHEN order_items.gift_flag THEN order_items.quantity ELSE 0 END",
               aggregation="SUM", format="integer"),
]

# ═══════════════════════════════════════════════════════════════════
# 会员域 (member) — 从 customers / mv_member_clv / member_transactions
# ═══════════════════════════════════════════════════════════════════

_MEMBER_DIMS: list[QueryField] = [
    QueryField("member_id", "会员ID", "", FieldType.DIMENSION, DataType.STRING,
               "member", "customers", "customers.id"),
    QueryField("member_name", "会员姓名", "", FieldType.DIMENSION, DataType.STRING,
               "member", "customers", "customers.display_name", drillable=True),
    QueryField("member_phone", "手机号", "脱敏显示", FieldType.FILTER_ONLY, DataType.STRING,
               "member", "customers", "customers.primary_phone"),
    QueryField("member_gender", "性别", "", FieldType.DIMENSION, DataType.STRING,
               "member", "customers", "customers.gender"),
    QueryField("member_source", "注册来源", "pos/wechat/manual/meituan", FieldType.DIMENSION, DataType.STRING,
               "member", "customers", "customers.source"),
    QueryField("member_rfm_level", "RFM等级", "S1-S5 五级", FieldType.DIMENSION, DataType.STRING,
               "member", "customers", "customers.rfm_level", drillable=True),
    QueryField("member_r_score", "R评分", "Recency 1-5", FieldType.DIMENSION, DataType.NUMBER,
               "member", "customers", "customers.r_score"),
    QueryField("member_f_score", "F评分", "Frequency 1-5", FieldType.DIMENSION, DataType.NUMBER,
               "member", "customers", "customers.f_score"),
    QueryField("member_m_score", "M评分", "Monetary 1-5", FieldType.DIMENSION, DataType.NUMBER,
               "member", "customers", "customers.m_score"),
    QueryField("member_risk_score", "流失风险", "0-1 流失概率", FieldType.DIMENSION, DataType.NUMBER,
               "member", "customers", "customers.risk_score"),
    QueryField("member_store_quadrant", "门店象限", "benchmark/defensive/potential/breakthrough",
               FieldType.DIMENSION, DataType.STRING, "member", "customers", "customers.store_quadrant"),
    QueryField("member_register_date", "注册日期", "", FieldType.DATE_DIM, DataType.DATE,
               "member", "customers", "customers.created_at::date"),
    QueryField("member_last_order_at", "最近消费时间", "", FieldType.DATE_DIM, DataType.DATETIME,
               "member", "customers", "customers.last_order_at"),
    QueryField("member_first_store_id", "首消门店", "", FieldType.DIMENSION, DataType.STRING,
               "member", "customers", "customers.first_store_id"),
]

_MEMBER_MEASURES: list[QueryField] = [
    QueryField("member_total_count", "会员数", "会员总数", FieldType.MEASURE, DataType.NUMBER,
               "member", "customers", "customers.id", aggregation="COUNT_DISTINCT", format="integer"),
    QueryField("member_new_count", "新增会员数", "本期新增", FieldType.MEASURE, DataType.NUMBER,
               "member", "customers", "1", aggregation="COUNT", format="integer"),
    QueryField("member_total_order_count", "累计消费次数", "", FieldType.MEASURE, DataType.NUMBER,
               "member", "customers", "customers.total_order_count", aggregation="SUM", format="integer"),
    QueryField("member_total_spend_fen", "累计消费金额", "累计消费金额（分）", FieldType.MEASURE, DataType.MONEY,
               "member", "customers", "customers.total_order_amount_fen", aggregation="SUM", format="money"),
    QueryField("member_clv_fen", "会员CLV", "客户生命周期价值（分）", FieldType.MEASURE, DataType.MONEY,
               "member", "mv_member_clv", "mv_member_clv.clv_fen", aggregation="SUM", format="money"),
    QueryField("member_avg_spend_fen", "人均消费", "平均每人消费金额（分）", FieldType.MEASURE, DataType.MONEY,
               "member", "customers",
               "customers.total_order_amount_fen / NULLIF(customers.total_order_count, 0)",
               aggregation="AVG", format="money"),
    QueryField("member_rfm_recency_days", "距末消天数", "平均距末次消费天数", FieldType.MEASURE, DataType.NUMBER,
               "member", "customers", "customers.rfm_recency_days", aggregation="AVG", format="integer"),
    QueryField("member_visit_count", "到访次数", "总到访次数", FieldType.MEASURE, DataType.NUMBER,
               "member", "mv_member_clv", "mv_member_clv.visit_count", aggregation="SUM", format="integer"),
    QueryField("member_churn_rate_pct", "流失率", "流失会员占比(%)", FieldType.MEASURE, DataType.PERCENT,
               "member", "customers",
               "CASE WHEN customers.risk_score > 0.7 THEN 1.0 ELSE 0.0 END::float / NULLIF(COUNT(*), 0) * 100",
               aggregation="AVG", format="percent"),
    QueryField("member_recharge_fen", "储值充值金额", "储值充值总额（分）", FieldType.MEASURE, DataType.MONEY,
               "member", "mv_member_clv", "mv_member_clv.stored_value_new_fen", aggregation="SUM", format="money"),
    QueryField("member_recharge_count", "储值充值次数", "", FieldType.MEASURE, DataType.NUMBER,
               "member", "mv_member_clv", "mv_member_clv.recharge_count", aggregation="SUM", format="integer"),
]

# ═══════════════════════════════════════════════════════════════════
# 成本域 (cost) — 从 mv_store_pnl / ingredients / ingredient_transactions
# ═══════════════════════════════════════════════════════════════════

_COST_DIMS: list[QueryField] = [
    QueryField("cost_store_id", "门店ID", "", FieldType.DIMENSION, DataType.STRING,
               "cost", "mv_store_pnl", "mv_store_pnl.store_id"),
    QueryField("cost_store_name", "门店名称", "", FieldType.DIMENSION, DataType.STRING,
               "cost", "stores", "stores.store_name"),
    QueryField("cost_stat_date", "统计日期", "", FieldType.DATE_DIM, DataType.DATE,
               "cost", "mv_store_pnl", "mv_store_pnl.stat_date"),
    QueryField("cost_category", "成本类别", "食材/人工/能耗/房租/其他", FieldType.DIMENSION, DataType.STRING,
               "cost", "mv_store_pnl", "mv_store_pnl.cost_category"),
    QueryField("cost_ingredient_category", "食材大类", "seafood/meat/vegetable/grain/condiment",
               FieldType.DIMENSION, DataType.STRING, "cost", "ingredient_masters", "ingredient_masters.category"),
    QueryField("cost_store_type", "门店类型", "physical/virtual/central_kitchen", FieldType.DIMENSION, DataType.STRING,
               "cost", "stores", "stores.store_type"),
    QueryField("cost_brand_id", "品牌", "", FieldType.DIMENSION, DataType.STRING,
               "cost", "stores", "stores.brand_id"),
    QueryField("cost_store_region", "区域", "", FieldType.DIMENSION, DataType.STRING,
               "cost", "stores", "stores.region"),
]

_COST_MEASURES: list[QueryField] = [
    QueryField("cost_total_cost_fen", "总成本", "总成本（分）", FieldType.MEASURE, DataType.MONEY,
               "cost", "mv_store_pnl", "mv_store_pnl.total_cost_fen", aggregation="SUM", format="money"),
    QueryField("cost_food_cost_fen", "食材成本", "食材成本总额（分）", FieldType.MEASURE, DataType.MONEY,
               "cost", "mv_store_pnl", "mv_store_pnl.food_cost_fen", aggregation="SUM", format="money"),
    QueryField("cost_labor_cost_fen", "人工成本", "人工成本总额（分）", FieldType.MEASURE, DataType.MONEY,
               "cost", "mv_store_pnl", "mv_store_pnl.labor_cost_fen", aggregation="SUM", format="money"),
    QueryField("cost_energy_cost_fen", "能耗成本", "水电气成本（分）", FieldType.MEASURE, DataType.MONEY,
               "cost", "mv_store_pnl", "mv_store_pnl.energy_cost_fen", aggregation="SUM", format="money"),
    QueryField("cost_rent_cost_fen", "房租成本", "房租成本（分）", FieldType.MEASURE, DataType.MONEY,
               "cost", "mv_store_pnl", "mv_store_pnl.rent_cost_fen", aggregation="SUM", format="money"),
    QueryField("cost_other_cost_fen", "其他成本", "其他成本（分）", FieldType.MEASURE, DataType.MONEY,
               "cost", "mv_store_pnl", "mv_store_pnl.other_cost_fen", aggregation="SUM", format="money"),
    QueryField("cost_ratio_pct", "成本率", "成本/营收百分比", FieldType.MEASURE, DataType.PERCENT,
               "cost", "mv_store_pnl",
               "CASE WHEN mv_store_pnl.gross_revenue_fen > 0 "
               "THEN mv_store_pnl.total_cost_fen::float / mv_store_pnl.gross_revenue_fen * 100 ELSE 0 END",
               aggregation="AVG", format="percent"),
    QueryField("cost_food_cost_ratio_pct", "食材成本率", "食材成本/营收(%)", FieldType.MEASURE, DataType.PERCENT,
               "cost", "mv_store_pnl",
               "CASE WHEN mv_store_pnl.gross_revenue_fen > 0 "
               "THEN mv_store_pnl.food_cost_fen::float / mv_store_pnl.gross_revenue_fen * 100 ELSE 0 END",
               aggregation="AVG", format="percent"),
    QueryField("cost_labor_cost_ratio_pct", "人工成本率", "人成/营收(%)", FieldType.MEASURE, DataType.PERCENT,
               "cost", "mv_store_pnl",
               "CASE WHEN mv_store_pnl.gross_revenue_fen > 0 "
               "THEN mv_store_pnl.labor_cost_fen::float / mv_store_pnl.gross_revenue_fen * 100 ELSE 0 END",
               aggregation="AVG", format="percent"),
    QueryField("cost_gross_profit_fen", "毛利额", "营收-成本（分）", FieldType.MEASURE, DataType.MONEY,
               "cost", "mv_store_pnl", "mv_store_pnl.gross_profit_fen", aggregation="SUM", format="money"),
    QueryField("cost_unit_cost_fen", "单位食材成本", "平均单位食材成本（分）", FieldType.MEASURE, DataType.MONEY,
               "cost", "ingredient_transactions", "ingredient_transactions.unit_cost_fen", aggregation="AVG", format="money"),
    QueryField("cost_waste_amount_fen", "损耗金额", "损耗成本总额（分）", FieldType.MEASURE, DataType.MONEY,
               "cost", "ingredient_transactions",
               "CASE WHEN ingredient_transactions.transaction_type = 'waste' THEN ingredient_transactions.total_cost_fen ELSE 0 END",
               aggregation="SUM", format="money"),
]

# ═══════════════════════════════════════════════════════════════════
# 供应链域 (supply) — 从 ingredients / ingredient_transactions / mv_inventory_bom
# ═══════════════════════════════════════════════════════════════════

_SUPPLY_DIMS: list[QueryField] = [
    QueryField("supply_ingredient_id", "食材ID", "", FieldType.DIMENSION, DataType.STRING,
               "supply", "ingredients", "ingredients.id"),
    QueryField("supply_ingredient_name", "食材名称", "", FieldType.DIMENSION, DataType.STRING,
               "supply", "ingredients", "ingredients.ingredient_name", drillable=True),
    QueryField("supply_category", "食材类别", "seafood/meat/vegetable/grain/condiment", FieldType.DIMENSION, DataType.STRING,
               "supply", "ingredients", "ingredients.category", drillable=True),
    QueryField("supply_store_id", "门店ID", "", FieldType.DIMENSION, DataType.STRING,
               "supply", "ingredients", "ingredients.store_id"),
    QueryField("supply_store_name", "门店名称", "", FieldType.DIMENSION, DataType.STRING,
               "supply", "stores", "stores.store_name"),
    QueryField("supply_supplier_name", "供应商", "", FieldType.DIMENSION, DataType.STRING,
               "supply", "ingredients", "ingredients.supplier_name"),
    QueryField("supply_status", "库存状态", "normal/low/warning/expired", FieldType.DIMENSION, DataType.STRING,
               "supply", "ingredients", "ingredients.status"),
    QueryField("supply_storage_type", "存储类型", "ambient/refrigerated/frozen", FieldType.DIMENSION, DataType.STRING,
               "supply", "ingredient_masters", "ingredient_masters.storage_type"),
    QueryField("supply_transaction_type", "变动类型", "purchase/usage/waste/adjustment", FieldType.DIMENSION, DataType.STRING,
               "supply", "ingredient_transactions", "ingredient_transactions.transaction_type"),
    QueryField("supply_unit", "单位", "kg/L/个/份", FieldType.DIMENSION, DataType.STRING,
               "supply", "ingredients", "ingredients.unit"),
]

_SUPPLY_MEASURES: list[QueryField] = [
    QueryField("supply_current_quantity", "当前库存", "当前库存量", FieldType.MEASURE, DataType.NUMBER,
               "supply", "ingredients", "ingredients.current_quantity", aggregation="SUM", format="decimal"),
    QueryField("supply_total_value_fen", "库存总值", "库存总值（分）", FieldType.MEASURE, DataType.MONEY,
               "supply", "ingredients", "ingredients.current_quantity * ingredients.unit_price_fen",
               aggregation="SUM", format="money"),
    QueryField("supply_theoretical_usage", "理论用量", "BOM推算理论用量(g)", FieldType.MEASURE, DataType.NUMBER,
               "supply", "mv_inventory_bom", "mv_inventory_bom.theoretical_usage_g", aggregation="SUM", format="decimal"),
    QueryField("supply_actual_usage", "实际用量", "实际用量(g)", FieldType.MEASURE, DataType.NUMBER,
               "supply", "mv_inventory_bom", "mv_inventory_bom.actual_usage_g", aggregation="SUM", format="decimal"),
    QueryField("supply_usage_variance_pct", "用量差异率", "(实际-理论)/理论(%)", FieldType.MEASURE, DataType.PERCENT,
               "supply", "mv_inventory_bom",
               "CASE WHEN mv_inventory_bom.theoretical_usage_g > 0 "
               "THEN (mv_inventory_bom.actual_usage_g - mv_inventory_bom.theoretical_usage_g) "
               "/ mv_inventory_bom.theoretical_usage_g * 100 ELSE 0 END",
               aggregation="AVG", format="percent"),
    QueryField("supply_waste_quantity", "损耗量", "损耗总量", FieldType.MEASURE, DataType.NUMBER,
               "supply", "ingredient_transactions",
               "CASE WHEN ingredient_transactions.transaction_type = 'waste' THEN ingredient_transactions.quantity ELSE 0 END",
               aggregation="SUM", format="decimal"),
    QueryField("supply_purchase_amount_fen", "采购金额", "采购总额（分）", FieldType.MEASURE, DataType.MONEY,
               "supply", "ingredient_transactions",
               "CASE WHEN ingredient_transactions.transaction_type = 'purchase' THEN ingredient_transactions.total_cost_fen ELSE 0 END",
               aggregation="SUM", format="money"),
    QueryField("supply_turnover_days", "库存周转天数", "平均库存周转天数", FieldType.MEASURE, DataType.NUMBER,
               "supply", "mv_inventory_bom", "mv_inventory_bom.inventory_turnover_days", aggregation="AVG", format="decimal"),
    QueryField("supply_stockout_count", "缺货次数", "库存低于最低阈值次数", FieldType.MEASURE, DataType.NUMBER,
               "supply", "ingredients",
               "CASE WHEN ingredients.current_quantity <= ingredients.min_quantity THEN 1 ELSE 0 END",
               aggregation="SUM", format="integer"),
    QueryField("supply_waste_rate_pct", "损耗率", "损耗占比(%)", FieldType.MEASURE, DataType.PERCENT,
               "supply", "mv_inventory_bom",
               "CASE WHEN mv_inventory_bom.theoretical_usage_g > 0 "
               "THEN mv_inventory_bom.waste_quantity_g::float / mv_inventory_bom.theoretical_usage_g * 100 ELSE 0 END",
               aggregation="AVG", format="percent"),
]

# ═══════════════════════════════════════════════════════════════════
# 财务域 (finance) — 从 mv_daily_settlement / mv_channel_margin / mv_discount_health
# ═══════════════════════════════════════════════════════════════════

_FINANCE_DIMS: list[QueryField] = [
    QueryField("fin_store_id", "门店ID", "", FieldType.DIMENSION, DataType.STRING,
               "finance", "mv_daily_settlement", "mv_daily_settlement.store_id"),
    QueryField("fin_store_name", "门店名称", "", FieldType.DIMENSION, DataType.STRING,
               "finance", "stores", "stores.store_name"),
    QueryField("fin_stat_date", "结算日期", "", FieldType.DATE_DIM, DataType.DATE,
               "finance", "mv_daily_settlement", "mv_daily_settlement.stat_date"),
    QueryField("fin_settlement_status", "结算状态", "open/closed/reconciled", FieldType.DIMENSION, DataType.STRING,
               "finance", "mv_daily_settlement", "mv_daily_settlement.status"),
    QueryField("fin_channel", "支付渠道", "wechat/alipay/card/cash/meituan/eleme/douyin",
               FieldType.DIMENSION, DataType.STRING, "finance", "mv_channel_margin", "mv_channel_margin.channel"),
    QueryField("fin_brand_id", "品牌", "", FieldType.DIMENSION, DataType.STRING,
               "finance", "stores", "stores.brand_id"),
    QueryField("fin_region", "区域", "", FieldType.DIMENSION, DataType.STRING,
               "finance", "stores", "stores.region"),
    QueryField("fin_month", "月份", "YYYY-MM", FieldType.DIMENSION, DataType.STRING,
               "finance", "mv_daily_settlement", "TO_CHAR(mv_daily_settlement.stat_date, 'YYYY-MM')"),
    QueryField("fin_discount_type", "折扣类型", "coupon/vip/manager/promotion/unauthorized",
               FieldType.DIMENSION, DataType.STRING, "finance", "mv_discount_health", "mv_discount_health.leak_type"),
]

_FINANCE_MEASURES: list[QueryField] = [
    QueryField("fin_total_revenue_fen", "总营收", "总营收（分）", FieldType.MEASURE, DataType.MONEY,
               "finance", "mv_daily_settlement", "mv_daily_settlement.total_revenue_fen", aggregation="SUM", format="money"),
    QueryField("fin_wechat_received_fen", "微信收款", "微信支付收款（分）", FieldType.MEASURE, DataType.MONEY,
               "finance", "mv_daily_settlement", "mv_daily_settlement.wechat_received_fen", aggregation="SUM", format="money"),
    QueryField("fin_alipay_received_fen", "支付宝收款", "支付宝收款（分）", FieldType.MEASURE, DataType.MONEY,
               "finance", "mv_daily_settlement", "mv_daily_settlement.alipay_received_fen", aggregation="SUM", format="money"),
    QueryField("fin_card_received_fen", "银行卡收款", "银行卡收款（分）", FieldType.MEASURE, DataType.MONEY,
               "finance", "mv_daily_settlement", "mv_daily_settlement.card_received_fen", aggregation="SUM", format="money"),
    QueryField("fin_cash_received_fen", "现金收款", "现金收款（分）", FieldType.MEASURE, DataType.MONEY,
               "finance", "mv_daily_settlement", "mv_daily_settlement.cash_received_fen", aggregation="SUM", format="money"),
    QueryField("fin_channel_gmv_fen", "渠道GMV", "渠道总交易额（分）", FieldType.MEASURE, DataType.MONEY,
               "finance", "mv_channel_margin", "mv_channel_margin.gross_revenue_fen", aggregation="SUM", format="money"),
    QueryField("fin_channel_commission_fen", "渠道佣金", "平台佣金（分）", FieldType.MEASURE, DataType.MONEY,
               "finance", "mv_channel_margin", "mv_channel_margin.commission_fen", aggregation="SUM", format="money"),
    QueryField("fin_channel_net_revenue_fen", "渠道净收入", "GMV-佣金（分）", FieldType.MEASURE, DataType.MONEY,
               "finance", "mv_channel_margin",
               "mv_channel_margin.gross_revenue_fen - mv_channel_margin.commission_fen",
               aggregation="SUM", format="money"),
    QueryField("fin_channel_promotion_fen", "平台补贴", "平台补贴收入（分）", FieldType.MEASURE, DataType.MONEY,
               "finance", "mv_channel_margin", "mv_channel_margin.promotion_subsidy_fen", aggregation="SUM", format="money"),
    QueryField("fin_total_discount_fen", "折扣总额", "折扣总金额（分）", FieldType.MEASURE, DataType.MONEY,
               "finance", "mv_discount_health", "mv_discount_health.total_discount_fen", aggregation="SUM", format="money"),
    QueryField("fin_discount_rate_pct", "折扣率", "折扣/营收(%)", FieldType.MEASURE, DataType.PERCENT,
               "finance", "mv_discount_health", "mv_discount_health.discount_rate", aggregation="AVG", format="percent"),
    QueryField("fin_discounted_order_count", "折扣订单数", "有折扣的订单数", FieldType.MEASURE, DataType.NUMBER,
               "finance", "mv_discount_health", "mv_discount_health.discounted_orders", aggregation="SUM", format="integer"),
    QueryField("fin_unauthorized_count", "无授权折扣数", "未授权折扣次数", FieldType.MEASURE, DataType.NUMBER,
               "finance", "mv_discount_health", "mv_discount_health.unauthorized_count", aggregation="SUM", format="integer"),
    QueryField("fin_threshold_breaches", "超阈值次数", "折扣超授权阈值次数", FieldType.MEASURE, DataType.NUMBER,
               "finance", "mv_discount_health", "mv_discount_health.threshold_breaches", aggregation="SUM", format="integer"),
]


# ═══════════════════════════════════════════════════════════════════
# 全局字段映射
# ═══════════════════════════════════════════════════════════════════

FIELDS_BY_DOMAIN: dict[str, list[QueryField]] = {
    "sales": _SALES_DIMS + _SALES_MEASURES,
    "dish": _DISH_DIMS + _DISH_MEASURES,
    "member": _MEMBER_DIMS + _MEMBER_MEASURES,
    "cost": _COST_DIMS + _COST_MEASURES,
    "supply": _SUPPLY_DIMS + _SUPPLY_MEASURES,
    "finance": _FINANCE_DIMS + _FINANCE_MEASURES,
}

# 展平为 field_id → QueryField 映射
_ALL_FIELDS: dict[str, QueryField] = {}
for _domain_fields in FIELDS_BY_DOMAIN.values():
    for _f in _domain_fields:
        _ALL_FIELDS[_f.field_id] = _f

DOMAIN_LABELS: dict[str, str] = {
    "sales": "销售",
    "dish": "菜品",
    "member": "会员",
    "cost": "成本",
    "supply": "供应链",
    "finance": "财务",
}


class FieldRegistry:
    """可用字段注册表 — 提供字段发现和查询接口"""

    @staticmethod
    def list_fields(domain: Optional[str] = None) -> list[dict]:
        """列出可用字段，可选按域过滤。

        Args:
            domain: 域名称（sales/dish/member/cost/supply/finance），None 返回全部

        Returns:
            字段列表，每个字段为 dict
        """
        if domain:
            fields = FIELDS_BY_DOMAIN.get(domain, [])
            return [f.to_dict() for f in fields]
        return [f.to_dict() for f in _ALL_FIELDS.values()]

    @staticmethod
    def list_fields_grouped() -> dict[str, list[dict]]:
        """按域分组列出所有字段。"""
        return {
            domain: [f.to_dict() for f in fields]
            for domain, fields in FIELDS_BY_DOMAIN.items()
        }

    @staticmethod
    def get_field(field_id: str) -> Optional[QueryField]:
        """按 field_id 获取单个字段定义。"""
        return _ALL_FIELDS.get(field_id)

    @staticmethod
    def list_domains() -> list[dict]:
        """列出所有数据域及其中文标签。"""
        return [
            {"domain": k, "label": v, "field_count": len(FIELDS_BY_DOMAIN[k])}
            for k, v in DOMAIN_LABELS.items()
        ]

    @staticmethod
    def search_fields(query: str) -> list[dict]:
        """搜索字段 — 在 field_id、label、description 中匹配。

        Args:
            query: 搜索关键词（中文或英文）
        """
        q = query.lower()
        results = []
        for f in _ALL_FIELDS.values():
            if (q in f.field_id.lower()
                    or q in f.label.lower()
                    or q in f.description.lower()):
                results.append(f.to_dict())
        return results
