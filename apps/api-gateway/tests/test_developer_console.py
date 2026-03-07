"""
Tests for Phase 4 Month 12 — ISV 开发者控制台
Run: python3 -m pytest tests/test_developer_console.py -v
"""
from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with patch("src.core.config", create=True):
    from src.api.developer_console import (
        _float,
        get_console_overview,
        compute_snapshot,
        get_api_trend,
        get_developer_plugins_health,
        get_developer_revenue,
        get_developer_leaderboard,
    )


# ── TestHelpers ───────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_float_none_returns_zero(self):
        self.assertEqual(_float(None), 0.0)

    def test_float_decimal_converted(self):
        self.assertAlmostEqual(_float(Decimal("3.14")), 3.14)

    def test_float_int_converted(self):
        self.assertEqual(_float(5), 5.0)

    def test_float_float_passthrough(self):
        self.assertAlmostEqual(_float(2.718), 2.718)


# ── TestConsoleOverview ───────────────────────────────────────────────────────

class TestConsoleOverview(unittest.IsolatedAsyncioTestCase):

    def _make_db(self, dev_exists=True):
        db = AsyncMock()

        async def execute_side(stmt, params=None):
            stmt_str = str(stmt)
            result = MagicMock()

            if "isv_developers" in stmt_str and "SELECT *" in stmt_str:
                if dev_exists:
                    mock_row = MagicMock()
                    mock_row._mapping = {
                        "id": "dev-1", "company_name": "TestCo",
                        "tier": "basic", "status": "active",
                    }
                    result.fetchone.return_value = mock_row
                else:
                    result.fetchone.return_value = None

            elif "api_usage_logs" in stmt_str:
                mock_row = MagicMock()
                mock_row.total = 5000
                mock_row.billable = 3000
                result.fetchone.return_value = mock_row

            elif "marketplace_plugins" in stmt_str and "AVG" in stmt_str:
                mock_row = MagicMock()
                mock_row.total = 3
                mock_row.published = 2
                mock_row.installs = 150
                mock_row.avgr = Decimal("4.2")
                result.fetchone.return_value = mock_row

            elif "revenue_share_records" in stmt_str and "SUM" in stmt_str:
                mock_row = MagicMock()
                mock_row.pending_fen = 50000    # 500 yuan
                mock_row.paid_fen = 200000      # 2000 yuan
                result.fetchone.return_value = mock_row

            elif "webhook_subscriptions" in stmt_str and "failure_count" in stmt_str:
                mock_row = MagicMock()
                mock_row.total = 3
                mock_row.failing = 1
                result.fetchone.return_value = mock_row

            elif "developer_console_snapshots" in stmt_str:
                result.fetchone.return_value = None

            return result

        db.execute = execute_side
        db.commit = AsyncMock()
        return db

    async def test_overview_has_required_fields(self):
        db = self._make_db()
        result = await get_console_overview("dev-1", db)
        self.assertIn("developer", result)
        self.assertIn("api_usage", result)
        self.assertIn("plugin_summary", result)
        self.assertIn("revenue_summary", result)
        self.assertIn("webhook_health", result)
        self.assertIn("as_of", result)

    async def test_developer_info_populated(self):
        db = self._make_db()
        result = await get_console_overview("dev-1", db)
        self.assertEqual(result["developer"]["tier"], "basic")
        self.assertEqual(result["developer"]["name"], "TestCo")

    async def test_nonexistent_dev_raises_404(self):
        from fastapi import HTTPException
        db = self._make_db(dev_exists=False)
        with self.assertRaises(HTTPException) as ctx:
            await get_console_overview("no-dev", db)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_revenue_yuan_fields(self):
        db = self._make_db()
        result = await get_console_overview("dev-1", db)
        rev = result["revenue_summary"]
        self.assertIn("pending_yuan", rev)
        self.assertAlmostEqual(rev["pending_yuan"], 500.0)

    async def test_plugin_avg_rating_is_float(self):
        db = self._make_db()
        result = await get_console_overview("dev-1", db)
        ps = result["plugin_summary"]
        self.assertIsNotNone(ps["avg_rating"])
        self.assertIsInstance(ps["avg_rating"], float)


# ── TestComputeSnapshot ───────────────────────────────────────────────────────

