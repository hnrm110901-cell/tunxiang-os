"""
Banquet Agent Phase 18 — 单元测试

覆盖端点：
  - get_contract_compliance
  - get_overdue_deposits
  - get_pricing_recommendation
  - get_pricing_analysis
  - get_reviews_summary
  - get_low_score_alerts
  - get_lead_source_roi
  - get_hall_utilization_forecast
"""
import pytest
from datetime import datetime, date, timedelta
from unittest.mock import AsyncMock, MagicMock


# ── helpers ─────────────────────────────────────────────────────────────────

def _mock_user():
    u = MagicMock()
    u.id       = "user-001"
    u.brand_id = "BRAND-001"
    return u


def _scalars_returning(items):
    r = MagicMock()
    r.scalars.return_value.first.return_value = items[0] if items else None
    r.scalars.return_value.all.return_value   = items
    return r


def _rows_returning(rows):
    r = MagicMock()
    r.all.return_value = rows
    return r


def _make_order(oid="O-001", store_id="S001", status="confirmed",
                days_ago=-5, total_fen=200000, paid_fen=0, deposit_fen=50000,
                table_count=20, btype="wedding", deposit_status="unpaid"):
    from src.models.banquet import OrderStatusEnum, BanquetTypeEnum, DepositStatusEnum
    o = MagicMock()
    o.id = oid
    o.store_id = store_id
    o.order_status = (
        OrderStatusEnum.CONFIRMED  if status == "confirmed"  else
        OrderStatusEnum.COMPLETED  if status == "completed"  else
        OrderStatusEnum.CANCELLED
    )
    o.banquet_date = date.today() + timedelta(days=-days_ago)
    o.banquet_type = BanquetTypeEnum.WEDDING if btype == "wedding" else BanquetTypeEnum.BIRTHDAY
    o.total_amount_fen = total_fen
    o.paid_fen         = paid_fen
    o.deposit_fen      = deposit_fen
    o.deposit_status   = DepositStatusEnum.UNPAID if deposit_status == "unpaid" else DepositStatusEnum.PAID
    o.table_count      = table_count
    o.contact_name     = "张三"
    o.contact_phone    = "138-0000-0000"
    o.created_at       = datetime.utcnow()
    return o


def _make_contract(cid="C-001", oid="O-001", status="draft"):
    c = MagicMock()
    c.id = cid
    c.banquet_order_id = oid
    c.contract_status  = status  # draft / signed / void
    c.signed_at        = datetime.utcnow() if status == "signed" else None
    return c


def _make_review(rid="R-001", oid="O-001", rating=5, summary="很好"):
    r = MagicMock()
    r.id                 = rid
    r.banquet_order_id   = oid
    r.customer_rating    = rating
    r.ai_score           = rating * 20.0
    r.ai_summary         = summary
    r.improvement_tags   = []
    r.created_at         = datetime.utcnow()
    return r


def _make_lead(lid="L-001", store_id="S001", source="微信", budget_fen=100000,
               people=100, converted_oid=None, btype="wedding"):
    from src.models.banquet import BanquetTypeEnum, LeadStageEnum
    l = MagicMock()
    l.id                    = lid
    l.store_id              = store_id
    l.source_channel        = source
    l.expected_budget_fen   = budget_fen
    l.expected_people_count = people
    l.banquet_type          = BanquetTypeEnum.WEDDING if btype == "wedding" else BanquetTypeEnum.BIRTHDAY
    l.current_stage         = LeadStageEnum.WON if converted_oid else LeadStageEnum.NEW
    l.converted_order_id    = converted_oid
    return l


def _make_hall(hid="H-001", store_id="S001"):
    h = MagicMock()
    h.id         = hid
    h.store_id   = store_id
    h.is_active  = True
    h.max_tables = 30
    return h


def _make_booking(bid="BK-001", hall_id="H-001", slot_date=None):
    b = MagicMock()
    b.id        = bid
    b.hall_id   = hall_id
    b.slot_date = slot_date or (date.today() + timedelta(days=3))
    b.slot_name = "dinner"
    return b


# ── TestContractCompliance ────────────────────────────────────────────────────

