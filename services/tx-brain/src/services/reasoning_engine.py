"""多因子归因推理 — 从数据到洞察

不是简单统计，而是因果推理。
V1迁入（530行核心逻辑），在V3架构上重建。

核心能力：
- 指标变化分解：营收下降10% = 客流↓5% + 客单价↓3% + 退单↑2%
- 多因子归因：哪些因素对目标指标贡献最大
- 门店对比：为什么A店比B店好
- 自动洞察：每日/周自动生成Top5洞察
- "为什么"问答：自然语言→结构化归因
"""

from datetime import datetime, timedelta
from typing import Any, Optional

import structlog

from ..ontology.repository import OntologyRepository

logger = structlog.get_logger()


# ─── Metric Decomposition Trees ───

METRIC_DECOMPOSITION: dict[str, list[dict[str, Any]]] = {
    "revenue": [
        {"factor": "traffic", "cn_name": "客流量", "weight": 0.40, "unit": "人"},
        {"factor": "avg_check", "cn_name": "客单价", "weight": 0.30, "unit": "元"},
        {"factor": "conversion_rate", "cn_name": "转化率", "weight": 0.15, "unit": "%"},
        {"factor": "cancellation_rate", "cn_name": "退单率", "weight": 0.10, "unit": "%", "inverse": True},
        {"factor": "channel_mix", "cn_name": "渠道结构", "weight": 0.05, "unit": ""},
    ],
    "margin": [
        {"factor": "food_cost", "cn_name": "食材成本", "weight": 0.45, "unit": "元", "inverse": True},
        {"factor": "discount_rate", "cn_name": "折扣率", "weight": 0.25, "unit": "%", "inverse": True},
        {"factor": "waste_rate", "cn_name": "损耗率", "weight": 0.15, "unit": "%", "inverse": True},
        {"factor": "labor_cost", "cn_name": "人工成本", "weight": 0.10, "unit": "元", "inverse": True},
        {"factor": "energy_cost", "cn_name": "能源成本", "weight": 0.05, "unit": "元", "inverse": True},
    ],
    "traffic": [
        {"factor": "weather", "cn_name": "天气", "weight": 0.20, "unit": ""},
        {"factor": "competition", "cn_name": "竞争", "weight": 0.25, "unit": ""},
        {"factor": "marketing", "cn_name": "营销活动", "weight": 0.20, "unit": ""},
        {"factor": "seasonality", "cn_name": "季节性", "weight": 0.15, "unit": ""},
        {"factor": "reputation", "cn_name": "口碑评价", "weight": 0.20, "unit": "分"},
    ],
}

# ─── Insight Templates ───

INSIGHT_TEMPLATES: list[dict[str, Any]] = [
    {
        "type": "cost_anomaly",
        "template": "{ingredient}价格{direction}{change_pct:.1f}%，影响{dish_count}道菜品毛利",
        "priority": "high",
        "category": "成本",
    },
    {
        "type": "margin_warning",
        "template": "{dish_name}毛利率降至{margin:.1%}，低于{threshold:.0%}警戒线",
        "priority": "high",
        "category": "毛利",
    },
    {
        "type": "traffic_change",
        "template": "本周客流量较上周{direction}{change:.1f}%，主要受{reason}影响",
        "priority": "medium",
        "category": "客流",
    },
    {
        "type": "top_seller",
        "template": "{dish_name}本周销量{sales}份，环比{direction}{change:.1f}%",
        "priority": "low",
        "category": "销售",
    },
    {
        "type": "waste_alert",
        "template": "本日损耗率{waste_rate:.1f}%，超出标准{threshold:.1f}%",
        "priority": "medium",
        "category": "损耗",
    },
]