class TestComputeSnapshot(unittest.IsolatedAsyncioTestCase):

    def _make_db(self):
        db = AsyncMock()

        async def execute_side(stmt, params=None):
            stmt_str = str(stmt)
            result = MagicMock()

            if "isv_developers" in stmt_str:
                mock_row = MagicMock()
                mock_row._mapping = {"id": "dev-1", "tier": "pro", "status": "active"}
                result.fetchone.return_value = mock_row

            elif "today_cnt" in stmt_str or "month_cnt" in stmt_str:
                mock_row = MagicMock()
                mock_row.today_cnt = 200
                mock_row.month_cnt = 5000
                result.fetchone.return_value = mock_row

            elif "marketplace_plugins" in stmt_str:
                mock_row = MagicMock()
                mock_row.pub = 2
                mock_row.inst = 100
                mock_row.avgr = Decimal("4.0")
                result.fetchone.return_value = mock_row

            elif "revenue_share_records" in stmt_str:
                mock_row = MagicMock()
                mock_row.pend = 30000
                mock_row.paid = 100000
                result.fetchone.return_value = mock_row

            elif "webhook_subscriptions" in stmt_str:
                mock_row = MagicMock()
                mock_row.cnt = 2
                mock_row.fail = 0
                result.fetchone.return_value = mock_row

            elif "api_billing_cycles" in stmt_str:
                mock_row = MagicMock()
                mock_row.free_quota = 200_000
                mock_row.billable_calls = 50_000
                result.fetchone.return_value = mock_row

            return result

        db.execute = execute_side
        db.commit = AsyncMock()
        return db

    async def test_snapshot_returns_date(self):
        db = self._make_db()
        result = await compute_snapshot("dev-1", db)
        self.assertIn("snapshot_date", result)
        self.assertIn("api_calls_today", result)

    async def test_snapshot_pending_yuan_correct(self):
        db = self._make_db()
        result = await compute_snapshot("dev-1", db)
        self.assertAlmostEqual(result["pending_settlement_yuan"], 300.0)

    async def test_quota_pct_calculated(self):
        db = self._make_db()
        result = await compute_snapshot("dev-1", db)
        # 50k / 200k * 100 = 25%
        self.assertAlmostEqual(result["api_quota_used_pct"], 25.0)


# ── TestApiTrend ──────────────────────────────────────────────────────────────

class TestApiTrend(unittest.IsolatedAsyncioTestCase):

    def _make_db(self):
        db = AsyncMock()

        async def execute_side(stmt, params=None):
            stmt_str = str(stmt)
            result = MagicMock()

            if "isv_developers" in stmt_str:
                mock_row = MagicMock()
                mock_row._mapping = {"id": "dev-1"}
                result.fetchone.return_value = mock_row

            elif "DATE(called_at)" in stmt_str:
                result.fetchall.return_value = []  # no data → all zeros

            return result

        db.execute = execute_side
        db.commit = AsyncMock()
        return db

    async def test_trend_returns_n_days(self):
        db = self._make_db()
        result = await get_api_trend("dev-1", days=7, db=db)
        self.assertEqual(len(result["trend"]), 7)

    async def test_trend_dates_ascending(self):
        db = self._make_db()
        result = await get_api_trend("dev-1", days=5, db=db)
        dates = [t["date"] for t in result["trend"]]
        self.assertEqual(dates, sorted(dates))

    async def test_missing_days_filled_with_zero(self):
        db = self._make_db()
        result = await get_api_trend("dev-1", days=7, db=db)
        for item in result["trend"]:
            self.assertEqual(item["calls"], 0)


# ── TestLeaderboard ───────────────────────────────────────────────────────────

class TestLeaderboard(unittest.IsolatedAsyncioTestCase):

    def _make_db(self, rows_data=None):
        db = AsyncMock()

        async def execute_side(stmt, params=None):
            result = MagicMock()
            mock_rows = []
            for i, (name, fen, installs) in enumerate(rows_data or []):
                r = MagicMock()
                r._mapping = {
                    "id": f"dev-{i}", "company_name": name, "tier": "pro",
                    "status": "active", "plugin_count": 2,
                    "total_installs": installs, "net_fen": fen,
                }
                mock_rows.append(r)
            result.fetchall.return_value = mock_rows
            return result

        db.execute = execute_side
        db.commit = AsyncMock()
        return db

    async def test_leaderboard_structure(self):
        db = self._make_db([("A Corp", 1000000, 500), ("B Corp", 500000, 200)])
        result = await get_developer_leaderboard(limit=10, db=db)
        self.assertIn("leaderboard", result)
        self.assertEqual(len(result["leaderboard"]), 2)

    async def test_leaderboard_rank_assigned(self):
        db = self._make_db([("A Corp", 1000000, 500)])
        result = await get_developer_leaderboard(limit=10, db=db)
        self.assertEqual(result["leaderboard"][0]["rank"], 1)

    async def test_net_yuan_is_fen_div_100(self):
        db = self._make_db([("A Corp", 50000, 100)])
        result = await get_developer_leaderboard(limit=10, db=db)
        self.assertAlmostEqual(result["leaderboard"][0]["net_yuan"], 500.0)

    async def test_empty_leaderboard(self):
        db = self._make_db([])
        result = await get_developer_leaderboard(limit=10, db=db)
        self.assertEqual(result["total"], 0)


if __name__ == "__main__":
    unittest.main()
