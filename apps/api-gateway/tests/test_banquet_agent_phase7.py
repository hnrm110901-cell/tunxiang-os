"""
Banquet Agent Phase 7 — 单元测试

覆盖端点：
  - mark_lead_lost        : 标记流失（含 lost_reason）
  - list_followup_due     : 今日到期 + 已逾期跟进列表
  - get_conversion_funnel : 阶段转化漏斗
  - get_revenue_forecast  : 营收预测
  - get_lost_analysis     : 流失原因分析
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock


# ── helpers ────────────────────────────────────────────────────────────────────

def _mock_user():
    u = MagicMock()
    u.id = "user-001"
    u.brand_id = "BRAND-001"
    return u


def _make_lead(
    lead_id="LEAD-001",
    store_id="S001",
    stage="new",
    lost_reason=None,
    last_followup_at=None,
    next_followup_at=None,
):
    from src.models.banquet import LeadStageEnum
    l = MagicMock()
    l.id = lead_id
    l.store_id = store_id
    stage_map = {v.value: v for v in LeadStageEnum}
    l.current_stage = stage_map.get(stage, LeadStageEnum.NEW)
    l.lost_reason = lost_reason
    l.banquet_type = MagicMock()
    l.banquet_type.value = "wedding"
    l.expected_date = date(2026, 10, 1)
    l.last_followup_at = last_followup_at or datetime(2026, 3, 1)
    l.next_followup_at = next_followup_at
    l.customer_id = "CUST-001"
    return l


def _make_order(order_id="ORD-001", store_id="S001", status="confirmed",
                banquet_date=None, total_amount_fen=5000000):
    from src.models.banquet import OrderStatusEnum
    o = MagicMock()
    o.id = order_id
    o.store_id = store_id
    o.order_status = OrderStatusEnum.CONFIRMED
    o.banquet_date = banquet_date or date(2026, 4, 15)
    o.total_amount_fen = total_amount_fen
    return o


def _scalars_returning(items):
    r = MagicMock()
    r.scalars.return_value.first.return_value = items[0] if items else None
    r.scalars.return_value.all.return_value = items
    r.first.return_value = items[0] if items else None
    r.all.return_value = items
    return r


def _grouped_result(pairs):
    """Return a mock whose .all() gives [(key, count), ...] rows"""
    r = MagicMock()
    r.all.return_value = pairs
    return r


# ── mark_lead_lost ─────────────────────────────────────────────────────────────

class TestMarkLeadLost:

    @pytest.mark.asyncio
    async def test_marks_lead_lost_successfully(self):
        from src.api.banquet_agent import mark_lead_lost, LostReq

        lead = _make_lead(stage="quoted")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([lead]))
        db.add = MagicMock()
        db.commit = AsyncMock()

        body = LostReq(lost_reason="价格太高", followup_note="客户反馈预算不足")
        result = await mark_lead_lost(
            store_id="S001", lead_id="LEAD-001",
            body=body, db=db, current_user=_mock_user(),
        )

        from src.models.banquet import LeadStageEnum
        assert lead.current_stage == LeadStageEnum.LOST
        assert lead.lost_reason == "价格太高"
        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        assert result["current_stage"] == "lost"
        assert result["lost_reason"] == "价格太高"

    @pytest.mark.asyncio
    async def test_404_when_lead_not_found(self):
        from fastapi import HTTPException
        from src.api.banquet_agent import mark_lead_lost, LostReq

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        with pytest.raises(HTTPException) as exc:
            await mark_lead_lost(
                store_id="S001", lead_id="NONEXISTENT",
                body=LostReq(lost_reason="竞品"),
                db=db, current_user=_mock_user(),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_400_when_already_lost(self):
        from fastapi import HTTPException
        from src.api.banquet_agent import mark_lead_lost, LostReq

        lead = _make_lead(stage="lost")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([lead]))

        with pytest.raises(HTTPException) as exc:
            await mark_lead_lost(
                store_id="S001", lead_id="LEAD-001",
                body=LostReq(lost_reason="already lost"),
                db=db, current_user=_mock_user(),
            )
        assert exc.value.status_code == 400


# ── list_followup_due ──────────────────────────────────────────────────────────

class TestListFollowupDue:

    @pytest.mark.asyncio
    async def test_returns_due_and_overdue(self):
        from src.api.banquet_agent import list_followup_due

        now = datetime.utcnow()
        due_lead   = _make_lead(lead_id="LEAD-A", next_followup_at=now + timedelta(hours=2))
        stale_lead = _make_lead(lead_id="LEAD-B", last_followup_at=now - timedelta(days=10))
        stale_lead.next_followup_at = None

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalars_returning([due_lead]),
            _scalars_returning([stale_lead]),
        ])

        result = await list_followup_due(store_id="S001", db=db, _=_mock_user())

        assert len(result["due_today"]) == 1
        assert result["due_today"][0]["lead_id"] == "LEAD-A"
        assert len(result["overdue"]) == 1
        assert result["overdue"][0]["lead_id"] == "LEAD-B"
        assert result["total"] == 2

    @pytest.mark.asyncio
    async def test_empty_when_no_followups(self):
        from src.api.banquet_agent import list_followup_due

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalars_returning([]),
            _scalars_returning([]),
        ])

        result = await list_followup_due(store_id="S001", db=db, _=_mock_user())

        assert result["total"] == 0
        assert result["due_today"] == []
        assert result["overdue"] == []

    @pytest.mark.asyncio
    async def test_deduplicates_leads(self):
        """A lead in both due_today and overdue lists should only appear once"""
        from src.api.banquet_agent import list_followup_due

        now = datetime.utcnow()
        lead = _make_lead(
            lead_id="LEAD-X",
            next_followup_at=now - timedelta(hours=1),   # past due
            last_followup_at=now - timedelta(days=10),   # also stale
        )

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalars_returning([lead]),
            _scalars_returning([lead]),  # same lead returned by both queries
        ])

        result = await list_followup_due(store_id="S001", db=db, _=_mock_user())

        assert result["total"] == 1


# ── get_conversion_funnel ──────────────────────────────────────────────────────

class TestGetConversionFunnel:

    @pytest.mark.asyncio
    async def test_returns_funnel_with_conversion_rates(self):
        from src.api.banquet_agent import get_conversion_funnel
        from src.models.banquet import LeadStageEnum

        # simulate: new=10, contacted=7, visit_scheduled=5, quoted=4,
        #           waiting_decision=3, deposit_pending=2, won=2, lost=1
        pairs = [
            (LeadStageEnum.NEW, 10),
            (LeadStageEnum.CONTACTED, 7),
            (LeadStageEnum.VISIT_SCHEDULED, 5),
            (LeadStageEnum.QUOTED, 4),
            (LeadStageEnum.WAITING_DECISION, 3),
            (LeadStageEnum.DEPOSIT_PENDING, 2),
            (LeadStageEnum.WON, 2),
            (LeadStageEnum.LOST, 1),
        ]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_grouped_result(pairs))

        result = await get_conversion_funnel(
            store_id="S001", month="2026-03", db=db, _=_mock_user(),
        )

        assert result["period"] == "2026-03"
        assert result["total_leads"] == 34  # sum of all
        assert result["won_count"] == 2
        assert result["lost_count"] == 1
        assert len(result["stages"]) == 7
        # first stage has no conversion rate
        assert result["stages"][0]["conversion_rate"] is None
        # second stage: 7/10 = 0.7
        assert result["stages"][1]["conversion_rate"] == 0.7

    @pytest.mark.asyncio
    async def test_400_on_invalid_month_format(self):
        from fastapi import HTTPException
        from src.api.banquet_agent import get_conversion_funnel

        db = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await get_conversion_funnel(
                store_id="S001", month="2026/03", db=db, _=_mock_user(),
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_zero_conversion_when_no_leads(self):
        from src.api.banquet_agent import get_conversion_funnel

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_grouped_result([]))

        result = await get_conversion_funnel(
            store_id="S001", month="2026-03", db=db, _=_mock_user(),
        )

        assert result["total_leads"] == 0
        assert result["overall_conversion_rate"] == 0.0


# ── get_revenue_forecast ───────────────────────────────────────────────────────

class TestGetRevenueForecast:

    @pytest.mark.asyncio
    async def test_returns_monthly_buckets(self):
        from src.api.banquet_agent import get_revenue_forecast

        o1 = _make_order("O1", banquet_date=date(2026, 4, 10), total_amount_fen=5000000)
        o2 = _make_order("O2", banquet_date=date(2026, 4, 20), total_amount_fen=3000000)
        o3 = _make_order("O3", banquet_date=date(2026, 5, 15), total_amount_fen=2000000)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([o1, o2, o3]))

        result = await get_revenue_forecast(
            store_id="S001", months=3, db=db, _=_mock_user(),
        )

        assert len(result["forecast"]) == 3
        april = next(b for b in result["forecast"] if b["month"].endswith("-04"))
        assert april["order_count"] == 2
        assert april["confirmed_revenue_yuan"] == pytest.approx(80000.0)

    @pytest.mark.asyncio
    async def test_fills_empty_months_with_zeros(self):
        from src.api.banquet_agent import get_revenue_forecast

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        result = await get_revenue_forecast(
            store_id="S001", months=3, db=db, _=_mock_user(),
        )

        assert len(result["forecast"]) == 3
        for bucket in result["forecast"]:
            assert bucket["confirmed_revenue_yuan"] == 0.0
            assert bucket["order_count"] == 0

    @pytest.mark.asyncio
    async def test_respects_months_parameter(self):
        from src.api.banquet_agent import get_revenue_forecast

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        result = await get_revenue_forecast(
            store_id="S001", months=6, db=db, _=_mock_user(),
        )
        assert len(result["forecast"]) == 6


# ── get_lost_analysis ──────────────────────────────────────────────────────────

class TestGetLostAnalysis:

    @pytest.mark.asyncio
    async def test_returns_grouped_reasons(self):
        from src.api.banquet_agent import get_lost_analysis

        pairs = [
            ("价格太高", 5),
            ("竞品抢单", 3),
            ("日期冲突", 2),
        ]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_grouped_result(pairs))

        result = await get_lost_analysis(
            store_id="S001", month="2026-03", db=db, _=_mock_user(),
        )

        assert result["period"] == "2026-03"
        assert result["total_lost"] == 10
        assert result["reasons"][0]["reason"] == "价格太高"
        assert result["reasons"][0]["count"] == 5
        assert result["reasons"][0]["pct"] == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_no_lost_leads_returns_empty(self):
        from src.api.banquet_agent import get_lost_analysis

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_grouped_result([]))

        result = await get_lost_analysis(
            store_id="S001", month="2026-03", db=db, _=_mock_user(),
        )

        assert result["total_lost"] == 0
        assert result["reasons"] == []

    @pytest.mark.asyncio
    async def test_null_reason_shown_as_not_stated(self):
        from src.api.banquet_agent import get_lost_analysis

        pairs = [(None, 2), ("价格太高", 1)]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_grouped_result(pairs))

        result = await get_lost_analysis(
            store_id="S001", month="2026-03", db=db, _=_mock_user(),
        )

        reasons_map = {r["reason"]: r for r in result["reasons"]}
        assert "未说明" in reasons_map
        assert reasons_map["未说明"]["count"] == 2

    @pytest.mark.asyncio
    async def test_400_on_invalid_month(self):
        from fastapi import HTTPException
        from src.api.banquet_agent import get_lost_analysis

        db = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await get_lost_analysis(
                store_id="S001", month="bad-format", db=db, _=_mock_user(),
            )
        assert exc.value.status_code == 400
