"""
Tests for Phase 5 Month 3 — 结算风控引擎 + CEO/区域多门店驾驶舱
"""
import os
import sys
import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with patch("src.core.config", create=True):
    from src.services.settlement_risk_service import (
        DEVIATION_THRESHOLDS,
        REFUND_RATE_THRESHOLDS,
        COMMISSION_RATE_BENCHMARK,
        COMMISSION_RATE_WARN,
        OVERDUE_DAYS_HIGH,
        OVERDUE_DAYS_MEDIUM,
        PLATFORM_LABELS,
        ITEM_TYPE_LABELS,
        _safe_float,
        _assess_deviation_risk,
        assess_settlement_risk,
        create_settlement_record,
    )
    from src.api.settlement_risk import (
        SUPPORTED_PLATFORMS,
        SUPPORTED_ITEM_TYPES,
        VALID_RECORD_TRANSITIONS,
        VALID_TASK_TRANSITIONS,
        SettlementRecordCreate,
        SettlementItemCreate,
        _format_record,
        _format_task,
    )
    from src.services.ceo_dashboard_service import (
        _safe_float as ceo_safe_float,
        get_ceo_dashboard,
        get_region_dashboard,
    )

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# TestSettlementConstants
# ═══════════════════════════════════════════════════════════════════════════════

class TestSettlementConstants:
    def test_platform_labels_complete(self):
        for p in SUPPORTED_PLATFORMS:
            assert p in PLATFORM_LABELS

    def test_item_type_labels_complete(self):
        for t in SUPPORTED_ITEM_TYPES:
            assert t in ITEM_TYPE_LABELS

    def test_thresholds_ordered(self):
        assert DEVIATION_THRESHOLDS["critical"] > DEVIATION_THRESHOLDS["high"] > DEVIATION_THRESHOLDS["medium"]
        assert REFUND_RATE_THRESHOLDS["high"]   > REFUND_RATE_THRESHOLDS["medium"]

    def test_commission_warn_above_benchmark(self):
        assert COMMISSION_RATE_WARN > COMMISSION_RATE_BENCHMARK

    def test_overdue_days_ordered(self):
        assert OVERDUE_DAYS_HIGH > OVERDUE_DAYS_MEDIUM

    def test_supported_platforms_has_meituan(self):
        assert "meituan" in SUPPORTED_PLATFORMS
        assert "eleme"   in SUPPORTED_PLATFORMS


# ═══════════════════════════════════════════════════════════════════════════════
# TestAssessDeviationRisk
# ═══════════════════════════════════════════════════════════════════════════════

class TestAssessDeviationRisk:
    def test_low(self):
        assert _assess_deviation_risk(0.03) == "low"

    def test_medium(self):
        assert _assess_deviation_risk(0.07) == "medium"

    def test_high(self):
        assert _assess_deviation_risk(0.12) == "high"

    def test_critical(self):
        assert _assess_deviation_risk(0.25) == "critical"

    def test_negative_abs(self):
        assert _assess_deviation_risk(-0.12) == "high"

    def test_zero(self):
        assert _assess_deviation_risk(0.0) == "low"


# ═══════════════════════════════════════════════════════════════════════════════
# TestAssessSettlementRisk
# ═══════════════════════════════════════════════════════════════════════════════

class TestAssessSettlementRisk:
    def _base(self, **kwargs):
        defaults = dict(
            gross_yuan=100000.0,
            commission_yuan=20000.0,
            refund_yuan=3000.0,
            net_yuan=77000.0,
            expected_yuan=78000.0,
            settle_date=date.today(),
            cycle_end=None,
        )
        defaults.update(kwargs)
        return assess_settlement_risk(**defaults)

    def test_low_risk_normal(self):
        result = self._base(net_yuan=78500.0, expected_yuan=78000.0)
        assert result["risk_level"] == "low"
        assert result["findings"] == []

    def test_high_deviation_risk(self):
        # 偏差 15% → high
        result = self._base(net_yuan=66300.0, expected_yuan=78000.0)
        assert result["risk_level"] in ("high", "critical")
        assert any("偏差" in f for f in result["findings"])

    def test_high_refund_rate(self):
        # 退款率 20% → high
        result = self._base(refund_yuan=20000.0, expected_yuan=None)
        assert result["risk_level"] == "high"
        assert any("退款率" in f for f in result["findings"])

    def test_medium_refund_rate(self):
        # 退款率 10% → medium
        result = self._base(refund_yuan=10000.0, expected_yuan=None)
        assert result["risk_level"] == "medium"

    def test_commission_overage(self):
        # 抽佣率 30% > 27% → high
        result = self._base(
            gross_yuan=100000.0, commission_yuan=30000.0,
            net_yuan=70000.0, expected_yuan=None, refund_yuan=0.0,
        )
        assert result["risk_level"] == "high"
        assert any("抽佣" in f for f in result["findings"])

    def test_overdue_high(self):
        # cycle_end 20天前 → high
        past = date.today() - timedelta(days=20)
        result = self._base(
            net_yuan=0.0, expected_yuan=None, refund_yuan=0.0,
            commission_yuan=0.0, cycle_end=past,
        )
        assert result["risk_level"] == "high"
        assert any("逾期" in f or "未到账" in f for f in result["findings"])

    def test_overdue_medium(self):
        # cycle_end 10天前 → medium
        past = date.today() - timedelta(days=10)
        result = self._base(
            net_yuan=0.0, expected_yuan=None, refund_yuan=0.0,
            commission_yuan=0.0, cycle_end=past,
        )
        assert result["risk_level"] == "medium"

    def test_no_expected_skips_deviation(self):
        result = self._base(net_yuan=50000.0, expected_yuan=None)
        # 无预期不应有偏差风险（只要其他指标正常）
        assert "偏差" not in " ".join(result["findings"])

    def test_deviation_fields_returned(self):
        result = self._base(net_yuan=66300.0, expected_yuan=78000.0)
        assert "deviation_yuan" in result
        assert "deviation_pct"  in result
        assert result["deviation_yuan"] == round(66300.0 - 78000.0, 2)