class TestContractCompliance:

    @pytest.mark.asyncio
    async def test_unsigned_flagged(self):
        """宴会30天内未签合同 → 出现在 unsigned 列表"""
        from src.api.banquet_agent import get_contract_compliance

        # banquet_date = 15天后，合同 draft
        order    = _make_order(days_ago=-15, status="confirmed")
        contract = _make_contract(oid=order.id, status="draft")

        call_n = [0]
        def side_effect(*a, **kw):
            call_n[0] += 1
            n = call_n[0]
            if n == 1: return _scalars_returning([order])
            if n == 2: return _scalars_returning([contract])
            return _scalars_returning([])

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=side_effect)

        result = await get_contract_compliance(store_id="S001", db=db, _=_mock_user())

        assert result["unsigned"]["count"] == 1
        assert result["unsigned"]["orders"][0]["order_id"] == order.id

    @pytest.mark.asyncio
    async def test_deposit_overdue_flagged(self):
        """deposit_status=unpaid 且宴会14天内 → deposit_due"""
        from src.api.banquet_agent import get_contract_compliance

        # banquet_date = 7天后，未付定金
        order = _make_order(days_ago=-7, status="confirmed",
                            deposit_fen=50000, deposit_status="unpaid")

        call_n = [0]
        def side_effect(*a, **kw):
            call_n[0] += 1
            n = call_n[0]
            if n == 1: return _scalars_returning([order])
            if n == 2: return _scalars_returning([])    # no contracts
            return _scalars_returning([])

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=side_effect)

        result = await get_contract_compliance(store_id="S001", db=db, _=_mock_user())

        assert result["deposit_due"]["count"] == 1
        assert result["deposit_due"]["orders"][0]["deposit_yuan"] == pytest.approx(500.0)

    @pytest.mark.asyncio
    async def test_compliance_empty_store(self):
        """无订单时全零不崩溃"""
        from src.api.banquet_agent import get_contract_compliance

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalars_returning([]),   # orders
            _scalars_returning([]),   # contracts (won't be called)
        ])

        result = await get_contract_compliance(store_id="S001", db=db, _=_mock_user())

        assert result["total_orders"] == 0
        assert result["unsigned"]["count"]    == 0
        assert result["deposit_due"]["count"] == 0
        assert result["final_due"]["count"]   == 0


# ── TestPricingRecommendation ─────────────────────────────────────────────────

class TestPricingRecommendation:

    @pytest.mark.asyncio
    async def test_tiers_from_history(self):
        """≥5 条历史数据时返回 p25/p50/p75 三档"""
        from src.api.banquet_agent import get_pricing_recommendation

        target_order = _make_order("O-TGT", table_count=20, days_ago=-30)
        # 10 条历史订单，价格从 50000 到 140000 分 / 桌 (100元到280元)
        hist_orders = []
        for i in range(10):
            o = _make_order(f"O-H{i}", status="confirmed",
                            total_fen=(50000 + i * 10000) * 20,
                            table_count=20, days_ago=30 * (i + 1))
            hist_orders.append(o)

        call_n = [0]
        def side_effect(*a, **kw):
            call_n[0] += 1
            n = call_n[0]
            if n == 1: return _scalars_returning([target_order])  # target order
            if n == 2: return _scalars_returning(hist_orders)     # history
            if n == 3: return _scalars_returning([])              # kpi day
            return _scalars_returning([])

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=side_effect)

        result = await get_pricing_recommendation(
            store_id="S001", order_id="O-TGT", db=db, _=_mock_user()
        )

        assert result["sample_count"] == 10
        assert len(result["tiers"]) == 3
        tiers = {t["tier"]: t for t in result["tiers"]}
        assert tiers["economy"]["price_per_table_yuan"] <= tiers["standard"]["price_per_table_yuan"]
        assert tiers["standard"]["price_per_table_yuan"] <= tiers["premium"]["price_per_table_yuan"]

    @pytest.mark.asyncio
    async def test_fallback_to_package_price(self):
        """历史 < 5 条时 → 使用 MenuPackage 估算且 sample_count < 5"""
        from src.api.banquet_agent import get_pricing_recommendation
        from src.models.banquet import BanquetTypeEnum

        target_order = _make_order("O-TGT", table_count=10, days_ago=-30)
        # 仅2条历史
        hist_orders = [
            _make_order(f"O-H{i}", status="confirmed",
                        total_fen=200000, table_count=20, days_ago=60)
            for i in range(2)
        ]

        pkg = MagicMock()
        pkg.id = "PKG-001"
        pkg.suggested_price_fen = 100000
        pkg.is_active = True
        pkg.banquet_type = BanquetTypeEnum.WEDDING

        call_n = [0]
        def side_effect(*a, **kw):
            call_n[0] += 1
            n = call_n[0]
            if n == 1: return _scalars_returning([target_order])
            if n == 2: return _scalars_returning(hist_orders)
            if n == 3: return _scalars_returning([])      # kpi day
            if n == 4: return _scalars_returning([pkg])   # menu packages
            return _scalars_returning([])

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=side_effect)

        result = await get_pricing_recommendation(
            store_id="S001", order_id="O-TGT", db=db, _=_mock_user()
        )

        assert result["sample_count"] < 5
        assert len(result["tiers"]) == 3
        # 所有 conversion_rate_pct 为 None（样本不足时）
        assert all(t["conversion_rate_pct"] is None for t in result["tiers"])


# ── TestReviewsSummary ────────────────────────────────────────────────────────

