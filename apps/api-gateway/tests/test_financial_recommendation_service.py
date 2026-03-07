"""Tests for financial_recommendation_service.py — Phase 5 Month 10"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
import sys

# ── mock config before import ──────────────────────────────────────────────
mock_settings = MagicMock()
mock_settings.database_url = "postgresql+asyncpg://x:x@localhost/x"
mock_config_mod = MagicMock()
mock_config_mod.settings = mock_settings
sys.modules.setdefault("src.core.config", mock_config_mod)

from src.services.financial_recommendation_service import (  # noqa: E402
    compute_priority_score,
    classify_urgency,
    generate_rec_title,
    generate_rec_action,
    generate_rec_description,
    build_anomaly_recommendations,
    build_ranking_recommendations,
    build_forecast_recommendations,
    merge_and_prioritize,
    generate_store_recommendations,
    get_recommendations,
    update_recommendation_status,
    get_recommendation_stats,
    get_brand_rec_summary,
    URGENCY_HIGH,
    URGENCY_MEDIUM,
)


# ══════════════════════════════════════════════════════════════════════════════
# compute_priority_score
# ══════════════════════════════════════════════════════════════════════════════

class TestComputePriorityScore:
    def test_no_impact(self):
        score = compute_priority_score("anomaly_moderate", None, 75.0)
        assert score == 75.0 * 0.5

    def test_large_impact_caps_at_50(self):
        score = compute_priority_score("anomaly_moderate", 200000, 75.0)
        # impact_score = min(50, 200000/1000) = 50; conf_score = 75*0.5 = 37.5 → 87.5
        assert abs(score - 87.5) < 0.01

    def test_severe_boost(self):
        # anomaly_severe has 1.2x conf multiplier
        normal   = compute_priority_score("anomaly_moderate", None, 80.0)
        severe   = compute_priority_score("anomaly_severe",   None, 80.0)
        assert severe > normal

    def test_capped_at_100(self):
        score = compute_priority_score("anomaly_severe", 1_000_000, 100.0)
        assert score == 100.0

    def test_zero_impact(self):
        score = compute_priority_score("ranking_laggard", 0.0, 80.0)
        assert score == round(80.0 * 0.5, 2)

    def test_moderate_range(self):
        score = compute_priority_score("forecast_decline", 5000, 70.0)
        # impact = min(50, 5) = 5; conf = 35; total = 40
        assert abs(score - 40.0) < 0.01


class TestComputePriorityScoreCorrected:
    def test_large_impact(self):
        score = compute_priority_score("anomaly_moderate", 200000, 75.0)
        # impact = min(50, 200) = 50; conf = 75*0.5 = 37.5 → 87.5
        assert abs(score - 87.5) < 0.01


# ══════════════════════════════════════════════════════════════════════════════
# classify_urgency
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyUrgency:
    def test_high(self):
        assert classify_urgency(URGENCY_HIGH) == "high"
        assert classify_urgency(100.0) == "high"

    def test_medium(self):
        assert classify_urgency(URGENCY_MEDIUM) == "medium"
        assert classify_urgency(50.0) == "medium"

    def test_low(self):
        assert classify_urgency(0.0) == "low"
        assert classify_urgency(29.9) == "low"


# ══════════════════════════════════════════════════════════════════════════════
# generate_rec_title
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateRecTitle:
    def test_anomaly_severe(self):
        title = generate_rec_title("anomaly_severe", "revenue")
        assert "紧急" in title
        assert "月净收入" in title

    def test_ranking_laggard(self):
        title = generate_rec_title("ranking_laggard", "food_cost_rate")
        assert "提升" in title or "落后" in title
        assert "食材成本率" in title

    def test_forecast_decline(self):
        title = generate_rec_title("forecast_decline", "profit_margin")
        assert "预警" in title


# ══════════════════════════════════════════════════════════════════════════════
# generate_rec_action
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateRecAction:
    def test_returns_string(self):
        action = generate_rec_action("anomaly_severe", "revenue")
        assert isinstance(action, str)
        assert len(action) > 5

    def test_all_combos_return_string(self):
        for rtype in ["anomaly_severe", "anomaly_moderate", "ranking_laggard",
                      "forecast_decline", "forecast_surge"]:
            for metric in ["revenue", "food_cost_rate", "profit_margin", "health_score"]:
                action = generate_rec_action(rtype, metric)
                assert isinstance(action, str)


# ══════════════════════════════════════════════════════════════════════════════
# generate_rec_description
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateRecDescription:
    def test_length_limit(self):
        desc = generate_rec_description(
            "anomaly_severe", "revenue",
            80000, 100000, -20.0, -20000,
            "额外很长很长的背景说明" * 10,
        )
        assert len(desc) <= 200

    def test_contains_values(self):
        desc = generate_rec_description(
            "anomaly_moderate", "food_cost_rate",
            45.0, 38.0, 18.4, 5000,
        )
        assert "45" in desc or "38" in desc

    def test_empty_when_no_values(self):
        desc = generate_rec_description("forecast_decline", "revenue", None, None, None, None)
        assert desc == ""

    def test_yuan_impact_shown(self):
        desc = generate_rec_description(
            "ranking_laggard", "profit_margin",
            10.0, 15.0, -33.3, 7500,
        )
        assert "7,500" in desc or "7500" in desc


# ══════════════════════════════════════════════════════════════════════════════
# build_anomaly_recommendations
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildAnomalyRecommendations:
    def test_skips_normal(self):
        recs = build_anomaly_recommendations([
            {"metric": "revenue", "severity": "normal",
             "actual_value": 100000, "expected_value": 98000,
             "deviation_pct": 2.0, "yuan_impact": 2000, "description": ""},
        ])
        assert recs == []

    def test_severe_creates_rec(self):
        recs = build_anomaly_recommendations([
            {"metric": "revenue", "severity": "severe",
             "actual_value": 60000, "expected_value": 100000,
             "deviation_pct": -40.0, "yuan_impact": -40000, "description": "收入严重下滑"},
        ])
        assert len(recs) == 1
        assert recs[0]["rec_type"] == "anomaly_severe"
        assert recs[0]["urgency"] in ("high", "medium")

    def test_moderate_creates_rec(self):
        recs = build_anomaly_recommendations([
            {"metric": "food_cost_rate", "severity": "moderate",
             "actual_value": 45.0, "expected_value": 38.0,
             "deviation_pct": 18.4, "yuan_impact": 8000, "description": ""},
        ])
        assert len(recs) == 1
        assert recs[0]["rec_type"] == "anomaly_moderate"

    def test_multiple_anomalies(self):
        recs = build_anomaly_recommendations([
            {"metric": "revenue",    "severity": "severe",   "actual_value": 60000,
             "expected_value": 100000, "deviation_pct": -40, "yuan_impact": -40000, "description": ""},
            {"metric": "health_score","severity": "moderate", "actual_value": 45,
             "expected_value": 70, "deviation_pct": -35, "yuan_impact": None, "description": ""},
        ])
        assert len(recs) == 2


# ══════════════════════════════════════════════════════════════════════════════
# build_ranking_recommendations
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildRankingRecommendations:
    def test_skips_non_laggard(self):
        rankings = {
            "health_score": {"tier": "top", "percentile": 90.0, "rank": 1, "value": 85.0}
        }
        recs = build_ranking_recommendations(rankings, [])
        assert recs == []

    def test_laggard_creates_rec(self):
        rankings = {
            "food_cost_rate": {"tier": "laggard", "percentile": 15.0, "rank": 9, "value": 52.0}
        }
        gaps = [
            {"metric": "food_cost_rate", "benchmark_type": "top_quartile",
             "gap_direction": "below", "yuan_potential": 15000}
        ]
        recs = build_ranking_recommendations(rankings, gaps)
        assert len(recs) == 1
        assert recs[0]["rec_type"] == "ranking_laggard"
        assert recs[0]["metric"] == "food_cost_rate"

    def test_yuan_potential_applied(self):
        rankings = {
            "profit_margin": {"tier": "laggard", "percentile": 10.0, "rank": 10, "value": 5.0}
        }
        gaps = [
            {"metric": "profit_margin", "benchmark_type": "top_quartile",
             "gap_direction": "below", "yuan_potential": 20000}
        ]
        recs = build_ranking_recommendations(rankings, gaps)
        assert recs[0]["expected_yuan_impact"] == 20000


# ══════════════════════════════════════════════════════════════════════════════
# build_forecast_recommendations
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildForecastRecommendations:
    def test_revenue_down_creates_decline_rec(self):
        forecasts = {
            "revenue": {"trend_direction": "down", "predicted_value": 80000, "actual_value": 95000}
        }
        recs = build_forecast_recommendations(forecasts)
        assert len(recs) == 1
        assert recs[0]["rec_type"] == "forecast_decline"

    def test_food_cost_up_creates_surge_rec(self):
        forecasts = {
            "food_cost_rate": {"trend_direction": "up", "predicted_value": 48.0, "actual_value": 40.0}
        }
        recs = build_forecast_recommendations(forecasts)
        assert len(recs) == 1
        assert recs[0]["rec_type"] == "forecast_surge"

    def test_flat_skipped(self):
        forecasts = {
            "revenue": {"trend_direction": "flat", "predicted_value": 100000, "actual_value": 98000}
        }
        recs = build_forecast_recommendations(forecasts)
        assert recs == []

    def test_revenue_up_skipped(self):
        forecasts = {
            "revenue": {"trend_direction": "up", "predicted_value": 110000, "actual_value": 100000}
        }
        recs = build_forecast_recommendations(forecasts)
        assert recs == []  # revenue going up is good, no rec needed

    def test_health_score_down_creates_rec(self):
        forecasts = {
            "health_score": {"trend_direction": "down", "predicted_value": 55.0, "actual_value": 72.0}
        }
        recs = build_forecast_recommendations(forecasts)
        assert len(recs) == 1
        assert recs[0]["rec_type"] == "forecast_decline"


# ══════════════════════════════════════════════════════════════════════════════
# merge_and_prioritize
# ══════════════════════════════════════════════════════════════════════════════

class TestMergeAndPrioritize:
    def _make_rec(self, rec_type, metric, score):
        return {
            "rec_type": rec_type, "metric": metric,
            "title": "T", "description": "D", "action": "A",
            "expected_yuan_impact": None, "confidence_pct": 80.0,
            "urgency": "medium", "priority_score": score,
            "source_type": "test", "source_ref": "test",
        }

    def test_deduplicates(self):
        recs = [
            self._make_rec("anomaly_severe", "revenue", 90.0),
            self._make_rec("anomaly_severe", "revenue", 85.0),   # duplicate type+metric
        ]
        result = merge_and_prioritize(recs)
        assert len(result) == 1

    def test_sorted_by_priority(self):
        recs = [
            self._make_rec("ranking_laggard",  "revenue",    40.0),
            self._make_rec("anomaly_severe",    "revenue",    90.0),
            self._make_rec("forecast_decline",  "health_score", 55.0),
        ]
        result = merge_and_prioritize(recs)
        scores = [r["priority_score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_max_recs_respected(self):
        recs = [
            self._make_rec(f"anomaly_moderate", f"metric_{i}", float(i))
            for i in range(15)
        ]
        result = merge_and_prioritize(recs, max_recs=5)
        assert len(result) == 5

    def test_empty_input(self):
        assert merge_and_prioritize([]) == []


# ══════════════════════════════════════════════════════════════════════════════
# DB 层 — generate_store_recommendations
# ══════════════════════════════════════════════════════════════════════════════

def _make_db(calls: list):
    call_idx = [0]

    async def mock_execute(stmt, params=None):
        idx = call_idx[0]
        call_idx[0] += 1
        val = calls[idx] if idx < len(calls) else []
        r = MagicMock()
        if val is None or val == []:
            r.fetchone.return_value = None
            r.fetchall.return_value = []
        elif isinstance(val, list):
            r.fetchall.return_value = val
            r.fetchone.return_value = val[0] if val else None
        else:
            r.fetchone.return_value = val
            r.fetchall.return_value = [val]
        return r

    db = MagicMock()
    db.execute = mock_execute
    db.commit = AsyncMock()
    return db


class TestGenerateStoreRecommendations:
    @pytest.mark.asyncio
    async def test_no_signals_returns_empty(self):
        # All fetches return empty: anomalies, rankings, gaps, forecasts
        db = _make_db([[], [], [], []])
        result = await generate_store_recommendations(db, "S001", "2024-07")
        assert result["total_recs"] == 0

    @pytest.mark.asyncio
    async def test_severe_anomaly_creates_rec(self):
        anomalies = [
            ("revenue", 60000, 100000, -40.0, "severe", "收入大幅下滑", -40000),
        ]
        # anomalies, rankings, gaps, forecasts, then upsert(s)
        db = _make_db([anomalies, [], [], [], None])
        result = await generate_store_recommendations(db, "S001", "2024-07")
        assert result["total_recs"] >= 1
        recs = result["recommendations"]
        types = [r["rec_type"] for r in recs]
        assert "anomaly_severe" in types

    @pytest.mark.asyncio
    async def test_urgency_counts_filled(self):
        anomalies = [
            ("revenue",   60000, 100000, -40.0, "severe",   "desc", -40000),
            ("food_cost_rate", 50, 38, 31.6, "moderate", "desc", 5000),
        ]
        db = _make_db([anomalies, [], [], [], None, None])
        result = await generate_store_recommendations(db, "S001", "2024-07")
        assert "urgency_counts" in result
        total = sum(result["urgency_counts"].values())
        assert total == result["total_recs"]


# ══════════════════════════════════════════════════════════════════════════════
# get_recommendations
# ══════════════════════════════════════════════════════════════════════════════

class TestGetRecommendations:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        from datetime import datetime
        rows = [
            (1, "anomaly_severe", "revenue", "收入异常",
             "收入下滑40%", "立即排查", -40000, 90.0, "high", 95.0,
             "anomaly", "anomaly:revenue", "pending", datetime(2024, 7, 15)),
        ]
        db = _make_db([rows])
        recs = await get_recommendations(db, "S001", "2024-07")
        assert len(recs) == 1
        assert recs[0]["rec_type"] == "anomaly_severe"
        assert recs[0]["urgency"] == "high"

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        recs = await get_recommendations(db, "S001", "2024-07")
        assert recs == []


# ══════════════════════════════════════════════════════════════════════════════
# update_recommendation_status
# ══════════════════════════════════════════════════════════════════════════════

class TestUpdateRecommendationStatus:
    @pytest.mark.asyncio
    async def test_adopt(self):
        db = _make_db([(42,)])
        result = await update_recommendation_status(db, 42, "adopted")
        assert result["updated"] is True
        assert result["status"] == "adopted"

    @pytest.mark.asyncio
    async def test_dismiss(self):
        db = _make_db([(42,)])
        result = await update_recommendation_status(db, 42, "dismissed")
        assert result["updated"] is True

    @pytest.mark.asyncio
    async def test_not_found(self):
        db = _make_db([None])
        result = await update_recommendation_status(db, 99, "adopted")
        assert result["updated"] is False

    @pytest.mark.asyncio
    async def test_invalid_status(self):
        db = _make_db([])
        result = await update_recommendation_status(db, 1, "invalid_status")
        assert result["updated"] is False


# ══════════════════════════════════════════════════════════════════════════════
# get_recommendation_stats
# ══════════════════════════════════════════════════════════════════════════════

class TestGetRecommendationStats:
    @pytest.mark.asyncio
    async def test_adoption_rate(self):
        rows = [
            ("2024-07", 2, 3, 1, 6),
            ("2024-06", 1, 2, 0, 3),
        ]
        db = _make_db([rows])
        stats = await get_recommendation_stats(db, "S001", periods=6)
        # reversed (ascending)
        assert stats[0]["period"] == "2024-06"
        assert stats[1]["period"] == "2024-07"
        assert abs(stats[1]["adoption_rate"] - 50.0) < 0.1

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        stats = await get_recommendation_stats(db, "S001")
        assert stats == []


# ══════════════════════════════════════════════════════════════════════════════
# get_brand_rec_summary
# ══════════════════════════════════════════════════════════════════════════════

class TestGetBrandRecSummary:
    @pytest.mark.asyncio
    async def test_aggregates(self):
        rows = [
            ("S001", "high",   "pending",  -40000),
            ("S001", "medium", "adopted",   8000),
            ("S002", "high",   "pending",  -30000),
            ("S002", "low",    "dismissed", 1000),
        ]
        db = _make_db([rows])
        summary = await get_brand_rec_summary(db, "B001", "2024-07")
        assert summary["total_recs"] == 4
        assert summary["affected_stores"] == 2
        assert summary["urgency_counts"]["high"] == 2
        assert summary["status_counts"]["pending"] == 2
        assert summary["adoption_rate"] == 25.0   # 1/4

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        summary = await get_brand_rec_summary(db, "B001", "2024-07")
        assert summary["total_recs"] == 0
        assert summary["adoption_rate"] == 0.0
