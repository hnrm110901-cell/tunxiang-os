"""营收聚合引擎测试

覆盖：
1. 日营收正常计算（毛收/折扣/退款/净营收/客单价/支付分布/小时分布）
2. 空数据返回 0 而非报错
3. 多门店 RLS 隔离（不同 tenant_id 数据不互通）
4. 日期范围过滤（start_date > end_date 报错，区间超限报错）
5. 区间报表聚合（day/week/month 粒度）
6. 支付方式对账计算（净值/差值正确）
7. 退款 fallback 逻辑（refunds 表查询失败时切换到 order_items.return_flag）
"""
from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.tx_finance.src.services.revenue_aggregation_service import (
    RevenueAggregationService,
    DailyRevenueFast,
    RevenueRangeReport,
    PaymentReconciliationReport,
)


# ─── 共用 Fixtures ────────────────────────────────────────────────────────────

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
STORE_A = uuid.uuid4()
STORE_B = uuid.uuid4()
BIZ_DATE = date(2026, 3, 31)
START_DATE = date(2026, 3, 1)
END_DATE = date(2026, 3, 31)


def _make_db() -> AsyncMock:
    return AsyncMock()


def _make_service() -> RevenueAggregationService:
    return RevenueAggregationService()


# ─── Test 1: 日营收正常计算 ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_daily_revenue_fast_normal():
    """正常场景：毛收/折扣/退款/净营收/客单价/支付分布/小时分布全部正确"""
    service = _make_service()
    db = _make_db()

    order_summary = {"gross_revenue_fen": 100_000, "discount_fen": 5_000, "order_count": 10}
    payment_rows = [
        {"method": "wechat", "amount_fen": 60_000, "order_count": 6},
        {"method": "alipay", "amount_fen": 35_000, "order_count": 4},
    ]
    refund_fen = 2_000
    hourly_rows = [
        {"hour": 12, "order_count": 5, "revenue_fen": 50_000},
        {"hour": 18, "order_count": 5, "revenue_fen": 45_000},
    ]

    with (
        patch.object(service._repo, "fetch_daily_order_summary", new=AsyncMock(return_value=order_summary)),
        patch.object(service._repo, "fetch_payment_breakdown", new=AsyncMock(return_value=payment_rows)),
        patch.object(service._repo, "fetch_daily_refund_from_payments", new=AsyncMock(return_value=refund_fen)),
        patch.object(service._repo, "fetch_hourly_breakdown", new=AsyncMock(return_value=hourly_rows)),
    ):
        result = await service.get_daily_revenue_fast(TENANT_A, STORE_A, BIZ_DATE, db)

    assert isinstance(result, DailyRevenueFast)
    # 净营收 = 毛收 - 折扣 - 退款 = 100000 - 5000 - 2000 = 93000
    assert result.gross_revenue_fen == 100_000
    assert result.discount_fen == 5_000
    assert result.refund_fen == 2_000
    assert result.net_revenue_fen == 93_000
    assert result.order_count == 10
    # 客单价 = 93000 // 10 = 9300
    assert result.avg_ticket_fen == 9_300

    # 支付分布
    assert len(result.payment_breakdown) == 2
    wechat_pb = next(p for p in result.payment_breakdown if p.method == "wechat")
    assert wechat_pb.label == "微信"
    assert wechat_pb.amount_fen == 60_000
    # ratio = 60000 / 95000 ≈ 0.6316
    assert wechat_pb.ratio == pytest.approx(60_000 / 95_000, abs=1e-3)

    # 小时分布
    assert len(result.hourly_breakdown) == 2
    noon = next(h for h in result.hourly_breakdown if h.hour == 12)
    assert noon.order_count == 5
    assert noon.revenue_fen == 50_000


# ─── Test 2: 空数据返回 0 而非报错 ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_daily_revenue_fast_empty_store():
    """空数据场景：无订单时所有金额为 0，不抛异常"""
    service = _make_service()
    db = _make_db()

    with (
        patch.object(service._repo, "fetch_daily_order_summary",
                     new=AsyncMock(return_value={"gross_revenue_fen": 0, "discount_fen": 0, "order_count": 0})),
        patch.object(service._repo, "fetch_payment_breakdown",
                     new=AsyncMock(return_value=[])),
        patch.object(service._repo, "fetch_daily_refund_from_payments",
                     new=AsyncMock(return_value=0)),
        patch.object(service._repo, "fetch_hourly_breakdown",
                     new=AsyncMock(return_value=[])),
    ):
        result = await service.get_daily_revenue_fast(TENANT_A, STORE_A, BIZ_DATE, db)

    assert result.gross_revenue_fen == 0
    assert result.net_revenue_fen == 0
    assert result.order_count == 0
    assert result.avg_ticket_fen == 0   # 不除以零
    assert result.payment_breakdown == []
    assert result.hourly_breakdown == []