class ReasoningEngine:
    """多因子归因推理引擎

    From data to insights via causal decomposition.
    """

    def __init__(self, repository: OntologyRepository) -> None:
        self.repo = repository
        logger.info("reasoning_engine_init")

    def analyze_metric_change(
        self,
        store_id: str,
        metric: str,
        period_a: str,
        period_b: str,
    ) -> dict[str, Any]:
        """Decompose a metric change into contributing factors.

        Example: revenue down 10% =
          traffic down 5% (contributes 40%)
          + avg_check down 3% (contributes 30%)
          + cancellation up 2% (contributes 20%)
          + other (10%)

        Args:
            store_id: Store node ID
            metric: Target metric (revenue, margin, traffic)
            period_a: Earlier period label
            period_b: Later period label

        Returns:
            Dict with total_change, factor decomposition
        """
        store_result = self.repo.get_node("Store", store_id)
        if not store_result.get("ok"):
            return {"ok": False, "error": f"Store {store_id} not found"}

        store_props = store_result["node"]["properties"]

        decomposition_tree = METRIC_DECOMPOSITION.get(metric, [])
        if not decomposition_tree:
            return {"ok": False, "error": f"Unknown metric: {metric}"}

        # Get total change from store properties
        current = store_props.get(f"{metric}_current", store_props.get("margin_current", 0))
        previous = store_props.get(f"{metric}_previous", store_props.get("margin_previous", 0))

        if isinstance(current, (int, float)) and isinstance(previous, (int, float)):
            if previous != 0:
                total_change_pct = (current - previous) / abs(previous) * 100
            else:
                total_change_pct = 0.0
        else:
            total_change_pct = 0.0

        # Decompose into factors
        factors: list[dict[str, Any]] = []
        remaining_pct = total_change_pct

        for factor_def in decomposition_tree:
            factor_name = factor_def["factor"]
            weight = factor_def["weight"]
            cn_name = factor_def["cn_name"]
            is_inverse = factor_def.get("inverse", False)

            # Get factor-specific data from store properties
            factor_change = self._get_factor_change(store_props, factor_name, metric)

            # Contribution to total change
            contribution_pct = factor_change * weight
            if is_inverse:
                contribution_pct = -contribution_pct

            direction = "上升" if factor_change > 0 else "下降"
            if is_inverse:
                direction = "下降" if factor_change > 0 else "上升"

            factors.append(
                {
                    "factor": factor_name,
                    "cn_name": cn_name,
                    "change_pct": round(factor_change, 2),
                    "weight": weight,
                    "contribution_pct": round(contribution_pct, 2),
                    "direction": direction,
                    "unit": factor_def.get("unit", ""),
                    "confidence": round(0.7 + weight * 0.3, 2),
                }
            )

            remaining_pct -= abs(contribution_pct)

        # Sort by absolute contribution
        factors.sort(key=lambda x: abs(x["contribution_pct"]), reverse=True)

        # Add "other" factor for unexplained portion
        if abs(remaining_pct) > 0.1:
            factors.append(
                {
                    "factor": "other",
                    "cn_name": "其他因素",
                    "change_pct": round(remaining_pct, 2),
                    "weight": 0.0,
                    "contribution_pct": round(remaining_pct, 2),
                    "direction": "上升" if remaining_pct > 0 else "下降",
                    "unit": "",
                    "confidence": 0.3,
                }
            )

        return {
            "ok": True,
            "store_id": store_id,
            "metric": metric,
            "period_a": period_a,
            "period_b": period_b,
            "total_change_pct": round(total_change_pct, 2),
            "direction": "上升" if total_change_pct > 0 else "下降",
            "factors": factors,
            "top_factor": factors[0] if factors else None,
            "analyzed_at": datetime.now().isoformat(),
        }

    def multi_factor_attribution(
        self,
        store_id: str,
        target_metric: str,
        candidate_factors: list[str],
        period: str = "last_week",
    ) -> dict[str, Any]:
        """Determine which factors contribute most to target metric.

        Args:
            store_id: Store node ID
            target_metric: Target metric to explain
            candidate_factors: List of candidate factor names
            period: Analysis period

        Returns:
            Dict with factor attributions sorted by contribution
        """
        store_result = self.repo.get_node("Store", store_id)
        if not store_result.get("ok"):
            return {"ok": False, "error": f"Store {store_id} not found"}

        store_props = store_result["node"]["properties"]

        attributions: list[dict[str, Any]] = []

        for factor in candidate_factors:
            # Get factor change from store data
            factor_change = self._get_factor_change(store_props, factor, target_metric)

            # Estimate contribution using known decomposition weights
            weight = self._get_factor_weight(target_metric, factor)
            contribution = factor_change * weight
            is_inverse = self._is_inverse_factor(target_metric, factor)
            if is_inverse:
                contribution = -contribution

            direction = "正向" if contribution > 0 else "负向"
            confidence = min(0.95, 0.5 + abs(contribution) / 20.0)

            attributions.append(
                {
                    "factor": factor,
                    "cn_name": self._get_factor_cn_name(factor),
                    "contribution_pct": round(contribution, 2),
                    "direction": direction,
                    "confidence": round(confidence, 2),
                    "factor_change_pct": round(factor_change, 2),
                    "weight": weight,
                }
            )

        # Sort by absolute contribution
        attributions.sort(key=lambda x: abs(x["contribution_pct"]), reverse=True)

        return {
            "ok": True,
            "store_id": store_id,
            "target_metric": target_metric,
            "period": period,
            "attributions": attributions,
            "primary_driver": attributions[0] if attributions else None,
            "analyzed_at": datetime.now().isoformat(),
        }

    def compare_stores(self, store_ids: list[str], metrics: list[str]) -> dict[str, Any]:
        """Compare stores and explain performance differences.

        Args:
            store_ids: List of store IDs to compare
            metrics: Metrics to compare

        Returns:
            Dict with per-metric comparisons and explanations
        """
        stores_data: list[dict[str, Any]] = []

        for sid in store_ids:
            store_result = self.repo.get_node("Store", sid)
            if store_result.get("ok"):
                stores_data.append(
                    {
                        "store_id": sid,
                        "store_name": store_result["node"]["properties"].get("name", ""),
                        "properties": store_result["node"]["properties"],
                    }
                )

        if len(stores_data) < 2:
            return {"ok": False, "error": "Need at least 2 valid stores to compare"}

        comparisons: list[dict[str, Any]] = []

        for metric in metrics:
            metric_key_current = f"{metric}_current"
            metric_key = (
                metric_key_current if any(metric_key_current in s["properties"] for s in stores_data) else metric
            )

            values = []
            for store in stores_data:
                val = store["properties"].get(metric_key, store["properties"].get(metric, 0))
                values.append(
                    {
                        "store_id": store["store_id"],
                        "store_name": store["store_name"],
                        "value": val,
                    }
                )

            # Sort by value descending
            values.sort(key=lambda x: x["value"] if isinstance(x["value"], (int, float)) else 0, reverse=True)

            best = values[0]
            worst = values[-1]

            # Generate explanation
            explanation = self._explain_difference(best, worst, metric, stores_data)

            comparisons.append(
                {
                    "metric": metric,
                    "rankings": values,
                    "best": best,
                    "worst": worst,
                    "gap": self._calc_gap(best["value"], worst["value"]),
                    "explanation": explanation,
                }
            )

        return {
            "ok": True,
            "store_ids": store_ids,
            "metrics": metrics,
            "comparisons": comparisons,
            "analyzed_at": datetime.now().isoformat(),
        }

    def generate_insight(self, store_id: str, period: str = "last_week") -> dict[str, Any]:
        """Auto-generate top 5 insights for a store.

        Scans all available data and produces prioritized insights.

        Args:
            store_id: Store node ID
            period: Analysis period

        Returns:
            Dict with prioritized insights list
        """
        store_result = self.repo.get_node("Store", store_id)
        if not store_result.get("ok"):
            return {"ok": False, "error": f"Store {store_id} not found"}

        store_props = store_result["node"]["properties"]
        store_name = store_props.get("name", "")
        insights: list[dict[str, Any]] = []

        # 1. Check margin change
        margin_current = store_props.get("margin_current", 0)
        margin_previous = store_props.get("margin_previous", 0)
        if margin_current and margin_previous:
            margin_change = margin_current - margin_previous
            if abs(margin_change) > 0.02:
                direction = "上升" if margin_change > 0 else "下降"
                insights.append(
                    {
                        "type": "margin_change",
                        "priority": "high",
                        "category": "毛利",
                        "title": f"毛利率{direction}",
                        "description": (
                            f"{store_name}毛利率从{margin_previous:.1%}{direction}至"
                            f"{margin_current:.1%}，变动{abs(margin_change):.1%}"
                        ),
                        "metric_value": margin_current,
                        "metric_change": round(margin_change, 4),
                        "action": "查看成本分析" if margin_change < 0 else "保持当前策略",
                    }
                )

        # 2. Check traffic change
        traffic_change = store_props.get("traffic_change_pct", 0)
        if abs(traffic_change) > 3:
            direction = "上升" if traffic_change > 0 else "下降"
            insights.append(
                {
                    "type": "traffic_change",
                    "priority": "high" if abs(traffic_change) > 10 else "medium",
                    "category": "客流",
                    "title": f"客流量{direction}{abs(traffic_change):.1f}%",
                    "description": (f"{store_name}本周客流量{direction}{abs(traffic_change):.1f}%"),
                    "metric_value": traffic_change,
                    "action": "分析客流下降原因" if traffic_change < 0 else "分析增长来源",
                }
            )

        # 3. Check waste rate
        waste_rate = store_props.get("waste_rate", 0)
        if waste_rate > 5:
            insights.append(
                {
                    "type": "waste_alert",
                    "priority": "medium",
                    "category": "损耗",
                    "title": f"损耗率偏高: {waste_rate:.1f}%",
                    "description": (f"{store_name}损耗率{waste_rate:.1f}%，超出5%标准线"),
                    "metric_value": waste_rate,
                    "action": "审查备料流程和库存管理",
                }
            )

        # 4. Check discount rate
        discount_rate = store_props.get("discount_rate", 0)
        if discount_rate > 10:
            insights.append(
                {
                    "type": "discount_alert",
                    "priority": "medium",
                    "category": "折扣",
                    "title": f"折扣率偏高: {discount_rate:.1f}%",
                    "description": (f"{store_name}折扣率{discount_rate:.1f}%，高于10%健康线"),
                    "metric_value": discount_rate,
                    "action": "审查折扣权限和活动规则",
                }
            )

        # 5. Check ingredient price changes (via dishes)
        dish_rels = self.repo.get_relationships("Store", store_id, rel_type="SERVES", direction="out")
        price_alerts: list[dict[str, Any]] = []
        for rel in dish_rels:
            dish_id = rel.get("to_node_id", "")
            bom_rels = self.repo.get_relationships("Dish", dish_id, rel_type="USES_INGREDIENT", direction="out")
            for bom_rel in bom_rels:
                ing_id = bom_rel.get("to_node_id", "")
                ing_node = self.repo.get_node("Ingredient", ing_id)
                if ing_node.get("ok"):
                    pct = ing_node["node"]["properties"].get("price_change_pct", 0)
                    if abs(pct) > 15:
                        price_alerts.append(
                            {
                                "ingredient": ing_node["node"]["properties"].get("name", ""),
                                "change_pct": pct,
                            }
                        )

        # Deduplicate
        seen_ingredients: set[str] = set()
        unique_alerts: list[dict[str, Any]] = []
        for alert in price_alerts:
            name = alert["ingredient"]
            if name not in seen_ingredients:
                seen_ingredients.add(name)
                unique_alerts.append(alert)

        if unique_alerts:
            names = "、".join(a["ingredient"] for a in unique_alerts[:3])
            insights.append(
                {
                    "type": "cost_anomaly",
                    "priority": "high",
                    "category": "成本",
                    "title": f"食材价格异动: {names}",
                    "description": (
                        f"{len(unique_alerts)}种食材价格大幅变动: "
                        + ", ".join(f"{a['ingredient']}{a['change_pct']:+.0f}%" for a in unique_alerts[:3])
                    ),
                    "metric_value": len(unique_alerts),
                    "action": "评估成本影响，考虑调整售价或BOM",
                }
            )

        # Sort by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        insights.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 2))

        return {
            "ok": True,
            "store_id": store_id,
            "store_name": store_name,
            "period": period,
            "insights": insights[:5],
            "total_insights": len(insights),
            "generated_at": datetime.now().isoformat(),
        }

    def answer_why(self, question: str, store_id: Optional[str] = None) -> dict[str, Any]:
        """Answer a natural language "why" question with structured analysis.

        Example: "为什么上周营收下降了？" →
        factor decomposition + root cause analysis

        Args:
            question: Natural language question in Chinese
            store_id: Optional store context

        Returns:
            Dict with structured answer
        """
        # Parse question to determine metric and direction
        metric, direction = self._parse_why_question(question)

        if not metric:
            return {
                "ok": False,
                "error": "无法从问题中识别指标，请尝试包含：营收、毛利、客流、成本等关键词",
                "question": question,
            }

        # Use default store if none specified
        if not store_id:
            stores = self.repo.find_nodes("Store")
            if stores:
                store_id = stores[0].get("id", "")
            else:
                return {"ok": False, "error": "No store found"}

        # Decompose the metric change
        analysis = self.analyze_metric_change(store_id, metric, "上周", "本周")

        if not analysis.get("ok"):
            return {"ok": False, "error": analysis.get("error", "Analysis failed")}

        # Generate human-readable answer
        factors = analysis.get("factors", [])
        top_factors = [f for f in factors if abs(f.get("contribution_pct", 0)) > 1]

        answer_parts: list[str] = []
        if top_factors:
            answer_parts.append(f"{metric}{'下降' if direction == 'decline' else '上升'}的主要原因：")
            for i, factor in enumerate(top_factors[:3], 1):
                answer_parts.append(
                    f"{i}. {factor['cn_name']}{factor['direction']}"
                    f"{abs(factor['change_pct']):.1f}%"
                    f"（贡献{abs(factor['contribution_pct']):.1f}%）"
                )

        answer = "\n".join(answer_parts) if answer_parts else "数据不足，无法确定原因"

        return {
            "ok": True,
            "question": question,
            "metric": metric,
            "direction": direction,
            "answer": answer,
            "analysis": analysis,
            "store_id": store_id,
            "answered_at": datetime.now().isoformat(),
        }

    def predict_trend(self, store_id: str, metric: str, days_ahead: int = 7) -> dict[str, Any]:
        """Predict metric trend for the next N days.

        Uses store properties and known patterns for simple forecasting.

        Args:
            store_id: Store node ID
            metric: Metric to predict
            days_ahead: Days to forecast

        Returns:
            Dict with daily predictions
        """
        store_result = self.repo.get_node("Store", store_id)
        if not store_result.get("ok"):
            return {"ok": False, "error": f"Store {store_id} not found"}

        store_props = store_result["node"]["properties"]

        current_value = store_props.get(f"{metric}_current", store_props.get(metric, 0))
        if not isinstance(current_value, (int, float)):
            current_value = 0

        change_rate = store_props.get(f"{metric}_change_rate", 0)
        if not isinstance(change_rate, (int, float)):
            # Derive from current vs previous
            previous = store_props.get(f"{metric}_previous", current_value)
            if isinstance(previous, (int, float)) and previous != 0:
                change_rate = (current_value - previous) / abs(previous)
            else:
                change_rate = 0

        predictions: list[dict[str, Any]] = []
        now = datetime.now()

        for day in range(1, days_ahead + 1):
            date = now + timedelta(days=day)
            # Simple linear extrapolation with dampening
            dampening = 0.95**day  # Predictions become less certain
            daily_change = change_rate * dampening / 7  # Weekly → daily

            predicted_value = current_value * (1 + daily_change * day)

            # Weekend boost for traffic/revenue
            if date.weekday() >= 5 and metric in ("revenue", "traffic"):
                predicted_value *= 1.15

            confidence = max(0.3, 0.9 - 0.08 * day)

            predictions.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "day_of_week": date.strftime("%A"),
                    "predicted_value": round(predicted_value, 4)
                    if isinstance(predicted_value, float)
                    else predicted_value,
                    "confidence": round(confidence, 2),
                    "is_weekend": date.weekday() >= 5,
                }
            )

        return {
            "ok": True,
            "store_id": store_id,
            "metric": metric,
            "current_value": current_value,
            "days_ahead": days_ahead,
            "predictions": predictions,
            "trend_direction": "上升" if change_rate > 0 else "下降" if change_rate < 0 else "平稳",
            "predicted_at": datetime.now().isoformat(),
        }

    # ─── Private Helpers ───

    def _get_factor_change(self, store_props: dict[str, Any], factor: str, metric: str) -> float:
        """Get the change percentage for a specific factor."""
        # Try direct property first
        change = store_props.get(f"{factor}_change_pct")
        if change is not None and isinstance(change, (int, float)):
            return float(change)

        # Derive from known store properties
        if factor == "traffic":
            return float(store_props.get("traffic_change_pct", 0))
        if factor == "food_cost":
            # Derive from margin change
            mc = store_props.get("margin_current", 0)
            mp = store_props.get("margin_previous", 0)
            if isinstance(mc, (int, float)) and isinstance(mp, (int, float)):
                return round((mp - mc) * 100, 2)  # Inverse: margin down = cost up
            return 0.0
        if factor == "discount_rate":
            return float(store_props.get("discount_rate", 0)) - 8.0  # vs 8% baseline
        if factor == "waste_rate":
            return float(store_props.get("waste_rate", 0)) - 4.0  # vs 4% baseline
        if factor == "avg_check":
            return float(store_props.get("avg_check_change_pct", 0))

        return 0.0

    def _get_factor_weight(self, metric: str, factor: str) -> float:
        """Get the weight of a factor for a metric from decomposition tree."""
        tree = METRIC_DECOMPOSITION.get(metric, [])
        for item in tree:
            if item["factor"] == factor:
                return item["weight"]
        return 0.1  # Default weight

    def _is_inverse_factor(self, metric: str, factor: str) -> bool:
        """Check if a factor has inverse relationship with metric."""
        tree = METRIC_DECOMPOSITION.get(metric, [])
        for item in tree:
            if item["factor"] == factor:
                return item.get("inverse", False)
        return False

    def _get_factor_cn_name(self, factor: str) -> str:
        """Get Chinese name for a factor."""
        name_map = {
            "traffic": "客流量",
            "avg_check": "客单价",
            "conversion_rate": "转化率",
            "cancellation_rate": "退单率",
            "channel_mix": "渠道结构",
            "food_cost": "食材成本",
            "discount_rate": "折扣率",
            "waste_rate": "损耗率",
            "labor_cost": "人工成本",
            "energy_cost": "能源成本",
            "weather": "天气",
            "competition": "竞争",
            "marketing": "营销活动",
            "seasonality": "季节性",
            "reputation": "口碑评价",
        }
        return name_map.get(factor, factor)

    def _parse_why_question(self, question: str) -> tuple[str, str]:
        """Parse a Chinese "why" question to extract metric and direction.

        Returns (metric, direction) tuple.
        """
        metric = ""
        direction = "decline"

        metric_keywords = {
            "营收": "revenue",
            "收入": "revenue",
            "营业额": "revenue",
            "毛利": "margin",
            "利润": "margin",
            "客流": "traffic",
            "客流量": "traffic",
            "成本": "margin",  # Cost questions map to margin analysis
            "食材": "margin",
        }

        for keyword, m in metric_keywords.items():
            if keyword in question:
                metric = m
                break

        if "下降" in question or "减少" in question or "降" in question or "少" in question:
            direction = "decline"
        elif "上升" in question or "增加" in question or "涨" in question or "多" in question:
            direction = "increase"

        return metric, direction

    def _explain_difference(
        self,
        best: dict[str, Any],
        worst: dict[str, Any],
        metric: str,
        stores_data: list[dict[str, Any]],
    ) -> str:
        """Generate explanation for why one store outperforms another."""
        best_name = best["store_name"]
        worst_name = worst["store_name"]

        # Find property differences
        best_props = {}
        worst_props = {}
        for s in stores_data:
            if s["store_id"] == best["store_id"]:
                best_props = s["properties"]
            if s["store_id"] == worst["store_id"]:
                worst_props = s["properties"]

        explanations: list[str] = []

        # Compare key factors
        factors_to_check = [
            ("waste_rate", "损耗率", True),
            ("discount_rate", "折扣率", True),
            ("traffic_change_pct", "客流变化", False),
            ("table_count", "桌台数", False),
        ]

        for prop, cn_name, lower_is_better in factors_to_check:
            best_val = best_props.get(prop, 0)
            worst_val = worst_props.get(prop, 0)
            if isinstance(best_val, (int, float)) and isinstance(worst_val, (int, float)):
                diff = best_val - worst_val
                if abs(diff) > 1:
                    if lower_is_better:
                        if best_val < worst_val:
                            explanations.append(f"{best_name}{cn_name}更低({best_val}% vs {worst_val}%)")
                    else:
                        if best_val > worst_val:
                            explanations.append(f"{best_name}{cn_name}更优({best_val} vs {worst_val})")

        if explanations:
            return f"{best_name}表现更优，原因: " + "; ".join(explanations)
        return f"{best_name}在{metric}指标上领先{worst_name}"

    def _calc_gap(self, val_a: Any, val_b: Any) -> float:
        """Calculate gap between two values."""
        if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
            if val_b != 0:
                return round((val_a - val_b) / abs(val_b) * 100, 2)
        return 0.0
