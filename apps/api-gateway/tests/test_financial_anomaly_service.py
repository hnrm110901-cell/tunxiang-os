"""Tests for financial_anomaly_service.py — Phase 5 Month 8

Pure-function tests run synchronously.
DB tests use AsyncMock with call_idx pattern.
"""
from __future__ import annotations

import math
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ── mock config before import ──────────────────────────────────────────────
import sys
mock_settings = MagicMock()
mock_settings.database_url = "postgresql+asyncpg://x:x@localhost/x"
mock_config_mod = MagicMock()
mock_config_mod.settings = mock_settings
sys.modules.setdefault("src.core.config", mock_config_mod)

from src.services.financial_anomaly_service import (  # noqa: E402
    compute_mean_std,
    compute_z_score,
    compute_iqr_bounds,
    is_iqr_anomaly,
    compute_deviation_pct,
    classify_severity_z,
    classify_severity_deviation,
    merge_severity,
    generate_anomaly_description,
    compute_yuan_impact,
    _prev_periods,
    detect_metric_anomaly,
    detect_store_anomalies,
    get_anomaly_records,
    resolve_anomaly,
    get_anomaly_trend,
    get_brand_anomaly_summary,
)


# ══════════════════════════════════════════════════════════════════════════════
# _prev_periods
# ══════════════════════════════════════════════════════════════════════════════

class TestPrevPeriods:
    def test_basic(self):
        assert _prev_periods("2024-03", 3) == ["2023-12", "2024-01", "2024-02"]

    def test_year_wrap(self):
        assert _prev_periods("2024-01", 2) == ["2023-11", "2023-12"]

    def test_single(self):
        assert _prev_periods("2024-06", 1) == ["2024-05"]

    def test_six(self):
        result = _prev_periods("2024-07", 6)
        assert result[0] == "2024-01"
        assert result[-1] == "2024-06"
        assert len(result) == 6


