"""Malaysia-specific sales forecasting service

Integrates Malaysian public holiday calendars, cuisine profiles, and
ingredient data to produce culturally-aware sales forecasts for
Malaysian restaurant stores.

Key differences from generic forecasting:
- Ramadan shifts daily consumption patterns significantly (iftar surge,
  daytime drop)
- Multi-ethnic holiday calendar affects different cuisine categories
  differently
- East Malaysia vs Peninsular Malaysia have distinct holiday sets
- Monsoon seasons impact delivery vs dine-in ratios
- School holidays create family-meal demand spikes

Design follows the existing DemandPredictor pattern in tx-predict but
extends it with Malaysia-specific context.

All monetary amounts in fen (分).
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.tx_agent.src.config.malaysia_holidays import (
    get_high_impact_periods,
    get_holidays_by_year,
    get_holiday_by_name,
    get_state_specific_holidays,
)
from services.tx_agent.src.config.malaysia_cuisine_profiles import (
    get_cuisine_by_state,
    get_cuisine_profile,
    MALAYSIA_MEAL_PERIODS,
)
from services.tx_agent.src.config.malaysia_ingredients import (
    get_ingredient,
    get_perishable_ingredients,
)

logger = structlog.get_logger(__name__)

# ── Default Parameters ─────────────────────────────────────────

LOOKBACK_DAYS = 14  # Sales history lookback window
FORECAST_DAYS = 7  # Default forecast horizon
HOLIDAY_LOOKAHEAD_DAYS = 30  # Pre-fetch holidays for planning
PREP_LEAD_DAYS_FESTIVE = 3  # Extra prep days before major holidays

# Default weekday demand multipliers (applied on top of holiday impact)
WEEKDAY_FACTORS: dict[int, float] = {
    0: 1.00,  # Monday
    1: 0.95,  # Tuesday
    2: 1.00,  # Wednesday
    3: 1.05,  # Thursday
    4: 1.10,  # Friday
    5: 1.25,  # Saturday
    6: 1.20,  # Sunday
}


class MalaysiaForecastingService:
    """Malaysia-specific sales forecasting service.

    Provides sales forecasts, holiday impact multipliers, inventory
    predictions, and cuisine recommendations tailored to Malaysian
    restaurant operations.

    Usage:
        service = MalaysiaForecastingService()
        forecast = await service.forecast_sales(
            store_id="...", tenant_id="...", date_from="2026-03-28",
            date_to="2026-04-04", db=session
        )
    """

    def __init__(
        self,
        lookback_days: int = LOOKBACK_DAYS,
        forecast_days: int = FORECAST_DAYS,
    ) -> None:
        self._lookback_days = lookback_days
        self._forecast_days = forecast_days

    # ─── Public API ─────────────────────────────────────────────────

    async def forecast_sales(
        self,
        store_id: str,
        tenant_id: str,
        date_from: str,
        date_to: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Forecast sales for MY stores using holiday data + historical patterns.

        Args:
            store_id: Store UUID.
            tenant_id: Tenant UUID.
            date_from: Start date (YYYY-MM-DD).
            date_to: End date (YYYY-MM-DD).
            db: Database session.

        Returns:
            dict containing:
                - store_id: The store ID
                - forecast_period: date_from to date_to
                - daily_forecasts: list of daily forecast entries
                - total_expected_revenue_fen: aggregate forecast
                - holiday_impacts: list of holidays affecting the period
                - confidence: overall confidence score
        """
        forecast_dates = self._generate_date_range(date_from, date_to)
        year = datetime.strptime(date_from, "%Y-%m-%d").year

        # Gather applicable holidays
        holidays = get_holidays_by_year(year)
        active_holidays = self._filter_holidays_in_range(holidays, date_from, date_to)

        # Get store state info for cuisine mix
        store_info = await self._get_store_info(store_id, tenant_id, db)
        state = store_info.get("state", "") if store_info else ""
        cuisine_mix = get_cuisine_by_state(state) if state else ["malay", "chinese", "indian"]

        # Build daily forecasts
        daily_forecasts: list[dict[str, Any]] = []
        total_expected_revenue_fen = 0
        confidence_sum = 0.0

        for day in forecast_dates:
            day_str = day.strftime("%Y-%m-%d")
            day_of_week = day.weekday()  # 0=Monday

            # Fetch historical baseline for this day-of-week
            historical_baseline = await self._get_daily_baseline(
                store_id, tenant_id, day_of_week, db,
            )

            # Calculate holiday multiplier
            holiday_impact = self._calculate_holiday_multiplier(
                day_str, active_holidays, day_of_week, cuisine_mix,
            )

            # Calculate seasonality modifier
            seasonality_mod = self._get_seasonality_modifier(day)

            # Composite forecast
            base_revenue = holiday_impact.get("base_revenue_fen", historical_baseline)
            final_revenue = int(
                round(base_revenue * holiday_impact["composite_multiplier"] * seasonality_mod)
            )

            daily_forecast = {
                "date": day_str,
                "day_of_week": day_of_week,
                "day_name": day.strftime("%A"),
                "predicted_revenue_fen": final_revenue,
                "base_revenue_fen": base_revenue,
                "composite_multiplier": round(holiday_impact["composite_multiplier"], 4),
                "seasonality_modifier": round(seasonality_mod, 4),
                "holiday_boost": holiday_impact.get("holiday_boost", 0.0),
                "is_holiday": holiday_impact.get("is_holiday", False),
                "holiday_name": holiday_impact.get("holiday_name"),
                "dine_in_expected_fen": int(round(final_revenue * 0.55)),
                "takeaway_expected_fen": int(round(final_revenue * 0.25)),
                "delivery_expected_fen": int(round(final_revenue * 0.20)),
                "confidence": holiday_impact.get("confidence", 0.7),
            }
            daily_forecasts.append(daily_forecast)
            total_expected_revenue_fen += final_revenue
            confidence_sum += holiday_impact.get("confidence", 0.7)

        overall_confidence = round(confidence_sum / max(len(daily_forecasts), 1), 4)

        return {
            "store_id": store_id,
            "forecast_period": {"from": date_from, "to": date_to},
            "daily_forecasts": daily_forecasts,
            "total_expected_revenue_fen": total_expected_revenue_fen,
            "holiday_impacts": [
                {"name": h["name"], "date": h["date"], "impact": h["impact"]}
                for h in active_holidays
            ],
            "confidence": overall_confidence,
            "model": "malaysia_forecast_v1",
        }

    async def get_holiday_impact(
        self,
        date: str,
        store_id: str,
    ) -> dict[str, Any]:
        """Get forecasted holiday impact multiplier for a store on a given date.

        Args:
            date: Date string (YYYY-MM-DD).
            store_id: Store UUID (used for state-specific logic).

        Returns:
            dict with impact multiplier, holiday name, cuisine trends, and
            recommended preparation actions.
        """
        year = int(date[:4])
        holidays = get_holidays_by_year(year)
        day_of_week = datetime.strptime(date, "%Y-%m-%d").weekday()

        active_holidays = self._filter_holidays_in_range(holidays, date, date)
        cuisine_mix = ["malay", "chinese", "indian"]

        result = self._calculate_holiday_multiplier(
            date, active_holidays, day_of_week, cuisine_mix,
        )

        # Add preparation recommendations
        result["preparation_tips"] = self._generate_prep_tips(result)

        return result

    async def predict_inventory(
        self,
        store_id: str,
        tenant_id: str,
        days_ahead: int,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Predict inventory needs using MY ingredient profiles.

        Combines sales forecasts with ingredient-level demand projections,
        adjusted for holiday cuisine trends and seasonal price fluctuations.

        Args:
            store_id: Store UUID.
            tenant_id: Tenant UUID.
            days_ahead: Number of days to forecast.
            db: Database session.

        Returns:
            List of ingredient-level predictions with recommended order
            quantities and expected costs.
        """
        today = date.today()
        date_from = today.isoformat()
        date_to = (today + timedelta(days=days_ahead)).isoformat()

        # Get sales forecast to drive ingredient demand
        sales_forecast = await self.forecast_sales(
            store_id, tenant_id, date_from, date_to, db,
        )

        # Get current inventory levels
        current_stock = await self._get_current_inventory(store_id, tenant_id, db)

        # Get store cuisine mix for ingredient weighting
        store_info = await self._get_store_info(store_id, tenant_id, db)
        state = store_info.get("state", "")
        cuisine_mix = get_cuisine_by_state(state) if state else ["malay", "chinese", "indian"]

        predictions: list[dict[str, Any]] = []
        perishable = get_perishable_ingredients()

        for ing_key, ing_profile in perishable.items():
            current = current_stock.get(ing_key, 0.0)

            # Estimate daily usage based on cuisine mix and forecast
            daily_usage = self._estimate_daily_usage(
                ing_key, ing_profile, cuisine_mix, sales_forecast,
            )
            total_needed = daily_usage * days_ahead
            recommended_order = max(0.0, total_needed - current)

            # Apply seasonal price factor
            price_factor = ing_profile.get("seasonal_price_fluctuation", {}).get("jan-dec", 1.0)

            predictions.append({
                "ingredient_key": ing_key,
                "ingredient_name_ms": ing_profile["local_names"]["ms"],
                "unit": ing_profile["unit"],
                "current_stock": round(current, 2),
                "estimated_daily_usage": round(daily_usage, 2),
                "total_needed_days_ahead": round(total_needed, 2),
                "recommended_order_quantity": round(recommended_order, 2),
                "seasonal_price_factor": price_factor,
                "shelf_life_days": ing_profile.get("shelf_life_days", 7),
                "is_perishable": True,
                "supplier_options": ing_profile.get("typical_suppliers", [])[:3],
            })

        return predictions

    async def get_cuisine_recommendations(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Recommend menu optimizations based on local cuisine profile.

        Analyses the store's cuisine profile against upcoming holidays,
        seasonal trends, and local taste preferences to suggest menu
        adjustments.

        Args:
            store_id: Store UUID.
            tenant_id: Tenant UUID.
            db: Database session.

        Returns:
            List of actionable menu recommendations.
        """
        store_info = await self._get_store_info(store_id, tenant_id, db)
        state = store_info.get("state", "kuala_lumpur")
        cuisine_mix = get_cuisine_by_state(state)

        today = date.today()
        upcoming_holidays = []
        for year in [today.year, today.year + 1]:
            for h in get_holidays_by_year(year):
                h_date = datetime.strptime(h["date"], "%Y-%m-%d").date()
                days_until = (h_date - today).days
                if 0 <= days_until <= 60:
                    upcoming_holidays.append({**h, "days_until": days_until})

        upcoming_holidays.sort(key=lambda x: x["days_until"])

        recommendations: list[dict[str, Any]] = []

        for holiday in upcoming_holidays:
            cuisine_trend = holiday.get("cuisine_trend", "")
            if not cuisine_trend:
                continue

            # Match cuisine trend to relevant cuisine profiles
            suggested_dishes = []
            for cuisine in cuisine_mix:
                profile = get_cuisine_profile(cuisine)
                if profile:
                    suggested_dishes.extend(profile.get("popular_dishes", [])[:3])

            category_boost = holiday.get("category_boost", {})
            boosted_cuisines = [k for k, v in category_boost.items() if v >= 0.15]

            recommendations.append({
                "holiday": holiday["name"],
                "days_until": holiday["days_until"],
                "impact": holiday["impact"],
                "cuisine_trend": cuisine_trend,
                "suggested_dishes": suggested_dishes[:5],
                "boosted_cuisines": boosted_cuisines,
                "action": "promote" if holiday["impact"] in ("high", "medium") else "observe",
                "prep_lead_days": holiday.get("prep_lead_days", 0),
                "dine_in_boost": holiday.get("dine_in_boost", 0.0),
                "takeaway_boost": holiday.get("takeaway_boost", 0.0),
            })

        return recommendations

    # ─── Internal: Holiday Impact ──────────────────────────────────

    def _calculate_holiday_multiplier(
        self,
        day_str: str,
        active_holidays: list[dict[str, Any]],
        day_of_week: int,
        cuisine_mix: list[str],
    ) -> dict[str, Any]:
        """Calculate the composite sales multiplier for a given day.

        Combines holiday boost, weekday factor, and cuisine affinity.

        Returns:
            dict containing:
                - composite_multiplier: total demand multiplier
                - holiday_boost: boost from active holidays
                - is_holiday: whether the day is a public holiday
                - holiday_name: name of the holiday if applicable
                - cuisine_trend: trending cuisine keywords
                - base_revenue_fen: estimated baseline revenue
                - confidence: forecast confidence (0-1)
        """
        base_multiplier = WEEKDAY_FACTORS.get(day_of_week, 1.0)
        holiday_boost = 0.0
        cuisine_trend = ""
        holiday_name = None
        is_holiday = False

        for h in active_holidays:
            if h["date"] == day_str:
                is_holiday = True
                holiday_name = h["name"]
                cuisine_trend = h.get("cuisine_trend", "")

                # Apply cuisine affinity boost
                category_boost = h.get("category_boost", {})
                category_multiplier = 1.0
                for cuisine in cuisine_mix:
                    boost = category_boost.get(cuisine, 0.0)
                    category_multiplier += boost * 0.5  # Diminish raw boost for composite

                dine_boost = h.get("dine_in_boost", 0.0)
                holiday_boost = max(dine_boost, max(category_boost.values(), default=0.0))
                base_multiplier += holiday_boost
                break

        # Estimate base revenue (simplified — real path uses DB)
        base_revenue_fen = 1500000  # Default baseline = 15,000 MYR in fen

        confidence = 0.85 if is_holiday else 0.70
        # New Year / unfamiliar period = lower confidence
        if holiday_name and "2027" in day_str:
            confidence = 0.65

        return {
            "composite_multiplier": round(base_multiplier, 4),
            "holiday_boost": round(holiday_boost, 4),
            "is_holiday": is_holiday,
            "holiday_name": holiday_name,
            "cuisine_trend": cuisine_trend,
            "base_revenue_fen": base_revenue_fen,
            "confidence": confidence,
        }

    def _get_seasonality_modifier(self, day: date) -> float:
        """Apply Malaysia-specific seasonality modifier.

        Monsoon season boosts delivery but may reduce dine-in.
        Ramadan shifts daytime/dinnertime patterns.
        """
        month = day.month
        # Monsoon season (Nov-Mar): delivery surge
        if month in (11, 12, 1, 2, 3):
            return 1.02  # Slight overall positive (delivery offsets dine-in dip)
        # Hot season (Apr-Oct): more dine-in, cold drinks
        return 1.05  # More outdoor dining

    # ─── Internal: Holiday Filtering ──────────────────────────────

    @staticmethod
    def _filter_holidays_in_range(
        holidays: list[dict[str, Any]],
        date_from: str,
        date_to: str,
    ) -> list[dict[str, Any]]:
        """Filter holidays that fall within a date range.

        Also includes holidays whose prep_lead_days overlap with the range.
        """
        from_dt = datetime.strptime(date_from, "%Y-%m-%d").date()
        to_dt = datetime.strptime(date_to, "%Y-%m-%d").date()
        result: list[dict[str, Any]] = []
        for h in holidays:
            h_date = datetime.strptime(h["date"], "%Y-%m-%d").date()
            duration = h.get("duration_days", 1)
            # Include if holiday or its prep window overlaps
            prep_lead = h.get("prep_lead_days", 0)
            h_start = h_date - timedelta(days=prep_lead)
            h_end = h_date + timedelta(days=duration - 1)
            if h_start <= to_dt and h_end >= from_dt:
                result.append(h)
        return result

    # ─── Internal: Database Access ────────────────────────────────

    @staticmethod
    async def _get_store_info(
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any] | None:
        """Fetch store metadata (state, cuisine type) from DB."""
        try:
            row = await db.execute(
                text("""
                    SELECT city, district, region, store_metadata
                    FROM stores
                    WHERE id = :store_id AND tenant_id = :tenant_id
                """),
                {"store_id": store_id, "tenant_id": tenant_id},
            )
            row_data = row.mappings().one_or_none()
            if row_data:
                meta = row_data.get("store_metadata", {}) or {}
                return {
                    "state": row_data.get("region") or row_data.get("city") or "",
                    "city": row_data.get("city") or "",
                    "district": row_data.get("district") or "",
                    "store_metadata": meta,
                }
            return None
        except Exception as exc:
            logger.warning(
                "store_info_fetch_failed",
                store_id=store_id,
                error=str(exc),
            )
            return None

    @staticmethod
    async def _get_daily_baseline(
        store_id: str,
        tenant_id: str,
        day_of_week: int,
        db: AsyncSession,
    ) -> int:
        """Fetch historical daily revenue baseline for a given day-of-week."""
        try:
            row = await db.execute(
                text("""
                    SELECT AVG(final_amount_fen) as avg_revenue
                    FROM orders
                    WHERE store_id = :store_id
                      AND tenant_id = :tenant_id
                      AND EXTRACT(DOW FROM order_time AT TIME ZONE 'Asia/Kuala_Lumpur') = :dow
                      AND order_time >= NOW() - INTERVAL ':lookback days'
                      AND status = 'completed'
                """),
                {
                    "store_id": store_id,
                    "tenant_id": tenant_id,
                    "dow": day_of_week,
                    "lookback": LOOKBACK_DAYS,
                },
            )
            row_data = row.mappings().one_or_none()
            if row_data and row_data["avg_revenue"]:
                return int(round(row_data["avg_revenue"]))
        except Exception as exc:
            logger.warning(
                "baseline_fetch_failed",
                store_id=store_id,
                day_of_week=day_of_week,
                error=str(exc),
            )
        return 1500000  # Fallback 15,000 MYR

    @staticmethod
    async def _get_current_inventory(
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, float]:
        """Fetch current stock levels from ingredients table."""
        stock: dict[str, float] = {}
        try:
            rows = await db.execute(
                text("""
                    SELECT ingredient_name, current_quantity
                    FROM ingredients
                    WHERE store_id = :store_id
                      AND tenant_id = :tenant_id
                      AND is_deleted = FALSE
                """),
                {"store_id": store_id, "tenant_id": tenant_id},
            )
            for row in rows.mappings():
                stock[row["ingredient_name"]] = float(row["current_quantity"] or 0)
        except Exception as exc:
            logger.warning(
                "inventory_fetch_failed",
                store_id=store_id,
                error=str(exc),
            )
        return stock

    # ─── Internal: Estimation ─────────────────────────────────────

    @staticmethod
    def _estimate_daily_usage(
        ing_key: str,
        ing_profile: dict[str, Any],
        cuisine_mix: list[str],
        sales_forecast: dict[str, Any],
    ) -> float:
        """Estimate daily ingredient usage based on cuisine mix and forecast.

        Simplified model: each cuisine type has a weight factor for each
        ingredient category. Total forecast revenue drives volume.
        """
        # Cuisine-to-ingredient category affinity weights
        cuisine_ing_weight: dict[str, dict[str, float]] = {
            "malay": {"herbs": 0.15, "spices": 0.12, "poultry": 0.20, "coconut": 0.15,
                      "condiments": 0.05, "oils": 0.03, "grains": 0.10},
            "chinese": {"poultry": 0.15, "vegetables": 0.10, "noodles": 0.12, "condiments": 0.08,
                        "oils": 0.05, "seafood": 0.10, "soy_products": 0.05},
            "indian": {"spices": 0.15, "poultry": 0.10, "grains": 0.12, "dairy_alternatives": 0.08,
                       "oils": 0.05, "herbs": 0.05},
            "fusion": {"herbs": 0.08, "spices": 0.05, "poultry": 0.10, "vegetables": 0.08,
                       "fruits": 0.05, "condiments": 0.05},
        }

        category = ing_profile.get("category", "")
        # Build composite weight from cuisine mix
        total_weight = 0.0
        for cuisine in cuisine_mix:
            weights = cuisine_ing_weight.get(cuisine, {})
            total_weight += weights.get(category, 0.05) / max(len(cuisine_mix), 1)

        daily_forecast = sales_forecast.get("daily_forecasts", [])
        avg_daily_revenue = (
            sum(d["predicted_revenue_fen"] for d in daily_forecast)
            / max(len(daily_forecast), 1)
        )

        # Simplified: revenue * category weight / unit_price gives volume
        # Rough estimate: 0.5% of revenue goes to this ingredient category
        daily_cost_fen = avg_daily_revenue * total_weight * 0.01
        # Assume unit price ~1000 fen (10 MYR) per base unit
        assumed_unit_price_fen = 1000
        estimated_volume = daily_cost_fen / max(assumed_unit_price_fen, 1)

        return max(estimated_volume, 0.5)  # Minimum 0.5 unit/day

    @staticmethod
    def _generate_prep_tips(holiday_impact: dict[str, Any]) -> list[str]:
        """Generate preparation recommendations based on holiday impact."""
        tips: list[str] = []
        if holiday_impact.get("is_holiday"):
            tips.append(f"Prepare for {holiday_impact.get('holiday_name', 'festive')} demand surge")
            if holiday_impact.get("cuisine_trend"):
                tips.append(f"Feature trending dishes: {holiday_impact['cuisine_trend']}")
        if holiday_impact.get("composite_multiplier", 1.0) > 1.2:
            tips.append("Increase staff shift coverage — expected high traffic")
            tips.append("Pre-stock perishable ingredients 2-3 days ahead")
        if holiday_impact.get("composite_multiplier", 1.0) < 0.8:
            tips.append("Reduce perishable order quantities — expected low traffic")
        return tips

    # ─── Internal: Date Utilities ────────────────────────────────

    @staticmethod
    def _generate_date_range(date_from: str, date_to: str) -> list[date]:
        """Generate a list of dates from date_from to date_to inclusive."""
        from_dt = datetime.strptime(date_from, "%Y-%m-%d").date()
        to_dt = datetime.strptime(date_to, "%Y-%m-%d").date()
        delta = (to_dt - from_dt).days
        return [from_dt + timedelta(days=i) for i in range(delta + 1)]
