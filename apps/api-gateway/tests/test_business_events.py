"""
Tests for Phase 5 Month 1 — 经营事件中心 + 利润归因基础
"""
import os
import sys
import json
from unittest.mock import AsyncMock, MagicMock, patch

# L002: set env vars before importing src modules
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with patch("src.core.config", create=True):
    from src.api.business_events import (
        SUPPORTED_EVENT_TYPES,
        SOURCE_SYSTEMS,
        PROFIT_RELEVANT_TYPES,
        EVENT_TYPE_LABELS,
        _derive_period,
        _yuan_to_fen,
        _float,
        _format_event,
        EventIngestItem,
        EventIngestRequest,
        MappingRuleCreate,
    )
    from src.services.profit_attribution_service import (
        _safe_float,
        _pct,
        build_attribution_detail,
        compute_profit_attribution,
    )

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# TestConstants
# ═══════════════════════════════════════════════════════════════════════════════

class TestConstants:
    def test_supported_event_types_count(self):
        assert len(SUPPORTED_EVENT_TYPES) == 10

    def test_all_required_types_present(self):
        required = {"sale", "refund", "purchase", "receipt", "waste",
                    "invoice", "payment", "collection", "expense", "settlement"}
        assert required == set(SUPPORTED_EVENT_TYPES)

    def test_profit_relevant_subset(self):
        assert PROFIT_RELEVANT_TYPES.issubset(set(SUPPORTED_EVENT_TYPES))
        # invoice and collection NOT profit relevant
        assert "invoice" not in PROFIT_RELEVANT_TYPES
        assert "collection" not in PROFIT_RELEVANT_TYPES

    def test_event_type_labels_complete(self):
        for t in SUPPORTED_EVENT_TYPES:
            assert t in EVENT_TYPE_LABELS, f"Missing label for {t}"

    def test_source_systems_has_manual(self):
        assert "manual" in SOURCE_SYSTEMS
        assert "pos" in SOURCE_SYSTEMS


# ═══════════════════════════════════════════════════════════════════════════════
# TestHelpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestHelpers:
    def test_derive_period(self):
        assert _derive_period("2026-03-07") == "2026-03"
        assert _derive_period("2025-12-31") == "2025-12"

    def test_yuan_to_fen_normal(self):
        assert _yuan_to_fen(100.0) == 10000
        assert _yuan_to_fen(0.01) == 1
        assert _yuan_to_fen(99.99) == 9999

    def test_yuan_to_fen_zero(self):
        assert _yuan_to_fen(0.0) == 0

    def test_float_none(self):
        assert _float(None) == 0.0

    def test_float_decimal(self):
        from decimal import Decimal
        assert _float(Decimal("123.45")) == 123.45

    def test_float_int(self):
        assert _float(5) == 5.0


# ═══════════════════════════════════════════════════════════════════════════════
# TestEventIngestItem
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventIngestItem:
    def _make(self, **kwargs):
        defaults = {
            "store_id":   "store-001",
            "event_type": "sale",
            "source_system": "pos",
            "amount_yuan": 100.0,
            "event_date":  "2026-03-07",
        }
        defaults.update(kwargs)
        return EventIngestItem(**defaults)

    def test_valid_item(self):
        item = self._make()
        assert item.event_type == "sale"
        assert item.store_id == "store-001"

    def test_period_auto_derived_by_api(self):
        item = self._make(event_date="2026-03-07")
        # period is optional at model level, derived in API layer
        period = item.period or _derive_period(item.event_date)
        assert period == "2026-03"

    def test_invalid_event_type(self):
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            self._make(event_type="unknown_type")

    def test_invalid_source_system(self):
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            self._make(source_system="fax_machine")

    def test_invalid_event_date(self):
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            self._make(event_date="07-03-2026")

    def test_payload_dict(self):
        item = self._make(payload={"table": "A1", "items": 3})
        assert item.payload["table"] == "A1"


# ═══════════════════════════════════════════════════════════════════════════════
# TestEventIngestRequest
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventIngestRequest:
    def _make_item(self, event_type="sale"):
        return {
            "store_id": "s001", "event_type": event_type,
            "source_system": "pos", "amount_yuan": 100.0, "event_date": "2026-03-07",
        }

    def test_valid_request(self):
        req = EventIngestRequest(events=[self._make_item()])
        assert len(req.events) == 1

    def test_empty_events_rejected(self):
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            EventIngestRequest(events=[])

    def test_max_100_events(self):
        items = [self._make_item() for _ in range(101)]
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            EventIngestRequest(events=items)


