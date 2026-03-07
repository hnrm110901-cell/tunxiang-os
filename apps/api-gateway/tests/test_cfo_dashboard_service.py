"""tests/test_cfo_dashboard_service.py — Phase 5 Month 6

覆盖：
  - compute_brand_grade_distribution
  - compute_brand_avg_grade
  - generate_financial_narrative
  - prioritize_brand_actions
  - get_brand_health_overview (mock DB)
  - get_brand_alert_summary   (mock DB)
  - get_brand_budget_summary  (mock DB)
  - get_brand_actions         (mock DB)
  - save_report_snapshot      (mock DB)
  - get_cfo_dashboard BFF     (mock DB)
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret")

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.cfo_dashboard_service import (
    compute_brand_grade_distribution,
    compute_brand_avg_grade,
    generate_financial_narrative,
    prioritize_brand_actions,
    get_brand_health_overview,
    get_brand_alert_summary,
    get_brand_budget_summary,
    get_brand_actions,
    save_report_snapshot,
    get_cfo_dashboard,
    GRADE_THRESHOLDS,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _mock_db(rows_by_query=None):
    """Build an async DB mock where execute returns preset rows."""
    db = AsyncMock()
    rows_by_query = rows_by_query or {}
    call_count = [0]

    async def _execute(stmt, params=None):
        result = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        all_rows = list(rows_by_query.values())
        if idx < len(all_rows):
            result.fetchall.return_value = all_rows[idx]
        else:
            result.fetchall.return_value = []
        return result

    db.execute = _execute
    db.commit = AsyncMock()
    return db


# ══════════════════════════════════════════════════════════════════════════════
# 纯函数
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeBrandGradeDistribution:
    def test_all_a(self):
        dist = compute_brand_grade_distribution([85, 90, 95])
        assert dist == {"A": 3, "B": 0, "C": 0, "D": 0}

    def test_mixed(self):
        dist = compute_brand_grade_distribution([85, 70, 50, 35])
        assert dist == {"A": 1, "B": 1, "C": 1, "D": 1}

    def test_boundary_a(self):
        dist = compute_brand_grade_distribution([80.0])
        assert dist["A"] == 1

    def test_boundary_b(self):
        dist = compute_brand_grade_distribution([60.0])
        assert dist["B"] == 1

    def test_boundary_c(self):
        dist = compute_brand_grade_distribution([40.0])
        assert dist["C"] == 1

    def test_boundary_d(self):
        dist = compute_brand_grade_distribution([39.9])
        assert dist["D"] == 1

    def test_empty(self):
        dist = compute_brand_grade_distribution([])
        assert dist == {"A": 0, "B": 0, "C": 0, "D": 0}


class TestComputeBrandAvgGrade:
    def test_a(self):
        assert compute_brand_avg_grade(85) == "A"

    def test_b(self):
        assert compute_brand_avg_grade(65) == "B"

    def test_c(self):
        assert compute_brand_avg_grade(45) == "C"

    def test_d(self):
        assert compute_brand_avg_grade(30) == "D"

    def test_exact_80(self):
        assert compute_brand_avg_grade(80) == "A"

    def test_exact_60(self):
        assert compute_brand_avg_grade(60) == "B"

    def test_exact_40(self):
        assert compute_brand_avg_grade(40) == "C"


class TestGenerateFinancialNarrative:
    def _base_kwargs(self):
        return dict(
            avg_score=75.0,
            brand_grade="B",
            store_count=5,
            open_alerts=3,
            critical_alerts=0,
            budget_achievement_pct=92.5,
            worst_store_id="STORE003",
            worst_store_score=55.0,
            top_insight_type="profit",
        )

    def test_returns_string(self):
        result = generate_financial_narrative(**self._base_kwargs())
        assert isinstance(result, str)

    def test_within_300_chars(self):
        result = generate_financial_narrative(**self._base_kwargs())
        assert len(result) <= 300

    def test_includes_avg_score(self):
        result = generate_financial_narrative(**self._base_kwargs())
        assert "75.0" in result

    def test_critical_alert_mentioned(self):
        kwargs = self._base_kwargs()
        kwargs["critical_alerts"] = 2
        result = generate_financial_narrative(**kwargs)
        assert "严重" in result

    def test_no_alerts_stable(self):
        kwargs = self._base_kwargs()
        kwargs["open_alerts"] = 0
        kwargs["critical_alerts"] = 0
        result = generate_financial_narrative(**kwargs)
        assert "稳定" in result

    def test_over_budget_message(self):
        kwargs = self._base_kwargs()
        kwargs["budget_achievement_pct"] = 110.0
        result = generate_financial_narrative(**kwargs)
        assert "超额" in result

    def test_under_budget_message(self):
        kwargs = self._base_kwargs()
        kwargs["budget_achievement_pct"] = 65.0
        result = generate_financial_narrative(**kwargs)
        assert "偏差" in result

    def test_none_budget(self):
        kwargs = self._base_kwargs()
        kwargs["budget_achievement_pct"] = None
        result = generate_financial_narrative(**kwargs)
        assert isinstance(result, str)

    def test_worst_store_mentioned(self):
        result = generate_financial_narrative(**self._base_kwargs())
        assert "STORE003" in result

    def test_insight_type_label(self):
        result = generate_financial_narrative(**self._base_kwargs())
        assert "利润率" in result

    def test_cash_insight_label(self):
        kwargs = self._base_kwargs()
        kwargs["top_insight_type"] = "cash"
        result = generate_financial_narrative(**kwargs)
        assert "现金流" in result

    def test_no_worst_store(self):
        kwargs = self._base_kwargs()
        kwargs["worst_store_id"] = None
        kwargs["worst_store_score"] = None
        result = generate_financial_narrative(**kwargs)
        assert isinstance(result, str)


class TestPrioritizeBrandActions:
    def _insights(self):
        return [
            {"store_id": "S1", "insight_type": "profit", "priority": "high",   "content": "利润率低"},
            {"store_id": "S2", "insight_type": "cash",   "priority": "medium", "content": "现金缺口大"},
            {"store_id": "S3", "insight_type": "tax",    "priority": "low",    "content": "税务偏差小"},
        ]

    def _alerts(self):
        return [
            {"store_id": "S1", "metric": "food_cost_rate", "severity": "critical", "message": "食材成本超标", "event_id": "evt1"},
            {"store_id": "S2", "metric": "cash_gap_days",  "severity": "medium",   "message": "资金缺口", "event_id": "evt2"},
        ]

    def test_returns_list(self):
        result = prioritize_brand_actions(self._insights(), self._alerts())
        assert isinstance(result, list)

    def test_max_15(self):
        big_insights = [
            {"store_id": f"S{i}", "insight_type": "profit", "priority": "high", "content": "x"}
            for i in range(20)
        ]
        result = prioritize_brand_actions(big_insights, [])
        assert len(result) <= 15

    def test_high_priority_before_low(self):
        result = prioritize_brand_actions(self._insights(), [])
        priorities = [r["priority"] for r in result]
        high_idx = priorities.index("high")
        low_idx  = priorities.index("low")
        assert high_idx < low_idx

    def test_critical_alert_is_high_priority(self):
        result = prioritize_brand_actions([], self._alerts())
        critical = [r for r in result if r.get("source") == "alert" and "evt1" in r.get("action_id", "")]
        assert critical[0]["priority"] == "high"

    def test_source_tagged(self):
        result = prioritize_brand_actions(self._insights(), self._alerts())
        sources = {r["source"] for r in result}
        assert "insight" in sources
        assert "alert" in sources

    def test_empty_inputs(self):
        result = prioritize_brand_actions([], [])
        assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# DB 函数
# ══════════════════════════════════════════════════════════════════════════════

class TestGetBrandHealthOverview:
    @pytest.mark.asyncio
    async def test_no_data_returns_empty(self):
        db = _mock_db({"health": []})
        result = await get_brand_health_overview(db, "BRAND001", "2026-03")
        assert result["store_count"] == 0
        assert result["avg_score"] == 0.0
        assert result["best_store"] is None

    @pytest.mark.asyncio
    async def test_single_store(self):
        rows = [("STORE001", 82.5, "A", 28.0, 18.0, 16.0, 12.0, 8.5)]
        db = _mock_db({"health": rows})
        result = await get_brand_health_overview(db, "BRAND001", "2026-03")
        assert result["store_count"] == 1
        assert result["avg_score"] == 82.5
        assert result["best_store"]["store_id"] == "STORE001"
        assert result["worst_store"]["store_id"] == "STORE001"

    @pytest.mark.asyncio
    async def test_multiple_stores_sorted(self):
        # get_brand_health_overview expects ORDER BY total_score DESC from DB
        rows = [
            ("STORE001", 88.0, "A", 26.0, 18.0, 18.0, 14.0, 12.0),
            ("STORE002", 62.0, "B", 18.0, 14.0, 12.0, 10.0,  8.0),
            ("STORE003", 42.0, "C", 12.0, 10.0,  8.0,  8.0,  4.0),
        ]
        db = _mock_db({"health": rows})
        result = await get_brand_health_overview(db, "BRAND001", "2026-03")
        assert result["store_count"] == 3
        assert result["best_store"]["store_id"] == "STORE001"
        assert result["worst_store"]["store_id"] == "STORE003"
        assert result["grade_distribution"] == {"A": 1, "B": 1, "C": 1, "D": 0}
        avg = (88.0 + 62.0 + 42.0) / 3
        assert abs(result["avg_score"] - avg) < 0.01


class TestGetBrandAlertSummary:
    @pytest.mark.asyncio
    async def test_no_alerts(self):
        db = _mock_db({"alerts": []})
        result = await get_brand_alert_summary(db, "BRAND001")
        assert result["open_count"] == 0
        assert result["critical_count"] == 0
        assert result["by_store"] == []

    @pytest.mark.asyncio
    async def test_counts(self):
        rows = [
            ("STORE001", "critical", "open",         "food_cost_rate", "食材超标", 1),
            ("STORE001", "medium",   "acknowledged",  "tax_deviation",  "税务偏差", 2),
            ("STORE002", "high",     "open",           "cash_gap_days",  "现金缺口", 3),
        ]
        db = _mock_db({"alerts": rows})
        result = await get_brand_alert_summary(db, "BRAND001")
        assert result["open_count"] == 2
        assert result["critical_count"] == 1
        assert result["acknowledged_count"] == 1
        assert result["total_count"] == 3

    @pytest.mark.asyncio
    async def test_by_store_grouping(self):
        rows = [
            ("STORE001", "critical", "open", "food_cost_rate", "msg", 1),
            ("STORE001", "high",     "open", "cash_gap_days",  "msg", 2),
            ("STORE002", "medium",   "open", "tax_deviation",  "msg", 3),
        ]
        db = _mock_db({"alerts": rows})
        result = await get_brand_alert_summary(db, "BRAND001")
        store_ids = {g["store_id"] for g in result["by_store"]}
        assert "STORE001" in store_ids
        assert "STORE002" in store_ids


class TestGetBrandBudgetSummary:
    @pytest.mark.asyncio
    async def test_no_plans(self):
        db = _mock_db({"plans": []})
        result = await get_brand_budget_summary(db, "BRAND001", "2026-03")
        assert result["store_count_with_budget"] == 0
        assert result["avg_achievement_pct"] is None

    @pytest.mark.asyncio
    async def test_over_achievement(self):
        # 3 queries: plans, budget_line_items, profit_attribution_results
        plan_rows   = [(1, "STORE001", "active")]
        budget_rows = [(1, 100000.0)]   # 预算10万
        actual_rows = [("STORE001", 110000.0)]  # 实际11万

        call_idx = [0]
        results_seq = [plan_rows, budget_rows, actual_rows]

        db = AsyncMock()
        async def _exec(stmt, params=None):
            r = MagicMock()
            idx = call_idx[0]
            call_idx[0] += 1
            r.fetchall.return_value = results_seq[idx] if idx < len(results_seq) else []
            return r
        db.execute = _exec
        db.commit = AsyncMock()

        result = await get_brand_budget_summary(db, "BRAND001", "2026-03")
        assert result["store_count_with_budget"] == 1
        assert result["avg_achievement_pct"] == 110.0
        assert result["over_budget_count"] == 1
        assert result["under_budget_count"] == 0

    @pytest.mark.asyncio
    async def test_under_achievement(self):
        plan_rows   = [(1, "STORE001", "active")]
        budget_rows = [(1, 100000.0)]
        actual_rows = [("STORE001", 75000.0)]

        call_idx = [0]
        results_seq = [plan_rows, budget_rows, actual_rows]

        db = AsyncMock()
        async def _exec(stmt, params=None):
            r = MagicMock()
            idx = call_idx[0]
            call_idx[0] += 1
            r.fetchall.return_value = results_seq[idx] if idx < len(results_seq) else []
            return r
        db.execute = _exec
        db.commit = AsyncMock()

        result = await get_brand_budget_summary(db, "BRAND001", "2026-03")
        assert result["avg_achievement_pct"] == 75.0
        assert result["under_budget_count"] == 1


class TestGetBrandActions:
    @pytest.mark.asyncio
    async def test_empty(self):
        db = _mock_db({"insights": []})
        result = await get_brand_actions(db, "BRAND001", "2026-03")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_dicts(self):
        rows = [
            ("STORE001", "profit", "high",   "利润率偏低"),
            ("STORE002", "cash",   "medium", "现金缺口"),
        ]
        db = _mock_db({"insights": rows})
        result = await get_brand_actions(db, "BRAND001", "2026-03")
        assert len(result) == 2
        assert result[0]["store_id"] == "STORE001"
        assert result[0]["insight_type"] == "profit"
        assert result[0]["priority"] == "high"
        assert result[0]["content"] == "利润率偏低"


class TestSaveReportSnapshot:
    @pytest.mark.asyncio
    async def test_calls_execute_and_commit(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        data = {
            "narrative": "test",
            "store_count": 3,
            "avg_health_score": 75.0,
            "brand_grade": "B",
            "open_alerts_count": 2,
            "critical_alerts_count": 0,
            "budget_achievement_pct": 88.0,
        }
        await save_report_snapshot(db, "BRAND001", "2026-03", data)
        db.execute.assert_called_once()
        db.commit.assert_called_once()


class TestGetCfoDashboard:
    @pytest.mark.asyncio
    async def test_degraded_empty_db(self):
        """When DB returns empty results for all sub-queries, BFF should not crash."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(fetchall=lambda: []))
        db.commit = AsyncMock()
        result = await get_cfo_dashboard(db, "BRAND001", "2026-03")
        assert result["brand_id"] == "BRAND001"
        assert result["period"] == "2026-03"
        assert "health_overview" in result
        assert "alert_summary" in result
        assert "budget_summary" in result
        assert "actions" in result
        assert "narrative" in result

    @pytest.mark.asyncio
    async def test_brand_grade_in_result(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(fetchall=lambda: []))
        db.commit = AsyncMock()
        result = await get_cfo_dashboard(db, "BRAND001", "2026-03")
        assert result["brand_grade"] in ("A", "B", "C", "D", "—")

    @pytest.mark.asyncio
    async def test_partial_failure_does_not_crash(self):
        """If one sub-service fails with exception, BFF still returns."""
        db = AsyncMock()
        call_count = [0]

        async def _failing_exec(stmt, params=None):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("DB error")
            r = MagicMock()
            r.fetchall.return_value = []
            return r

        db.execute = _failing_exec
        db.commit = AsyncMock()
        result = await get_cfo_dashboard(db, "BRAND001", "2026-03")
        assert "brand_id" in result
