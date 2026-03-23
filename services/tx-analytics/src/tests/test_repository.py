"""AnalyticsRepository 单元测试 — 使用 mock AsyncSession"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.repository import AnalyticsRepository


TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())


def _make_store(**overrides):
    s = MagicMock()
    s.id = overrides.get("id", uuid.UUID(STORE_ID))
    s.tenant_id = uuid.UUID(TENANT_ID)
    s.store_name = overrides.get("store_name", "测试门店")
    s.seats = overrides.get("seats", 80)
    s.monthly_revenue_target_fen = overrides.get("monthly_revenue_target_fen", 300000_00)
    s.turnover_rate_target = overrides.get("turnover_rate_target", 2.0)
    s.waste_rate_target = overrides.get("waste_rate_target", 3.0)
    return s


def _mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


# ─── Tests ───


@pytest.mark.asyncio
async def test_get_store_health():
    """get_store_health 应返回 5 维度评分"""
    session = _mock_session()
    store = _make_store()

    store_result = MagicMock()
    store_result.scalar_one_or_none.return_value = store

    # revenue query: revenue_fen=150000, order_count=60, guest_count=120
    rev_row = MagicMock()
    rev_row.__getitem__ = lambda self, idx: [150000_00, 60, 120][idx]
    revenue_result = MagicMock()
    revenue_result.one.return_value = rev_row

    # complaint count
    complaint_result = MagicMock()
    complaint_result.scalar.return_value = 2

    # employee count
    emp_result = MagicMock()
    emp_result.scalar.return_value = 10

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        store_result,
        revenue_result,
        complaint_result,
        emp_result,
    ]

    repo = AnalyticsRepository(session, TENANT_ID)
    result = await repo.get_store_health(STORE_ID, date="2026-03-23")

    assert result["store_id"] == STORE_ID
    assert result["date"] == "2026-03-23"
    assert "overall_score" in result
    assert "dimensions" in result
    assert "revenue" in result["dimensions"]
    assert "turnover" in result["dimensions"]
    assert "complaint" in result["dimensions"]
    assert "labor" in result["dimensions"]
    assert result["order_count"] == 60


@pytest.mark.asyncio
async def test_get_daily_report():
    """get_daily_report 应返回日报数据"""
    session = _mock_session()

    # main query row
    main_row = MagicMock()
    main_row.__getitem__ = lambda self, idx: [250000_00, 15000_00, 80, 160, 312500][idx]
    main_result = MagicMock()
    main_result.one.return_value = main_row

    # channels
    channel_rows = [("dine_in", 60, 200000_00), ("takeout", 20, 50000_00)]
    channel_result = MagicMock()
    channel_result.all.return_value = channel_rows

    # cancel count
    cancel_result = MagicMock()
    cancel_result.scalar.return_value = 3

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        main_result,
        channel_result,
        cancel_result,
    ]

    repo = AnalyticsRepository(session, TENANT_ID)
    result = await repo.get_daily_report(STORE_ID, date="2026-03-23")

    assert result["store_id"] == STORE_ID
    assert result["date"] == "2026-03-23"
    assert result["revenue_fen"] == 250000_00
    assert result["order_count"] == 80
    assert result["cancel_count"] == 3
    assert "dine_in" in result["channels"]
    assert result["channels"]["dine_in"]["count"] == 60


@pytest.mark.asyncio
async def test_get_kpi_alerts_revenue_behind():
    """get_kpi_alerts 营收落后时应产生预警"""
    session = _mock_session()
    store = _make_store(monthly_revenue_target_fen=300000_00)

    store_result = MagicMock()
    store_result.scalar_one_or_none.return_value = store

    # month revenue - very low
    rev_result = MagicMock()
    rev_result.scalar.return_value = 10000_00

    # inventory alerts
    inv_result = MagicMock()
    inv_result.scalar.return_value = 0

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        store_result,
        rev_result,
        inv_result,
    ]

    repo = AnalyticsRepository(session, TENANT_ID)
    result = await repo.get_kpi_alerts(STORE_ID)

    assert len(result) >= 1
    assert any(a["type"] == "revenue_behind" for a in result)


@pytest.mark.asyncio
async def test_get_kpi_alerts_inventory_critical():
    """get_kpi_alerts 库存告急时应产生预警"""
    session = _mock_session()
    store = _make_store(monthly_revenue_target_fen=0)  # no revenue target

    store_result = MagicMock()
    store_result.scalar_one_or_none.return_value = store

    rev_result = MagicMock()
    rev_result.scalar.return_value = 0

    inv_result = MagicMock()
    inv_result.scalar.return_value = 5  # 5 items critical

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        store_result,
        rev_result,
        inv_result,
    ]

    repo = AnalyticsRepository(session, TENANT_ID)
    result = await repo.get_kpi_alerts(STORE_ID)

    assert any(a["type"] == "inventory_critical" for a in result)
    inv_alert = [a for a in result if a["type"] == "inventory_critical"][0]
    assert inv_alert["count"] == 5
    assert inv_alert["severity"] == "high"


@pytest.mark.asyncio
async def test_get_top3_decisions():
    """get_top3_decisions 应返回最多 3 条决策"""
    session = _mock_session()

    # slow items
    slow_result = MagicMock()
    slow_result.all.return_value = [("冷菜A", 2), ("冷菜B", 3)]

    # discount stats
    d_row = MagicMock()
    d_row.__getitem__ = lambda self, idx: [100, 40][idx]  # 40% discount rate
    discount_result = MagicMock()
    discount_result.one.return_value = d_row

    # inventory low count
    inv_result = MagicMock()
    inv_result.scalar.return_value = 3

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        slow_result,
        discount_result,
        inv_result,
    ]

    repo = AnalyticsRepository(session, TENANT_ID)
    result = await repo.get_top3_decisions(STORE_ID)

    assert len(result) <= 3
    assert len(result) >= 1
    types = [d["type"] for d in result]
    assert "menu_optimization" in types


@pytest.mark.asyncio
async def test_parse_date():
    """_parse_date 应正确解析日期字符串"""
    from datetime import date

    assert AnalyticsRepository._parse_date("2026-03-23") == date(2026, 3, 23)
    assert AnalyticsRepository._parse_date("today") == date.today()
    assert AnalyticsRepository._parse_date(None) == date.today()
