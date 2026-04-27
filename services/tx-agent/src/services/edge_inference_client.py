"""edge_inference_client.py — Enhanced EdgeInferenceClient for CoreML Bridge

Mac mini M4 CoreML Bridge runs at localhost:8100.
This client aligns with the actual CoreML Bridge API (coreml-bridge/src/main.py)
and adds:
  - 60s health status caching
  - 2s timeout (vs 1s in the legacy client)
  - Proper request/response models matching the bridge endpoints
  - Prediction statistics tracking
  - Graceful fallback on all failures (never crashes the agent)

Environment variables:
    COREML_BRIDGE_URL: CoreML Bridge address, default http://localhost:8100
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

_DEFAULT_BRIDGE_URL = "http://localhost:8100"
_TIMEOUT_SECONDS = 2.0
_HEALTH_CACHE_TTL_SECONDS = 60.0


class EdgeInferenceClient:
    """Client for Mac mini M4 Core ML bridge (localhost:8100).

    All predict methods return dict | None. None means edge is unavailable
    or prediction failed -- callers should fall through to cloud inference.

    Usage:
        client = EdgeInferenceClient()
        if await client.is_available():
            result = await client.predict_discount_risk(order_data)
    """

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.environ.get("COREML_BRIDGE_URL", _DEFAULT_BRIDGE_URL)).rstrip("/")
        self._available: bool | None = None
        self._available_checked_at: float = 0.0
        # Prediction stats
        self._stats: dict[str, dict[str, int]] = {
            "dish-time": {"success": 0, "failure": 0},
            "discount-risk": {"success": 0, "failure": 0},
            "traffic": {"success": 0, "failure": 0},
        }

    # ─── Health Check (cached 60s) ──────────────────────────────────────────

    async def is_available(self) -> bool:
        """Check if edge inference is reachable. Caches result for 60 seconds."""
        now = time.monotonic()
        if self._available is not None and (now - self._available_checked_at) < _HEALTH_CACHE_TTL_SECONDS:
            return self._available

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.get(f"{self.base_url}/health")
                data = resp.json()
                self._available = resp.status_code == 200 and data.get("ok", False)
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError):
            self._available = False

        self._available_checked_at = now
        logger.debug("edge_health_checked", available=self._available)
        return self._available

    def invalidate_health_cache(self) -> None:
        """Force next is_available() call to re-check the bridge."""
        self._available = None
        self._available_checked_at = 0.0

    # ─── Predict: Dish Time ─────────────────────────────────────────────────

    async def predict_dish_time(
        self,
        dish_id: str,
        store_id: str,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Predict cooking time for a dish.

        Args:
            dish_id: Dish identifier (used for logging, not sent to bridge)
            store_id: Store identifier (used for logging)
            context: Must contain keys matching DishTimePredictRequest:
                - dish_category: str (hot_dishes/cold_dishes/noodles/grill/dessert)
                - dish_complexity: int (1-5)
                - current_queue_depth: int (default 0)
                - hour_of_day: int (0-23)
                - concurrent_orders: int (default 1)

        Returns:
            {"predicted_minutes": float, "confidence": float, "method": str} or None
        """
        payload = {
            "dish_category": context.get("dish_category", "hot_dishes"),
            "dish_complexity": context.get("dish_complexity", 3),
            "current_queue_depth": context.get("current_queue_depth", 0),
            "hour_of_day": context.get("hour_of_day", 12),
            "concurrent_orders": context.get("concurrent_orders", 1),
        }
        result = await self._post("/predict/dish-time", payload)
        if result is None:
            return None

        data = result.get("data", {})
        return {
            "predicted_minutes": data.get("estimated_minutes", 0),
            "confidence": data.get("confidence", 0),
            "method": data.get("method", "unknown"),
            "p95_minutes": data.get("p95_minutes"),
            "inference_ms": data.get("inference_ms", 0),
            "source": "edge",
        }

    # ─── Predict: Discount Risk ─────────────────────────────────────────────

    async def predict_discount_risk(self, order_data: dict[str, Any]) -> dict[str, Any] | None:
        """Score discount risk.

        Args:
            order_data: Must contain keys matching DiscountRiskRequest:
                - discount_rate: float (0.0-1.0)
                - hour_of_day: int (0-23)
                - order_amount_fen: int (default 0)
                - employee_id: str (default "")
                - table_id: str (default "")

        Returns:
            {"risk_score": float, "risk_level": str, "risk_factors": list,
             "should_alert": bool, "confidence": float} or None
        """
        payload = {
            "discount_rate": order_data.get("discount_rate", 0.0),
            "hour_of_day": order_data.get("hour_of_day", 12),
            "order_amount_fen": order_data.get("order_amount_fen", 0),
            "employee_id": order_data.get("employee_id", ""),
            "table_id": order_data.get("table_id", ""),
        }
        result = await self._post("/predict/discount-risk", payload)
        if result is None:
            return None

        data = result.get("data", {})
        # Normalize risk_score to 0-1 range (bridge returns 0-100)
        raw_score = data.get("risk_score", 0)
        risk_score = raw_score / 100.0 if raw_score > 1 else raw_score
        return {
            "risk_score": risk_score,
            "risk_level": data.get("risk_level", "low"),
            "risk_factors": data.get("reasons", []),
            "should_alert": data.get("should_alert", False),
            "method": data.get("method", "unknown"),
            "confidence": 0.85 if data.get("method") == "coreml" else 0.75,
            "source": "edge",
        }

    # ─── Predict: Traffic ───────────────────────────────────────────────────

    async def predict_traffic(
        self,
        store_id: str,
        date: str,
        hour: int,
    ) -> dict[str, Any] | None:
        """Predict customer traffic.

        Args:
            store_id: Store identifier (used for logging, seats derived from context)
            date: Date string "YYYY-MM-DD" (used to derive day_of_week)
            hour: Target hour (0-23)

        Returns:
            {"predicted_count": int, "confidence": float, "peak_label": str} or None
        """
        # Derive day_of_week from date string
        from datetime import date as date_cls

        try:
            dt = date_cls.fromisoformat(date)
            day_of_week = dt.weekday()  # 0=Monday, 6=Sunday
        except (ValueError, TypeError):
            day_of_week = 2  # default to Wednesday

        payload = {
            "hour_of_day": hour,
            "day_of_week": day_of_week,
            "seats_total": 80,  # default, could be parameterized
            "weather_score": 1.0,
        }
        result = await self._post("/predict/traffic", payload)
        if result is None:
            return None

        data = result.get("data", {})
        return {
            "predicted_count": data.get("expected_covers", 0),
            "confidence": data.get("confidence", 0),
            "turnover_rate": data.get("turnover_rate", 0),
            "peak_label": data.get("peak_label", "off_peak"),
            "method": data.get("method", "unknown"),
            "source": "edge",
        }

    # ─── Model Status ──────────────────────────────────────────────────────

    async def get_model_status(self) -> dict[str, Any] | None:
        """Get current model status from the bridge (GET /model-status)."""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.get(f"{self.base_url}/model-status")
                resp.raise_for_status()
                data = resp.json()
                return data.get("data", {})
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
            logger.warning("edge_model_status_failed", error=str(exc))
            return None

    # ─── Stats ─────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, dict[str, int]]:
        """Return prediction call statistics."""
        return dict(self._stats)

    # ─── Internal HTTP POST ─────────────────────────────────────────────────

    async def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """HTTP POST with timeout and graceful fallback.

        Returns the parsed JSON response dict on success, or None on any failure.
        Never raises exceptions -- logs warnings and returns None.
        """
        # Determine stats key from path
        stats_key = path.replace("/predict/", "")
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    f"{self.base_url}{path}",
                    json=data,
                )
                resp.raise_for_status()
                result = resp.json()

                if stats_key in self._stats:
                    self._stats[stats_key]["success"] += 1

                logger.info(
                    "edge_inference_success",
                    endpoint=path,
                    ok=result.get("ok"),
                )
                return result

        except httpx.TimeoutException as exc:
            logger.warning(
                "edge_inference_timeout",
                endpoint=path,
                timeout=_TIMEOUT_SECONDS,
                error=str(exc),
            )
        except httpx.ConnectError as exc:
            logger.warning(
                "edge_inference_connect_error",
                endpoint=path,
                error=str(exc),
            )
            # Invalidate health cache on connection errors
            self.invalidate_health_cache()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "edge_inference_http_error",
                endpoint=path,
                status_code=exc.response.status_code,
                error=str(exc),
            )

        if stats_key in self._stats:
            self._stats[stats_key]["failure"] += 1

        return None
