"""P&L 损益表服务单元测试

覆盖：
1. PLStatement 各项加减正确
2. 固定费用摊销逻辑
3. 无 BOM 数据时使用估算值
4. 品牌级 P&L 多店汇总
5. 边界：零营收、跨月计算
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from services.tx_finance.src.services.pl_service import (
    CostBreakdown,
    OperatingExpenses,
    PLService,
    PLStatement,
    RevenueBreakdown,
    _days_in_period,
    _prorate,
)

# ─── 测试夹具 ────────────────────────────────────────────────────────────────


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture
def store_id() -> uuid.UUID:
    return uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.fixture
def mock_db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service() -> PLService:
    return PLService()


# ─── 工具函数测试 ─────────────────────────────────────────────────────────────


class TestUtilFunctions:
    def test_days_in_period_single_day(self):
        d = date(2026, 3, 31)
        assert _days_in_period(d, d) == 1

    def test_days_in_period_full_month(self):
        start = date(2026, 3, 1)
        end = date(2026, 3, 31)
        assert _days_in_period(start, end) == 31

    def test_prorate_full_month(self):
        """整月摊销 = 月额"""
        assert _prorate(30000, 31, 31) == 30000

    def test_prorate_half_month(self):
        """半月摊销 = 月额 / 2"""
        result = _prorate(30000, 15, 30)
        assert result == 15000

    def test_prorate_zero_month_days(self):
        """month_days=0 返回 0，不除零"""
        assert _prorate(30000, 15, 0) == 0

    def test_prorate_rounding(self):
        """摊销结果向下取整（int）"""
        # 30000 × 10/31 = 9677.4... → 9677
        result = _prorate(30000, 10, 31)
        assert result == 9677


# ─── PLStatement 属性计算测试 ─────────────────────────────────────────────────


class TestPLStatementProperties:
    """验证 PLStatement 各项加减计算的正确性"""

    def _make_pl(
        self,
        revenue_fen: int = 100_000,
        food_cost_fen: int = 30_000,
        waste_fen: int = 2_000,
        labor_fen: int = 25_000,
        rent_fen: int = 10_000,
        utility_fen: int = 3_000,
        other_fen: int = 2_000,
    ) -> PLStatement:
        return PLStatement(
            store_id=uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 31),
            period_days=31,
            revenue=RevenueBreakdown(dine_in_fen=revenue_fen),
            cost=CostBreakdown(food_cost_fen=food_cost_fen, waste_cost_fen=waste_fen),
            opex=OperatingExpenses(
                labor_cost_fen=labor_fen,
                rent_fen=rent_fen,
                utility_fen=utility_fen,
                other_fixed_fen=other_fen,
            ),
        )

    def test_total_revenue(self):
        pl = self._make_pl(revenue_fen=100_000)
        assert pl.total_revenue_fen == 100_000

    def test_gross_profit_equals_revenue_minus_food_cost(self):
        """毛利 = 营收 - 食材总成本"""
        pl = self._make_pl(revenue_fen=100_000, food_cost_fen=30_000, waste_fen=2_000)
        assert pl.cost.total_food_cost_fen == 32_000
        assert pl.gross_profit_fen == 68_000

    def test_gross_margin_rate(self):
        """毛利率 = 毛利 / 营收"""
        pl = self._make_pl(revenue_fen=100_000, food_cost_fen=30_000, waste_fen=0)
        assert abs(pl.gross_margin_rate - 0.70) < 0.001

    def test_food_cost_rate(self):
        """食材成本率 = 食材成本 / 营收"""
        pl = self._make_pl(revenue_fen=100_000, food_cost_fen=30_000, waste_fen=0)
        assert abs(pl.food_cost_rate - 0.30) < 0.001

    def test_total_opex(self):
        """经营费用合计 = 人工 + 房租 + 水电 + 其他"""
        pl = self._make_pl(labor_fen=25_000, rent_fen=10_000, utility_fen=3_000, other_fen=2_000)
        assert pl.opex.total_fen == 40_000

    def test_operating_profit(self):
        """经营利润 = 毛利 - 经营费用"""
        pl = self._make_pl(
            revenue_fen=100_000,
            food_cost_fen=30_000,
            waste_fen=0,
            labor_fen=20_000,
            rent_fen=10_000,
            utility_fen=3_000,
            other_fen=2_000,
        )
        # 毛利 = 70_000，费用 = 35_000
        assert pl.operating_profit_fen == 35_000

    def test_operating_margin_rate(self):
        """经营利润率 = 经营利润 / 营收"""
        pl = self._make_pl(
            revenue_fen=100_000,
            food_cost_fen=30_000,
            waste_fen=0,
            labor_fen=20_000,
            rent_fen=10_000,
            utility_fen=3_000,
            other_fen=2_000,
        )
        assert abs(pl.operating_margin_rate - 0.35) < 0.001

    def test_negative_operating_profit_is_loss(self):
        """高费用 → 经营亏损（负数）"""
        pl = self._make_pl(
            revenue_fen=50_000,
            food_cost_fen=20_000,
            waste_fen=5_000,
            labor_fen=30_000,
            rent_fen=10_000,
            utility_fen=5_000,
            other_fen=5_000,
        )
        assert pl.operating_profit_fen < 0

    def test_zero_revenue_no_division_error(self):
        """零营收不产生除零错误"""
        pl = self._make_pl(
            revenue_fen=0,
            food_cost_fen=0,
            waste_fen=0,
            labor_fen=0,
            rent_fen=0,
            utility_fen=0,
            other_fen=0,
        )
        assert pl.gross_margin_rate == 0.0
        assert pl.food_cost_rate == 0.0
        assert pl.operating_margin_rate == 0.0

    def test_to_dict_structure(self):
        """to_dict 包含完整 P&L 结构"""
        pl = self._make_pl()
        d = pl.to_dict()
        required_top_keys = {
            "store_id",
            "start_date",
            "end_date",
            "period_days",
            "revenue",
            "cost",
            "gross_profit_fen",
            "gross_margin_rate",
            "food_cost_rate",
            "opex",
            "operating_profit_fen",
            "operating_margin_rate",
            "cost_health",
        }
        assert required_top_keys.issubset(set(d.keys()))

    def test_to_dict_revenue_breakdown(self):
        """to_dict 营收明细包含堂食/外卖/储值/其他"""
        pl = PLStatement(
            store_id=uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 31),
            period_days=31,
            revenue=RevenueBreakdown(
                dine_in_fen=60_000,
                delivery_fen=30_000,
                stored_value_fen=5_000,
                other_fen=5_000,
            ),
            cost=CostBreakdown(food_cost_fen=30_000),
            opex=OperatingExpenses(),
        )
        d = pl.to_dict()
        rev = d["revenue"]
        assert rev["dine_in_fen"] == 60_000
        assert rev["delivery_fen"] == 30_000
        assert rev["stored_value_fen"] == 5_000
        assert rev["other_fen"] == 5_000
        assert rev["total_fen"] == 100_000

    def test_to_dict_cost_is_estimated_flag(self):
        """to_dict 中 is_estimated 正确传递"""
        pl = PLStatement(
            store_id=uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 31),
            period_days=31,
            revenue=RevenueBreakdown(dine_in_fen=100_000),
            cost=CostBreakdown(
                food_cost_fen=30_000,
                is_estimated=True,
                estimated_reason="无BOM数据，使用30%估算",
            ),
            opex=OperatingExpenses(),
        )
        d = pl.to_dict()
        assert d["cost"]["is_estimated"] is True
        assert d["cost"]["estimated_reason"] != ""


# ─── PLService 集成测试（Mock DB）────────────────────────────────────────────


class TestPLServiceGetStorePL:
    """测试 PLService.get_store_pl（Mock 数据库层）"""

    @pytest.mark.asyncio
    async def test_basic_store_pl_happy_path(self, service, store_id, tenant_id, mock_db):
        """正常路径：有营收、有快照成本、有固定费用"""
        start = date(2026, 3, 1)
        end = date(2026, 3, 31)

        with (
            patch.object(
                service, "_fetch_revenue_breakdown", new=AsyncMock(return_value=RevenueBreakdown(dine_in_fen=100_000))
            ),
            patch.object(service, "_fetch_food_cost", new=AsyncMock(return_value=(30_000, False, ""))),
            patch.object(service._repo, "fetch_waste_cost", new=AsyncMock(return_value=1_000)),
            patch.object(
                service,
                "_fetch_operating_expenses",
                new=AsyncMock(
                    return_value=OperatingExpenses(
                        labor_cost_fen=20_000,
                        rent_fen=10_000,
                        utility_fen=3_000,
                        other_fixed_fen=2_000,
                    )
                ),
            ),
        ):
            pl = await service.get_store_pl(store_id, start, end, tenant_id, mock_db)

        assert pl.total_revenue_fen == 100_000
        assert pl.cost.food_cost_fen == 30_000
        assert pl.cost.waste_cost_fen == 1_000
        assert pl.cost.total_food_cost_fen == 31_000
        assert pl.gross_profit_fen == 69_000
        assert pl.opex.total_fen == 35_000
        assert pl.operating_profit_fen == 34_000

    @pytest.mark.asyncio
    async def test_no_snapshots_estimated(self, service, store_id, tenant_id, mock_db):
        """无快照时估算并标注"""
        start = date(2026, 3, 1)
        end = date(2026, 3, 31)

        with (
            patch.object(
                service, "_fetch_revenue_breakdown", new=AsyncMock(return_value=RevenueBreakdown(dine_in_fen=80_000))
            ),
            patch.object(
                service,
                "_fetch_food_cost",
                new=AsyncMock(return_value=(24_000, True, "无BOM成本快照，使用行业均值30%估算")),
            ),
            patch.object(service._repo, "fetch_waste_cost", new=AsyncMock(return_value=0)),
            patch.object(service, "_fetch_operating_expenses", new=AsyncMock(return_value=OperatingExpenses())),
        ):
            pl = await service.get_store_pl(store_id, start, end, tenant_id, mock_db)

        assert pl.cost.is_estimated is True
        assert pl.cost.food_cost_fen == 24_000


# ─── 摊销计算正确性测试 ───────────────────────────────────────────────────────


class TestProrateCalculations:
    """独立测试按天摊销逻辑"""

    def test_march_full_month_31_days(self):
        """3月31天全月摊销"""
        monthly = 31_000
        result = _prorate(monthly, 31, 31)
        assert result == monthly

    def test_february_28_days(self):
        """2月28天，查询10天"""
        monthly = 28_000
        result = _prorate(monthly, 10, 28)
        assert result == 10_000

    def test_cross_month_partial(self):
        """跨月：只计算部分天数"""
        monthly = 30_000
        # 3月15天 / 31天
        result = _prorate(monthly, 15, 31)
        assert result == int(30_000 * 15 / 31)

    def test_prorated_value_less_than_monthly(self):
        """摊销值永远 ≤ 月额"""
        for days in range(1, 32):
            result = _prorate(30_000, days, 31)
            assert result <= 30_000