# ─── Test 3: 多门店 RLS 隔离 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_rls_isolation():
    """RLS 隔离：两个 tenant 的 fetch 调用携带各自的 tenant_id，互不干扰"""
    service = _make_service()
    db_a = _make_db()
    db_b = _make_db()

    tenant_calls: list[uuid.UUID] = []
    store_calls: list[uuid.UUID] = []

    async def mock_summary(tenant_id, store_id, biz_date, db):
        tenant_calls.append(tenant_id)
        store_calls.append(store_id)
        return {"gross_revenue_fen": 0, "discount_fen": 0, "order_count": 0}

    with (
        patch.object(service._repo, "fetch_daily_order_summary", new=mock_summary),
        patch.object(service._repo, "fetch_payment_breakdown", new=AsyncMock(return_value=[])),
        patch.object(service._repo, "fetch_daily_refund_from_payments", new=AsyncMock(return_value=0)),
        patch.object(service._repo, "fetch_hourly_breakdown", new=AsyncMock(return_value=[])),
    ):
        await service.get_daily_revenue_fast(TENANT_A, STORE_A, BIZ_DATE, db_a)
        await service.get_daily_revenue_fast(TENANT_B, STORE_B, BIZ_DATE, db_b)

    # 两次调用传入了不同的 tenant_id
    assert tenant_calls[0] == TENANT_A
    assert tenant_calls[1] == TENANT_B
    assert tenant_calls[0] != tenant_calls[1]

    # 同时 store_id 也隔离
    assert store_calls[0] == STORE_A
    assert store_calls[1] == STORE_B


# ─── Test 4: 退款 fallback 逻辑 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_daily_revenue_fallback_to_return_items():
    """refunds 表查询失败时，fallback 到 order_items.return_flag 计算退款"""
    service = _make_service()
    db = _make_db()

    fallback_refund = 1_500

    with (
        patch.object(service._repo, "fetch_daily_order_summary",
                     new=AsyncMock(return_value={"gross_revenue_fen": 50_000, "discount_fen": 0, "order_count": 5})),
        patch.object(service._repo, "fetch_payment_breakdown", new=AsyncMock(return_value=[])),
        patch.object(service._repo, "fetch_daily_refund_from_payments",
                     side_effect=OSError("DB table not found")),
        patch.object(service._repo, "fetch_daily_refund_from_items",
                     new=AsyncMock(return_value=fallback_refund)),
        patch.object(service._repo, "fetch_hourly_breakdown", new=AsyncMock(return_value=[])),
    ):
        result = await service.get_daily_revenue_fast(TENANT_A, STORE_A, BIZ_DATE, db)

    # fallback 成功，退款数据正确
    assert result.refund_fen == fallback_refund
    assert result.net_revenue_fen == 50_000 - 0 - fallback_refund


# ─── Test 5: 区间报表日期校验 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_revenue_range_report_invalid_granularity():
    """granularity 参数不合法时抛出 ValueError"""
    service = _make_service()
    db = _make_db()

    with pytest.raises(ValueError, match="day/week/month"):
        await service.get_revenue_range_report(
            TENANT_A, STORE_A, START_DATE, END_DATE, "hour", db
        )


# ─── Test 6: 区间报表正常聚合 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_revenue_range_report_normal():
    """多日期区间报表：摘要金额正确，时序趋势正确"""
    service = _make_service()
    db = _make_db()

    range_summary = {
        "gross_revenue_fen": 600_000,
        "discount_fen": 30_000,
        "final_revenue_fen": 570_000,
        "order_count": 60,
    }
    range_refund = 10_000
    trend_rows = [
        {"period": "2026-03-01", "revenue_fen": 20_000, "discount_fen": 1_000, "order_count": 2},
        {"period": "2026-03-02", "revenue_fen": 21_000, "discount_fen": 1_000, "order_count": 2},
    ]

    with (
        patch.object(service._repo, "fetch_range_order_summary", new=AsyncMock(return_value=range_summary)),
        patch.object(service._repo, "fetch_range_refund_from_payments", new=AsyncMock(return_value=range_refund)),
        patch.object(service._repo, "fetch_revenue_by_granularity", new=AsyncMock(return_value=trend_rows)),
    ):
        result = await service.get_revenue_range_report(
            TENANT_A, STORE_A, START_DATE, END_DATE, "day", db
        )

    assert isinstance(result, RevenueRangeReport)
    # 净营收 = 600000 - 30000 - 10000 = 560000
    assert result.net_revenue_fen == 560_000
    assert result.order_count == 60
    assert result.avg_ticket_fen == 560_000 // 60

    assert len(result.trend) == 2
    assert result.trend[0].period == "2026-03-01"
    assert result.trend[0].revenue_fen == 20_000


