"""
Tests for Phase 4 Month 11 — API 计量计费
Run: python3 -m pytest tests/test_api_billing.py -v
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with patch("src.core.config", create=True):
    from src.api.api_billing import (
        FREE_QUOTA_MAP,
        PRICE_PER_1K_FEN,
        VALID_CYCLE_TRANSITIONS,
        VALID_INVOICE_TRANSITIONS,
        compute_billing,
        make_invoice_no,
        build_line_items,
        _validate_period,
        compute_billing_cycle,
        finalize_billing_cycle,
        generate_invoice,
        mark_invoice_paid,
        get_admin_billing_summary,
        ComputeCycleRequest,
    )


# ── TestConstants ─────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):

    def test_all_tiers_in_free_quota(self):
        for tier in ("free", "basic", "pro", "enterprise"):
            self.assertIn(tier, FREE_QUOTA_MAP)

    def test_free_quota_ascending(self):
        quotas = [FREE_QUOTA_MAP[t] for t in ("free", "basic", "pro", "enterprise")]
        self.assertEqual(quotas, sorted(quotas))

    def test_all_tiers_in_price_map(self):
        for tier in ("free", "basic", "pro", "enterprise"):
            self.assertIn(tier, PRICE_PER_1K_FEN)

    def test_free_tier_price_is_zero(self):
        self.assertEqual(PRICE_PER_1K_FEN["free"], 0)

    def test_enterprise_cheapest_per_call(self):
        # Enterprise has lowest per-call price (but also highest free quota)
        non_free = {k: v for k, v in PRICE_PER_1K_FEN.items() if k != "free" and v > 0}
        self.assertEqual(min(non_free.values()), PRICE_PER_1K_FEN["enterprise"])

    def test_cycle_transitions_fsm(self):
        self.assertIn("finalized", VALID_CYCLE_TRANSITIONS["draft"])
        self.assertIn("invoiced", VALID_CYCLE_TRANSITIONS["finalized"])
        self.assertEqual(VALID_CYCLE_TRANSITIONS["invoiced"], set())

    def test_invoice_transitions_fsm(self):
        self.assertIn("paid", VALID_INVOICE_TRANSITIONS["unpaid"])
        self.assertIn("void", VALID_INVOICE_TRANSITIONS["unpaid"])
        self.assertEqual(VALID_INVOICE_TRANSITIONS["paid"], set())


# ── TestComputeBilling ────────────────────────────────────────────────────────

class TestComputeBilling(unittest.TestCase):

    def test_within_free_quota_no_charge(self):
        result = compute_billing(1000, "basic")   # basic quota = 50,000
        self.assertEqual(result["amount_fen"], 0)
        self.assertEqual(result["overage_calls"], 0)

    def test_overage_calculated_correctly(self):
        # basic: 50k free, price 50 fen/1000
        result = compute_billing(51_000, "basic")
        self.assertEqual(result["overage_calls"], 1000)
        self.assertEqual(result["amount_fen"], 50)  # 1000 * 50 / 1000
        self.assertAlmostEqual(result["amount_yuan"], 0.50)

    def test_free_tier_never_charged(self):
        result = compute_billing(999_999, "free")
        self.assertEqual(result["amount_fen"], 0)
        self.assertEqual(result["amount_yuan"], 0.0)

    def test_pro_tier_billing(self):
        # pro: 200k free, price 30 fen/1000
        result = compute_billing(210_000, "pro")
        self.assertEqual(result["overage_calls"], 10_000)
        self.assertEqual(result["amount_fen"], 300)  # 10000 * 30 / 1000
        self.assertAlmostEqual(result["amount_yuan"], 3.00)

    def test_enterprise_billing(self):
        # enterprise: 1M free, price 15 fen/1000
        result = compute_billing(2_000_000, "enterprise")
        self.assertEqual(result["overage_calls"], 1_000_000)
        self.assertEqual(result["amount_fen"], 15_000)  # 1M * 15 / 1000
        self.assertAlmostEqual(result["amount_yuan"], 150.0)

    def test_yuan_equals_fen_div_100(self):
        result = compute_billing(55_000, "basic")
        self.assertAlmostEqual(result["amount_yuan"], result["amount_fen"] / 100)

    def test_zero_calls(self):
        result = compute_billing(0, "pro")
        self.assertEqual(result["amount_fen"], 0)
        self.assertEqual(result["overage_calls"], 0)

    def test_unknown_tier_uses_free_defaults(self):
        result = compute_billing(999_999, "unknown")
        # unknown tier → free defaults → no charge
        self.assertEqual(result["amount_fen"], 0)


# ── TestHelpers ───────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_make_invoice_no_format(self):
        no = make_invoice_no("dev-abc123", "2026-03")
        self.assertTrue(no.startswith("INV-2026-03-"))

    def test_make_invoice_no_deterministic(self):
        no1 = make_invoice_no("dev-abc", "2026-03")
        no2 = make_invoice_no("dev-abc", "2026-03")
        self.assertEqual(no1, no2)

    def test_build_line_items_no_overage(self):
        billing = {"free_quota": 50000, "overage_calls": 0, "amount_fen": 0, "amount_yuan": 0.0}
        items = build_line_items("basic", 10000, billing)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["amount_yuan"], 0.0)

    def test_build_line_items_with_overage(self):
        billing = {"free_quota": 50000, "overage_calls": 1000, "amount_fen": 50, "amount_yuan": 0.5}
        items = build_line_items("basic", 51000, billing)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[1]["quantity"], 1000)

    def test_validate_period_valid(self):
        _validate_period("2026-03")  # should not raise

    def test_validate_period_invalid_format_raises(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            _validate_period("2026-3")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_period_month_13_raises(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            _validate_period("2026-13")


# ── TestComputeBillingCycle ───────────────────────────────────────────────────

class TestComputeBillingCycle(unittest.IsolatedAsyncioTestCase):

    def _make_db(self, *, dev_tier="basic", existing_status=None, call_count=1000):
        db = AsyncMock()

        async def execute_side(stmt, params=None):
            stmt_str = str(stmt)
            result = MagicMock()

            if "isv_developers" in stmt_str:
                if dev_tier:
                    mock_row = MagicMock()
                    mock_row.id = "dev-1"
                    mock_row.tier = dev_tier
                    result.fetchone.return_value = mock_row
                else:
                    result.fetchone.return_value = None

            elif "SELECT * FROM api_billing_cycles" in stmt_str:
                if existing_status:
                    mock_row = MagicMock()
                    mock_row._mapping = {
                        "id": "cycle-1", "developer_id": "dev-1",
                        "period": "2026-03", "status": existing_status,
                        "total_calls": 1000, "billable_calls": 1000,
                        "free_quota": 50000, "overage_calls": 0,
                        "amount_fen": 0, "amount_yuan": 0.0,
                    }
                    result.fetchone.return_value = mock_row
                else:
                    result.fetchone.return_value = None

            elif "COUNT(*)" in stmt_str:
                mock_row = MagicMock()
                mock_row.cnt = call_count
                result.fetchone.return_value = mock_row

            return result

        db.execute = execute_side
        db.commit = AsyncMock()
        return db

    async def test_new_cycle_created(self):
        db = self._make_db()
        req = ComputeCycleRequest(developer_id="dev-1", period="2026-03")
        result = await compute_billing_cycle(req, db)
        self.assertIn("cycle_id", result)
        self.assertEqual(result["period"], "2026-03")
        self.assertEqual(result["tier"], "basic")

    async def test_nonexistent_dev_raises_404(self):
        from fastapi import HTTPException
        db = self._make_db(dev_tier=None)
        req = ComputeCycleRequest(developer_id="no-dev", period="2026-03")
        with self.assertRaises(HTTPException) as ctx:
            await compute_billing_cycle(req, db)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_invalid_period_raises_400(self):
        from fastapi import HTTPException
        db = self._make_db()
        req = ComputeCycleRequest(developer_id="dev-1", period="2026-3")
        with self.assertRaises(HTTPException) as ctx:
            await compute_billing_cycle(req, db)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_finalized_cycle_not_recomputed(self):
        from fastapi import HTTPException
        db = self._make_db(existing_status="finalized")
        req = ComputeCycleRequest(developer_id="dev-1", period="2026-03")
        with self.assertRaises(HTTPException) as ctx:
            await compute_billing_cycle(req, db)
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_draft_cycle_can_be_recomputed(self):
        db = self._make_db(existing_status="draft")
        req = ComputeCycleRequest(developer_id="dev-1", period="2026-03")
        result = await compute_billing_cycle(req, db)
        self.assertEqual(result["cycle_id"], "cycle-1")

    async def test_overage_billing_applied(self):
        db = self._make_db(dev_tier="basic", call_count=60_000)
        req = ComputeCycleRequest(developer_id="dev-1", period="2026-03")
        result = await compute_billing_cycle(req, db)
        # basic: 50k free, 10k overage @ 50 fen/1k = 500 fen = ¥5.00
        self.assertEqual(result["overage_calls"], 10_000)
        self.assertEqual(result["amount_fen"], 500)


# ── TestFinalizeAndInvoice ────────────────────────────────────────────────────

class TestFinalizeAndInvoice(unittest.IsolatedAsyncioTestCase):

    def _make_cycle_db(self, status="draft", tier="basic"):
        db = AsyncMock()

        async def execute_side(stmt, params=None):
            stmt_str = str(stmt)
            result = MagicMock()

            if "JOIN isv_developers" in stmt_str:
                mock_row = MagicMock()
                mock_row._mapping = {
                    "id": "cycle-1", "developer_id": "dev-1",
                    "period": "2026-03", "status": status,
                    "total_calls": 51000, "billable_calls": 51000,
                    "free_quota": 50000, "overage_calls": 1000,
                    "amount_fen": 50, "amount_yuan": 0.5,
                    "tier": tier,
                }
                result.fetchone.return_value = mock_row

            elif "SELECT * FROM api_billing_cycles" in stmt_str:
                mock_row = MagicMock()
                mock_row._mapping = {
                    "id": "cycle-1", "status": status
                }
                result.fetchone.return_value = mock_row

            elif "SELECT * FROM api_invoices WHERE cycle_id" in stmt_str:
                result.fetchone.return_value = None  # no existing invoice

            return result

        db.execute = execute_side
        db.commit = AsyncMock()
        return db

    async def test_finalize_draft_succeeds(self):
        db = self._make_cycle_db(status="draft")
        result = await finalize_billing_cycle("cycle-1", "dev-1", db)
        self.assertEqual(result["status"], "finalized")

    async def test_finalize_invoiced_raises_409(self):
        from fastapi import HTTPException
        db = self._make_cycle_db(status="invoiced")
        with self.assertRaises(HTTPException) as ctx:
            await finalize_billing_cycle("cycle-1", "dev-1", db)
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_generate_invoice_from_finalized(self):
        db = self._make_cycle_db(status="finalized")
        result = await generate_invoice("cycle-1", "dev-1", db)
        self.assertIn("invoice_id", result)
        self.assertIn("invoice_no", result)
        self.assertEqual(result["status"], "unpaid")

    async def test_generate_invoice_not_finalized_raises_409(self):
        from fastapi import HTTPException
        db = self._make_cycle_db(status="draft")
        with self.assertRaises(HTTPException) as ctx:
            await generate_invoice("cycle-1", "dev-1", db)
        self.assertEqual(ctx.exception.status_code, 409)


# ── TestMarkPaid ──────────────────────────────────────────────────────────────

class TestMarkPaid(unittest.IsolatedAsyncioTestCase):

    def _make_db(self, status="unpaid"):
        db = AsyncMock()

        async def execute_side(stmt, params=None):
            result = MagicMock()
            if "SELECT * FROM api_invoices WHERE id" in str(stmt):
                if status:
                    mock_row = MagicMock()
                    mock_row._mapping = {"id": "inv-1", "status": status}
                    result.fetchone.return_value = mock_row
                else:
                    result.fetchone.return_value = None
            return result

        db.execute = execute_side
        db.commit = AsyncMock()
        return db

    async def test_mark_unpaid_as_paid(self):
        db = self._make_db("unpaid")
        result = await mark_invoice_paid("inv-1", db)
        self.assertEqual(result["status"], "paid")

    async def test_already_paid_raises_409(self):
        from fastapi import HTTPException
        db = self._make_db("paid")
        with self.assertRaises(HTTPException) as ctx:
            await mark_invoice_paid("inv-1", db)
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_not_found_raises_404(self):
        from fastapi import HTTPException
        db = self._make_db(None)
        with self.assertRaises(HTTPException) as ctx:
            await mark_invoice_paid("no-inv", db)
        self.assertEqual(ctx.exception.status_code, 404)


# ── TestAdminSummary ──────────────────────────────────────────────────────────

class TestAdminSummary(unittest.IsolatedAsyncioTestCase):

    def _make_db(self):
        db = AsyncMock()

        async def execute_side(stmt, params=None):
            result = MagicMock()
            stmt_str = str(stmt)

            if "GROUP BY period" in stmt_str:
                rows = []
                for period, yuan in [("2026-01", 100.0), ("2026-02", 200.0)]:
                    r = MagicMock()
                    r.period = period
                    r.total_yuan = yuan
                    r.dev_count = 3
                    r.total_calls = 100_000
                    rows.append(r)
                result.fetchall.return_value = rows

            elif "GROUP BY status" in stmt_str:
                rows = []
                for st, cnt, yuan in [("unpaid", 2, 300.0), ("paid", 5, 1000.0)]:
                    r = MagicMock()
                    r.status = st
                    r.cnt = cnt
                    r.total_yuan = yuan
                    rows.append(r)
                result.fetchall.return_value = rows

            return result

        db.execute = execute_side
        db.commit = AsyncMock()
        return db

    async def test_summary_structure(self):
        db = self._make_db()
        result = await get_admin_billing_summary(months=6, db=db)
        self.assertIn("monthly_revenue", result)
        self.assertIn("invoice_summary", result)
        self.assertIn("outstanding_yuan", result)

    async def test_outstanding_is_unpaid_total(self):
        db = self._make_db()
        result = await get_admin_billing_summary(months=6, db=db)
        self.assertAlmostEqual(result["outstanding_yuan"], 300.0)

    async def test_monthly_revenue_ascending(self):
        db = self._make_db()
        result = await get_admin_billing_summary(months=6, db=db)
        periods = [m["period"] for m in result["monthly_revenue"]]
        self.assertEqual(periods, sorted(periods))


if __name__ == "__main__":
    unittest.main()
