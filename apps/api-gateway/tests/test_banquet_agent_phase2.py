"""
Banquet Agent API — Phase 2 单元测试

覆盖新增/修复的端点：
  - list_leads          : GET  .../leads?stage=          （字段对齐 + stage 过滤）
  - update_lead_stage   : PATCH .../leads/{id}/stage     （followup_note 兼容）
  - list_orders         : GET  .../orders?status=        （status= 别名 + 字段对齐）
  - add_payment         : POST .../orders/{id}/payment   （payment_type 默认值）
  - banquet_dashboard   : GET  .../dashboard             （year+month 双参数格式）
"""

import pytest
import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock


# ── helpers ────────────────────────────────────────────────────────────────────

def _mock_user(uid: str = "user-001"):
    u = MagicMock()
    u.id = uid
    return u


def _scalars_returning(rows: list):
    """Return a mock db.execute() result that yields `rows` via .scalars().all()."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = rows
    result.scalars.return_value = scalars
    return result


def _scalar_first_returning(row):
    """Return a mock db.execute() result for .scalars().first()."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.first.return_value = row
    result.scalars.return_value = scalars
    return result


def _make_lead(
    lead_id: str = "LEAD-001",
    store_id: str = "S001",
    stage: str = "new",
    budget_fen: int = 5000_00,
):
    """Build a minimal BanquetLead-like mock."""
    from src.models.banquet import LeadStageEnum, BanquetTypeEnum
    lead = MagicMock()
    lead.id               = lead_id
    lead.store_id         = store_id
    lead.banquet_type     = BanquetTypeEnum.WEDDING
    lead.expected_date    = date(2026, 8, 8)
    lead.expected_budget_fen = budget_fen
    lead.current_stage    = LeadStageEnum(stage)
    lead.expected_people_count = 200
    lead.owner_user_id    = "user-001"
    lead.last_followup_at = datetime(2026, 3, 1, 9, 0)
    # Eager-loaded customer
    customer = MagicMock()
    customer.name = "张三"
    lead.customer = customer
    return lead


def _make_order(
    order_id: str = "ORD-001",
    store_id: str = "S001",
    status: str = "confirmed",
    amount_fen: int = 20000_00,
):
    from src.models.banquet import OrderStatusEnum, BanquetTypeEnum, DepositStatusEnum
    order = MagicMock()
    order.id               = order_id
    order.store_id         = store_id
    order.banquet_type     = BanquetTypeEnum.WEDDING
    order.banquet_date     = date(2026, 9, 18)
    order.people_count     = 200
    order.table_count      = 20
    order.order_status     = OrderStatusEnum(status)
    order.deposit_status   = DepositStatusEnum.PAID
    order.total_amount_fen = amount_fen
    order.paid_fen         = amount_fen // 2
    return order


# ── list_leads ─────────────────────────────────────────────────────────────────

