"""Tests for Phase 3 Month 6 — Platform Analytics API"""
import os
import sys
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with patch("src.core.config", create=True):
    from src.api.platform_analytics import (
        _last_n_months,
        _row_to_dict,
        get_platform_overview,
        get_revenue_trends,
        get_top_plugins,
        log_api_usage,
        get_usage_stats,
        rate_plugin,
        get_plugin_ratings,
        LogUsageRequest,
        RatePluginRequest,
    )


# ── Helpers ────────────────────────────────────────────────────────────────────


def make_db(first_return=None, fetchall_return=None):
    db = AsyncMock()
    result = MagicMock()
    result.first.return_value = first_return
    result.fetchall.return_value = fetchall_return or []
    db.execute.return_value = result
    return db


def make_row(**kwargs):
    row = MagicMock()
    row._mapping = kwargs
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


# ── _last_n_months ─────────────────────────────────────────────────────────────


class TestLastNMonths:
    def test_returns_correct_count(self):
        result = _last_n_months(6)
        assert len(result) == 6

    def test_most_recent_is_last(self):
        result = _last_n_months(3)
        today = date.today().strftime("%Y-%m")
        assert result[-1] == today

    def test_oldest_is_first(self):
        result = _last_n_months(1)
        assert len(result) == 1
        assert result[0] == date.today().strftime("%Y-%m")

    def test_ascending_order(self):
        result = _last_n_months(6)
        assert result == sorted(result)

    def test_twelve_months(self):
        result = _last_n_months(12)
        assert len(result) == 12


# ── Platform overview ──────────────────────────────────────────────────────────