# ═══════════════════════════════════════════════════════════════════════════════
# TestMappingRuleCreate
# ═══════════════════════════════════════════════════════════════════════════════

class TestMappingRuleCreate:
    def test_valid_rule(self):
        rule = MappingRuleCreate(
            source_system="meituan",
            source_event_type="order_paid",
            target_event_type="sale",
        )
        assert rule.target_event_type == "sale"

    def test_invalid_target(self):
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            MappingRuleCreate(
                source_system="meituan",
                source_event_type="order_paid",
                target_event_type="unknown",
            )

    def test_default_priority(self):
        rule = MappingRuleCreate(
            source_system="pos",
            source_event_type="daily_close",
            target_event_type="settlement",
        )
        assert rule.priority == 100


# ═══════════════════════════════════════════════════════════════════════════════
# TestFormatEvent
# ═══════════════════════════════════════════════════════════════════════════════

class TestFormatEvent:
    def _make_row(self, **kwargs):
        row = MagicMock()
        row.id = "evt-001"
        row.store_id = "s001"
        row.brand_id = None
        row.event_type = "sale"
        row.event_type_label = "销售收入"
        row.event_subtype = None
        row.source_system = "pos"
        row.source_event_id = "POS-20260307-001"
        row.amount_yuan = 500.0
        row.amount_fen = 50000
        row.payload = None
        row.period = "2026-03"
        row.event_date = MagicMock()
        row.event_date.__str__ = lambda s: "2026-03-07"
        row.status = "raw"
        row.created_at = None
        for k, v in kwargs.items():
            setattr(row, k, v)
        return row

    def test_basic_format(self):
        row = self._make_row()
        result = _format_event(row)
        assert result["id"] == "evt-001"
        assert result["event_type"] == "sale"
        assert result["event_type_label"] == "销售收入"
        assert result["amount_yuan"] == 500.0

    def test_payload_parsed(self):
        row = self._make_row(payload='{"table": "A1"}')
        result = _format_event(row)
        assert result["payload"] == {"table": "A1"}

    def test_bad_payload_returns_none(self):
        row = self._make_row(payload="not-json{{{")
        result = _format_event(row)
        assert result["payload"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# TestProfitAttributionService
# ═══════════════════════════════════════════════════════════════════════════════

class TestSafeFloat:
    def test_none(self):
        assert _safe_float(None) == 0.0

    def test_decimal(self):
        from decimal import Decimal
        assert _safe_float(Decimal("99.5")) == 99.5

    def test_int(self):
        assert _safe_float(100) == 100.0


class TestPct:
    def test_normal(self):
        assert _pct(30, 100) == 30.0

    def test_zero_denominator(self):
        assert _pct(30, 0) == 0.0

    def test_negative_denominator(self):
        assert _pct(30, -10) == 0.0

    def test_rounding(self):
        assert _pct(1, 3) == 33.33


class TestBuildAttributionDetail:
    def test_structure(self):
        detail = build_attribution_detail(
            gross_revenue=100000.0, refund=2000.0, net_revenue=98000.0,
            food_cost=35000.0, waste_cost=3000.0, platform_commission=15000.0,
            labor_cost=20000.0, other_expense=5000.0, total_cost=78000.0,
            gross_profit=20000.0,
        )
        assert "revenue_breakdown" in detail
        assert "cost_breakdown" in detail
        assert "profit_summary" in detail

    def test_revenue_breakdown(self):
        detail = build_attribution_detail(
            gross_revenue=100000.0, refund=2000.0, net_revenue=98000.0,
            food_cost=35000.0, waste_cost=3000.0, platform_commission=15000.0,
            labor_cost=20000.0, other_expense=5000.0, total_cost=78000.0,
            gross_profit=20000.0,
        )
        rb = detail["revenue_breakdown"]
        assert rb["gross_revenue_yuan"] == 100000.0
        assert rb["refund_yuan"] == 2000.0
        assert rb["refund_rate_pct"] == 2.0  # 2000/100000

    def test_cost_breakdown_percentages(self):
        detail = build_attribution_detail(
            gross_revenue=100000.0, refund=0.0, net_revenue=100000.0,
            food_cost=35000.0, waste_cost=5000.0, platform_commission=10000.0,
            labor_cost=20000.0, other_expense=0.0, total_cost=70000.0,
            gross_profit=30000.0,
        )
        cb = detail["cost_breakdown"]
        assert cb["food_cost"]["pct_of_revenue"] == 35.0
        assert cb["waste_cost"]["pct_of_revenue"] == 5.0

    def test_profit_summary(self):
        detail = build_attribution_detail(
            gross_revenue=100000.0, refund=0.0, net_revenue=100000.0,
            food_cost=60000.0, waste_cost=0.0, platform_commission=0.0,
            labor_cost=20000.0, other_expense=0.0, total_cost=80000.0,
            gross_profit=20000.0,
        )
        ps = detail["profit_summary"]
        assert ps["gross_profit_yuan"] == 20000.0
        assert ps["profit_margin_pct"] == 20.0


class TestComputeProfitAttribution:
    """Test compute_profit_attribution with mocked DB"""

    def _make_db(self, rows_by_type: dict):
        """
        Mock DB for force=True path:
          call 1: GROUP BY aggregation  → fetchall returns rows_by_type
          call 2: existing upsert check → fetchone returns None (no existing)
          call 3: INSERT                → no-op
        """
        db = AsyncMock()
        call_count = [0]

        async def side_effect(q, params=None):
            call_count[0] += 1
            result = MagicMock()

            if call_count[0] == 1:
                # GROUP BY aggregation
                mock_rows = []
                for event_type, (total_yuan, cnt) in rows_by_type.items():
                    row = MagicMock()
                    row.event_type = event_type
                    row.total_yuan = total_yuan
                    row.cnt        = cnt
                    mock_rows.append(row)
                result.fetchall = MagicMock(return_value=mock_rows)
                return result

            # call 2: existing check → None = do INSERT
            result.fetchone = MagicMock(return_value=None)
            return result

        db.execute = side_effect
        db.commit  = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_basic_computation(self):
        db = self._make_db({
            "sale":       (100000.0, 500),
            "refund":     (2000.0,   20),
            "purchase":   (35000.0,  50),
            "waste":      (3000.0,   10),
            "settlement": (15000.0,  30),
            "expense":    (10000.0,  15),
        })
        result = await compute_profit_attribution(db, "s001", "2026-03", force=True)
        assert result["revenue"]["gross_revenue_yuan"] == 100000.0
        assert result["revenue"]["refund_yuan"]        == 2000.0
        assert result["revenue"]["net_revenue_yuan"]   == 98000.0
        assert result["costs"]["food_cost_yuan"]       == 35000.0
        assert result["costs"]["waste_cost_yuan"]      == 3000.0
        assert result["costs"]["platform_commission_yuan"] == 15000.0
        assert result["costs"]["other_expense_yuan"]   == 10000.0
        expected_total = 35000 + 3000 + 15000 + 10000
        assert result["costs"]["total_cost_yuan"] == float(expected_total)
        expected_profit = 98000.0 - expected_total
        assert result["profit"]["gross_profit_yuan"] == expected_profit

    @pytest.mark.asyncio
    async def test_zero_revenue_no_division_error(self):
        db = self._make_db({"expense": (5000.0, 3)})
        result = await compute_profit_attribution(db, "s001", "2026-03", force=True)
        assert result["revenue"]["gross_revenue_yuan"] == 0.0
        assert result["profit"]["profit_margin_pct"]   == 0.0

    @pytest.mark.asyncio
    async def test_purchase_preferred_over_receipt(self):
        db = self._make_db({
            "purchase": (40000.0, 10),
            "receipt":  (38000.0, 10),
            "sale":     (100000.0, 100),
        })
        result = await compute_profit_attribution(db, "s001", "2026-03", force=True)
        # purchase takes priority when present
        assert result["costs"]["food_cost_yuan"] == 40000.0

    @pytest.mark.asyncio
    async def test_receipt_used_when_no_purchase(self):
        db = self._make_db({
            "receipt": (38000.0, 10),
            "sale":    (100000.0, 100),
        })
        result = await compute_profit_attribution(db, "s001", "2026-03", force=True)
        assert result["costs"]["food_cost_yuan"] == 38000.0

    @pytest.mark.asyncio
    async def test_event_count_aggregated(self):
        db = self._make_db({
            "sale":  (100000.0, 500),
            "waste": (3000.0,   10),
        })
        result = await compute_profit_attribution(db, "s001", "2026-03", force=True)
        assert result["event_count"] == 510

    @pytest.mark.asyncio
    async def test_attribution_detail_included(self):
        db = self._make_db({"sale": (100000.0, 100)})
        result = await compute_profit_attribution(db, "s001", "2026-03", force=True)
        assert result["attribution_detail"] is not None
        assert "revenue_breakdown" in result["attribution_detail"]
        assert "cost_breakdown" in result["attribution_detail"]
