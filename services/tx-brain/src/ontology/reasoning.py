"""因果链推理 — 回答"为什么"类问题

"为什么上周酸菜鱼毛利下降了？" →
酸菜鱼毛利↓ ← 食材成本↑ ← 酸菜价格↑40% ← 供应商涨价 ← 季节性短缺

Uses the graph's CAUSES relationships to trace cause-effect chains,
and the BOM/pricing data to compute numeric evidence.
"""

from datetime import datetime
from typing import Any

import structlog

from .repository import OntologyRepository

logger = structlog.get_logger()


# ─── Known Causal Templates (industry knowledge) ───

CAUSAL_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "margin_decline": [
        {
            "pattern": "ingredient_price_up",
            "description": "食材价格上涨导致毛利下降",
            "check": "ingredient_cost_change",
            "confidence_base": 0.85,
        },
        {
            "pattern": "discount_excess",
            "description": "折扣过度导致毛利下降",
            "check": "discount_rate_change",
            "confidence_base": 0.75,
        },
        {
            "pattern": "waste_increase",
            "description": "食材损耗增加导致成本上升",
            "check": "waste_rate_change",
            "confidence_base": 0.70,
        },
        {
            "pattern": "portion_drift",
            "description": "出品分量偏差导致成本超标",
            "check": "portion_deviation",
            "confidence_base": 0.60,
        },
    ],
    "revenue_decline": [
        {
            "pattern": "traffic_decline",
            "description": "客流量下降导致营收下降",
            "check": "traffic_change",
            "confidence_base": 0.80,
        },
        {
            "pattern": "avg_check_decline",
            "description": "客单价下降导致营收下降",
            "check": "avg_check_change",
            "confidence_base": 0.75,
        },
        {
            "pattern": "competition_new",
            "description": "新竞争对手开业分流客源",
            "check": "competition_event",
            "confidence_base": 0.65,
        },
        {
            "pattern": "weather_impact",
            "description": "恶劣天气影响到店客流",
            "check": "weather_event",
            "confidence_base": 0.55,
        },
    ],
    "cost_spike": [
        {
            "pattern": "seasonal_shortage",
            "description": "季节性短缺导致食材涨价",
            "check": "seasonal_price_pattern",
            "confidence_base": 0.80,
        },
        {
            "pattern": "supplier_issue",
            "description": "供应商问题导致采购成本上升",
            "check": "supplier_price_change",
            "confidence_base": 0.75,
        },
        {
            "pattern": "logistics_cost",
            "description": "物流成本上升传导至食材价格",
            "check": "logistics_cost_change",
            "confidence_base": 0.60,
        },
    ],
}

# ─── Suggested Actions per Root Cause ───

ACTION_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "ingredient_price_up": [
        {"action": "negotiate_with_supplier", "description": "与供应商谈判议价或寻找替代供应商", "urgency": "high"},
        {"action": "adjust_bom", "description": "优化配方用量或寻找替代食材", "urgency": "medium"},
        {"action": "adjust_selling_price", "description": "适当上调菜品售价", "urgency": "low"},
    ],
    "discount_excess": [
        {"action": "review_discount_rules", "description": "审查折扣规则，收紧毛利底线", "urgency": "high"},
        {"action": "train_staff", "description": "培训员工正确使用折扣权限", "urgency": "medium"},
    ],
    "waste_increase": [
        {"action": "review_prep_process", "description": "审查备料流程，优化切配标准", "urgency": "high"},
        {"action": "adjust_order_quantity", "description": "根据销售预测调整采购量", "urgency": "medium"},
    ],
    "traffic_decline": [
        {"action": "marketing_campaign", "description": "发起营销活动吸引客流", "urgency": "high"},
        {"action": "review_customer_feedback", "description": "分析客户评价找出流失原因", "urgency": "medium"},
    ],
    "seasonal_shortage": [
        {"action": "pre_stock", "description": "提前储备即将涨价的食材", "urgency": "high"},
        {"action": "seasonal_menu", "description": "推出应季菜品替代高价食材菜品", "urgency": "medium"},
    ],
    "supplier_issue": [
        {"action": "diversify_suppliers", "description": "增加备选供应商分散风险", "urgency": "high"},
        {"action": "long_term_contract", "description": "与可靠供应商签订长期合同锁价", "urgency": "medium"},
    ],
}


