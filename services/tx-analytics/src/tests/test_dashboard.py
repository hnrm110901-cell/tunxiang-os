"""经营驾驶舱 API + 服务层测试

覆盖：today_overview / store_ranking / alert_summary
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.alert_summary import (
    aggregate_alert_stats,
    get_alert_stats,
    get_today_alerts,
    sort_alerts_by_severity,
)
from services.store_ranking import (
    calc_vs_avg_pct,
    determine_trend,
    get_store_comparison,
    get_store_ranking,
)
from services.today_overview import (
    calc_pct_change,
    find_peak_hour,
    get_multi_store_overview,
    get_today_overview,
)

# ════════════════════════════════════════
# today_overview 测试
# ════════════════════════════════════════

class TestCalcPctChange:
    def test_positive_growth(self):
        assert calc_pct_change(120, 100) == 20.0

    def test_negative_growth(self):
        assert calc_pct_change(80, 100) == -20.0

    def test_zero_previous_returns_none(self):
        assert calc_pct_change(100, 0) is None

    def test_negative_previous_returns_none(self):
        assert calc_pct_change(100, -5) is None

    def test_no_change(self):
        assert calc_pct_change(100, 100) == 0.0


class TestFindPeakHour:
    def test_normal(self):
        assert find_peak_hour({11: 100, 12: 300, 13: 200}) == 12

    def test_empty(self):
        assert find_peak_hour({}) is None

    def test_single_hour(self):
        assert find_peak_hour({18: 500}) == 18


@pytest.mark.asyncio
async def test_get_today_overview_mock():
    """使用 mock 数据测试单店今日总览"""
    result = await get_today_overview("store-001", "tenant-001", db=None)
    assert result["store_id"] == "store-001"
    assert result["revenue_fen"] > 0
    assert result["order_count"] > 0
    assert result["avg_ticket_fen"] > 0
    assert "vs_yesterday" in result
    assert "vs_last_week" in result
    assert result["peak_hour"] is not None
    assert 0 <= result["current_occupancy_pct"] <= 100


@pytest.mark.asyncio
async def test_get_multi_store_overview_mock():
    """使用 mock 数据测试多店概览"""
    result = await get_multi_store_overview("tenant-001", db=None)
    assert len(result) == 3
    for store in result:
        assert "store_id" in store
        assert "store_name" in store
        assert "revenue_fen" in store
        assert "orders" in store
        assert "health_score" in store


# ════════════════════════════════════════
# store_ranking 测试
# ════════════════════════════════════════

class TestCalcVsAvgPct:
    def test_above_avg(self):
        assert calc_vs_avg_pct(120, 100) == 20.0

    def test_below_avg(self):
        assert calc_vs_avg_pct(80, 100) == -20.0

    def test_zero_avg(self):
        assert calc_vs_avg_pct(100, 0) is None


class TestDetermineTrend:
    def test_up(self):
        assert determine_trend([100, 110]) == "up"

    def test_down(self):
        assert determine_trend([100, 90]) == "down"

    def test_flat(self):
        assert determine_trend([100, 100]) == "flat"

    def test_single_value(self):
        assert determine_trend([100]) == "flat"

    def test_empty(self):
        assert determine_trend([]) == "flat"


@pytest.mark.asyncio
async def test_get_store_ranking_mock():
    """使用 mock 数据测试门店排行（倒序）"""
    result = await get_store_ranking("revenue", "today", "tenant-001", db=None)
    assert len(result) == 4
    # 默认倒序，第1名 value 应该最大
    assert result[0]["rank"] == 1
    assert result[0]["value"] >= result[1]["value"]
    for item in result:
        assert "store_id" in item
        assert "vs_avg_pct" in item
        assert "trend" in item


@pytest.mark.asyncio
async def test_get_store_ranking_ascending():
    """正序排行"""
    result = await get_store_ranking("revenue", "today", "tenant-001", db=None, ascending=True)
    assert result[0]["value"] <= result[1]["value"]


@pytest.mark.asyncio
async def test_get_store_ranking_invalid_metric():
    """非法 metric 应抛出 ValueError"""
    with pytest.raises(ValueError, match="invalid metric"):
        await get_store_ranking("invalid", "today", "tenant-001", db=None)


@pytest.mark.asyncio
async def test_get_store_ranking_invalid_date_range():
    """非法 date_range 应抛出 ValueError"""
    with pytest.raises(ValueError, match="invalid date_range"):
        await get_store_ranking("revenue", "invalid", "tenant-001", db=None)


@pytest.mark.asyncio
async def test_get_store_comparison_mock():
    """多店对比"""
    result = await get_store_comparison(
        ["store-001", "store-002"],
        ["revenue", "margin"],
        "today",
        "tenant-001",
        db=None,
    )
    assert "stores" in result
    assert "metrics" in result
    assert "revenue" in result["metrics"]
    assert "margin" in result["metrics"]


# ════════════════════════════════════════
# alert_summary 测试
# ════════════════════════════════════════

class TestAggregateAlertStats:
    def test_normal(self):
        alerts = [
            {"type": "discount_anomaly", "severity": "critical", "status": "pending"},
            {"type": "cooking_timeout", "severity": "warning", "status": "resolved"},
            {"type": "stockout", "severity": "info", "status": "pending"},
        ]
        stats = aggregate_alert_stats(alerts)
        assert stats["total"] == 3
        assert stats["by_severity"]["critical"] == 1
        assert stats["by_severity"]["warning"] == 1
        assert stats["by_severity"]["info"] == 1
        assert stats["unresolved"] == 2  # pending + pending

    def test_empty(self):
        stats = aggregate_alert_stats([])
        assert stats["total"] == 0
        assert stats["unresolved"] == 0

    def test_all_resolved(self):
        alerts = [
            {"type": "margin_drop", "severity": "info", "status": "resolved"},
            {"type": "food_safety", "severity": "warning", "status": "resolved"},
        ]
        stats = aggregate_alert_stats(alerts)
        assert stats["unresolved"] == 0


class TestSortAlertsBySeverity:
    def test_severity_order(self):
        alerts = [
            {"severity": "info", "_ts": 100},
            {"severity": "critical", "_ts": 200},
            {"severity": "warning", "_ts": 150},
        ]
        sorted_alerts = sort_alerts_by_severity(alerts)
        assert sorted_alerts[0]["severity"] == "critical"
        assert sorted_alerts[1]["severity"] == "warning"
        assert sorted_alerts[2]["severity"] == "info"

    def test_same_severity_by_time(self):
        alerts = [
            {"severity": "warning", "_ts": 100},
            {"severity": "warning", "_ts": 200},
        ]
        sorted_alerts = sort_alerts_by_severity(alerts)
        # 同级别按时间倒序（_ts 越大越新，排越前）
        assert sorted_alerts[0]["_ts"] == 200


@pytest.mark.asyncio
async def test_get_today_alerts_mock():
    """使用 mock 数据测试今日告警"""
    result = await get_today_alerts("store-001", "tenant-001", db=None)
    assert len(result) > 0
    # 应按 severity 排序：critical 在前
    assert result[0]["severity"] == "critical"
    for alert in result:
        assert "id" in alert
        assert "type" in alert
        assert "title" in alert
        assert "status" in alert
        # 内部排序字段应已移除
        assert "_ts" not in alert


@pytest.mark.asyncio
async def test_get_alert_stats_mock():
    """使用 mock 数据测试异常统计"""
    result = await get_alert_stats("tenant-001", db=None)
    assert result["total"] == 7
    assert result["by_severity"]["critical"] == 2
    assert result["by_severity"]["warning"] == 3
    assert result["by_severity"]["info"] == 1
    # unresolved = total - resolved(2) = 5
    assert result["unresolved"] == 5
    assert "by_type" in result
