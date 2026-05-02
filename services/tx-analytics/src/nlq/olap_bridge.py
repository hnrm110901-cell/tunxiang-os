"""NLQ → OLAP 查询桥接器（BI-1.3）

将 NLQ 意图识别结果转换为 OLAP 多维查询，并推荐下钻维度。
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# OLAP query shape
# ---------------------------------------------------------------------------


class OLAPQuery:
    """OLAP 多维查询描述"""

    def __init__(
        self,
        measures: list[str] | None = None,
        dimensions: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        order_by: list[str] | None = None,
        limit: int = 100,
    ):
        self.measures = measures or ["revenue_fen"]
        self.dimensions = dimensions or ["biz_date"]
        self.filters = filters or {}
        self.order_by = order_by or []
        self.limit = limit

    def to_dict(self) -> dict[str, Any]:
        return {
            "measures": self.measures,
            "dimensions": self.dimensions,
            "filters": self.filters,
            "order_by": self.order_by,
            "limit": self.limit,
        }


# ---------------------------------------------------------------------------
# Intent → OLAP mapping
# ---------------------------------------------------------------------------

# 维度-数据列映射（用于 OLAP drill-down）
_DRILL_DIMENSIONS: dict[str, list[str]] = {
    "revenue_today": ["store_name", "biz_date", "hour", "channel"],
    "top_store": ["channel", "dish_name", "hour", "guest_count"],
    "top_dishes": ["store_name", "category", "hour", "channel"],
    "channel_breakdown": ["store_name", "biz_date", "dish_name", "hour"],
    "repurchase_rate": ["store_name", "tier", "biz_date", "age_group"],
    "store_health": ["channel", "dish_name", "biz_date", "cost_category"],
    "member_rfm": ["store_name", "biz_date", "age_group", "channel"],
    "inventory_alert": ["category", "supplier_name", "store_name"],
    "avg_order_value": ["store_name", "channel", "hour", "meal_period"],
    "dish_margin": ["store_name", "channel", "category", "cooking_method"],
}


def nlq_to_olap_query(intent_result: dict[str, Any]) -> OLAPQuery:
    """将 NLQ 意图结果转换为 OLAPQuery。

    策略：
    - 如果意图包含 dimensions/measures → 映射为 OLAPQuery
    - 否则从 intent 名称推导默认维度和度量
    """
    intent = intent_result.get("intent", "")
    category = intent_result.get("category", "")

    # 从答案模板提取隐含的度量和维度
    measures = _extract_measures(intent, category)
    dimensions = _extract_dimensions(intent, category)

    return OLAPQuery(
        measures=measures,
        dimensions=dimensions,
        filters=intent_result.get("context_filters", {}),
    )


def suggest_drill(intent_result: dict[str, Any]) -> list[str]:
    """根据当前查询上下文推荐可下钻维度"""
    intent = intent_result.get("intent", "")
    return _DRILL_DIMENSIONS.get(intent, ["biz_date", "store_name", "channel"])


def _extract_measures(intent: str, category: str) -> list[str]:
    """从意图名称推导 OLAP 度量"""
    measure_map: dict[str, list[str]] = {
        "revenue": ["revenue_fen", "order_count"],
        "dish": ["total_qty", "total_fen", "margin_rate"],
        "member": ["member_count", "total_spend_fen", "visit_count"],
        "cost": ["cost_fen", "revenue_fen", "margin_fen"],
        "store": ["revenue_fen", "order_count", "turnover_rate"],
        "channel": ["order_count", "total_fen", "commission_fen"],
        "supply": ["current_qty", "waste_qty", "value_fen"],
        "finance": ["revenue_fen", "cost_fen", "net_fen", "margin_rate"],
        "hr": ["headcount", "per_capita_fen", "overtime_hours"],
        "marketing": ["redeemed", "revenue_fen", "roi"],
    }
    if category in measure_map:
        return measure_map[category]
    return ["revenue_fen", "order_count"]


def _extract_dimensions(intent: str, category: str) -> list[str]:
    """从意图名称推导 OLAP 维度"""
    # 大多数查询天然带有时间维度
    if "trend" in intent or "趋势" in intent:
        return ["biz_date", "store_name"]

    dim_map: dict[str, list[str]] = {
        "revenue": ["store_name", "biz_date"],
        "dish": ["dish_name", "category"],
        "member": ["store_name", "tier"],
        "cost": ["category", "store_name"],
        "store": ["store_name", "biz_date"],
        "channel": ["channel", "store_name"],
        "supply": ["ingredient_name", "category"],
        "finance": ["store_name", "biz_date"],
        "hr": ["store_name", "employee_name"],
        "marketing": ["campaign_name", "coupon_type"],
    }

    if category in dim_map:
        return dim_map[category]
    return ["biz_date", "store_name"]