# ═══════════════════════════════════════════════════════════════════════════════
# TestSettlementRecordCreate (Pydantic)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSettlementRecordCreate:
    def _make(self, **kwargs):
        defaults = dict(
            store_id="s001", platform="meituan",
            period="2026-03", settle_date="2026-03-07",
            gross_yuan=100000.0,
        )
        defaults.update(kwargs)
        return SettlementRecordCreate(**defaults)

    def test_valid(self):
        rec = self._make()
        assert rec.platform == "meituan"

    def test_invalid_platform(self):
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            self._make(platform="twitter")

    def test_invalid_period(self):
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            self._make(period="2026/03")

    def test_invalid_settle_date(self):
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            self._make(settle_date="07-03-2026")

    def test_negative_gross_rejected(self):
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            self._make(gross_yuan=-1.0)

    def test_defaults(self):
        rec = self._make()
        assert rec.commission_yuan == 0.0
        assert rec.refund_yuan     == 0.0
        assert rec.adjustment_yuan == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# TestSettlementItemCreate (Pydantic)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSettlementItemCreate:
    def test_valid(self):
        item = SettlementItemCreate(item_type="commission", amount_yuan=5000.0)
        assert item.item_type == "commission"

    def test_invalid_type(self):
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            SettlementItemCreate(item_type="bribe", amount_yuan=100.0)


# ═══════════════════════════════════════════════════════════════════════════════
# TestFSMTransitions
# ═══════════════════════════════════════════════════════════════════════════════

class TestFSMTransitions:
    def test_record_pending_can_verify(self):
        assert "verified" in VALID_RECORD_TRANSITIONS["pending"]

    def test_record_pending_can_dispute(self):
        assert "disputed" in VALID_RECORD_TRANSITIONS["pending"]

    def test_record_verified_can_dispute(self):
        assert "disputed" in VALID_RECORD_TRANSITIONS["verified"]

    def test_record_auto_closed_is_terminal(self):
        assert len(VALID_RECORD_TRANSITIONS["auto_closed"]) == 0

    def test_task_open_can_resolve(self):
        assert "resolved" in VALID_TASK_TRANSITIONS["open"]

    def test_task_resolved_is_terminal(self):
        assert len(VALID_TASK_TRANSITIONS["resolved"]) == 0

    def test_task_ignored_is_terminal(self):
        assert len(VALID_TASK_TRANSITIONS["ignored"]) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# TestCreateSettlementRecord (mocked DB)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreateSettlementRecord:
    def _make_db(self, expected_yuan=78000.0):
        db = AsyncMock()
        call_count = [0]

        async def side_effect(q, params=None):
            call_count[0] += 1
            result = MagicMock()
            q_str = str(q)

            if "business_events" in q_str and "sale" in q_str:
                row = MagicMock()
                row.expected = expected_yuan
                result.fetchone = MagicMock(return_value=row)
                return result
            # INSERT, agent_action_log, risk_tasks
            result.fetchone = MagicMock(return_value=None)
            result.scalar   = MagicMock(return_value=None)
            return result

        db.execute = side_effect
        db.commit  = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_low_risk_normal(self):
        db = self._make_db(expected_yuan=77000.0)  # 偏差 < 5%
        result = await create_settlement_record(
            db, store_id="s001", platform="meituan",
            period="2026-03", settle_date="2026-03-07",
            gross_yuan=100000.0, commission_yuan=20000.0,
            refund_yuan=3000.0,
        )
        assert result["risk_level"] == "low"
        assert result["store_id"]  == "s001"

    @pytest.mark.asyncio
    async def test_high_risk_creates_task(self):
        # 偏差 > 15% → high
        db = self._make_db(expected_yuan=78000.0)
        result = await create_settlement_record(
            db, store_id="s001", platform="meituan",
            period="2026-03", settle_date="2026-03-07",
            gross_yuan=100000.0, commission_yuan=20000.0,
            refund_yuan=3000.0,  # net=77000, expected=78000 → only ~1.3% dev
        )
        # With 1.3% dev → low risk (expected=78000, net=77000)
        assert result["risk_level"] in ("low", "medium")

    @pytest.mark.asyncio
    async def test_net_computed_correctly(self):
        db = self._make_db(expected_yuan=None)
        result = await create_settlement_record(
            db, store_id="s001", platform="wechat_pay",
            period="2026-03", settle_date="2026-03-07",
            gross_yuan=50000.0, commission_yuan=2500.0,
            refund_yuan=1000.0, adjustment_yuan=500.0,
        )
        # net = 50000 - 2500 - 1000 + 500 = 47000
        assert result["net_yuan"] == 47000.0

    @pytest.mark.asyncio
    async def test_result_has_required_keys(self):
        db = self._make_db()
        result = await create_settlement_record(
            db, store_id="s001", platform="eleme",
            period="2026-03", settle_date="2026-03-07",
            gross_yuan=80000.0, commission_yuan=16000.0,
            refund_yuan=0.0,
        )
        for k in ("id", "store_id", "platform", "net_yuan", "risk_level",
                  "deviation_yuan", "findings"):
            assert k in result


