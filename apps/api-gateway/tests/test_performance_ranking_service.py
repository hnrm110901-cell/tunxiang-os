"""Tests for performance_ranking_service.py — Phase 5 Month 9

Pure-function tests run synchronously.
DB tests use call_idx mock pattern.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys

# ── mock config before import ──────────────────────────────────────────────
mock_settings = MagicMock()
mock_settings.database_url = "postgresql+asyncpg://x:x@localhost/x"
mock_config_mod = MagicMock()
mock_config_mod.settings = mock_settings
sys.modules.setdefault("src.core.config", mock_config_mod)

from src.services.performance_ranking_service import (  # noqa: E402
    compute_rank,
    compute_percentile,
    classify_tier,
    classify_rank_change,
    compute_benchmark_value,
    compute_gap_pct,
    compute_gap_direction,
    compute_yuan_potential,
    build_ranking_row,
    build_gap_rows,
    _prev_period,
    compute_period_rankings,
    get_store_ranking,
    get_leaderboard,
    get_benchmark_gaps,
    get_ranking_trend,
    get_brand_ranking_summary,
)


# ══════════════════════════════════════════════════════════════════════════════
# _prev_period
# ══════════════════════════════════════════════════════════════════════════════

class TestPrevPeriod:
    def test_normal(self):
        assert _prev_period("2024-07") == "2024-06"

    def test_year_wrap(self):
        assert _prev_period("2024-01") == "2023-12"

    def test_december(self):
        assert _prev_period("2024-12") == "2024-11"


# ══════════════════════════════════════════════════════════════════════════════
# compute_rank
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeRank:
    def test_best_higher_is_better(self):
        assert compute_rank(100, [60, 70, 80, 90, 100], higher_is_better=True) == 1

    def test_worst_higher_is_better(self):
        assert compute_rank(60, [60, 70, 80, 90, 100], higher_is_better=True) == 5

    def test_middle(self):
        assert compute_rank(80, [60, 70, 80, 90, 100], higher_is_better=True) == 3

    def test_lower_is_better(self):
        # food_cost_rate: 30% is rank 1 (best), 50% is rank 5
        assert compute_rank(30, [30, 35, 40, 45, 50], higher_is_better=False) == 1
        assert compute_rank(50, [30, 35, 40, 45, 50], higher_is_better=False) == 5

    def test_empty_list(self):
        assert compute_rank(100, [], higher_is_better=True) == 1

    def test_single(self):
        assert compute_rank(75, [75], higher_is_better=True) == 1

    def test_tie(self):
        # Two stores with same value share rank 1
        assert compute_rank(80, [80, 80, 70], higher_is_better=True) == 1


# ══════════════════════════════════════════════════════════════════════════════
# compute_percentile
# ══════════════════════════════════════════════════════════════════════════════

class TestComputePercentile:
    def test_best_is_100(self):
        assert compute_percentile(100, [60, 70, 80, 90, 100]) == 100.0

    def test_worst_is_0(self):
        assert compute_percentile(60, [60, 70, 80, 90, 100]) == 0.0

    def test_middle(self):
        pct = compute_percentile(80, [60, 70, 80, 90, 100])
        assert 40.0 <= pct <= 60.0

    def test_single_value(self):
        assert compute_percentile(50, [50]) == 100.0

    def test_lower_is_better(self):
        # 30% cost rate is best (100th percentile)
        assert compute_percentile(30, [30, 35, 40, 45, 50], higher_is_better=False) == 100.0
        # 50% cost rate is worst (0th percentile)
        assert compute_percentile(50, [30, 35, 40, 45, 50], higher_is_better=False) == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# classify_tier
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyTier:
    def test_top(self):
        assert classify_tier(75.0) == "top"
        assert classify_tier(100.0) == "top"

    def test_above_avg(self):
        assert classify_tier(50.0) == "above_avg"
        assert classify_tier(74.9) == "above_avg"

    def test_below_avg(self):
        assert classify_tier(25.0) == "below_avg"
        assert classify_tier(49.9) == "below_avg"

    def test_laggard(self):
        assert classify_tier(0.0) == "laggard"
        assert classify_tier(24.9) == "laggard"


# ══════════════════════════════════════════════════════════════════════════════
# classify_rank_change
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyRankChange:
    def test_new(self):
        assert classify_rank_change(1, None) == "new"

    def test_improved(self):
        assert classify_rank_change(2, 5) == "improved"

    def test_declined(self):
        assert classify_rank_change(5, 2) == "declined"

    def test_stable(self):
        assert classify_rank_change(3, 3) == "stable"


# ══════════════════════════════════════════════════════════════════════════════
# compute_benchmark_value
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeBenchmarkValue:
    VALUES_EVEN = [10.0, 20.0, 30.0, 40.0]
    VALUES_ODD  = [10.0, 20.0, 30.0]

    def test_median_even(self):
        bv = compute_benchmark_value(self.VALUES_EVEN, "median")
        assert bv == 25.0  # (20+30)/2

    def test_median_odd(self):
        bv = compute_benchmark_value(self.VALUES_ODD, "median")
        assert bv == 20.0

    def test_best_higher(self):
        assert compute_benchmark_value(self.VALUES_EVEN, "best", higher_is_better=True) == 40.0

    def test_best_lower(self):
        assert compute_benchmark_value(self.VALUES_EVEN, "best", higher_is_better=False) == 10.0

    def test_top_quartile_higher(self):
        bv = compute_benchmark_value([10, 20, 30, 40, 50, 60, 70, 80], "top_quartile", True)
        assert bv is not None
        assert bv >= 60.0  # top 25% threshold

    def test_empty(self):
        assert compute_benchmark_value([], "median") is None


# ══════════════════════════════════════════════════════════════════════════════
# compute_gap_pct + compute_gap_direction
# ══════════════════════════════════════════════════════════════════════════════

class TestGap:
    def test_gap_positive(self):
        assert abs(compute_gap_pct(110, 100) - 10.0) < 1e-9

    def test_gap_negative(self):
        assert abs(compute_gap_pct(90, 100) - (-10.0)) < 1e-9

    def test_gap_zero_benchmark(self):
        assert compute_gap_pct(100, 0) == 0.0

    def test_direction_above_higher(self):
        assert compute_gap_direction(10.0, higher_is_better=True) == "above"

    def test_direction_below_higher(self):
        assert compute_gap_direction(-10.0, higher_is_better=True) == "below"

    def test_direction_above_lower(self):
        # cost rate store < benchmark → gap_pct < 0 → "above" (better)
        assert compute_gap_direction(-10.0, higher_is_better=False) == "above"

    def test_direction_equal(self):
        assert compute_gap_direction(0.005, True) == "equal"


# ══════════════════════════════════════════════════════════════════════════════
# compute_yuan_potential
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeYuanPotential:
    def test_revenue(self):
        pot = compute_yuan_potential("revenue", 80000, 100000, 0)
        assert pot == 20000.0  # benchmark - store

    def test_food_cost_rate(self):
        # store=45%, benchmark=38%, revenue=200k → |45-38|/100*200k = 14000
        pot = compute_yuan_potential("food_cost_rate", 45.0, 38.0, 200000)
        assert abs(pot - 14000) < 1e-6

    def test_profit_margin(self):
        # store=10%, benchmark=15%, revenue=150k → 5/100*150k = 7500
        pot = compute_yuan_potential("profit_margin", 10.0, 15.0, 150000)
        assert abs(pot - 7500) < 1e-6

    def test_health_score_no_yuan(self):
        assert compute_yuan_potential("health_score", 60, 80, 100000) is None

    def test_zero_revenue(self):
        assert compute_yuan_potential("food_cost_rate", 45, 38, 0) is None


# ══════════════════════════════════════════════════════════════════════════════
# build_ranking_row
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildRankingRow:
    ALL = [60.0, 70.0, 80.0, 90.0, 100.0]

    def test_best_store(self):
        row = build_ranking_row("S001", "2024-07", "health_score", 100.0, self.ALL, None)
        assert row["rank"] == 1
        assert row["percentile"] == 100.0
        assert row["tier"] == "top"
        assert row["rank_change"] == "new"

    def test_worst_store(self):
        row = build_ranking_row("S005", "2024-07", "health_score", 60.0, self.ALL, None)
        assert row["rank"] == 5
        assert row["tier"] == "laggard"

    def test_improved(self):
        row = build_ranking_row("S002", "2024-07", "health_score", 90.0, self.ALL, prev_rank=4)
        assert row["rank_change"] == "improved"

    def test_lower_is_better(self):
        fcr_values = [30.0, 35.0, 38.0, 42.0, 50.0]
        row = build_ranking_row("S001", "2024-07", "food_cost_rate", 30.0, fcr_values, None)
        assert row["rank"] == 1
        assert row["tier"] == "top"


# ══════════════════════════════════════════════════════════════════════════════
# build_gap_rows
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildGapRows:
    ALL = [60.0, 70.0, 80.0, 90.0, 100.0]

    def test_returns_three_rows(self):
        rows = build_gap_rows("S001", "2024-07", "health_score", 70.0, self.ALL)
        assert len(rows) == 3
        btypes = {r["benchmark_type"] for r in rows}
        assert btypes == {"median", "top_quartile", "best"}

    def test_below_best_is_below_direction(self):
        rows = build_gap_rows("S001", "2024-07", "health_score", 70.0, self.ALL)
        best_row = next(r for r in rows if r["benchmark_type"] == "best")
        assert best_row["gap_direction"] == "below"

    def test_above_benchmark_for_best(self):
        rows = build_gap_rows("S001", "2024-07", "health_score", 100.0, self.ALL)
        best_row = next(r for r in rows if r["benchmark_type"] == "best")
        assert best_row["gap_direction"] == "equal"

    def test_yuan_potential_computed(self):
        rows = build_gap_rows("S001", "2024-07", "revenue", 80000.0, [80000, 90000, 100000], 80000)
        median_row = next(r for r in rows if r["benchmark_type"] == "median")
        assert median_row["yuan_potential"] is not None

    def test_empty_values(self):
        rows = build_gap_rows("S001", "2024-07", "health_score", 70.0, [])
        assert rows == []


# ══════════════════════════════════════════════════════════════════════════════
# DB 层 — compute_period_rankings
# ══════════════════════════════════════════════════════════════════════════════

def _make_db(calls: list):
    call_idx = [0]

    async def mock_execute(stmt, params=None):
        idx = call_idx[0]
        call_idx[0] += 1
        val = calls[idx] if idx < len(calls) else []
        mock_result = MagicMock()
        if val is None or val == []:
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


class TestComputePeriodRankings:
    @pytest.mark.asyncio
    async def test_empty_returns_zero(self):
        # All metric snapshots return empty
        db = _make_db([[], [], [], []])
        result = await compute_period_rankings(db, "2024-07")
        assert result["ranking_rows"] == 0
        assert result["gap_rows"] == 0

    @pytest.mark.asyncio
    async def test_single_store(self):
        # revenue snapshot: 1 store (store_id, net_revenue_yuan, food_cost_yuan, profit_margin_pct)
        revenue_snapshot = [("S001", 100000, 38000, 12.0)]
        prev_ranks = []
        health_snapshot = [("S001", 75.0)]

        # Call sequence per metric (1 store each):
        #   revenue (no _fetch_store_revenue — metric == "revenue"):
        #     0: _fetch_metric_snapshot, 1: _fetch_prev_ranks,
        #     2: _upsert_ranking, 3-5: _upsert_gap × 3                     = 6 calls
        #   food_cost_rate (needs _fetch_store_revenue):
        #     6: _fetch_metric_snapshot, 7: _fetch_prev_ranks,
        #     8: _upsert_ranking, 9: _fetch_store_revenue, 10-12: upsert_gap × 3 = 7 calls
        #   profit_margin (same shape):  13-19                              = 7 calls
        #   health_score (separate table): 20-26                            = 7 calls
        calls = [
            revenue_snapshot,   # 0
            prev_ranks,         # 1
            None,               # 2 upsert ranking
            None, None, None,   # 3-5 upsert gap ×3

            revenue_snapshot,   # 6
            prev_ranks,         # 7
            None,               # 8 upsert ranking
            (100000.0,),        # 9 fetch_store_revenue
            None, None, None,   # 10-12 upsert gap ×3

            revenue_snapshot,   # 13
            prev_ranks,         # 14
            None,               # 15 upsert ranking
            (100000.0,),        # 16 fetch_store_revenue
            None, None, None,   # 17-19 upsert gap ×3

            health_snapshot,    # 20
            prev_ranks,         # 21
            None,               # 22 upsert ranking
            (100000.0,),        # 23 fetch_store_revenue
            None, None, None,   # 24-26 upsert gap ×3
        ]
        db = _make_db(calls)
        result = await compute_period_rankings(db, "2024-07")
        assert result["ranking_rows"] == 4   # 4 metrics × 1 store
        assert result["store_count"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# get_store_ranking
# ══════════════════════════════════════════════════════════════════════════════

class TestGetStoreRanking:
    @pytest.mark.asyncio
    async def test_returns_none_when_empty(self):
        db = _make_db([[]])
        result = await get_store_ranking(db, "S001", "2024-07")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_metrics_dict(self):
        rows = [
            ("health_score", 75.5, 2, 10, 80.0, "top", 3, "improved"),
            ("revenue", 100000, 1, 10, 100.0, "top", 2, "improved"),
        ]
        db = _make_db([rows])
        result = await get_store_ranking(db, "S001", "2024-07")
        assert result is not None
        assert "health_score" in result["metrics"]
        assert result["metrics"]["health_score"]["rank"] == 2
        assert result["metrics"]["health_score"]["tier"] == "top"


# ══════════════════════════════════════════════════════════════════════════════
# get_leaderboard
# ══════════════════════════════════════════════════════════════════════════════

class TestGetLeaderboard:
    @pytest.mark.asyncio
    async def test_returns_ordered_list(self):
        rows = [
            ("S001", 100.0, 1, 10, 100.0, "top", "improved"),
            ("S002", 90.0,  2, 10, 88.0,  "top", "stable"),
        ]
        db = _make_db([rows])
        board = await get_leaderboard(db, "2024-07", "health_score", limit=10)
        assert len(board) == 2
        assert board[0]["store_id"] == "S001"
        assert board[0]["rank"] == 1

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        board = await get_leaderboard(db, "2024-07", "health_score")
        assert board == []


# ══════════════════════════════════════════════════════════════════════════════
# get_benchmark_gaps
# ══════════════════════════════════════════════════════════════════════════════

class TestGetBenchmarkGaps:
    @pytest.mark.asyncio
    async def test_returns_gap_list(self):
        rows = [
            ("revenue", "best",         80000, 100000, -20.0, "below", 20000.0),
            ("revenue", "median",       80000, 90000,  -11.1, "below", 10000.0),
            ("revenue", "top_quartile", 80000, 95000,  -15.8, "below", 15000.0),
        ]
        db = _make_db([rows])
        gaps = await get_benchmark_gaps(db, "S001", "2024-07")
        assert len(gaps) == 3
        assert gaps[0]["metric"] == "revenue"
        assert gaps[0]["gap_direction"] == "below"

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        gaps = await get_benchmark_gaps(db, "S001", "2024-07")
        assert gaps == []


# ══════════════════════════════════════════════════════════════════════════════
# get_ranking_trend
# ══════════════════════════════════════════════════════════════════════════════

class TestGetRankingTrend:
    @pytest.mark.asyncio
    async def test_returns_ascending(self):
        rows = [
            ("2024-07", 3, 10, 60.0, "above_avg", "stable"),
            ("2024-06", 4, 10, 44.0, "below_avg", "declined"),
            ("2024-05", 2, 10, 77.0, "top", "improved"),
        ]
        db = _make_db([rows])
        trend = await get_ranking_trend(db, "S001", "health_score", periods=6)
        # reversed from DESC query
        assert trend[0]["period"] == "2024-05"
        assert trend[-1]["period"] == "2024-07"

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        trend = await get_ranking_trend(db, "S001", "health_score")
        assert trend == []


# ══════════════════════════════════════════════════════════════════════════════
# get_brand_ranking_summary
# ══════════════════════════════════════════════════════════════════════════════

class TestGetBrandRankingSummary:
    @pytest.mark.asyncio
    async def test_aggregates_tiers(self):
        rows = [
            ("S001", "health_score", 1, 3, 100.0, "top", 85.0),
            ("S002", "health_score", 2, 3, 50.0, "above_avg", 72.0),
            ("S003", "health_score", 3, 3, 0.0,  "laggard",   55.0),
            ("S001", "revenue", 1, 3, 100.0, "top",       100000.0),
            ("S002", "revenue", 2, 3, 50.0,  "above_avg",  90000.0),
            ("S003", "revenue", 3, 3, 0.0,   "laggard",    70000.0),
        ]
        db = _make_db([rows])
        summary = await get_brand_ranking_summary(db, "B001", "2024-07")
        assert summary["tier_counts"]["top"] == 1
        assert summary["tier_counts"]["laggard"] == 1
        assert "health_score" in summary["by_metric"]
        assert summary["by_metric"]["health_score"]["best_store"] == "S001"

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        summary = await get_brand_ranking_summary(db, "B001", "2024-07")
        assert summary["total_stores"] == 0
        assert summary["by_metric"] == {}