class CausalReasoningEngine:
    """因果链推理 — 回答"为什么"类问题

    Uses graph CAUSES relationships + industry causal templates
    to build evidence-backed causal chains.
    """

    def __init__(self, repository: OntologyRepository) -> None:
        self.repo = repository
        logger.info("causal_reasoning_engine_init")

    def trace_cause(
        self,
        entity_type: str,
        entity_id: str,
        metric: str,
        direction: str = "decline",
    ) -> list[dict[str, Any]]:
        """Trace the causal chain for a metric change.

        Args:
            entity_type: e.g., "Dish", "Store"
            entity_id: Node ID
            metric: e.g., "margin", "revenue", "cost"
            direction: "decline" or "increase"

        Returns:
            List of causal links: [{cause, evidence, confidence, depth}]
        """
        # Map metric+direction to template category
        category = self._classify_metric_direction(metric, direction)
        templates = CAUSAL_TEMPLATES.get(category, [])

        if not templates:
            return []

        # Get entity and its neighborhood for evidence
        entity_result = self.repo.get_node(entity_type, entity_id)
        if not entity_result.get("ok"):
            return []

        entity_props = entity_result["node"]["properties"]

        # Also check graph CAUSES relationships
        graph_causes = self.repo.get_relationships(
            entity_type, entity_id, rel_type="CAUSES", direction="in"
        )

        # Build causal chain from templates + graph evidence
        chain: list[dict[str, Any]] = []
        depth = 0

        for template in templates:
            evidence = self._check_evidence(template, entity_props, entity_type, entity_id)
            if evidence["has_evidence"]:
                depth += 1
                chain.append({
                    "cause": template["description"],
                    "pattern": template["pattern"],
                    "evidence": evidence["detail"],
                    "confidence": template["confidence_base"] * evidence["strength"],
                    "depth": depth,
                    "data": evidence.get("data", {}),
                })

        # Add graph-based causes
        for rel_data in graph_causes:
            from_id = rel_data.get("from_node_id", "")
            from_node = self.repo.get_node_model(from_id)
            if from_node is not None:
                depth += 1
                chain.append({
                    "cause": from_node.properties.get("description", f"Event {from_id}"),
                    "pattern": "graph_cause",
                    "evidence": rel_data.get("properties", {}).get("evidence", "Graph relationship"),
                    "confidence": float(rel_data.get("properties", {}).get("confidence", 0.5)),
                    "depth": depth,
                    "data": from_node.properties,
                })

        # Sort by confidence descending
        chain.sort(key=lambda x: x["confidence"], reverse=True)
        return chain

    def find_root_cause(
        self,
        store_id: str,
        metric: str,
        period: str = "last_week",
    ) -> dict[str, Any]:
        """Find the top root causes for a metric change at a store.

        Args:
            store_id: Store node ID
            metric: Metric name (margin, revenue, cost, traffic)
            period: Time period ("last_week", "last_month")

        Returns:
            Dict with root_causes list sorted by confidence
        """
        store_result = self.repo.get_node("Store", store_id)
        if not store_result.get("ok"):
            return {"ok": False, "error": f"Store {store_id} not found"}

        store_props = store_result["node"]["properties"]

        # Determine direction from store metrics
        direction = self._infer_direction(store_props, metric, period)

        # Get all dishes served by this store
        dish_rels = self.repo.get_relationships(
            "Store", store_id, rel_type="SERVES", direction="out"
        )

        # Trace causes for the store-level metric
        store_causes = self.trace_cause("Store", store_id, metric, direction)

        # Also trace per-dish causes for top dishes
        dish_causes: list[dict[str, Any]] = []
        for dish_rel in dish_rels[:5]:  # Top 5 dishes
            dish_id = dish_rel.get("to_node_id", "")
            if dish_id:
                causes = self.trace_cause("Dish", dish_id, metric, direction)
                for cause in causes:
                    cause["dish_id"] = dish_id
                    dish_causes.append(cause)

        # Merge and deduplicate
        all_causes = store_causes + dish_causes
        seen_patterns: set[str] = set()
        unique_causes: list[dict[str, Any]] = []
        for cause in sorted(all_causes, key=lambda x: x["confidence"], reverse=True):
            pattern = cause.get("pattern", "")
            if pattern not in seen_patterns:
                seen_patterns.add(pattern)
                unique_causes.append(cause)

        return {
            "ok": True,
            "store_id": store_id,
            "metric": metric,
            "direction": direction,
            "period": period,
            "root_causes": unique_causes[:10],
            "analyzed_at": datetime.now().isoformat(),
        }

    def predict_impact(
        self,
        cause_event: dict[str, Any],
        affected_entities: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Predict the impact of a cause event on affected entities.

        Example: If ingredient price goes up 20%, what's the margin impact
        on each dish using that ingredient?

        Args:
            cause_event: {type, entity_id, change_pct, ...}
            affected_entities: [{entity_type, entity_id}, ...]

        Returns:
            Dict with impacts per entity
        """
        event_type = cause_event.get("type", "")
        change_pct = cause_event.get("change_pct", 0.0)
        source_id = cause_event.get("entity_id", "")

        impacts: list[dict[str, Any]] = []

        for entity in affected_entities:
            entity_type = entity.get("entity_type", "")
            entity_id = entity.get("entity_id", "")
            entity_result = self.repo.get_node(entity_type, entity_id)

            if not entity_result.get("ok"):
                continue

            props = entity_result["node"]["properties"]

            if event_type == "ingredient_price_change":
                # Find BOM link from dish to ingredient
                rels = self.repo.get_relationships(
                    entity_type, entity_id, rel_type="USES_INGREDIENT", direction="out"
                )
                for rel in rels:
                    if rel.get("to_node_id") == source_id:
                        quantity_g = rel.get("properties", {}).get("quantity_g", 0)
                        current_price_fen = props.get("price_fen", 0)
                        # Approximate cost impact
                        ingredient_node = self.repo.get_node("Ingredient", source_id)
                        if ingredient_node.get("ok"):
                            old_unit_price = ingredient_node["node"]["properties"].get("price_per_kg_fen", 0)
                            cost_change_fen = int(quantity_g / 1000.0 * old_unit_price * change_pct / 100.0)
                            new_margin = 0.0
                            if current_price_fen > 0:
                                old_cost = props.get("total_cost_fen", 0)
                                new_cost = old_cost + cost_change_fen
                                new_margin = (current_price_fen - new_cost) / current_price_fen

                            impacts.append({
                                "entity_type": entity_type,
                                "entity_id": entity_id,
                                "entity_name": props.get("name", ""),
                                "cost_change_fen": cost_change_fen,
                                "old_margin": props.get("margin_rate", 0.0),
                                "new_margin": round(new_margin, 4),
                                "severity": "high" if abs(cost_change_fen) > 500 else "medium",
                            })
                        break
            else:
                # Generic impact estimation
                impacts.append({
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "entity_name": props.get("name", ""),
                    "estimated_impact_pct": change_pct * 0.5,
                    "severity": "medium",
                })

        return {
            "ok": True,
            "cause_event": cause_event,
            "impacts": impacts,
            "total_affected": len(impacts),
            "analyzed_at": datetime.now().isoformat(),
        }

    def suggest_actions(self, root_cause: dict[str, Any]) -> list[dict[str, Any]]:
        """Suggest mitigation actions based on a root cause.

        Args:
            root_cause: A cause dict from trace_cause/find_root_cause

        Returns:
            List of suggested actions with urgency levels
        """
        pattern = root_cause.get("pattern", "")
        actions = ACTION_TEMPLATES.get(pattern, [])

        if not actions:
            # Generic fallback
            return [
                {
                    "action": "investigate_further",
                    "description": f"深入调查: {root_cause.get('cause', '未知原因')}",
                    "urgency": "medium",
                    "confidence": root_cause.get("confidence", 0.5),
                }
            ]

        # Augment with confidence from root cause
        result = []
        for action in actions:
            result.append({
                **action,
                "based_on": root_cause.get("cause", ""),
                "cause_confidence": root_cause.get("confidence", 0.0),
            })
        return result

    def get_causal_graph(
        self, entity_type: str, entity_id: str, depth: int = 3
    ) -> dict[str, Any]:
        """Get the full causal neighborhood for visualization.

        Returns a subgraph centered on the entity, including all
        CAUSES relationships within the specified depth.

        Args:
            entity_type: Node label
            entity_id: Node ID
            depth: Max traversal depth

        Returns:
            Dict with nodes and edges for visualization
        """
        neighbors = self.repo.query_neighbors(entity_type, entity_id, depth=depth)

        # Filter to only causal relationships
        causal_edges = []
        causal_node_ids: set[str] = {entity_id}

        for rel in neighbors.get("relationships", []):
            if rel.get("rel_type") == "CAUSES":
                causal_edges.append(rel)
                causal_node_ids.add(rel.get("from_node_id", ""))
                causal_node_ids.add(rel.get("to_node_id", ""))

        # Also include USES_INGREDIENT for cost causality
        for rel in neighbors.get("relationships", []):
            if rel.get("rel_type") == "USES_INGREDIENT":
                causal_edges.append(rel)
                causal_node_ids.add(rel.get("to_node_id", ""))

        causal_nodes = [
            n for n in neighbors.get("neighbors", [])
            if n.get("id", "") in causal_node_ids
        ]

        # Include center node
        center = neighbors.get("center_node", {})
        if center:
            causal_nodes.insert(0, center)

        return {
            "ok": True,
            "center": {"entity_type": entity_type, "entity_id": entity_id},
            "nodes": causal_nodes,
            "edges": causal_edges,
            "depth": depth,
            "node_count": len(causal_nodes),
            "edge_count": len(causal_edges),
        }

    # ─── Private Helpers ───

    def _classify_metric_direction(self, metric: str, direction: str) -> str:
        """Map metric+direction to a causal template category."""
        if metric in ("margin", "profit_margin", "毛利率") and direction == "decline":
            return "margin_decline"
        if metric in ("revenue", "sales", "营业额") and direction == "decline":
            return "revenue_decline"
        if metric in ("cost", "food_cost", "成本") and direction == "increase":
            return "cost_spike"
        if metric in ("margin", "profit_margin") and direction == "increase":
            return "margin_decline"  # Same analysis, opposite direction
        return "margin_decline"  # Default

    def _infer_direction(
        self, store_props: dict[str, Any], metric: str, period: str
    ) -> str:
        """Infer whether metric is declining or increasing."""
        current = store_props.get(f"{metric}_current", 0)
        previous = store_props.get(f"{metric}_previous", 0)
        if current < previous:
            return "decline"
        return "increase"

    def _check_evidence(
        self,
        template: dict[str, Any],
        entity_props: dict[str, Any],
        entity_type: str,
        entity_id: str,
    ) -> dict[str, Any]:
        """Check if there's evidence for a causal template.

        Returns dict with has_evidence, strength (0-1), detail string.
        """
        check_type = template.get("check", "")

        if check_type == "ingredient_cost_change":
            # Check BOM ingredients for price changes
            rels = self.repo.get_relationships(
                entity_type, entity_id, rel_type="USES_INGREDIENT", direction="out"
            )
            for rel in rels:
                ing_id = rel.get("to_node_id", "")
                ing_node = self.repo.get_node_model(ing_id)
                if ing_node is not None:
                    price_change = ing_node.properties.get("price_change_pct", 0)
                    if abs(price_change) > 5:
                        return {
                            "has_evidence": True,
                            "strength": min(abs(price_change) / 50.0, 1.0),
                            "detail": f"{ing_node.properties.get('name', '食材')}价格变动{price_change:+.1f}%",
                            "data": {
                                "ingredient": ing_node.properties.get("name", ""),
                                "price_change_pct": price_change,
                            },
                        }
            return {"has_evidence": False, "strength": 0.0, "detail": ""}

        if check_type == "discount_rate_change":
            discount_rate = entity_props.get("discount_rate", 0)
            if discount_rate > 10:
                return {
                    "has_evidence": True,
                    "strength": min(discount_rate / 30.0, 1.0),
                    "detail": f"折扣率达{discount_rate:.1f}%，高于正常水平",
                    "data": {"discount_rate": discount_rate},
                }
            return {"has_evidence": False, "strength": 0.0, "detail": ""}

        if check_type == "waste_rate_change":
            waste_rate = entity_props.get("waste_rate", 0)
            if waste_rate > 5:
                return {
                    "has_evidence": True,
                    "strength": min(waste_rate / 15.0, 1.0),
                    "detail": f"损耗率{waste_rate:.1f}%，超出标准",
                    "data": {"waste_rate": waste_rate},
                }
            return {"has_evidence": False, "strength": 0.0, "detail": ""}

        if check_type == "traffic_change":
            traffic_change = entity_props.get("traffic_change_pct", 0)
            if traffic_change < -3:
                return {
                    "has_evidence": True,
                    "strength": min(abs(traffic_change) / 20.0, 1.0),
                    "detail": f"客流量下降{abs(traffic_change):.1f}%",
                    "data": {"traffic_change_pct": traffic_change},
                }
            return {"has_evidence": False, "strength": 0.0, "detail": ""}

        if check_type == "seasonal_price_pattern":
            # Check if any ingredient has seasonal flag
            rels = self.repo.get_relationships(
                entity_type, entity_id, rel_type="USES_INGREDIENT", direction="out"
            )
            for rel in rels:
                ing_id = rel.get("to_node_id", "")
                ing_node = self.repo.get_node_model(ing_id)
                if ing_node and ing_node.properties.get("seasonal", False):
                    return {
                        "has_evidence": True,
                        "strength": 0.8,
                        "detail": f"{ing_node.properties.get('name', '')}为季节性食材，当前处于涨价期",
                        "data": {"ingredient": ing_node.properties.get("name", ""), "seasonal": True},
                    }
            return {"has_evidence": False, "strength": 0.0, "detail": ""}

        if check_type == "supplier_price_change":
            # Check suppliers via ingredient→supplier chain
            rels = self.repo.get_relationships(
                entity_type, entity_id, rel_type="USES_INGREDIENT", direction="out"
            )
            for rel in rels:
                ing_id = rel.get("to_node_id", "")
                supplier_rels = self.repo.get_relationships(
                    "Ingredient", ing_id, rel_type="SUPPLIED_BY", direction="out"
                )
                for srel in supplier_rels:
                    supplier_id = srel.get("to_node_id", "")
                    supplier = self.repo.get_node_model(supplier_id)
                    if supplier and supplier.properties.get("price_increased", False):
                        return {
                            "has_evidence": True,
                            "strength": 0.75,
                            "detail": f"供应商{supplier.properties.get('name', '')}近期涨价",
                            "data": {"supplier": supplier.properties.get("name", "")},
                        }
            return {"has_evidence": False, "strength": 0.0, "detail": ""}

        # Default: no evidence for unknown checks
        return {"has_evidence": False, "strength": 0.0, "detail": ""}
