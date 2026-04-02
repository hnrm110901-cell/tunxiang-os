"""Boss BI 集团驾驶舱测试

覆盖场景：
  1. 获取今日集团核心KPI（营业额/客单价/翻台率/毛利率）
  2. 多品牌对标排名（含环比增长）
  3. 异常门店预警（低于基准20%触发）
  4. AI 摘要 mock（ModelRouter.complete 被调用）
  5. 数据缺失时返回空值/安全默认值
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from services.group_dashboard_service import (
    BrandPerformance,
    GroupDashboardService,
    GroupKPISnapshot,
    StoreAlert,
    _calc_deviation_pct,
)

# ─── 测试常量 ───
TENANT_ID = "tenant-001"
STORE_ID = "store-001"


# ════════════════════════════════════════
# 辅助纯函数测试
# ════════════════════════════════════════


class TestCalcDeviationPct:
    def test_below_baseline(self):
        """门店低于基准 → 返回负偏差"""
        assert _calc_deviation_pct(80, 100) == -20.0

    def test_above_baseline(self):
        """门店高于基准 → 返回正偏差"""
        assert _calc_deviation_pct(120, 100) == 20.0

    def test_zero_baseline_returns_none(self):
        """基准为 0 时返回 None，避免除零"""
        assert _calc_deviation_pct(100, 0) is None

    def test_no_deviation(self):
        """完全等于基准 → 0.0"""
        assert _calc_deviation_pct(100, 100) == 0.0


# ════════════════════════════════════════
# get_today_group_kpi 测试
# ════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_today_group_kpi_returns_snapshot():
    """db=None 时返回 mock 数据，字段齐全"""
    svc = GroupDashboardService()
    result = await svc.get_today_group_kpi(TENANT_ID, db=None)

    assert isinstance(result, GroupKPISnapshot)
    assert result.tenant_id == TENANT_ID
    assert result.total_revenue_fen >= 0
    assert result.avg_ticket_fen >= 0
    assert result.table_turnover_rate >= 0.0
    assert 0.0 <= result.gross_margin_pct <= 100.0
    assert result.active_store_count >= 0
    assert result.alert_count >= 0


@pytest.mark.asyncio
async def test_get_today_group_kpi_missing_data_returns_safe_defaults():
    """数据缺失（db=None 降级路径）时返回安全默认值，不抛异常"""
    svc = GroupDashboardService()
    result = await svc.get_today_group_kpi("tenant-empty", db=None)

    # 应返回 GroupKPISnapshot 而非抛出异常
    assert isinstance(result, GroupKPISnapshot)
    # 空数据时数值字段应为 0 或合理的默认值
    assert result.total_revenue_fen >= 0
    assert result.active_store_count >= 0


# ════════════════════════════════════════
# get_brand_ranking 测试
# ════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_brand_ranking_returns_list():
    """返回品牌排名列表，包含环比增长字段"""
    svc = GroupDashboardService()
    result = await svc.get_brand_ranking(TENANT_ID, days=7, db=None)

    assert isinstance(result, list)
    assert len(result) >= 1
    for brand in result:
        assert isinstance(brand, BrandPerformance)
        assert brand.brand_id
        assert brand.brand_name
        assert brand.revenue_fen >= 0
        assert brand.order_count >= 0
        # 环比增长可以为 None（没有上期数据时）
        assert brand.revenue_wow_pct is None or isinstance(brand.revenue_wow_pct, float)


@pytest.mark.asyncio
async def test_get_brand_ranking_sorted_by_revenue_desc():
    """排名应按营收倒序排列"""
    svc = GroupDashboardService()
    result = await svc.get_brand_ranking(TENANT_ID, days=7, db=None)

    if len(result) >= 2:
        assert result[0].revenue_fen >= result[1].revenue_fen


@pytest.mark.asyncio
async def test_get_brand_ranking_rank_field_sequential():
    """rank 字段应从 1 开始连续编号"""
    svc = GroupDashboardService()
    result = await svc.get_brand_ranking(TENANT_ID, days=7, db=None)

    for i, brand in enumerate(result, start=1):
        assert brand.rank == i


# ════════════════════════════════════════
# get_store_alerts 测试
# ════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_store_alerts_returns_list():
    """返回预警列表，结构正确"""
    svc = GroupDashboardService()
    result = await svc.get_store_alerts(TENANT_ID, threshold_pct=0.20, db=None)

    assert isinstance(result, list)
    for alert in result:
        assert isinstance(alert, StoreAlert)
        assert alert.store_id
        assert alert.store_name
        assert alert.metric_name
        assert alert.actual_value >= 0
        assert alert.baseline_value >= 0
        assert isinstance(alert.deviation_pct, float)
        assert alert.severity in ("critical", "warning", "info")


@pytest.mark.asyncio
async def test_get_store_alerts_threshold_20pct():
    """低于基准 20% 应触发预警"""
    svc = GroupDashboardService()
    # 使用 mock db，注入低营收门店数据
    result = await svc.get_store_alerts(TENANT_ID, threshold_pct=0.20, db=None)

    # mock 数据中至少有一个门店触发预警（deviation < -20%）
    triggered = [a for a in result if a.deviation_pct <= -20.0]
    assert len(triggered) >= 1


@pytest.mark.asyncio
async def test_get_store_alerts_no_alerts_when_all_normal():
    """若门店数据正常则不触发预警"""
    svc = GroupDashboardService()
    # 使用更严格的阈值（100% 偏差才触发），不应有任何告警
    result = await svc.get_store_alerts(TENANT_ID, threshold_pct=1.0, db=None)
    assert result == []


# ════════════════════════════════════════
# get_ai_daily_brief 测试
# ════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_ai_daily_brief_calls_model_router_when_alerts_exist():
    """有预警时应调用 ModelRouter.complete"""
    svc = GroupDashboardService()
    mock_model_router = MagicMock()
    mock_model_router.complete = AsyncMock(return_value="今日集团营业情况存在3家门店预警，建议重点关注。")

    kpi = GroupKPISnapshot(
        tenant_id=TENANT_ID,
        date="2026-03-31",
        total_revenue_fen=5_000_000,
        avg_ticket_fen=8500,
        table_turnover_rate=2.8,
        gross_margin_pct=62.5,
        active_store_count=12,
        alert_count=3,
    )
    alerts = [
        StoreAlert(
            store_id="store-003",
            store_name="测试门店",
            metric_name="revenue",
            actual_value=30000,
            baseline_value=50000,
            deviation_pct=-40.0,
            severity="critical",
        )
    ]

    brief = await svc.get_ai_daily_brief(TENANT_ID, kpi, alerts, mock_model_router)

    mock_model_router.complete.assert_called_once()
    assert isinstance(brief, str)
    assert len(brief) > 0


@pytest.mark.asyncio
async def test_get_ai_daily_brief_calls_model_router_when_revenue_change_large():
    """营业额变化 > 15% 时应触发 ModelRouter（即使无预警）"""
    svc = GroupDashboardService()
    mock_model_router = MagicMock()
    mock_model_router.complete = AsyncMock(return_value="今日营业额同比大幅增长，请关注备货情况。")

    kpi = GroupKPISnapshot(
        tenant_id=TENANT_ID,
        date="2026-03-31",
        total_revenue_fen=8_000_000,
        avg_ticket_fen=9200,
        table_turnover_rate=3.5,
        gross_margin_pct=65.0,
        active_store_count=12,
        alert_count=0,
        revenue_wow_pct=18.0,  # 超过15%阈值
    )

    brief = await svc.get_ai_daily_brief(TENANT_ID, kpi, [], mock_model_router)

    mock_model_router.complete.assert_called_once()
    assert isinstance(brief, str)


@pytest.mark.asyncio
async def test_get_ai_daily_brief_skips_model_router_when_normal():
    """无预警且营业额变化 ≤ 15% 时不调用 ModelRouter"""
    svc = GroupDashboardService()
    mock_model_router = MagicMock()
    mock_model_router.complete = AsyncMock(return_value="不应被调用")

    kpi = GroupKPISnapshot(
        tenant_id=TENANT_ID,
        date="2026-03-31",
        total_revenue_fen=5_000_000,
        avg_ticket_fen=8500,
        table_turnover_rate=2.8,
        gross_margin_pct=62.5,
        active_store_count=12,
        alert_count=0,
        revenue_wow_pct=5.0,  # 低于15%，不触发AI
    )

    brief = await svc.get_ai_daily_brief(TENANT_ID, kpi, [], mock_model_router)

    mock_model_router.complete.assert_not_called()
    # 返回空字符串或默认摘要
    assert brief == ""


@pytest.mark.asyncio
async def test_get_ai_daily_brief_returns_empty_when_model_unavailable():
    """ModelRouter 不可用（ImportError）时返回空字符串，不影响主流程"""
    svc = GroupDashboardService()

    kpi = GroupKPISnapshot(
        tenant_id=TENANT_ID,
        date="2026-03-31",
        total_revenue_fen=5_000_000,
        avg_ticket_fen=8500,
        table_turnover_rate=2.8,
        gross_margin_pct=62.5,
        active_store_count=12,
        alert_count=2,
    )
    alerts = [
        StoreAlert(
            store_id="store-003",
            store_name="测试门店",
            metric_name="revenue",
            actual_value=30000,
            baseline_value=50000,
            deviation_pct=-40.0,
            severity="critical",
        )
    ]

    # 传入 None 代替 ModelRouter（模拟不可用）
    brief = await svc.get_ai_daily_brief(TENANT_ID, kpi, alerts, model_router=None)

    assert brief == ""