class TestListLeads:

    @pytest.mark.asyncio
    async def test_returns_phase2_fields(self):
        """Response must include banquet_id, stage, stage_label, contact_name, budget_yuan."""
        from src.api.banquet_agent import list_leads

        lead = _make_lead(lead_id="L001", stage="new", budget_fen=30000_00)
        db = AsyncMock()
        db.execute.return_value = _scalars_returning([lead])

        result = await list_leads(
            store_id="S001", stage=None, owner_user_id=None,
            db=db, _=_mock_user(),
        )

        assert result["total"] == 1
        item = result["items"][0]
        assert item["banquet_id"]   == "L001"
        assert item["stage"]        == "new"
        assert item["stage_label"]  == "初步询价"
        assert item["contact_name"] == "张三"
        assert item["budget_yuan"]  == 30000.0

    @pytest.mark.asyncio
    async def test_backward_compat_fields_present(self):
        """Legacy fields (id, current_stage, expected_budget_yuan) must still be in response."""
        from src.api.banquet_agent import list_leads

        lead = _make_lead()
        db = AsyncMock()
        db.execute.return_value = _scalars_returning([lead])

        result = await list_leads(
            store_id="S001", stage=None, owner_user_id=None,
            db=db, _=_mock_user(),
        )

        item = result["items"][0]
        assert "id"                   in item
        assert "current_stage"        in item
        assert "expected_budget_yuan" in item

    @pytest.mark.asyncio
    async def test_stage_filter_valid_enum(self):
        """?stage=won should filter by the won enum value without raising."""
        from src.api.banquet_agent import list_leads

        db = AsyncMock()
        db.execute.return_value = _scalars_returning([])

        result = await list_leads(
            store_id="S001", stage="won", owner_user_id=None,
            db=db, _=_mock_user(),
        )
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_stage_filter_invalid_silently_ignored(self):
        """An invalid ?stage=inquiry should not raise — returns all leads."""
        from src.api.banquet_agent import list_leads

        lead = _make_lead()
        db = AsyncMock()
        db.execute.return_value = _scalars_returning([lead])

        # Should not raise ValueError
        result = await list_leads(
            store_id="S001", stage="inquiry", owner_user_id=None,
            db=db, _=_mock_user(),
        )
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_empty_result(self):
        """Empty store returns total=0 and items=[]."""
        from src.api.banquet_agent import list_leads

        db = AsyncMock()
        db.execute.return_value = _scalars_returning([])

        result = await list_leads(
            store_id="S999", stage=None, owner_user_id=None,
            db=db, _=_mock_user(),
        )
        assert result["total"] == 0
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_stage_labels_mapping(self):
        """All 8 stage enum values should produce Chinese stage_label."""
        from src.api.banquet_agent import list_leads, _LEAD_STAGE_LABELS

        stages = ["new", "contacted", "visit_scheduled", "quoted",
                  "waiting_decision", "deposit_pending", "won", "lost"]
        for stage in stages:
            lead = _make_lead(stage=stage)
            db = AsyncMock()
            db.execute.return_value = _scalars_returning([lead])

            result = await list_leads(
                store_id="S001", stage=None, owner_user_id=None,
                db=db, _=_mock_user(),
            )
            item = result["items"][0]
            assert item["stage_label"] != stage, (
                f"Stage '{stage}' should have a Chinese label, got value key instead"
            )
            assert item["stage_label"] == _LEAD_STAGE_LABELS[stage]


# ── update_lead_stage ──────────────────────────────────────────────────────────

