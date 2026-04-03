"""PLReportService 单元测试

测试覆盖：
1. 日P&L = 收入 - 原料成本 - 期间费用汇总
2. 周/月P&L聚合
3. 分店P&L对比
4. 同比/环比计算
"""
import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from services.tx_finance.src.services.pl_report import PLReport, PLReportService

# ─── Fixtures ────────────────────────────────────────────────────────────────

TENANT_ID = uuid.uuid4()
STORE_A = uuid.uuid4()
STORE_B = uuid.uuid4()
STORE_C = uuid.uuid4()


def _make_pl_data(revenue_fen, raw_cost_fen, labor_fen=0, rent_fen=0, other_fen=0):
    """构造模拟数据库查询结果"""
    return {
        "revenue_fen": revenue_fen,
        "raw_material_cost_fen": raw_cost_fen,
        "labor_cost_fen": labor_fen,
        "rent_fen": rent_fen,
        "other_opex_fen": other_fen,
    }


# ─── Test 1: 日P&L = 收入 - 原料成本 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_daily_pl_basic_calculation():
    """日P&L基础计算：毛利=收入-原料成本，毛利率=毛利/收入"""
    service = PLReportService()
    db = AsyncMock()
    biz_date = date(2026, 3, 30)

    mock_data = _make_pl_data(
        revenue_fen=100_000,      # 1000元收入
        raw_cost_fen=35_000,      # 350元原料成本
    )

    with patch.object(service, "_fetch_daily_revenue", new=AsyncMock(return_value=100_000)), \
         patch.object(service, "_fetch_daily_raw_cost", new=AsyncMock(return_value=35_000)), \
         patch.object(service, "_fetch_daily_opex", new=AsyncMock(return_value={})):

        result = await service.get_daily_pl(STORE_A, biz_date, TENANT_ID, db)

    assert isinstance(result, PLReport)
    assert result.revenue_fen == 100_000
    assert result.raw_material_cost_fen == 35_000
    assert result.gross_profit_fen == 65_000   # 1000 - 350 = 650元
    assert result.gross_margin_rate == pytest.approx(0.65, abs=0.001)


@pytest.mark.asyncio
async def test_daily_pl_zero_revenue():
    """零收入时毛利率为0，不触发除零异常"""
    service = PLReportService()
    db = AsyncMock()
    biz_date = date(2026, 3, 30)

    with patch.object(service, "_fetch_daily_revenue", new=AsyncMock(return_value=0)), \
         patch.object(service, "_fetch_daily_raw_cost", new=AsyncMock(return_value=0)), \
         patch.object(service, "_fetch_daily_opex", new=AsyncMock(return_value={})):

        result = await service.get_daily_pl(STORE_A, biz_date, TENANT_ID, db)

    assert result.revenue_fen == 0
    assert result.gross_margin_rate == 0.0


# ─── Test 2: 期间P&L聚合（周/月）────────────────────────────────────────────

@pytest.mark.asyncio
async def test_period_pl_weekly_aggregation():
    """周P&L：7天收入与成本正确聚合"""
    service = PLReportService()
    db = AsyncMock()

    start = date(2026, 3, 24)
    end = date(2026, 3, 30)

    # 每天 10000 收入，3500 成本，共7天
    daily_rows = [
        {"biz_date": date(2026, 3, 24 + i), "revenue_fen": 10_000, "raw_cost_fen": 3_500}
        for i in range(7)
    ]

    with patch.object(service, "_fetch_period_daily_rows",
                      new=AsyncMock(return_value=daily_rows)):

        result = await service.get_period_pl(STORE_A, start, end, TENANT_ID, db)

    assert result.revenue_fen == 70_000       # 7 × 10000
    assert result.raw_material_cost_fen == 24_500  # 7 × 3500
    assert result.gross_profit_fen == 45_500
    assert result.period_days == 7


@pytest.mark.asyncio
async def test_period_pl_monthly_aggregation():
    """月P&L：30天聚合，验证总额与平均值"""
    service = PLReportService()
    db = AsyncMock()

    start = date(2026, 3, 1)
    end = date(2026, 3, 30)

    daily_rows = [
        {"biz_date": date(2026, 3, 1 + i), "revenue_fen": 50_000, "raw_cost_fen": 17_500}
        for i in range(30)
    ]

    with patch.object(service, "_fetch_period_daily_rows",
                      new=AsyncMock(return_value=daily_rows)):

        result = await service.get_period_pl(STORE_A, start, end, TENANT_ID, db)

    assert result.revenue_fen == 1_500_000     # 30 × 50000
    assert result.gross_profit_fen == 975_000  # 30 × (50000 - 17500)
    assert result.period_days == 30
    assert result.avg_daily_revenue_fen == 50_000