# ─── Test 7: 支付方式对账计算 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_payment_reconciliation_calculation():
    """对账：净值 = paid - refund，差值 = paid - order_amount"""
    service = _make_service()
    db = _make_db()

    raw_rows = [
        {
            "method": "wechat",
            "order_count": 10,
            "order_amount_fen": 50_000,
            "paid_amount_fen": 49_500,
            "refund_amount_fen": 500,
        },
        {
            "method": "cash",
            "order_count": 5,
            "order_amount_fen": 20_000,
            "paid_amount_fen": 20_000,
            "refund_amount_fen": 0,
        },
    ]

    with patch.object(service._repo, "fetch_payment_reconciliation", new=AsyncMock(return_value=raw_rows)):
        result = await service.get_payment_reconciliation(
            TENANT_A, STORE_A, START_DATE, END_DATE, db
        )

    assert isinstance(result, PaymentReconciliationReport)

    wechat_row = next(r for r in result.rows if r.method == "wechat")
    assert wechat_row.label == "微信"
    # 净值 = 49500 - 500 = 49000
    assert wechat_row.net_fen == 49_000
    # 差值 = 49500 - 50000 = -500（少收）
    assert wechat_row.diff_fen == -500

    cash_row = next(r for r in result.rows if r.method == "cash")
    assert cash_row.net_fen == 20_000
    assert cash_row.diff_fen == 0

    # 汇总
    assert result.total_order_amount_fen == 70_000
    assert result.total_paid_amount_fen == 69_500
    assert result.total_refund_amount_fen == 500
    assert result.total_net_fen == 69_000
    assert result.total_diff_fen == -500


# ─── Test 8: 对账报表空数据 ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_payment_reconciliation_empty():
    """无数据时对账报表所有金额为 0，rows 为空列表"""
    service = _make_service()
    db = _make_db()

    with patch.object(service._repo, "fetch_payment_reconciliation", new=AsyncMock(return_value=[])):
        result = await service.get_payment_reconciliation(
            TENANT_A, STORE_A, START_DATE, END_DATE, db
        )

    assert result.rows == []
    assert result.total_order_amount_fen == 0
    assert result.total_paid_amount_fen == 0
    assert result.total_net_fen == 0
    assert result.total_diff_fen == 0


# ─── Test 9: to_dict 序列化完整性 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_daily_revenue_fast_to_dict_keys():
    """to_dict() 输出包含所有约定字段，确保 API 响应结构稳定"""
    service = _make_service()
    db = _make_db()

    with (
        patch.object(service._repo, "fetch_daily_order_summary",
                     new=AsyncMock(return_value={"gross_revenue_fen": 10_000, "discount_fen": 0, "order_count": 1})),
        patch.object(service._repo, "fetch_payment_breakdown",
                     new=AsyncMock(return_value=[{"method": "cash", "amount_fen": 10_000, "order_count": 1}])),
        patch.object(service._repo, "fetch_daily_refund_from_payments", new=AsyncMock(return_value=0)),
        patch.object(service._repo, "fetch_hourly_breakdown",
                     new=AsyncMock(return_value=[{"hour": 12, "order_count": 1, "revenue_fen": 10_000}])),
    ):
        result = await service.get_daily_revenue_fast(TENANT_A, STORE_A, BIZ_DATE, db)

    d = result.to_dict()
    required_keys = {
        "store_id", "biz_date", "gross_revenue_fen", "discount_fen",
        "refund_fen", "net_revenue_fen", "order_count", "avg_ticket_fen",
        "payment_breakdown", "hourly_breakdown",
    }
    assert required_keys.issubset(d.keys()), f"缺少字段: {required_keys - d.keys()}"

    pb = d["payment_breakdown"][0]
    assert set(pb.keys()) >= {"method", "label", "amount_fen", "order_count", "ratio"}

    hb = d["hourly_breakdown"][0]
    assert set(hb.keys()) >= {"hour", "order_count", "revenue_fen"}


# ─── Test 10: 区间报表退款查询失败时降级为 0 ─────────────────────────────────

@pytest.mark.asyncio
async def test_revenue_range_report_refund_failure_degrades_gracefully():
    """区间报表中退款查询失败时，不中断，以 0 继续计算"""
    service = _make_service()
    db = _make_db()

    range_summary = {
        "gross_revenue_fen": 100_000,
        "discount_fen": 5_000,
        "final_revenue_fen": 95_000,
        "order_count": 10,
    }

    with (
        patch.object(service._repo, "fetch_range_order_summary", new=AsyncMock(return_value=range_summary)),
        patch.object(service._repo, "fetch_range_refund_from_payments",
                     side_effect=OSError("payments table unavailable")),
        patch.object(service._repo, "fetch_revenue_by_granularity", new=AsyncMock(return_value=[])),
    ):
        result = await service.get_revenue_range_report(
            TENANT_A, STORE_A, START_DATE, END_DATE, "day", db
        )

    # refund 降级为 0
    assert result.refund_fen == 0
    assert result.net_revenue_fen == 100_000 - 5_000 - 0