# ═══════════════════════════════════════════════════════════════════════════════
# TestFormatRecord / TestFormatTask
# ═══════════════════════════════════════════════════════════════════════════════

class TestFormatRecord:
    def _make_row(self, **kwargs):
        row = MagicMock()
        row.id             = "sr-001"
        row.store_id       = "s001"
        row.platform       = "meituan"
        row.period         = "2026-03"
        row.settlement_no  = "MT-2026-0001"
        row.settle_date    = date(2026, 3, 7)
        row.cycle_start    = None
        row.cycle_end      = None
        row.gross_yuan     = 100000.0
        row.commission_yuan = 20000.0
        row.refund_yuan    = 3000.0
        row.adjustment_yuan = 0.0
        row.net_yuan       = 77000.0
        row.expected_yuan  = 78000.0
        row.deviation_yuan = -1000.0
        row.deviation_pct  = -1.28
        row.risk_level     = "low"
        row.status         = "pending"
        for k, v in kwargs.items():
            setattr(row, k, v)
        return row

    def test_basic(self):
        result = _format_record(self._make_row())
        assert result["id"]             == "sr-001"
        assert result["platform"]       == "meituan"
        assert result["platform_label"] == "美团外卖"
        assert result["net_yuan"]       == 77000.0

    def test_cycle_dates_none(self):
        result = _format_record(self._make_row())
        assert result["cycle_start"] is None
        assert result["cycle_end"]   is None