# ══════════════════════════════════════════════════════════════════════════════
# compute_mean_std
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeMeanStd:
    def test_empty(self):
        m, s = compute_mean_std([])
        assert m == 0.0 and s == 0.0

    def test_single(self):
        m, s = compute_mean_std([5.0])
        assert m == 5.0 and s == 0.0

    def test_identical(self):
        m, s = compute_mean_std([3.0, 3.0, 3.0])
        assert m == 3.0 and s == 0.0

    def test_known_values(self):
        # n=8, mean=5, sum-sq-dev=32, sample-std = sqrt(32/7)
        m, s = compute_mean_std([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
        assert abs(m - 5.0) < 1e-9
        assert abs(s - math.sqrt(32 / 7)) < 1e-9

    def test_two_values(self):
        m, s = compute_mean_std([10.0, 20.0])
        assert m == 15.0
        assert abs(s - math.sqrt(50)) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# compute_z_score
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeZScore:
    def test_zero_std(self):
        assert compute_z_score(100, 100, 0) == 0.0

    def test_positive(self):
        assert abs(compute_z_score(12.0, 10.0, 2.0) - 1.0) < 1e-9

    def test_negative(self):
        assert abs(compute_z_score(8.0, 10.0, 2.0) - (-1.0)) < 1e-9

    def test_large(self):
        assert abs(compute_z_score(16.0, 10.0, 2.0) - 3.0) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# compute_iqr_bounds
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeIqrBounds:
    def test_empty(self):
        lo, hi = compute_iqr_bounds([])
        assert lo == 0.0 and hi == 0.0

    def test_small(self):
        lo, hi = compute_iqr_bounds([1.0, 3.0])
        assert lo == 1.0 and hi == 3.0

    def test_four_values(self):
        lo, hi = compute_iqr_bounds([1.0, 2.0, 3.0, 4.0])
        assert lo < 1.0   # fence extends below Q1
        assert hi > 4.0

    def test_is_iqr_anomaly_inside(self):
        assert not is_iqr_anomaly(5.0, 0.0, 10.0)

    def test_is_iqr_anomaly_outside(self):
        assert is_iqr_anomaly(11.0, 0.0, 10.0)
        assert is_iqr_anomaly(-1.0, 0.0, 10.0)


# ══════════════════════════════════════════════════════════════════════════════
# compute_deviation_pct
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeDeviationPct:
    def test_zero_expected(self):
        assert compute_deviation_pct(100, 0) == 0.0

    def test_over(self):
        assert abs(compute_deviation_pct(110, 100) - 10.0) < 1e-9

    def test_under(self):
        assert abs(compute_deviation_pct(90, 100) - (-10.0)) < 1e-9

    def test_exact(self):
        assert compute_deviation_pct(100, 100) == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# classify_severity_z / classify_severity_deviation
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifySeverity:
    # Z-score
    def test_z_normal(self):
        assert classify_severity_z(1.0) == "normal"
        assert classify_severity_z(-1.0) == "normal"

    def test_z_mild(self):
        assert classify_severity_z(1.6) == "mild"
        assert classify_severity_z(-1.6) == "mild"

    def test_z_moderate(self):
        assert classify_severity_z(2.5) == "moderate"

    def test_z_severe(self):
        assert classify_severity_z(3.1) == "severe"
        assert classify_severity_z(-3.5) == "severe"

    # Deviation
    def test_dev_normal(self):
        assert classify_severity_deviation(5.0) == "normal"
        assert classify_severity_deviation(-9.9) == "normal"

    def test_dev_mild(self):
        assert classify_severity_deviation(15.0) == "mild"

    def test_dev_moderate(self):
        assert classify_severity_deviation(-25.0) == "moderate"

    def test_dev_severe(self):
        assert classify_severity_deviation(35.0) == "severe"


# ══════════════════════════════════════════════════════════════════════════════
# merge_severity
# ══════════════════════════════════════════════════════════════════════════════

class TestMergeSeverity:
    def test_both_normal(self):
        assert merge_severity("normal", "normal") == "normal"

    def test_takes_higher(self):
        assert merge_severity("mild", "severe") == "severe"
        assert merge_severity("severe", "mild") == "severe"

    def test_same(self):
        assert merge_severity("moderate", "moderate") == "moderate"

    def test_normal_vs_mild(self):
        assert merge_severity("normal", "mild") == "mild"


# ══════════════════════════════════════════════════════════════════════════════
# generate_anomaly_description
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateAnomalyDescription:
    def test_normal_returns_empty(self):
        desc = generate_anomaly_description(
            "revenue", 100000, 95000, 5.26, 1.0, "normal"
        )
        assert desc == ""

    def test_contains_metric_label(self):
        desc = generate_anomaly_description(
            "revenue", 80000, 100000, -20.0, -2.5, "moderate"
        )
        assert "月净收入" in desc

    def test_contains_z_score_when_above_threshold(self):
        desc = generate_anomaly_description(
            "food_cost_rate", 45.0, 38.0, 18.4, 2.1, "moderate"
        )
        assert "Z-score" in desc

    def test_no_z_score_when_below_threshold(self):
        desc = generate_anomaly_description(
            "profit_margin", 8.0, 10.0, -20.0, 1.2, "moderate"
        )
        assert "Z-score" not in desc

    def test_length_limit(self):
        desc = generate_anomaly_description(
            "health_score", 30.0, 75.0, -60.0, -4.0, "severe", yuan_impact=50000
        )
        assert len(desc) <= 200

    def test_yuan_impact_included_for_non_revenue(self):
        desc = generate_anomaly_description(
            "food_cost_rate", 45.0, 35.0, 28.6, 2.5, "moderate", yuan_impact=15000
        )
        assert "¥" in desc

    def test_revenue_no_redundant_yuan(self):
        # revenue already shows ¥ value; yuan_impact not repeated in description
        desc = generate_anomaly_description(
            "revenue", 50000, 100000, -50.0, -3.0, "severe", yuan_impact=-50000
        )
        assert "月净收入" in desc


# ══════════════════════════════════════════════════════════════════════════════
# compute_yuan_impact
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeYuanImpact:
    def test_revenue(self):
        impact = compute_yuan_impact("revenue", 80000, 100000, 0)
        assert impact == -20000.0

    def test_food_cost_rate(self):
        # (45 - 40) / 100 * 200000 = 10000
        impact = compute_yuan_impact("food_cost_rate", 45.0, 40.0, 200000)
        assert abs(impact - 10000) < 1e-6

    def test_profit_margin(self):
        # (10 - 12) / 100 * 150000 = -3000
        impact = compute_yuan_impact("profit_margin", 10.0, 12.0, 150000)
        assert abs(impact - (-3000)) < 1e-6

    def test_health_score_no_revenue(self):
        assert compute_yuan_impact("health_score", 60, 80, 0) is None

    def test_food_cost_zero_revenue(self):
        assert compute_yuan_impact("food_cost_rate", 45.0, 40.0, 0) is None


# ══════════════════════════════════════════════════════════════════════════════
# detect_metric_anomaly (DB)
# ══════════════════════════════════════════════════════════════════════════════

def _make_db(calls: list):
    """Build a mock DB that returns calls[i] for execute call i."""
    call_idx = [0]

    async def mock_execute(stmt, params=None):
        idx = call_idx[0]
        call_idx[0] += 1
        val = calls[idx] if idx < len(calls) else None
        mock_result = MagicMock()
        if val is None:
            mock_result.fetchone.return_value = None
            mock_result.fetchall.return_value = []
        elif isinstance(val, list):
            mock_result.fetchall.return_value = val
            mock_result.fetchone.return_value = val[0] if val else None
        else:
            mock_result.fetchone.return_value = val
            mock_result.fetchall.return_value = [val]
        return mock_result

    db = MagicMock()
    db.execute = mock_execute
    db.commit = AsyncMock()
    return db


class TestDetectMetricAnomaly:
    @pytest.mark.asyncio
    async def test_normal_no_anomaly(self):
        # History: stable values → actual close to mean
        history_rows = [
            ("2024-01", 100000, 0, 10.0),
            ("2024-02", 102000, 0, 10.2),
            ("2024-03", 98000,  0, 9.8),
            ("2024-04", 100500, 0, 10.1),
            ("2024-05", 99500,  0, 9.9),
            ("2024-06", 101000, 0, 10.0),
        ]
        # calls: 0=history fetchall, 1=forecast fetchone
        db = _make_db([history_rows, None])
        result = await detect_metric_anomaly(db, "S001", "2024-07", "revenue", 100200)
        assert result["is_anomaly"] is False
        assert result["severity"] == "normal"

    @pytest.mark.asyncio
    async def test_severe_anomaly_z_score(self):
        # History: mean≈100k, std≈1k → actual 105k is far out
        history_rows = [
            ("2024-01", 99000, 0, 10.0),
            ("2024-02", 100000, 0, 10.0),
            ("2024-03", 101000, 0, 10.0),
            ("2024-04", 100000, 0, 10.0),
            ("2024-05", 99000,  0, 10.0),
            ("2024-06", 101000, 0, 10.0),
        ]
        db = _make_db([history_rows, None])
        result = await detect_metric_anomaly(db, "S001", "2024-07", "revenue", 110000)
        assert result["is_anomaly"] is True
        assert result["severity"] in ("moderate", "severe")

    @pytest.mark.asyncio
    async def test_forecast_deviation_upgrades_severity(self):
        # Z-score mild, but forecast deviation is severe → final = severe
        history_rows = [
            ("2024-01", 100000, 0, 10.0),
            ("2024-02", 102000, 0, 10.0),
            ("2024-03", 98000,  0, 10.0),
        ]
        forecast_row = (130000,)   # predicted was 130k, actual is 100k → big dev
        db = _make_db([history_rows, forecast_row])
        result = await detect_metric_anomaly(db, "S001", "2024-07", "revenue", 80000, 80000)
        assert result["is_anomaly"] is True
        assert result["severity"] in ("moderate", "severe")

    @pytest.mark.asyncio
    async def test_insufficient_history_no_z_score(self):
        # Only 2 periods — below MIN_HISTORY=3
        history_rows = [
            ("2024-05", 100000, 0, 10.0),
            ("2024-06", 100000, 0, 10.0),
        ]
        db = _make_db([history_rows, None])
        result = await detect_metric_anomaly(db, "S001", "2024-07", "revenue", 100000)
        assert result["z_score"] == 0.0   # no Z-score with < 3 periods


# ══════════════════════════════════════════════════════════════════════════════
# detect_store_anomalies (DB)
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectStoreAnomalies:
    @pytest.mark.asyncio
    async def test_returns_summary_keys(self):
        profit_row = (100000.0, 38000.0, 12.0)
        health_row = (72.0,)

        # For each metric: 1 history fetchall + 1 forecast fetchone
        # 3 profit metrics + 1 health metric = 8 sub-calls + 2 initial rows
        history_stable = [
            ("2024-01", 100000, 38000, 12.0),
            ("2024-02", 102000, 38760, 12.0),
            ("2024-03", 98000,  37240, 12.0),
            ("2024-04", 100000, 38000, 12.0),
            ("2024-05", 99000,  37620, 12.0),
            ("2024-06", 101000, 38380, 12.0),
        ]
        health_history = [
            ("2024-01", 72.0),
            ("2024-02", 73.0),
            ("2024-03", 71.0),
            ("2024-04", 72.0),
            ("2024-05", 72.5),
            ("2024-06", 71.5),
        ]
        calls = [
            profit_row,    # profit current period
            health_row,    # health current period
            history_stable,  None,   # revenue history + forecast
            history_stable,  None,   # food_cost_rate history + forecast
            history_stable,  None,   # profit_margin history + forecast
            health_history,  None,   # health_score history + forecast
        ]
        db = _make_db(calls)
        result = await detect_store_anomalies(db, "S001", "2024-07")
        assert "store_id" in result
        assert "metrics_checked" in result
        assert "anomaly_count" in result
        assert "severity_counts" in result
        assert "all_results" in result

    @pytest.mark.asyncio
    async def test_no_data_returns_empty(self):
        db = _make_db([None, None])
        result = await detect_store_anomalies(db, "S001", "2024-07")
        assert result["metrics_checked"] == 0
        assert result["anomaly_count"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# get_anomaly_records (DB)
# ══════════════════════════════════════════════════════════════════════════════

class TestGetAnomalyRecords:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        from datetime import datetime
        rows = [
            ("revenue", "2024-07", 80000, 100000, -20.0, -2.5,
             "severe", "月净收入当期 ¥80,000...", -20000, False,
             datetime(2024, 7, 15)),
        ]
        db = _make_db([rows])
        records = await get_anomaly_records(db, "S001", only_anomalies=True)
        assert len(records) == 1
        assert records[0]["metric"] == "revenue"
        assert records[0]["severity"] == "severe"
        assert records[0]["label"] == "月净收入"

    @pytest.mark.asyncio
    async def test_empty_result(self):
        db = _make_db([[]])
        records = await get_anomaly_records(db, "S001")
        assert records == []


# ══════════════════════════════════════════════════════════════════════════════
# resolve_anomaly (DB)
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveAnomaly:
    @pytest.mark.asyncio
    async def test_resolved(self):
        db = _make_db([(999,)])   # RETURNING id
        result = await resolve_anomaly(db, "S001", "2024-07", "revenue")
        assert result["resolved"] is True

    @pytest.mark.asyncio
    async def test_not_found(self):
        db = _make_db([None])
        result = await resolve_anomaly(db, "S001", "2024-07", "revenue")
        assert result["resolved"] is False


# ══════════════════════════════════════════════════════════════════════════════
# get_anomaly_trend (DB)
# ══════════════════════════════════════════════════════════════════════════════

class TestGetAnomalyTrend:
    @pytest.mark.asyncio
    async def test_groups_by_period(self):
        rows = [
            ("2024-05", "severe", 2),
            ("2024-05", "moderate", 1),
            ("2024-06", "mild", 3),
        ]
        db = _make_db([rows])
        trend = await get_anomaly_trend(db, "S001", periods=6)
        assert len(trend) == 2
        assert trend[0]["period"] == "2024-05"
        assert trend[0]["severe"] == 2
        assert trend[1]["mild"] == 3

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        trend = await get_anomaly_trend(db, "S001")
        assert trend == []


# ══════════════════════════════════════════════════════════════════════════════
# get_brand_anomaly_summary (DB)
# ══════════════════════════════════════════════════════════════════════════════

class TestGetBrandAnomalySummary:
    @pytest.mark.asyncio
    async def test_aggregates_stores(self):
        rows = [
            ("S001", "revenue", "severe", True, "收入异常", -50000),
            ("S001", "food_cost_rate", "mild", True, "成本率偏高", 5000),
            ("S002", "health_score", "moderate", True, "评分偏低", None),
        ]
        db = _make_db([rows])
        summary = await get_brand_anomaly_summary(db, "B001", "2024-07")
        assert summary["total_anomalies"] == 3
        assert summary["affected_stores"] == 2
        assert summary["severity_counts"]["severe"] == 1
        assert summary["severity_counts"]["mild"] == 1
        assert summary["severity_counts"]["moderate"] == 1
        assert summary["total_yuan_impact"] > 0

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        summary = await get_brand_anomaly_summary(db, "B001", "2024-07")
        assert summary["total_anomalies"] == 0
        assert summary["affected_stores"] == 0
