"""Tests for Phase 3 Month 5 — Revenue Sharing API"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with patch("src.core.config", create=True):
    from src.api.revenue_sharing import (
        SHARE_PCT_MAP,
        VALID_TRANSITIONS,
        CALLS_PER_INSTALL_ESTIMATE,
        _add_yuan,
        _validate_period,
        generate_settlements,
        list_settlements,
        update_settlement_status,
        get_admin_summary,
        get_developer_summary,
        get_developer_settlements,
        get_developer_plugins,
        GenerateSettlementsRequest,
        UpdateSettlementStatusRequest,
    )


# ── Helpers ────────────────────────────────────────────────────────────────────


def make_db(first_return=None, scalar_return=0, fetchall_return=None):
    db = AsyncMock()
    result = MagicMock()
    result.first.return_value = first_return
    result.scalar.return_value = scalar_return
    result.fetchall.return_value = fetchall_return or []
    db.execute.return_value = result
    return db


def make_row(**kwargs):
    row = MagicMock()
    row._mapping = kwargs
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


# ── Constants ──────────────────────────────────────────────────────────────────


class TestSharePctMap:
    def test_free_tier_gets_zero(self):
        assert SHARE_PCT_MAP["free"] == 0.0

    def test_enterprise_tier_is_highest(self):
        assert SHARE_PCT_MAP["enterprise"] == max(SHARE_PCT_MAP.values())

    def test_all_four_tiers_present(self):
        assert set(SHARE_PCT_MAP.keys()) == {"free", "basic", "pro", "enterprise"}

    def test_tiers_ascending_order(self):
        tiers = ["free", "basic", "pro", "enterprise"]
        values = [SHARE_PCT_MAP[t] for t in tiers]
        assert values == sorted(values)

    def test_calls_estimate_positive(self):
        assert CALLS_PER_INSTALL_ESTIMATE > 0


class TestValidTransitions:
    def test_pending_can_go_to_approved(self):
        assert "approved" in VALID_TRANSITIONS["pending"]

    def test_approved_can_go_to_paid(self):
        assert "paid" in VALID_TRANSITIONS["approved"]

    def test_paid_is_terminal(self):
        assert len(VALID_TRANSITIONS["paid"]) == 0

    def test_pending_cannot_skip_to_paid(self):
        assert "paid" not in VALID_TRANSITIONS["pending"]


# ── Helpers ────────────────────────────────────────────────────────────────────


class TestAddYuan:
    def test_adds_yuan_fields(self):
        record = {"gross_revenue_fen": 5000, "net_payout_fen": 3500}
        result = _add_yuan(record)
        assert result["gross_revenue_yuan"] == 50.0
        assert result["net_payout_yuan"] == 35.0

    def test_handles_missing_fields(self):
        result = _add_yuan({})
        assert result["gross_revenue_yuan"] == 0.0
        assert result["net_payout_yuan"] == 0.0


class TestValidatePeriod:
    def test_valid_period_passes(self):
        _validate_period("2026-03")  # no exception

    def test_invalid_format_raises(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _validate_period("2026-3")
        assert exc.value.status_code == 400

    def test_invalid_month_raises(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _validate_period("2026-13")
        assert exc.value.status_code == 400

    def test_wrong_format_raises(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _validate_period("March 2026")
        assert exc.value.status_code == 400


# ── Settlement generation ──────────────────────────────────────────────────────


class TestGenerateSettlements:
    @pytest.mark.asyncio
    async def test_invalid_period_returns_400(self):
        from fastapi import HTTPException
        body = GenerateSettlementsRequest(period="2026-15")
        with pytest.raises(HTTPException) as exc:
            await generate_settlements(body, AsyncMock())
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_no_devs_returns_zero_counts(self):
        db = make_db(fetchall_return=[])
        body = GenerateSettlementsRequest(period="2026-03")
        result = await generate_settlements(body, db)
        assert result["created"] == 0
        assert result["updated"] == 0
        assert result["total"] == 0
        assert result["period"] == "2026-03"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_period_in_response(self):
        db = make_db(fetchall_return=[])
        body = GenerateSettlementsRequest(period="2026-01")
        result = await generate_settlements(body, db)
        assert result["period"] == "2026-01"


# ── Settlement status update ───────────────────────────────────────────────────


class TestSettlementStatusUpdate:
    @pytest.mark.asyncio
    async def test_approve_pending_settlement(self):
        record = make_row(id="rsr_1", status="pending")
        db = make_db(first_return=record)
        body = UpdateSettlementStatusRequest(status="approved")
        result = await update_settlement_status("rsr_1", body, db)
        assert result["status"] == "approved"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_pay_approved_settlement(self):
        record = make_row(id="rsr_2", status="approved")
        db = make_db(first_return=record)
        body = UpdateSettlementStatusRequest(status="paid")
        result = await update_settlement_status("rsr_2", body, db)
        assert result["status"] == "paid"

    @pytest.mark.asyncio
    async def test_pending_to_paid_returns_400(self):
        record = make_row(id="rsr_3", status="pending")
        db = make_db(first_return=record)
        body = UpdateSettlementStatusRequest(status="paid")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await update_settlement_status("rsr_3", body, db)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_nonexistent_record_returns_404(self):
        db = make_db(first_return=None)
        body = UpdateSettlementStatusRequest(status="approved")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await update_settlement_status("rsr_none", body, db)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_paid_is_terminal_returns_400(self):
        record = make_row(id="rsr_5", status="paid")
        db = make_db(first_return=record)
        body = UpdateSettlementStatusRequest(status="approved")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await update_settlement_status("rsr_5", body, db)
        assert exc.value.status_code == 400


# ── Admin summary ──────────────────────────────────────────────────────────────


class TestAdminSummary:
    @pytest.mark.asyncio
    async def test_summary_has_required_fields(self):
        stats_row = make_row(
            total_gross_fen=10000,
            total_net_fen=8000,
            pending_count=3,
            approved_count=1,
            paid_count=5,
            developer_count=9,
        )
        db = make_db(first_return=stats_row)
        result = await get_admin_summary(None, db)
        for field in ["total_gross_revenue_fen", "total_gross_revenue_yuan",
                      "total_net_payout_fen", "total_net_payout_yuan",
                      "platform_profit_fen", "platform_profit_yuan",
                      "pending_count", "approved_count", "paid_count", "developer_count"]:
            assert field in result, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_platform_profit_is_gross_minus_net(self):
        stats_row = make_row(
            total_gross_fen=10000,
            total_net_fen=8000,
            pending_count=0,
            approved_count=0,
            paid_count=0,
            developer_count=0,
        )
        db = make_db(first_return=stats_row)
        result = await get_admin_summary(None, db)
        assert result["platform_profit_fen"] == 2000
        assert abs(result["platform_profit_yuan"] - 20.0) < 0.01

    @pytest.mark.asyncio
    async def test_yuan_fields_are_fen_divided_by_100(self):
        stats_row = make_row(
            total_gross_fen=50000,
            total_net_fen=42500,
            pending_count=0,
            approved_count=0,
            paid_count=0,
            developer_count=0,
        )
        db = make_db(first_return=stats_row)
        result = await get_admin_summary("2026-03", db)
        assert result["total_gross_revenue_yuan"] == 500.0
        assert result["total_net_payout_yuan"] == 425.0


# ── Developer endpoints ────────────────────────────────────────────────────────


class TestDeveloperSummary:
    @pytest.mark.asyncio
    async def test_summary_structure(self):
        dev_row = make_row(id="dev_1", name="TestDev", tier="pro", status="active")
        plugin_row = make_row(published_count=3, total_installs=150)
        earn_row = make_row(total_earned_fen=30000, pending_earnings_fen=5000)

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
            else:
                result.first.return_value = earn_row
            return result

        db.execute.side_effect = execute_side
        result = await get_developer_summary("dev_1", db)
        assert result["name"] == "TestDev"
        assert result["tier"] == "pro"
        assert result["total_earned_yuan"] == 300.0
        assert result["pending_earnings_yuan"] == 50.0

    @pytest.mark.asyncio
    async def test_nonexistent_developer_returns_404(self):
        db = make_db(first_return=None)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await get_developer_summary("dev_none", db)
        assert exc.value.status_code == 404


class TestDeveloperSettlements:
    @pytest.mark.asyncio
    async def test_returns_settlement_list(self):
        dev_check = make_row(exists=1)
        settlement = make_row(
            id="rsr_x", period="2026-03", installed_plugins=2,
            gross_revenue_fen=5000, share_pct=80.0, net_payout_fen=4000,
            status="paid", created_at=None, settled_at=None,
        )
        db = AsyncMock()
        call_count = 0

        async def execute_side(sql, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.first.return_value = dev_check
            else:
                result.fetchall.return_value = [settlement]
            return result

        db.execute.side_effect = execute_side
        result = await get_developer_settlements("dev_1", db)
        assert len(result["settlements"]) == 1
        assert result["settlements"][0]["net_payout_yuan"] == 40.0

    @pytest.mark.asyncio
    async def test_nonexistent_developer_returns_404(self):
        db = make_db(first_return=None)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await get_developer_settlements("dev_none", db)
        assert exc.value.status_code == 404


class TestDeveloperPlugins:
    @pytest.mark.asyncio
    async def test_returns_plugin_list(self):
        dev_check = make_row(exists=1)
        plugin = make_row(
            id="plg_1", name="Test Plugin", slug="test", category="pos_integration",
            icon_emoji="🔌", status="published", tier_required="free",
            price_type="free", price_amount=0, install_count=10,
            created_at=None, published_at=None,
        )
        db = AsyncMock()
        call_count = 0

        async def execute_side(sql, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.first.return_value = dev_check
            else:
                result.fetchall.return_value = [plugin]
            return result

        db.execute.side_effect = execute_side
        result = await get_developer_plugins("dev_1", db)
        assert result["total"] == 1
        assert result["plugins"][0]["name"] == "Test Plugin"

    @pytest.mark.asyncio
    async def test_nonexistent_developer_returns_404(self):
        db = make_db(first_return=None)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await get_developer_plugins("dev_none", db)
        assert exc.value.status_code == 404