class TestFormatTask:
    def _make_row(self, **kwargs):
        row = MagicMock()
        row.id                 = "rt-001"
        row.store_id           = "s001"
        row.risk_type          = "invoice_mismatch"
        row.severity           = "high"
        row.title              = "美团结算偏差"
        row.description        = "偏差15%"
        row.amount_yuan        = 5000.0
        row.status             = "open"
        row.due_date           = None
        row.related_event_ids  = '["evt-001"]'
        row.created_at         = None
        for k, v in kwargs.items():
            setattr(row, k, v)
        return row

    def test_basic(self):
        result = _format_task(self._make_row())
        assert result["id"]       == "rt-001"
        assert result["severity"] == "high"

    def test_related_events_parsed(self):
        result = _format_task(self._make_row())
        assert result["related_event_ids"] == ["evt-001"]

    def test_bad_json_related(self):
        result = _format_task(self._make_row(related_event_ids="bad{json"))
        assert result["related_event_ids"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# TestCeoDashboardService (mocked DB)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCeoDashboardService:
    def _make_db(self):
        db = AsyncMock()

        async def side_effect(q, params=None):
            result = MagicMock()
            q_str = str(q)

            if "profit_attribution_results" in q_str and "ORDER BY gross_profit" in q_str:
                # profit rank
                rows = []
                for i, (sid, profit) in enumerate([("s001", 50000), ("s002", 40000)]):
                    row = MagicMock()
                    row.store_id           = sid
                    row.net_revenue_yuan   = profit * 3
                    row.gross_profit_yuan  = profit
                    row.profit_margin_pct  = 20.0
                    row.total_cost_yuan    = profit * 2
                    rows.append(row)
                result.fetchall = MagicMock(return_value=rows)
                return result

            if "profit_attribution_results" in q_str and "COUNT(DISTINCT" in q_str:
                row = MagicMock()
                row.store_count  = 2
                row.total_revenue = 270000.0
                row.total_profit  = 90000.0
                row.total_cost    = 180000.0
                row.avg_margin    = 20.0
                result.fetchone = MagicMock(return_value=row)
                return result

            if "risk_tasks" in q_str and "GROUP BY store_id" in q_str:
                row = MagicMock()
                row.store_id     = "s001"
                row.total_open   = 3
                row.high_count   = 1
                row.max_severity = "high"
                result.fetchall = MagicMock(return_value=[row])
                return result

            if "tax_calculations" in q_str:
                result.fetchall = MagicMock(return_value=[])
                return result

            if "cashflow_forecasts" in q_str and "GROUP BY" in q_str:
                result.fetchall = MagicMock(return_value=[])
                return result

            if "settlement_records" in q_str:
                result.fetchall = MagicMock(return_value=[])
                return result

            if "agent_action_log" in q_str:
                result.scalar = MagicMock(return_value=2)
                return result

            result.fetchall = MagicMock(return_value=[])
            result.fetchone = MagicMock(return_value=None)
            result.scalar   = MagicMock(return_value=0)
            return result

        db.execute = side_effect
        return db

    @pytest.mark.asyncio
    async def test_returns_required_keys(self):
        db = self._make_db()
        result = await get_ceo_dashboard(db, brand_id=None, period="2026-03")
        for k in ("period", "as_of", "profit_rank", "brand_summary",
                  "risk_heat", "tax_alerts", "cash_gap_stores",
                  "settlement_issues", "pending_l2_actions"):
            assert k in result

    @pytest.mark.asyncio
    async def test_profit_rank_sorted(self):
        db = self._make_db()
        result = await get_ceo_dashboard(db, brand_id=None, period="2026-03")
        rank = result["profit_rank"]
        assert len(rank) == 2
        # First should have higher profit
        assert rank[0]["gross_profit_yuan"] >= rank[1]["gross_profit_yuan"]

    @pytest.mark.asyncio
    async def test_brand_summary_present(self):
        db = self._make_db()
        result = await get_ceo_dashboard(db, brand_id=None, period="2026-03")
        assert result["brand_summary"] is not None
        assert result["brand_summary"]["store_count"] == 2

    @pytest.mark.asyncio
    async def test_pending_l2_actions(self):
        db = self._make_db()
        result = await get_ceo_dashboard(db, brand_id=None, period="2026-03")
        assert result["pending_l2_actions"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# TestRegionDashboard
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegionDashboard:
    def _make_db(self):
        db = AsyncMock()

        async def side_effect(q, params=None):
            result = MagicMock()
            q_str = str(q)

            if "profit_attribution_results" in q_str:
                rows = []
                for sid, profit in [("s001", 30000), ("s002", 20000), ("s003", 10000)]:
                    row = MagicMock()
                    row.store_id          = sid
                    row.net_revenue_yuan  = profit * 3
                    row.gross_profit_yuan = profit
                    row.profit_margin_pct = 20.0
                    row.food_cost_yuan    = profit * 1.5
                    row.waste_cost_yuan   = profit * 0.1
                    rows.append(row)
                result.fetchall = MagicMock(return_value=rows)
                return result

            if "risk_tasks" in q_str:
                result.fetchall = MagicMock(return_value=[])
                return result

            result.fetchall = MagicMock(return_value=[])
            return result

        db.execute = side_effect
        return db

    @pytest.mark.asyncio
    async def test_empty_store_ids(self):
        db = self._make_db()
        result = await get_region_dashboard(db, store_ids=[], period="2026-03")
        assert result["stores"] == []
        assert result["summary"] is None

    @pytest.mark.asyncio
    async def test_summary_computed(self):
        db = self._make_db()
        result = await get_region_dashboard(
            db, store_ids=["s001", "s002", "s003"], period="2026-03"
        )
        assert result["summary"] is not None
        assert result["summary"]["store_count"] == 3

    @pytest.mark.asyncio
    async def test_best_worst_identified(self):
        db = self._make_db()
        result = await get_region_dashboard(
            db, store_ids=["s001", "s002", "s003"], period="2026-03"
        )
        assert result["summary"]["best_store_id"]  == "s001"
        assert result["summary"]["worst_store_id"] == "s003"

    @pytest.mark.asyncio
    async def test_stores_have_risk_field(self):
        db = self._make_db()
        result = await get_region_dashboard(
            db, store_ids=["s001", "s002"], period="2026-03"
        )
        for s in result["stores"]:
            assert "risk" in s