class TestPlatformOverview:
    @pytest.mark.asyncio
    async def test_overview_has_required_fields(self):
        dev_row = make_row(
            total_developers=10, active_developers=8,
            free_count=5, basic_count=3, pro_count=1, enterprise_count=1,
        )
        plugin_row = make_row(
            published_plugins=15, pending_plugins=2,
            total_installs=500, avg_rating=4.2,
        )
        rev_row = make_row(
            total_gross_fen=100000, total_net_fen=80000,
            paid_records=5, pending_records=3,
        )
        curr_row = make_row(gross_fen=20000, net_fen=16000)

        db = AsyncMock()
        call_count = 0

        async def execute_side(sql, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.first.return_value = dev_row
            elif call_count == 2:
                result.first.return_value = plugin_row
            elif call_count == 3:
                result.first.return_value = rev_row
            else:
                result.first.return_value = curr_row
            return result

        db.execute.side_effect = execute_side
        result = await get_platform_overview(db)

        for field in ["total_developers", "active_developers", "by_tier",
                      "published_plugins", "total_installs",
                      "total_gross_revenue_yuan", "total_net_payout_yuan",
                      "platform_profit_yuan", "current_month",
                      "current_month_gross_yuan"]:
            assert field in result, f"Missing: {field}"

    @pytest.mark.asyncio
    async def test_yuan_fields_are_fen_divided_by_100(self):
        dev_row = make_row(total_developers=0, active_developers=0,
                           free_count=0, basic_count=0, pro_count=0, enterprise_count=0)
        plugin_row = make_row(published_plugins=0, pending_plugins=0,
                              total_installs=0, avg_rating=0)
        rev_row = make_row(total_gross_fen=50000, total_net_fen=42500,
                           paid_records=0, pending_records=0)
        curr_row = make_row(gross_fen=10000, net_fen=8000)

        db = AsyncMock()
        call_count = 0

        async def execute_side(sql, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.first.return_value = dev_row
            elif call_count == 2:
                result.first.return_value = plugin_row
            elif call_count == 3:
                result.first.return_value = rev_row
            else:
                result.first.return_value = curr_row
            return result

        db.execute.side_effect = execute_side
        result = await get_platform_overview(db)
        assert result["total_gross_revenue_yuan"] == 500.0
        assert result["total_net_payout_yuan"] == 425.0
        assert abs(result["platform_profit_yuan"] - 75.0) < 0.01

    @pytest.mark.asyncio
    async def test_by_tier_has_all_four_tiers(self):
        dev_row = make_row(total_developers=4, active_developers=4,
                           free_count=1, basic_count=1, pro_count=1, enterprise_count=1)
        plugin_row = make_row(published_plugins=0, pending_plugins=0,
                              total_installs=0, avg_rating=0)
        rev_row = make_row(total_gross_fen=0, total_net_fen=0,
                           paid_records=0, pending_records=0)
        curr_row = make_row(gross_fen=0, net_fen=0)

        db = AsyncMock()
        call_count = 0

        async def execute_side(sql, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            rows = [dev_row, plugin_row, rev_row, curr_row]
            result.first.return_value = rows[min(call_count - 1, 3)]
            return result

        db.execute.side_effect = execute_side
        result = await get_platform_overview(db)
        assert set(result["by_tier"].keys()) == {"free", "basic", "pro", "enterprise"}


# ── Revenue trends ─────────────────────────────────────────────────────────────


class TestRevenueTrends:
    @pytest.mark.asyncio
    async def test_returns_n_trend_items(self):
        db = make_db(fetchall_return=[])
        result = await get_revenue_trends(6, db)
        assert len(result["trends"]) == 6

    @pytest.mark.asyncio
    async def test_each_trend_has_required_fields(self):
        db = make_db(fetchall_return=[])
        result = await get_revenue_trends(3, db)
        for item in result["trends"]:
            assert "period" in item
            assert "gross_yuan" in item
            assert "net_yuan" in item
            assert "platform_profit_yuan" in item
            assert "developer_count" in item

    @pytest.mark.asyncio
    async def test_periods_are_ascending(self):
        db = make_db(fetchall_return=[])
        result = await get_revenue_trends(6, db)
        periods = [t["period"] for t in result["trends"]]
        assert periods == sorted(periods)

    @pytest.mark.asyncio
    async def test_db_data_fills_in_correct_period(self):
        today_period = date.today().strftime("%Y-%m")
        db_row = make_row(
            period=today_period, gross_fen=50000, net_fen=40000, developer_count=5,
        )
        db = make_db(fetchall_return=[db_row])
        result = await get_revenue_trends(1, db)
        latest = result["trends"][-1]
        assert latest["gross_yuan"] == 500.0
        assert latest["net_yuan"] == 400.0


# ── Top plugins ────────────────────────────────────────────────────────────────


class TestTopPlugins:
    @pytest.mark.asyncio
    async def test_returns_plugin_list(self):
        plugin = make_row(
            id="plg_1", name="美团同步", icon_emoji="🔌", category="pos_integration",
            version="1.0", install_count=100, rating_avg=4.5, rating_count=10,
            tier_required="free", price_type="free", developer_name="DevCo",
        )
        db = make_db(fetchall_return=[plugin])
        result = await get_top_plugins(10, db)
        assert len(result["plugins"]) == 1
        assert result["plugins"][0]["name"] == "美团同步"

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self):
        db = make_db(fetchall_return=[])
        result = await get_top_plugins(10, db)
        assert result["plugins"] == []


# ── API usage logging ──────────────────────────────────────────────────────────


class TestUsageLog:
    @pytest.mark.asyncio
    async def test_returns_log_id(self):
        db = AsyncMock()
        db.execute.return_value = MagicMock()
        body = LogUsageRequest(
            developer_id="dev_abc",
            endpoint="/api/v1/decisions/top3",
            capability_level=2,
            is_billable=True,
            response_ms=45,
        )
        result = await log_api_usage(body, db)
        assert result["log_id"].startswith("log_")
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_minimal_fields(self):
        db = AsyncMock()
        db.execute.return_value = MagicMock()
        body = LogUsageRequest(developer_id="dev_x", endpoint="/api/v1/orders")
        result = await log_api_usage(body, db)
        assert "log_id" in result


# ── Usage stats ────────────────────────────────────────────────────────────────


class TestUsageStats:
    @pytest.mark.asyncio
    async def test_stats_structure(self):
        stats_row = make_row(
            total_calls=500, billable_calls=120,
            avg_response_ms=38.5, unique_developers=7,
        )
        db = AsyncMock()
        call_count = 0

        async def execute_side(sql, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.first.return_value = stats_row
            else:
                result.fetchall.return_value = []
            return result

        db.execute.side_effect = execute_side
        result = await get_usage_stats(None, None, db)
        assert result["total_calls"] == 500
        assert result["billable_calls"] == 120
        assert "avg_response_ms" in result
        assert "top_endpoints" in result

    @pytest.mark.asyncio
    async def test_has_top_endpoints_list(self):
        stats_row = make_row(total_calls=10, billable_calls=3,
                             avg_response_ms=20.0, unique_developers=1)
        ep_row = make_row(endpoint="/api/v1/orders", call_count=10)
        db = AsyncMock()
        call_count = 0

        async def execute_side(sql, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.first.return_value = stats_row
            else:
                result.fetchall.return_value = [ep_row]
            return result

        db.execute.side_effect = execute_side
        result = await get_usage_stats("dev_x", "2026-03", db)
        assert len(result["top_endpoints"]) == 1
        assert result["top_endpoints"][0]["call_count"] == 10


# ── Plugin ratings ─────────────────────────────────────────────────────────────


class TestRatePlugin:
    @pytest.mark.asyncio
    async def test_valid_rating_succeeds(self):
        plugin_row = make_row(id="plg_1")
        install_row = make_row(exists=1)
        db = AsyncMock()
        call_count = 0

        async def execute_side(sql, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.first.return_value = plugin_row if call_count == 1 else install_row
            return result

        db.execute.side_effect = execute_side
        body = RatePluginRequest(store_id="STORE001", rating=5, comment="Great!")
        result = await rate_plugin("plg_1", body, db)
        assert result["rating"] == 5
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_rating_zero_returns_400(self):
        from fastapi import HTTPException
        body = RatePluginRequest(store_id="STORE001", rating=0)
        with pytest.raises(HTTPException) as exc:
            await rate_plugin("plg_1", body, AsyncMock())
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_rating_six_returns_400(self):
        from fastapi import HTTPException
        body = RatePluginRequest(store_id="STORE001", rating=6)
        with pytest.raises(HTTPException) as exc:
            await rate_plugin("plg_1", body, AsyncMock())
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_plugin_not_found_returns_404(self):
        db = make_db(first_return=None)
        from fastapi import HTTPException
        body = RatePluginRequest(store_id="STORE001", rating=4)
        with pytest.raises(HTTPException) as exc:
            await rate_plugin("plg_missing", body, db)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_not_installed_returns_403(self):
        plugin_row = make_row(id="plg_1")
        db = AsyncMock()
        call_count = 0

        async def execute_side(sql, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.first.return_value = plugin_row if call_count == 1 else None
            return result

        db.execute.side_effect = execute_side
        from fastapi import HTTPException
        body = RatePluginRequest(store_id="STORE999", rating=3)
        with pytest.raises(HTTPException) as exc:
            await rate_plugin("plg_1", body, db)
        assert exc.value.status_code == 403


# ── Get plugin ratings ─────────────────────────────────────────────────────────


class TestGetRatings:
    @pytest.mark.asyncio
    async def test_ratings_structure(self):
        summary_row = make_row(
            avg_rating=4.3, total_ratings=15,
            five_star_count=8, four_plus_count=12,
        )
        db = AsyncMock()
        call_count = 0

        async def execute_side(sql, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.first.return_value = summary_row
            else:
                result.fetchall.return_value = []
            return result

        db.execute.side_effect = execute_side
        result = await get_plugin_ratings("plg_1", db)
        assert result["avg_rating"] == 4.3
        assert result["total_ratings"] == 15
        assert "five_star_count" in result
        assert "four_plus_count" in result
        assert "ratings" in result

    @pytest.mark.asyncio
    async def test_empty_ratings(self):
        summary_row = make_row(avg_rating=0, total_ratings=0,
                               five_star_count=0, four_plus_count=0)
        db = AsyncMock()
        call_count = 0

        async def execute_side(sql, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.first.return_value = summary_row
            else:
                result.fetchall.return_value = []
            return result

        db.execute.side_effect = execute_side
        result = await get_plugin_ratings("plg_empty", db)
        assert result["avg_rating"] == 0.0
        assert result["ratings"] == []
