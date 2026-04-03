"""真实成本计算 — BOM层层展开+实时食材价

不是简单的"菜品售价-采购价"，而是：
菜品→BOM配方→每种食材×用量×实时价格→加工损耗→真实成本

V1迁入（560行核心逻辑），在V3架构上重建。
"""

from datetime import datetime, timedelta
from typing import Any, Optional

import structlog

from ..ontology.models import BOMEntry, DishCostBreakdown
from ..ontology.repository import OntologyRepository

logger = structlog.get_logger()

# ─── Processing Cost Constants ───

# 加工费用（分/菜）- 按菜品类型
PROCESSING_COST_MAP: dict[str, int] = {
    "招牌热菜": 300,   # 3元加工费
    "凉菜": 100,       # 1元
    "汤品": 200,       # 2元
    "主食": 150,       # 1.5元
    "default": 200,    # 2元默认
}

# 能源成本分摊（分/菜）
ENERGY_COST_PER_DISH_FEN = 80  # 0.8元

# 损耗系数默认值
DEFAULT_YIELD_RATE = 0.85  # 15% loss if not specified


class CostTruthEngine:
    """真实成本计算引擎

    BOM expansion → real-time ingredient pricing → yield adjustment → true cost.
    All monetary values in fen (分) to avoid floating-point issues.
    """

    def __init__(self, repository: OntologyRepository) -> None:
        self.repo = repository
        # Cache for ingredient prices (refreshed on demand)
        self._price_cache: dict[str, int] = {}
        self._price_cache_time: Optional[datetime] = None
        self._cost_history: dict[str, list[dict[str, Any]]] = {}
        logger.info("cost_truth_engine_init")

    def calculate_dish_cost(self, dish_id: str) -> dict[str, Any]:
        """Calculate the true cost of a dish via BOM expansion.

        Process:
        1. Get dish → BOM ingredients (USES_INGREDIENT relationships)
        2. For each ingredient: quantity_g × price_per_kg ÷ yield_rate
        3. Add processing cost + energy cost
        4. Compare to selling price → margin rate

        Args:
            dish_id: Dish node ID

        Returns:
            DishCostBreakdown as dict
        """
        dish_result = self.repo.get_node("Dish", dish_id)
        if not dish_result.get("ok"):
            return {"ok": False, "error": f"Dish {dish_id} not found"}

        dish_props = dish_result["node"]["properties"]
        dish_name = dish_props.get("name", "")
        selling_price_fen = dish_props.get("price_fen", 0)

        # Get BOM entries via USES_INGREDIENT relationships
        bom_rels = self.repo.get_relationships(
            "Dish", dish_id, rel_type="USES_INGREDIENT", direction="out"
        )

        bom_entries: list[BOMEntry] = []
        total_material_cost_fen = 0

        for rel in bom_rels:
            ing_id = rel.get("to_node_id", "")
            rel_props = rel.get("properties", {})
            quantity_g = rel_props.get("quantity_g", 0.0)
            yield_rate = rel_props.get("yield_rate", DEFAULT_YIELD_RATE)

            # Get ingredient price
            ing_node = self.repo.get_node("Ingredient", ing_id)
            if not ing_node.get("ok"):
                continue

            ing_props = ing_node["node"]["properties"]
            ing_name = ing_props.get("name", "")
            price_per_kg_fen = ing_props.get("price_per_kg_fen", 0)

            # True cost: (quantity / yield_rate) × price_per_kg
            # quantity_g / 1000 = kg, then × price_per_kg_fen
            effective_quantity_g = quantity_g / yield_rate if yield_rate > 0 else quantity_g
            cost_fen = int(effective_quantity_g / 1000.0 * price_per_kg_fen)

            unit_price_fen = int(price_per_kg_fen / 1000.0 * quantity_g)  # Before yield

            entry = BOMEntry(
                ingredient_id=ing_id,
                ingredient_name=ing_name,
                quantity_g=quantity_g,
                unit=ing_props.get("unit", "g"),
                unit_price_fen=unit_price_fen,
                cost_fen=cost_fen,
                yield_rate=yield_rate,
            )
            bom_entries.append(entry)
            total_material_cost_fen += cost_fen

        # Processing cost based on category
        category_name = self._get_dish_category(dish_id)
        processing_cost_fen = PROCESSING_COST_MAP.get(
            category_name, PROCESSING_COST_MAP["default"]
        )

        # Total cost
        total_cost_fen = total_material_cost_fen + processing_cost_fen + ENERGY_COST_PER_DISH_FEN

        # Margin rate
        margin_rate = 0.0
        if selling_price_fen > 0:
            margin_rate = (selling_price_fen - total_cost_fen) / selling_price_fen

        breakdown = DishCostBreakdown(
            dish_id=dish_id,
            dish_name=dish_name,
            selling_price_fen=selling_price_fen,
            bom_entries=bom_entries,
            total_material_cost_fen=total_material_cost_fen,
            processing_cost_fen=processing_cost_fen,
            total_cost_fen=total_cost_fen,
            margin_rate=round(margin_rate, 4),
            calculated_at=datetime.now(),
        )

        # Record in history
        self._record_cost(dish_id, total_cost_fen, margin_rate)

        logger.info(
            "dish_cost_calculated",
            dish_id=dish_id,
            dish_name=dish_name,
            total_cost_fen=total_cost_fen,
            margin_rate=round(margin_rate, 4),
        )

        result = breakdown.model_dump()
        result["ok"] = True
        result["vs_selling_price"] = {
            "selling_price_fen": selling_price_fen,
            "total_cost_fen": total_cost_fen,
            "profit_fen": selling_price_fen - total_cost_fen,
            "margin_rate": round(margin_rate, 4),
        }
        return result

    def calculate_order_cost(self, order_id: str) -> dict[str, Any]:
        """Calculate the total true cost for an order.

        Sums dish costs × quantity for all items in the order.

        Args:
            order_id: Order node ID

        Returns:
            Dict with order cost breakdown
        """
        order_result = self.repo.get_node("Order", order_id)
        if not order_result.get("ok"):
            return {"ok": False, "error": f"Order {order_id} not found"}

        order_props = order_result["node"]["properties"]
        order_total_fen = order_props.get("total_fen", 0)

        # Get order items via CONTAINS relationships
        item_rels = self.repo.get_relationships(
            "Order", order_id, rel_type="CONTAINS", direction="out"
        )

        items: list[dict[str, Any]] = []
        total_cost_fen = 0

        for rel in item_rels:
            dish_id = rel.get("to_node_id", "")
            rel_props = rel.get("properties", {})
            quantity = rel_props.get("quantity", 1)

            dish_cost = self.calculate_dish_cost(dish_id)
            if dish_cost.get("ok"):
                item_cost = dish_cost["total_cost_fen"] * quantity
                total_cost_fen += item_cost
                items.append({
                    "dish_id": dish_id,
                    "dish_name": dish_cost.get("dish_name", ""),
                    "quantity": quantity,
                    "unit_cost_fen": dish_cost["total_cost_fen"],
                    "total_cost_fen": item_cost,
                    "margin_rate": dish_cost.get("margin_rate", 0.0),
                })

        order_margin = 0.0
        if order_total_fen > 0:
            order_margin = (order_total_fen - total_cost_fen) / order_total_fen

        return {
            "ok": True,
            "order_id": order_id,
            "order_total_fen": order_total_fen,
            "total_cost_fen": total_cost_fen,
            "profit_fen": order_total_fen - total_cost_fen,
            "margin_rate": round(order_margin, 4),
            "items": items,
            "calculated_at": datetime.now().isoformat(),
        }

    def calculate_store_daily_cost(
        self, store_id: str, date: str
    ) -> dict[str, Any]:
        """Calculate daily cost for a store.

        Aggregates all order costs + waste + overhead allocation.

        Args:
            store_id: Store node ID
            date: Date string (YYYY-MM-DD)

        Returns:
            Dict with daily cost breakdown
        """
        store_result = self.repo.get_node("Store", store_id)
        if not store_result.get("ok"):
            return {"ok": False, "error": f"Store {store_id} not found"}

        store_props = store_result["node"]["properties"]

        # Get all dishes served and estimate daily cost
        dish_rels = self.repo.get_relationships(
            "Store", store_id, rel_type="SERVES", direction="out"
        )

        dish_costs: list[dict[str, Any]] = []
        total_food_cost_fen = 0

        for rel in dish_rels:
            dish_id = rel.get("to_node_id", "")
            dish_cost = self.calculate_dish_cost(dish_id)
            if dish_cost.get("ok"):
                daily_sales = dish_cost.get("bom_entries", [])
                dish_node = self.repo.get_node("Dish", dish_id)
                avg_daily = 0
                if dish_node.get("ok"):
                    avg_daily = dish_node["node"]["properties"].get("daily_sales_avg", 0)

                daily_cost = dish_cost["total_cost_fen"] * avg_daily
                total_food_cost_fen += daily_cost
                dish_costs.append({
                    "dish_id": dish_id,
                    "dish_name": dish_cost.get("dish_name", ""),
                    "daily_sales": avg_daily,
                    "unit_cost_fen": dish_cost["total_cost_fen"],
                    "daily_cost_fen": daily_cost,
                })

        # Waste cost (based on store waste_rate)
        waste_rate = store_props.get("waste_rate", 5.0) / 100.0
        waste_cost_fen = int(total_food_cost_fen * waste_rate)

        # Overhead allocation (rent, utilities, etc.) — approximate
        daily_revenue = store_props.get("daily_revenue_avg_fen", 0)
        overhead_rate = 0.15  # 15% overhead
        overhead_cost_fen = int(daily_revenue * overhead_rate)

        total_daily_cost = total_food_cost_fen + waste_cost_fen + overhead_cost_fen

        daily_margin = 0.0
        if daily_revenue > 0:
            daily_margin = (daily_revenue - total_daily_cost) / daily_revenue

        return {
            "ok": True,
            "store_id": store_id,
            "store_name": store_props.get("name", ""),
            "date": date,
            "food_cost_fen": total_food_cost_fen,
            "waste_cost_fen": waste_cost_fen,
            "overhead_cost_fen": overhead_cost_fen,
            "total_daily_cost_fen": total_daily_cost,
            "daily_revenue_fen": daily_revenue,
            "daily_profit_fen": daily_revenue - total_daily_cost,
            "daily_margin_rate": round(daily_margin, 4),
            "dish_costs": sorted(dish_costs, key=lambda x: x["daily_cost_fen"], reverse=True),
            "calculated_at": datetime.now().isoformat(),
        }

    def get_cost_trend(
        self, dish_id: str, days: int = 30
    ) -> list[dict[str, Any]]:
        """Get daily cost fluctuation for a dish over time.

        In dev mode, simulates trend based on ingredient price changes.
        In prod, would query historical cost calculations.

        Args:
            dish_id: Dish node ID
            days: Number of days to look back

        Returns:
            List of {date, total_cost_fen, margin_rate, drivers}
        """
        current_cost = self.calculate_dish_cost(dish_id)
        if not current_cost.get("ok"):
            return []

        base_cost = current_cost["total_cost_fen"]
        selling_price = current_cost["selling_price_fen"]

        # Simulate trend by applying historical price changes
        trend: list[dict[str, Any]] = []
        now = datetime.now()

        for day_offset in range(days, 0, -1):
            date = now - timedelta(days=day_offset)
            # Simulate gradual price changes (linear interpolation)
            progress = 1.0 - (day_offset / days)

            # Calculate cost with partial price change
            day_cost_fen = self._simulate_historical_cost(
                dish_id, base_cost, progress
            )

            margin = 0.0
            if selling_price > 0:
                margin = (selling_price - day_cost_fen) / selling_price

            trend.append({
                "date": date.strftime("%Y-%m-%d"),
                "total_cost_fen": day_cost_fen,
                "margin_rate": round(margin, 4),
                "cost_change_pct": round(
                    (day_cost_fen - base_cost) / base_cost * 100 if base_cost > 0 else 0, 2
                ),
            })

        # Add today
        margin_today = 0.0
        if selling_price > 0:
            margin_today = (selling_price - base_cost) / selling_price
        trend.append({
            "date": now.strftime("%Y-%m-%d"),
            "total_cost_fen": base_cost,
            "margin_rate": round(margin_today, 4),
            "cost_change_pct": 0.0,
        })

        return trend

    def detect_cost_anomaly(
        self, store_id: str, date: str
    ) -> list[dict[str, Any]]:
        """Detect cost anomalies for a store on a given date.

        Flags:
        - Cost spike: ingredient cost significantly above average
        - Unusual consumption: usage higher than BOM standard
        - BOM deviation: actual cost deviates from expected BOM cost

        Args:
            store_id: Store node ID
            date: Date string

        Returns:
            List of anomaly dicts
        """
        anomalies: list[dict[str, Any]] = []

        # Get all dishes for this store
        dish_rels = self.repo.get_relationships(
            "Store", store_id, rel_type="SERVES", direction="out"
        )

        for rel in dish_rels:
            dish_id = rel.get("to_node_id", "")
            dish_cost = self.calculate_dish_cost(dish_id)
            if not dish_cost.get("ok"):
                continue

            # Check each ingredient for price anomaly
            for entry in dish_cost.get("bom_entries", []):
                ing_id = entry.get("ingredient_id", "")
                if not ing_id:
                    continue

                ing_node = self.repo.get_node("Ingredient", ing_id)
                if not ing_node.get("ok"):
                    continue

                price_change = ing_node["node"]["properties"].get("price_change_pct", 0)

                # Anomaly: price change > 15%
                if abs(price_change) > 15:
                    anomalies.append({
                        "type": "cost_spike",
                        "severity": "high" if abs(price_change) > 30 else "medium",
                        "dish_id": dish_id,
                        "dish_name": dish_cost.get("dish_name", ""),
                        "ingredient_id": ing_id,
                        "ingredient_name": entry.get("ingredient_name", ""),
                        "price_change_pct": price_change,
                        "cost_impact_fen": entry.get("cost_fen", 0),
                        "description": (
                            f"{entry.get('ingredient_name', '')}价格变动"
                            f"{price_change:+.1f}%，影响{dish_cost.get('dish_name', '')}成本"
                        ),
                        "date": date,
                    })

            # Check margin anomaly
            margin = dish_cost.get("margin_rate", 0)
            if margin < 0.4:
                anomalies.append({
                    "type": "low_margin",
                    "severity": "high" if margin < 0.3 else "medium",
                    "dish_id": dish_id,
                    "dish_name": dish_cost.get("dish_name", ""),
                    "margin_rate": margin,
                    "description": (
                        f"{dish_cost.get('dish_name', '')}毛利率仅{margin:.1%}，低于40%警戒线"
                    ),
                    "date": date,
                })

        # Sort by severity
        severity_order = {"high": 0, "medium": 1, "low": 2}
        anomalies.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 2))

        return anomalies

    def simulate_price_change(
        self, ingredient_id: str, new_price_fen: int
    ) -> dict[str, Any]:
        """Simulate the impact of an ingredient price change.

        Answers: "If this ingredient price changes, which dishes are affected
        and by how much?"

        Args:
            ingredient_id: Ingredient node ID
            new_price_fen: New price per kg in fen

        Returns:
            Dict with affected dishes and their new costs/margins
        """
        ing_result = self.repo.get_node("Ingredient", ingredient_id)
        if not ing_result.get("ok"):
            return {"ok": False, "error": f"Ingredient {ingredient_id} not found"}

        ing_props = ing_result["node"]["properties"]
        ing_name = ing_props.get("name", "")
        old_price_fen = ing_props.get("price_per_kg_fen", 0)
        price_change_pct = 0.0
        if old_price_fen > 0:
            price_change_pct = (new_price_fen - old_price_fen) / old_price_fen * 100

        # Find all dishes using this ingredient
        # We need to look at incoming USES_INGREDIENT relationships
        ing_rels = self.repo.get_relationships(
            "Ingredient", ingredient_id, rel_type="USES_INGREDIENT", direction="in"
        )

        affected_dishes: list[dict[str, Any]] = []

        for rel in ing_rels:
            dish_id = rel.get("from_node_id", "")
            rel_props = rel.get("properties", {})
            quantity_g = rel_props.get("quantity_g", 0)
            yield_rate = rel_props.get("yield_rate", DEFAULT_YIELD_RATE)

            dish_node = self.repo.get_node("Dish", dish_id)
            if not dish_node.get("ok"):
                continue

            dish_props = dish_node["node"]["properties"]
            selling_price = dish_props.get("price_fen", 0)

            # Calculate old cost for this ingredient in this dish
            effective_qty = quantity_g / yield_rate if yield_rate > 0 else quantity_g
            old_ing_cost = int(effective_qty / 1000.0 * old_price_fen)
            new_ing_cost = int(effective_qty / 1000.0 * new_price_fen)
            cost_diff = new_ing_cost - old_ing_cost

            # Get current total cost and recalculate
            old_total = dish_props.get("total_cost_fen", 0)
            # If no stored total, calculate it
            if old_total == 0:
                cost_result = self.calculate_dish_cost(dish_id)
                if cost_result.get("ok"):
                    old_total = cost_result["total_cost_fen"]

            new_total = old_total + cost_diff

            old_margin = (selling_price - old_total) / selling_price if selling_price > 0 else 0
            new_margin = (selling_price - new_total) / selling_price if selling_price > 0 else 0

            affected_dishes.append({
                "dish_id": dish_id,
                "dish_name": dish_props.get("name", ""),
                "selling_price_fen": selling_price,
                "old_cost_fen": old_total,
                "new_cost_fen": new_total,
                "cost_change_fen": cost_diff,
                "old_margin": round(old_margin, 4),
                "new_margin": round(new_margin, 4),
                "margin_change": round(new_margin - old_margin, 4),
                "quantity_g": quantity_g,
                "severity": "high" if abs(new_margin - old_margin) > 0.05 else "medium",
            })

        # Sort by cost impact
        affected_dishes.sort(key=lambda x: abs(x["cost_change_fen"]), reverse=True)

        return {
            "ok": True,
            "ingredient_id": ingredient_id,
            "ingredient_name": ing_name,
            "old_price_per_kg_fen": old_price_fen,
            "new_price_per_kg_fen": new_price_fen,
            "price_change_pct": round(price_change_pct, 2),
            "affected_dishes": affected_dishes,
            "total_affected": len(affected_dishes),
            "simulated_at": datetime.now().isoformat(),
        }

    def get_top_cost_drivers(
        self, store_id: str, date_range: Optional[dict[str, str]] = None, top_n: int = 10
    ) -> list[dict[str, Any]]:
        """Find the top ingredients driving cost for a store.

        Args:
            store_id: Store node ID
            date_range: Optional {start, end} date range
            top_n: Number of top drivers to return

        Returns:
            List of top cost drivers sorted by total cost contribution
        """
        # Get all dishes served by this store
        dish_rels = self.repo.get_relationships(
            "Store", store_id, rel_type="SERVES", direction="out"
        )

        # Aggregate ingredient costs across all dishes
        ingredient_totals: dict[str, dict[str, Any]] = {}

        for rel in dish_rels:
            dish_id = rel.get("to_node_id", "")
            dish_node = self.repo.get_node("Dish", dish_id)
            if not dish_node.get("ok"):
                continue

            dish_props = dish_node["node"]["properties"]
            daily_sales = dish_props.get("daily_sales_avg", 0)

            # Get BOM
            bom_rels = self.repo.get_relationships(
                "Dish", dish_id, rel_type="USES_INGREDIENT", direction="out"
            )

            for bom_rel in bom_rels:
                ing_id = bom_rel.get("to_node_id", "")
                bom_props = bom_rel.get("properties", {})
                quantity_g = bom_props.get("quantity_g", 0)
                yield_rate = bom_props.get("yield_rate", DEFAULT_YIELD_RATE)

                ing_node = self.repo.get_node("Ingredient", ing_id)
                if not ing_node.get("ok"):
                    continue

                ing_props = ing_node["node"]["properties"]
                price_per_kg_fen = ing_props.get("price_per_kg_fen", 0)
                effective_qty = quantity_g / yield_rate if yield_rate > 0 else quantity_g
                unit_cost = int(effective_qty / 1000.0 * price_per_kg_fen)
                daily_cost = unit_cost * daily_sales

                if ing_id not in ingredient_totals:
                    ingredient_totals[ing_id] = {
                        "ingredient_id": ing_id,
                        "ingredient_name": ing_props.get("name", ""),
                        "price_per_kg_fen": price_per_kg_fen,
                        "price_change_pct": ing_props.get("price_change_pct", 0),
                        "daily_cost_fen": 0,
                        "used_in_dishes": [],
                    }

                ingredient_totals[ing_id]["daily_cost_fen"] += daily_cost
                ingredient_totals[ing_id]["used_in_dishes"].append({
                    "dish_id": dish_id,
                    "dish_name": dish_props.get("name", ""),
                    "quantity_g": quantity_g,
                    "daily_sales": daily_sales,
                })

        # Sort by daily cost and return top N
        drivers = sorted(
            ingredient_totals.values(),
            key=lambda x: x["daily_cost_fen"],
            reverse=True,
        )[:top_n]

        # Add rank and percentage
        total_daily = sum(d["daily_cost_fen"] for d in drivers)
        for i, driver in enumerate(drivers):
            driver["rank"] = i + 1
            driver["cost_share_pct"] = round(
                driver["daily_cost_fen"] / total_daily * 100 if total_daily > 0 else 0, 2
            )

        return drivers

    # ─── Private Helpers ───

    def _get_dish_category(self, dish_id: str) -> str:
        """Get the category name for a dish."""
        cat_rels = self.repo.get_relationships(
            "Dish", dish_id, rel_type="BELONGS_TO", direction="out"
        )
        for rel in cat_rels:
            cat_id = rel.get("to_node_id", "")
            cat_node = self.repo.get_node("Category", cat_id)
            if cat_node.get("ok"):
                return cat_node["node"]["properties"].get("name", "default")
        return "default"

    def _simulate_historical_cost(
        self, dish_id: str, current_cost: int, progress: float
    ) -> int:
        """Simulate historical cost by interpolating price changes.

        At progress=0: all ingredient prices at old level (before changes)
        At progress=1: all prices at current level
        """
        bom_rels = self.repo.get_relationships(
            "Dish", dish_id, rel_type="USES_INGREDIENT", direction="out"
        )

        adjustment = 0
        for rel in bom_rels:
            ing_id = rel.get("to_node_id", "")
            rel_props = rel.get("properties", {})
            quantity_g = rel_props.get("quantity_g", 0)
            yield_rate = rel_props.get("yield_rate", DEFAULT_YIELD_RATE)

            ing_node = self.repo.get_node("Ingredient", ing_id)
            if not ing_node.get("ok"):
                continue

            ing_props = ing_node["node"]["properties"]
            price_per_kg = ing_props.get("price_per_kg_fen", 0)
            price_change_pct = ing_props.get("price_change_pct", 0)

            if price_change_pct == 0:
                continue

            # At this point in time, the price change was (progress * price_change_pct)
            # But we want historical cost, so we reverse: the change not yet applied
            remaining_change = (1 - progress) * price_change_pct / 100.0
            effective_qty = quantity_g / yield_rate if yield_rate > 0 else quantity_g
            price_diff = int(effective_qty / 1000.0 * price_per_kg * (-remaining_change))
            adjustment += price_diff

        return current_cost + adjustment

    def _record_cost(
        self, dish_id: str, cost_fen: int, margin_rate: float
    ) -> None:
        """Record cost calculation for trend tracking."""
        if dish_id not in self._cost_history:
            self._cost_history[dish_id] = []

        self._cost_history[dish_id].append({
            "cost_fen": cost_fen,
            "margin_rate": margin_rate,
            "calculated_at": datetime.now().isoformat(),
        })

        # Keep only last 90 entries
        if len(self._cost_history[dish_id]) > 90:
            self._cost_history[dish_id] = self._cost_history[dish_id][-90:]