class TestReviewsSummary:

    @pytest.mark.asyncio
    async def test_avg_score_computed(self):
        """均分计算正确"""
        from src.api.banquet_agent import get_reviews_summary
        from src.models.banquet import BanquetTypeEnum

        order = _make_order()
        rev4  = _make_review("R-001", rating=4)
        rev2  = _make_review("R-002", rating=2)

        bd = date.today() - timedelta(days=10)
        bt = BanquetTypeEnum.WEDDING

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_rows_returning([
            (rev4, bd, bt),
            (rev2, bd, bt),
        ]))

        result = await get_reviews_summary(
            store_id="S001", months=3, db=db, _=_mock_user()
        )

        assert result["total"] == 2
        assert result["avg_score"] == pytest.approx(3.0)

    @pytest.mark.asyncio
    async def test_score_distribution_has_5_keys(self):
        """score_distribution 必须包含 1-5 五个键"""
        from src.api.banquet_agent import get_reviews_summary
        from src.models.banquet import BanquetTypeEnum

        rev5 = _make_review(rating=5)
        bd   = date.today() - timedelta(days=5)
        bt   = BanquetTypeEnum.BIRTHDAY

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_rows_returning([(rev5, bd, bt)]))

        result = await get_reviews_summary(
            store_id="S001", months=3, db=db, _=_mock_user()
        )

        assert set(result["score_distribution"].keys()) == {"1", "2", "3", "4", "5"}
        assert result["score_distribution"]["5"] == 1

    @pytest.mark.asyncio
    async def test_empty_reviews_returns_zeros(self):
        """无评价时 total=0，avg_score=None"""
        from src.api.banquet_agent import get_reviews_summary

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_rows_returning([]))

        result = await get_reviews_summary(
            store_id="S001", months=3, db=db, _=_mock_user()
        )

        assert result["total"] == 0
        assert result["avg_score"] is None


# ── TestLeadSourceRoi ─────────────────────────────────────────────────────────

class TestLeadSourceRoi:

    @pytest.mark.asyncio
    async def test_roi_per_source(self):
        """已转化线索正确计算 revenue_per_lead_yuan"""
        from src.api.banquet_agent import get_lead_source_roi

        order = _make_order(total_fen=300000)
        lead_conv = _make_lead("L-001", source="抖音", converted_oid=order.id)
        lead_nope = _make_lead("L-002", source="抖音", converted_oid=None)

        call_n = [0]
        def side_effect(*a, **kw):
            call_n[0] += 1
            n = call_n[0]
            if n == 1: return _scalars_returning([lead_conv, lead_nope])
            if n == 2: return _scalars_returning([order])    # converted orders
            return _scalars_returning([])

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=side_effect)

        result = await get_lead_source_roi(store_id="S001", db=db, _=_mock_user())

        src = next(s for s in result["sources"] if s["source"] == "抖音")
        assert src["lead_count"] == 2
        assert src["converted"]  == 1
        assert src["conversion_rate_pct"] == pytest.approx(50.0)
        assert src["revenue_yuan"]        == pytest.approx(3000.0)
        # revenue_per_lead = 3000 / 2 = 1500
        assert src["revenue_per_lead_yuan"] == pytest.approx(1500.0)

    @pytest.mark.asyncio
    async def test_empty_leads_returns_empty(self):
        """无线索时返回空列表不崩溃"""
        from src.api.banquet_agent import get_lead_source_roi

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        result = await get_lead_source_roi(store_id="S001", db=db, _=_mock_user())

        assert result["sources"] == []


# ── TestHallUtilizationForecast ───────────────────────────────────────────────

class TestHallUtilizationForecast:

    @pytest.mark.asyncio
    async def test_overbooked_detected(self):
        """当日预订数 >= slots → status=overbooked"""
        from src.api.banquet_agent import get_hall_utilization_forecast

        hall  = _make_hall()
        # 1 hall × 2 slots/day = 2 capacity → book 2 slots same day → 100% → overbooked
        today  = date.today() + timedelta(days=3)
        book1  = _make_booking("BK-001", hall_id=hall.id, slot_date=today)
        book2  = _make_booking("BK-002", hall_id=hall.id, slot_date=today)

        call_n = [0]
        def side_effect(*a, **kw):
            call_n[0] += 1
            n = call_n[0]
            if n == 1: return _scalars_returning([hall])          # halls
            if n == 2: return _scalars_returning([book1, book2])  # future bookings
            if n == 3: return _scalars_returning([])              # hist bookings
            return _scalars_returning([])

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=side_effect)

        result = await get_hall_utilization_forecast(
            store_id="S001", days=7, db=db, _=_mock_user()
        )

        overbooked = [d for d in result["daily"] if d["status"] == "overbooked"]
        assert len(overbooked) == 1
        assert overbooked[0]["utilization_pct"] == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_summary_avg_computed(self):
        """summary.avg_utilization_pct 正确计算"""
        from src.api.banquet_agent import get_hall_utilization_forecast

        hall = _make_hall()

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalars_returning([hall]),  # halls
            _scalars_returning([]),      # future: no bookings
            _scalars_returning([]),      # hist: no bookings
        ])

        result = await get_hall_utilization_forecast(
            store_id="S001", days=7, db=db, _=_mock_user()
        )

        assert result["summary"]["avg_utilization_pct"] == pytest.approx(0.0)
        assert len(result["daily"]) == 7
        # All underbooked (0%)
        assert result["summary"]["underbooked_days"] == 7
