"""test_edge_mixin_integration.py — EdgeAwareMixin + Agent integration tests

Tests:
  1. EdgeAwareMixin dispatches to correct predict method
  2. EdgeAwareMixin returns None when edge unavailable
  3. DiscountGuardAgent uses edge shortcut on high confidence
  4. DiscountGuardAgent falls through to rules when edge unavailable
  5. InventoryAlertAgent uses traffic forecast for demand multiplier

Run:
    pytest services/tx-agent/src/tests/test_edge_mixin_integration.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch, MagicMock

_here = os.path.dirname(__file__)
_src = os.path.abspath(os.path.join(_here, ".."))
if _src not in sys.path:
    sys.path.insert(0, _src)

import pytest

from agents.skills.discount_guard import DiscountGuardAgent
from agents.skills.inventory_alert import InventoryAlertAgent


# ─── DiscountGuardAgent Edge Integration ────────────────────────────────────


class TestDiscountGuardEdge:

    @pytest.mark.asyncio
    async def test_edge_shortcut_high_confidence(self) -> None:
        """When edge returns high confidence (>0.8), agent skips Claude API."""
        agent = DiscountGuardAgent(tenant_id="test-tenant")

        # Mock edge prediction with high confidence
        mock_edge_result = {
            "risk_score": 0.85,
            "risk_level": "high",
            "risk_factors": ["折扣率超过50%阈值"],
            "should_alert": True,
            "method": "rule_fallback",
            "confidence": 0.85,
            "source": "edge",
        }

        with patch.object(agent, "get_edge_prediction", new_callable=AsyncMock, return_value=mock_edge_result):
            result = await agent.execute(
                "detect_discount_anomaly",
                {
                    "order": {
                        "total_amount_fen": 10000,
                        "discount_amount_fen": 6000,
                    },
                    "threshold": 0.5,
                },
            )

        assert result.success is True
        assert result.inference_layer == "edge"
        assert result.data["is_anomaly"] is True
        assert result.data["edge_method"] == "rule_fallback"
        # No LLM analysis since edge shortcut was used
        assert result.data["llm_analysis"] == ""

    @pytest.mark.asyncio
    async def test_edge_unavailable_falls_through(self) -> None:
        """When edge is unavailable, agent falls through to rule engine."""
        agent = DiscountGuardAgent(tenant_id="test-tenant")

        # Mock edge as unavailable
        with patch.object(agent, "get_edge_prediction", new_callable=AsyncMock, return_value=None):
            result = await agent.execute(
                "detect_discount_anomaly",
                {
                    "order": {
                        "total_amount_fen": 10000,
                        "discount_amount_fen": 2000,
                    },
                    "threshold": 0.5,
                },
            )

        assert result.success is True
        # discount_rate = 0.2, below threshold, no risk factors
        assert result.data["is_anomaly"] is False

    @pytest.mark.asyncio
    async def test_edge_low_confidence_falls_through(self) -> None:
        """When edge returns low confidence (<=0.8), agent uses rule engine + LLM."""
        agent = DiscountGuardAgent(tenant_id="test-tenant")

        # Mock edge prediction with low confidence
        mock_edge_result = {
            "risk_score": 0.5,
            "risk_level": "medium",
            "risk_factors": ["折扣率处于中等风险区间"],
            "should_alert": True,
            "method": "rule_fallback",
            "confidence": 0.6,  # Below 0.8 threshold
            "source": "edge",
        }

        with patch.object(agent, "get_edge_prediction", new_callable=AsyncMock, return_value=mock_edge_result):
            result = await agent.execute(
                "detect_discount_anomaly",
                {
                    "order": {
                        "total_amount_fen": 10000,
                        "discount_amount_fen": 6000,
                    },
                    "threshold": 0.5,
                },
            )

        assert result.success is True
        # Should fall through to rule engine path (no edge shortcut)
        # Edge risk factors should be merged
        assert "折扣率处于中等风险区间" in result.data["risk_factors"]


# ─── InventoryAlertAgent Edge Integration ───────────────────────────────────


class TestInventoryAlertEdge:

    @pytest.mark.asyncio
    async def test_traffic_forecast_boosts_demand(self) -> None:
        """When edge predicts peak traffic, demand_multiplier increases."""
        agent = InventoryAlertAgent(tenant_id="test-tenant", store_id="store_001")

        mock_traffic = {
            "predicted_count": 72,
            "peak_label": "lunch_peak",
            "confidence": 0.80,
            "source": "edge",
        }

        with patch.object(agent, "get_edge_prediction", new_callable=AsyncMock, return_value=mock_traffic):
            result = await agent.execute(
                "generate_restock_alerts",
                {
                    "store_id": "store_001",
                    "low_stock_items": [
                        {"name": "鸡蛋", "current_qty": 10, "safety_stock": 50, "gap": 40, "unit": "个"},
                    ],
                },
            )

        assert result.success is True
        assert result.data["demand_multiplier"] == 1.3
        assert "traffic_forecast" in result.data
        assert result.data["traffic_forecast"]["peak_label"] == "lunch_peak"

    @pytest.mark.asyncio
    async def test_no_traffic_forecast_normal_demand(self) -> None:
        """When edge is unavailable, demand_multiplier stays at 1.0."""
        agent = InventoryAlertAgent(tenant_id="test-tenant", store_id="store_001")

        with patch.object(agent, "get_edge_prediction", new_callable=AsyncMock, return_value=None):
            result = await agent.execute(
                "generate_restock_alerts",
                {
                    "store_id": "store_001",
                    "low_stock_items": [
                        {"name": "鸡蛋", "current_qty": 10, "safety_stock": 50, "gap": 40, "unit": "个"},
                    ],
                },
            )

        assert result.success is True
        assert result.data["demand_multiplier"] == 1.0
        assert "traffic_forecast" not in result.data

    @pytest.mark.asyncio
    async def test_off_peak_no_demand_boost(self) -> None:
        """Off-peak traffic does not boost demand_multiplier."""
        agent = InventoryAlertAgent(tenant_id="test-tenant", store_id="store_001")

        mock_traffic = {
            "predicted_count": 15,
            "peak_label": "off_peak",
            "confidence": 0.65,
            "source": "edge",
        }

        with patch.object(agent, "get_edge_prediction", new_callable=AsyncMock, return_value=mock_traffic):
            result = await agent.execute(
                "generate_restock_alerts",
                {
                    "store_id": "store_001",
                    "low_stock_items": [],
                },
            )

        assert result.success is True
        assert result.data["demand_multiplier"] == 1.0


# ─── EdgeAwareMixin Unit Tests ──────────────────────────────────────────────


class TestEdgeAwareMixin:

    @pytest.mark.asyncio
    async def test_edge_property_creates_singleton(self) -> None:
        """edge property creates client on first access and reuses it."""
        agent = DiscountGuardAgent(tenant_id="test-tenant")

        client1 = agent.edge
        client2 = agent.edge

        assert client1 is client2

    @pytest.mark.asyncio
    async def test_unknown_predict_type_returns_none(self) -> None:
        """Unknown predict_type returns None without crashing."""
        agent = DiscountGuardAgent(tenant_id="test-tenant")

        # Mock edge as available
        mock_client = AsyncMock()
        mock_client.is_available = AsyncMock(return_value=True)
        agent._edge_client = mock_client

        result = await agent.get_edge_prediction("unknown_type")
        assert result is None