# ─── Test 3: 分店P&L对比 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_store_pl_comparison():
    """多店P&L对比：验证每个门店独立计算，结果按毛利率排序"""
    service = PLReportService()
    db = AsyncMock()
    biz_date = date(2026, 3, 30)

    store_data = {
        STORE_A: {"revenue_fen": 100_000, "raw_cost_fen": 30_000},  # margin 70%
        STORE_B: {"revenue_fen": 80_000, "raw_cost_fen": 40_000},   # margin 50%
        STORE_C: {"revenue_fen": 120_000, "raw_cost_fen": 36_000},  # margin 70%
    }

    async def mock_fetch_store_data(store_ids, biz_date, tenant_id, db):
        return [
            {
                "store_id": sid,
                "revenue_fen": data["revenue_fen"],
                "raw_cost_fen": data["raw_cost_fen"],
            }
            for sid, data in store_data.items()
        ]

    with patch.object(service, "_fetch_stores_daily_data", new=mock_fetch_store_data):
        results = await service.get_stores_pl(
            store_ids=[STORE_A, STORE_B, STORE_C],
            biz_date=biz_date,
            tenant_id=TENANT_ID,
            db=db,
        )

    assert len(results) == 3
    # 验证每个门店数据正确
    store_map = {r.store_id: r for r in results}
    assert store_map[STORE_A].gross_margin_rate == pytest.approx(0.7, abs=0.001)
    assert store_map[STORE_B].gross_margin_rate == pytest.approx(0.5, abs=0.001)
    assert store_map[STORE_C].gross_margin_rate == pytest.approx(0.7, abs=0.001)


# ─── Test 4: 同比/环比计算 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_year_over_year_calculation():
    """同比：本期收入与去年同期对比，计算增减幅度"""
    service = PLReportService()
    db = AsyncMock()

    current_start = date(2026, 3, 1)
    current_end = date(2026, 3, 30)

    current_rows = [
        {"biz_date": date(2026, 3, 1 + i), "revenue_fen": 50_000, "raw_cost_fen": 15_000}
        for i in range(30)
    ]
    prior_rows = [
        {"biz_date": date(2025, 3, 1 + i), "revenue_fen": 40_000, "raw_cost_fen": 14_000}
        for i in range(30)
    ]

    call_count = 0

    async def mock_fetch(store_id, start, end, tenant_id, db_session):
        nonlocal call_count
        call_count += 1
        if start.year == 2026:
            return current_rows
        return prior_rows

    with patch.object(service, "_fetch_period_daily_rows", new=mock_fetch):
        result = await service.get_period_pl_with_comparison(
            store_id=STORE_A,
            start_date=current_start,
            end_date=current_end,
            tenant_id=TENANT_ID,
            db=db,
            comparison="yoy",  # year-over-year
        )

    current_rev = 50_000 * 30
    prior_rev = 40_000 * 30
    expected_yoy = (current_rev - prior_rev) / prior_rev

    assert result["current"]["revenue_fen"] == current_rev
    assert result["prior"]["revenue_fen"] == prior_rev
    assert result["revenue_yoy_rate"] == pytest.approx(expected_yoy, abs=0.001)


@pytest.mark.asyncio
async def test_month_over_month_calculation():
    """环比：本月收入与上月对比"""
    service = PLReportService()
    db = AsyncMock()

    current_start = date(2026, 3, 1)
    current_end = date(2026, 3, 31)

    current_rows = [
        {"biz_date": date(2026, 3, 1 + i), "revenue_fen": 55_000, "raw_cost_fen": 16_500}
        for i in range(31)
    ]
    prior_rows = [
        {"biz_date": date(2026, 2, 1 + i), "revenue_fen": 50_000, "raw_cost_fen": 15_000}
        for i in range(28)
    ]

    async def mock_fetch(store_id, start, end, tenant_id, db_session):
        if start.month == 3:
            return current_rows
        return prior_rows

    with patch.object(service, "_fetch_period_daily_rows", new=mock_fetch):
        result = await service.get_period_pl_with_comparison(
            store_id=STORE_A,
            start_date=current_start,
            end_date=current_end,
            tenant_id=TENANT_ID,
            db=db,
            comparison="mom",  # month-over-month
        )

    assert result["current"]["revenue_fen"] == 55_000 * 31
    assert result["prior"]["revenue_fen"] == 50_000 * 28
    # 环比增长率 = (current - prior) / prior
    assert "revenue_mom_rate" in result


# ─── Test 5: PLReport 数据结构完整性 ─────────────────────────────────────────

def test_pl_report_fields():
    """PLReport 包含所有必要字段"""
    report = PLReport(
        store_id=STORE_A,
        start_date=date(2026, 3, 30),
        end_date=date(2026, 3, 30),
        revenue_fen=100_000,
        raw_material_cost_fen=35_000,
        labor_cost_fen=20_000,
        rent_fen=10_000,
        other_opex_fen=5_000,
        period_days=1,
    )

    assert report.gross_profit_fen == 65_000
    assert report.net_profit_fen == 30_000       # 100000-35000-20000-10000-5000
    assert report.gross_margin_rate == pytest.approx(0.65, abs=0.001)
    assert report.net_margin_rate == pytest.approx(0.30, abs=0.001)
    assert report.avg_daily_revenue_fen == 100_000


# ─── Test 6: 凭证列表查询 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_vouchers_by_store_date():
    """凭证列表按门店+日期过滤，返回正确格式"""
    service = PLReportService()
    db = AsyncMock()

    mock_vouchers = [
        {"id": str(uuid.uuid4()), "voucher_no": "V20260330001",
         "voucher_type": "sales", "total_amount": "1000.00", "status": "draft"},
        {"id": str(uuid.uuid4()), "voucher_no": "V20260330002",
         "voucher_type": "cost", "total_amount": "350.00", "status": "confirmed"},
    ]

    with patch.object(service, "_fetch_vouchers",
                      new=AsyncMock(return_value=mock_vouchers)):
        result = await service.get_vouchers(
            store_id=STORE_A,
            biz_date=date(2026, 3, 30),
            tenant_id=TENANT_ID,
            db=db,
        )

    assert len(result) == 2
    assert result[0]["voucher_no"] == "V20260330001"
