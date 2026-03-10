"""
Banquet Agent Phase 22 — 单元测试

覆盖端点：
  - get_revenue_forecast
  - get_booking_heatmap
  - get_menu_performance
  - get_loyalty_metrics
  - get_peak_analysis
  - get_payment_efficiency
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


def _scalar_returning(value):
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _rows_returning(rows):
    r = MagicMock()
    r.all.return_value = rows
    return r


def _make_kpi(stat_date=None, revenue_fen=200000, order_count=5):
    k = MagicMock()
    k.stat_date    = stat_date or (date.today() - timedelta(days=30))
    k.revenue_fen  = revenue_fen
    k.order_count  = order_count
    k.gross_profit_fen = int(revenue_fen * 0.3)
    k.lead_count   = 10
    k.hall_utilization_pct = 60.0
    k.conversion_rate_pct  = 30.0
    return k


def _make_order(oid="O-001", store_id="S001", total_fen=300000,
                paid_fen=300000, deposit_fen=100000, table_count=10,
                banquet_date=None, customer_id="C-001",
                package_id=None, banquet_type="wedding",
                status="confirmed"):
    from src.models.banquet import OrderStatusEnum, BanquetTypeEnum
    o = MagicMock()
    o.id               = oid
    o.store_id         = store_id
    o.total_amount_fen = total_fen
    o.paid_fen         = paid_fen
    o.deposit_fen      = deposit_fen
    o.table_count      = table_count
    o.banquet_date     = banquet_date or (date.today() - timedelta(days=10))
    o.customer_id      = customer_id
    o.package_id       = package_id
    o.banquet_type     = BanquetTypeEnum(banquet_type)
    o.order_status     = OrderStatusEnum.CONFIRMED if status == "confirmed" else OrderStatusEnum.COMPLETED
    o.contact_name     = "张三"
    return o


def _make_package(pid="P-001", store_id="S001", name="婚宴标准套餐",
                  price_fen=50000, cost_fen=30000, banquet_type="wedding"):
    from src.models.banquet import BanquetTypeEnum
    p = MagicMock()
    p.id                   = pid
    p.store_id             = store_id
    p.name                 = name
    p.suggested_price_fen  = price_fen
    p.cost_fen             = cost_fen
    p.banquet_type         = BanquetTypeEnum(banquet_type)
    p.target_people_min    = 1
    p.target_people_max    = 999
    p.description          = "精选食材，精心搭配"
    p.is_active            = True
    return p


def _make_customer(cid="C-001", total_fen=500000, count=3):
    c = MagicMock()
    c.id                       = cid
    c.total_banquet_amount_fen = total_fen
    c.total_banquet_count      = count
    c.vip_level                = 1
    return c


# ── TestRevenueForecast ───────────────────────────────────────────────────────

class TestRevenueForecast:

    @pytest.mark.asyncio
    async def test_forecast_generated_from_history(self):
        """有历史KPI时，forecast 列表非空"""
        from src.api.banquet_agent import get_revenue_forecast

        kpi = _make_kpi(stat_date=date.today() - timedelta(days=30), revenue_fen=500000)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([kpi]))

        result = await get_revenue_forecast(store_id="S001", months=3, db=db, _=_mock_user())

        assert len(result["forecast"]) == 3
        assert result["forecast"][0]["forecast_revenue_yuan"] == pytest.approx(5000.0)
        assert result["method"] == "moving_average_3m"

    @pytest.mark.asyncio
    async def test_no_history_returns_empty_forecast(self):
        """无历史KPI时 forecast 为空"""
        from src.api.banquet_agent import get_revenue_forecast

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        result = await get_revenue_forecast(store_id="S001", months=3, db=db, _=_mock_user())

        assert result["history"] == []
        assert result["forecast"] == []


# ── TestBookingHeatmap ────────────────────────────────────────────────────────

class TestBookingHeatmap:

    @pytest.mark.asyncio
    async def test_heatmap_counts_weekday(self):
        """订单按星期汇总，total_orders 正确"""
        from src.api.banquet_agent import get_booking_heatmap

        # banquet_date on a known weekday
        o = _make_order(banquet_date=date(2025, 10, 4))   # Saturday (weekday=5)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([o]))

        result = await get_booking_heatmap(store_id="S001", months=12, db=db, _=_mock_user())

        assert result["total_orders"] == 1
        sat_row = next((r for r in result["matrix"] if r["weekday"] == 5), None)
        assert sat_row is not None
        assert sat_row["total"] == 1

    @pytest.mark.asyncio
    async def test_empty_orders_returns_zero(self):
        """无订单时 total_orders == 0"""
        from src.api.banquet_agent import get_booking_heatmap

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        result = await get_booking_heatmap(store_id="S001", months=12, db=db, _=_mock_user())

        assert result["total_orders"] == 0


# ── TestMenuPerformance ───────────────────────────────────────────────────────

class TestMenuPerformance:

    @pytest.mark.asyncio
    async def test_gross_margin_computed(self):
        """毛利率 = (price - cost) / price × 100"""
        from src.api.banquet_agent import get_menu_performance

        pkg   = _make_package(price_fen=50000, cost_fen=30000)
        order = _make_order(package_id=pkg.id)

        call_n = [0]
        def side_effect(*a, **kw):
            call_n[0] += 1
            if call_n[0] == 1:
                return _scalars_returning([pkg])
            return _scalars_returning([order])

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=side_effect)

        result = await get_menu_performance(store_id="S001", db=db, _=_mock_user())

        assert result["total_packages"] == 1
        pkg_result = result["packages"][0]
        assert pkg_result["gross_margin_pct"] == pytest.approx(40.0)
        assert pkg_result["order_count"] == 1

    @pytest.mark.asyncio
    async def test_no_packages_returns_empty(self):
        """无套餐时返回空列表"""
        from src.api.banquet_agent import get_menu_performance

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        result = await get_menu_performance(store_id="S001", db=db, _=_mock_user())

        assert result["packages"] == []


# ── TestLoyaltyMetrics ────────────────────────────────────────────────────────

class TestLoyaltyMetrics:

    @pytest.mark.asyncio
    async def test_repeat_rate_computed(self):
        """2 客户有1个复购（count≥2）→ 50% 复购率"""
        from src.api.banquet_agent import get_loyalty_metrics

        c1 = _make_customer(cid="C-001", total_fen=500000, count=3)  # repeat
        c2 = _make_customer(cid="C-002", total_fen=200000, count=1)  # new only

        call_n = [0]
        def side_effect(*a, **kw):
            call_n[0] += 1
            if call_n[0] == 1:
                return _scalars_returning([c1, c2])
            return _scalars_returning([])   # no recent orders

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=side_effect)

        result = await get_loyalty_metrics(store_id="S001", db=db, _=_mock_user())

        assert result["repeat_customers"] == 1
        assert result["repeat_rate_pct"]  == pytest.approx(50.0)
        assert result["avg_ltv_yuan"]     == pytest.approx(3500.0)

    @pytest.mark.asyncio
    async def test_no_customers_returns_zero(self):
        """无客户时所有指标为 0"""
        from src.api.banquet_agent import get_loyalty_metrics

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        result = await get_loyalty_metrics(store_id="S001", db=db, _=_mock_user())

        assert result["total_customers"] == 0
        assert result["repeat_rate_pct"] == pytest.approx(0.0)


# ── TestPeakAnalysis ──────────────────────────────────────────────────────────

class TestPeakAnalysis:

    @pytest.mark.asyncio
    async def test_peak_month_identified(self):
        """有订单时 peak_month 不为空"""
        from src.api.banquet_agent import get_peak_analysis

        o = _make_order(banquet_date=date(2025, 6, 15))

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([o]))

        result = await get_peak_analysis(store_id="S001", db=db, _=_mock_user())

        assert result["total_orders"] == 1
        assert result["peak_month"] is not None
        assert result["peak_weekday"] is not None

    @pytest.mark.asyncio
    async def test_no_orders_returns_empty(self):
        """无订单时返回空列表"""
        from src.api.banquet_agent import get_peak_analysis

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([]))

        result = await get_peak_analysis(store_id="S001", db=db, _=_mock_user())

        assert result["by_month"] == []
        assert result["by_type"] == []


# ── TestPaymentEfficiency ─────────────────────────────────────────────────────

class TestPaymentEfficiency:

    @pytest.mark.asyncio
    async def test_full_payment_rate_computed(self):
        """1/1 订单全额付款 → full_payment_rate_pct = 100"""
        from src.api.banquet_agent import get_payment_efficiency

        o = _make_order(total_fen=300000, paid_fen=300000, deposit_fen=100000,
                        banquet_date=date.today() + timedelta(days=30))

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([o]))

        result = await get_payment_efficiency(store_id="S001", db=db, _=_mock_user())

        assert result["total_orders"] == 1
        assert result["full_payment_rate_pct"] == pytest.approx(100.0)
        assert result["deposit_rate_pct"] == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_overdue_receivable_detected(self):
        """过去宴会未付清 → overdue_yuan > 0"""
        from src.api.banquet_agent import get_payment_efficiency

        # 宴会日期在过去，仅付50%
        o = _make_order(total_fen=300000, paid_fen=150000, deposit_fen=100000,
                        banquet_date=date.today() - timedelta(days=30))

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_returning([o]))

        result = await get_payment_efficiency(store_id="S001", db=db, _=_mock_user())

        assert result["overdue_yuan"] == pytest.approx(1500.0)