class TestUpdateLeadStage:

    @pytest.mark.asyncio
    async def test_followup_note_accepted(self):
        """Phase 2 frontend sends followup_note (not followup_content) — must be accepted."""
        from src.api.banquet_agent import update_lead_stage, LeadStageUpdateReq
        from src.models.banquet import LeadStageEnum

        lead = _make_lead(stage="new")
        db = AsyncMock()
        db.execute.return_value = _scalar_first_returning(lead)
        db.add = MagicMock()

        body = LeadStageUpdateReq(
            stage=LeadStageEnum.CONTACTED,
            followup_note="电话沟通确认来访时间",
        )

        result = await update_lead_stage(
            store_id="S001", lead_id="L001", body=body,
            db=db, current_user=_mock_user(),
        )

        assert result["new_stage"] == LeadStageEnum.CONTACTED.value
        assert "last_followup_at"  in result

    @pytest.mark.asyncio
    async def test_followup_content_still_works(self):
        """Legacy followup_content field must still work for backward compat."""
        from src.api.banquet_agent import update_lead_stage, LeadStageUpdateReq
        from src.models.banquet import LeadStageEnum

        lead = _make_lead(stage="new")
        db = AsyncMock()
        db.execute.return_value = _scalar_first_returning(lead)
        db.add = MagicMock()

        body = LeadStageUpdateReq(
            stage=LeadStageEnum.QUOTED,
            followup_content="发送了报价单",
        )

        result = await update_lead_stage(
            store_id="S001", lead_id="L001", body=body,
            db=db, current_user=_mock_user(),
        )
        assert result["new_stage"] == LeadStageEnum.QUOTED.value

    @pytest.mark.asyncio
    async def test_no_note_uses_default_text(self):
        """Both fields omitted → fallback placeholder, no crash."""
        from src.api.banquet_agent import update_lead_stage, LeadStageUpdateReq
        from src.models.banquet import LeadStageEnum

        lead = _make_lead(stage="new")
        db = AsyncMock()
        db.execute.return_value = _scalar_first_returning(lead)
        db.add = MagicMock()

        # Neither followup_content nor followup_note
        body = LeadStageUpdateReq(stage=LeadStageEnum.CONTACTED)

        result = await update_lead_stage(
            store_id="S001", lead_id="L001", body=body,
            db=db, current_user=_mock_user(),
        )
        assert result["new_stage"] == LeadStageEnum.CONTACTED.value

    @pytest.mark.asyncio
    async def test_lead_not_found_raises_404(self):
        """Missing lead_id should raise HTTPException 404."""
        from fastapi import HTTPException
        from src.api.banquet_agent import update_lead_stage, LeadStageUpdateReq
        from src.models.banquet import LeadStageEnum

        db = AsyncMock()
        db.execute.return_value = _scalar_first_returning(None)

        body = LeadStageUpdateReq(
            stage=LeadStageEnum.CONTACTED,
            followup_note="test",
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_lead_stage(
                store_id="S001", lead_id="MISSING", body=body,
                db=db, current_user=_mock_user(),
            )
        assert exc_info.value.status_code == 404


# ── list_orders ────────────────────────────────────────────────────────────────

class TestListOrders:

    @pytest.mark.asyncio
    async def test_returns_phase2_fields(self):
        """Response must include banquet_id, status, amount_yuan."""
        from src.api.banquet_agent import list_orders

        order = _make_order(order_id="ORD-001", status="confirmed", amount_fen=50000_00)
        db = AsyncMock()
        db.execute.return_value = _scalars_returning([order])

        result = await list_orders(
            store_id="S001", status=None, order_status=None,
            date_from=None, date_to=None,
            db=db, _=_mock_user(),
        )

        item = result["items"][0]
        assert item["banquet_id"]  == "ORD-001"
        assert item["status"]      == "confirmed"
        assert item["amount_yuan"] == 50000.0

    @pytest.mark.asyncio
    async def test_status_param_accepted(self):
        """?status=confirmed (Phase 2 param) must filter correctly without error."""
        from src.api.banquet_agent import list_orders

        order = _make_order(status="confirmed")
        db = AsyncMock()
        db.execute.return_value = _scalars_returning([order])

        result = await list_orders(
            store_id="S001", status="confirmed", order_status=None,
            date_from=None, date_to=None,
            db=db, _=_mock_user(),
        )
        assert result["total"] == 1
        assert result["items"][0]["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_order_status_param_still_works(self):
        """Legacy ?order_status= param must still be accepted."""
        from src.api.banquet_agent import list_orders

        order = _make_order(status="completed")
        db = AsyncMock()
        db.execute.return_value = _scalars_returning([order])

        result = await list_orders(
            store_id="S001", status=None, order_status="completed",
            date_from=None, date_to=None,
            db=db, _=_mock_user(),
        )
        assert result["items"][0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_status_param_takes_precedence(self):
        """When both status and order_status provided, status wins."""
        from src.api.banquet_agent import list_orders

        order = _make_order(status="confirmed")
        db = AsyncMock()
        db.execute.return_value = _scalars_returning([order])

        # Pass both — status= takes precedence in effective_status
        result = await list_orders(
            store_id="S001", status="confirmed", order_status="completed",
            date_from=None, date_to=None,
            db=db, _=_mock_user(),
        )
        assert result["items"][0]["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_invalid_status_silently_ignored(self):
        """?status=pending (old frontend value) should not raise — returns all."""
        from src.api.banquet_agent import list_orders

        order = _make_order()
        db = AsyncMock()
        db.execute.return_value = _scalars_returning([order])

        result = await list_orders(
            store_id="S001", status="pending", order_status=None,
            date_from=None, date_to=None,
            db=db, _=_mock_user(),
        )
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_backward_compat_fields_present(self):
        """Legacy fields (id, order_status, total_amount_yuan) must still appear."""
        from src.api.banquet_agent import list_orders

        order = _make_order()
        db = AsyncMock()
        db.execute.return_value = _scalars_returning([order])

        result = await list_orders(
            store_id="S001", status=None, order_status=None,
            date_from=None, date_to=None,
            db=db, _=_mock_user(),
        )
        item = result["items"][0]
        assert "id"               in item
        assert "order_status"     in item
        assert "total_amount_yuan" in item
        assert "balance_yuan"     in item


# ── add_payment ────────────────────────────────────────────────────────────────

class TestAddPayment:

    @pytest.mark.asyncio
    async def test_payment_type_defaults_to_balance(self):
        """Frontend omits payment_type → default PaymentTypeEnum.BALANCE, no error."""
        from src.api.banquet_agent import add_payment, PaymentReq
        from src.models.banquet import PaymentTypeEnum

        body = PaymentReq(amount_yuan=5000.0, payment_method="wechat")
        assert body.payment_type == PaymentTypeEnum.BALANCE

    @pytest.mark.asyncio
    async def test_add_payment_updates_paid_fen(self):
        """Successful payment should increment order.paid_fen and return paid_yuan."""
        from src.api.banquet_agent import add_payment, PaymentReq
        from src.models.banquet import DepositStatusEnum

        order = _make_order(status="confirmed", amount_fen=20000_00)
        order.paid_fen   = 5000_00
        order.deposit_fen = 10000_00   # must be int for >= comparison
        order.deposit_status = DepositStatusEnum.PARTIAL

        db = AsyncMock()
        db.execute.return_value = _scalar_first_returning(order)
        db.add = MagicMock()

        body = PaymentReq(amount_yuan=3000.0, payment_method="wechat")

        result = await add_payment(
            store_id="S001", order_id="ORD-001", body=body,
            db=db, current_user=_mock_user(),
        )

        assert result["paid_yuan"]    == pytest.approx(8000.0, abs=0.01)
        assert result["balance_yuan"] == pytest.approx(12000.0, abs=0.01)
        assert "payment_id"           in result
        assert "deposit_status"       in result

    @pytest.mark.asyncio
    async def test_payment_order_not_found_raises_404(self):
        """Missing order_id should raise HTTPException 404."""
        from fastapi import HTTPException
        from src.api.banquet_agent import add_payment, PaymentReq

        db = AsyncMock()
        db.execute.return_value = _scalar_first_returning(None)

        body = PaymentReq(amount_yuan=1000.0)

        with pytest.raises(HTTPException) as exc_info:
            await add_payment(
                store_id="S001", order_id="MISSING", body=body,
                db=db, current_user=_mock_user(),
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_explicit_payment_type_accepted(self):
        """Explicit payment_type=deposit must still be accepted."""
        from src.api.banquet_agent import PaymentReq
        from src.models.banquet import PaymentTypeEnum

        body = PaymentReq(amount_yuan=2000.0, payment_type=PaymentTypeEnum.DEPOSIT)
        assert body.payment_type == PaymentTypeEnum.DEPOSIT


# ── banquet_dashboard ──────────────────────────────────────────────────────────

class TestBanquetDashboard:

    def _make_kpi_row(self, revenue_fen=10000000, profit_fen=3000000,
                      order_count=5, lead_count=20, utilization=65.0):
        row = MagicMock()
        row.revenue_fen    = revenue_fen
        row.profit_fen     = profit_fen
        row.order_count    = order_count
        row.lead_count     = lead_count
        row.avg_utilization = utilization
        return row

    @pytest.mark.asyncio
    async def test_year_and_month_integers_accepted(self):
        """?year=2026&month=3 (frontend format) should not raise."""
        from src.api.banquet_agent import banquet_dashboard

        db = AsyncMock()
        kpi_mock = MagicMock()
        kpi_mock.first.return_value = self._make_kpi_row()
        db.execute.return_value = kpi_mock

        result = await banquet_dashboard(
            store_id="S001", year=2026, month="3",
            db=db, _=_mock_user(),
        )
        assert result["year"]  == 2026
        assert result["month"] == 3

    @pytest.mark.asyncio
    async def test_month_yyyymm_string_accepted(self):
        """?month=2026-03 (YYYY-MM string) should parse correctly."""
        from src.api.banquet_agent import banquet_dashboard

        db = AsyncMock()
        kpi_mock = MagicMock()
        kpi_mock.first.return_value = self._make_kpi_row()
        db.execute.return_value = kpi_mock

        result = await banquet_dashboard(
            store_id="S001", year=None, month="2026-03",
            db=db, _=_mock_user(),
        )
        assert result["year"]  == 2026
        assert result["month"] == 3

    @pytest.mark.asyncio
    async def test_defaults_to_current_month(self):
        """No params → current year/month used."""
        from src.api.banquet_agent import banquet_dashboard
        from datetime import date as _date

        db = AsyncMock()
        kpi_mock = MagicMock()
        kpi_mock.first.return_value = self._make_kpi_row()
        db.execute.return_value = kpi_mock

        result = await banquet_dashboard(
            store_id="S001", year=None, month=None,
            db=db, _=_mock_user(),
        )
        today = _date.today()
        assert result["year"]  == today.year
        assert result["month"] == today.month

    @pytest.mark.asyncio
    async def test_returns_phase2_field_names(self):
        """Response must include gross_margin_pct, conversion_rate, room_utilization."""
        from src.api.banquet_agent import banquet_dashboard

        db = AsyncMock()
        kpi_mock = MagicMock()
        kpi_mock.first.return_value = self._make_kpi_row(
            revenue_fen=10000000, profit_fen=3000000,
            order_count=10, lead_count=40, utilization=70.0,
        )
        db.execute.return_value = kpi_mock

        result = await banquet_dashboard(
            store_id="S001", year=2026, month="3",
            db=db, _=_mock_user(),
        )

        assert "gross_margin_pct" in result
        assert "conversion_rate"  in result
        assert "room_utilization" in result
        assert result["gross_margin_pct"] == pytest.approx(30.0, abs=0.1)
        assert result["conversion_rate"]  == pytest.approx(25.0, abs=0.1)   # 10/40*100
        assert result["room_utilization"] == pytest.approx(70.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_returns_legacy_field_names(self):
        """Legacy fields (gross_profit_yuan, conversion_rate_pct) still present."""
        from src.api.banquet_agent import banquet_dashboard

        db = AsyncMock()
        kpi_mock = MagicMock()
        kpi_mock.first.return_value = self._make_kpi_row()
        db.execute.return_value = kpi_mock

        result = await banquet_dashboard(
            store_id="S001", year=2026, month="3",
            db=db, _=_mock_user(),
        )

        assert "gross_profit_yuan"   in result
        assert "conversion_rate_pct" in result
        assert "hall_utilization_pct" in result

    @pytest.mark.asyncio
    async def test_zero_revenue_gross_margin_is_zero(self):
        """Zero revenue should not cause division by zero — gross_margin_pct = 0."""
        from src.api.banquet_agent import banquet_dashboard

        db = AsyncMock()
        kpi_mock = MagicMock()
        kpi_mock.first.return_value = self._make_kpi_row(revenue_fen=0, profit_fen=0)
        db.execute.return_value = kpi_mock

        result = await banquet_dashboard(
            store_id="S001", year=2026, month="3",
            db=db, _=_mock_user(),
        )
        assert result["gross_margin_pct"] == 0

    @pytest.mark.asyncio
    async def test_zero_leads_conversion_is_zero(self):
        """Zero leads should not cause division by zero — conversion_rate = 0."""
        from src.api.banquet_agent import banquet_dashboard

        db = AsyncMock()
        kpi_mock = MagicMock()
        kpi_mock.first.return_value = self._make_kpi_row(order_count=5, lead_count=0)
        db.execute.return_value = kpi_mock

        result = await banquet_dashboard(
            store_id="S001", year=2026, month="3",
            db=db, _=_mock_user(),
        )
        assert result["conversion_rate"] == 0
