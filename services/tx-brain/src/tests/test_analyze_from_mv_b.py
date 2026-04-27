"""Team B: finance_auditor 和 member_insight 的 analyze_from_mv 测试

测试范围（每个 Agent 各 4 个场景）：
  finance_auditor:
    1. 正常路径：返回 pnl + channel_margins，risk_signal = "normal"（gross_margin_rate = 0.50）
    2. 高风险：gross_margin_rate = 0.30 → risk_signal = "high"
    3. 空数据：pnl_row = None → pnl={}, channel_margins=[]
    4. DB错误：SQLAlchemyError → inference_layer = "mv_fast_path_error"

  member_insight:
    1. 正常：total_members=100, high_churn_count=10 → churn_rate=0.10, risk_signal="medium"
    2. 高流失风险：high_churn_count=25, total=100 → risk_signal="high"
    3. 空数据：total_members=0 → note 字段存在
    4. DB错误：SQLAlchemyError → error 字段存在

技术约束：
  - 全部使用 unittest.mock，不连接真实数据库
  - get_db() 通过 async generator 模拟（async def mock_get_db(): yield mock_db）
  - SQLAlchemyError 注入模拟 DB 故障
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from ..agents.finance_auditor import FinanceAuditor
from ..agents.member_insight import MemberInsightAgent

# ═══════════════════════════════════════════════════════════════════
# FinanceAuditor.analyze_from_mv
# ═══════════════════════════════════════════════════════════════════


def _make_pnl_row(gross_margin_rate: float = 0.50) -> MagicMock:
    """构造 mv_store_pnl 物化视图模拟行。"""
    row = MagicMock()
    row._mapping = {
        "store_id": "store-1",
        "stat_date": "2026-04-04",
        "gross_revenue_fen": 100000,
        "net_revenue_fen": 95000,
        "cogs_fen": 47500,
        "gross_profit_fen": 47500,
        "gross_margin_rate": gross_margin_rate,
        "labor_cost_fen": 15000,
        "net_profit_fen": 32500,
        "order_count": 80,
        "avg_check_fen": 1250,
    }
    return row


def _make_channel_rows() -> list[MagicMock]:
    """构造 mv_channel_margin 物化视图模拟行列表。"""
    rows = []
    for channel, rate in [("dine_in", 0.52), ("meituan", 0.38)]:
        row = MagicMock()
        row._mapping = {
            "channel": channel,
            "gross_margin_rate": rate,
            "net_revenue_fen": 60000 if channel == "dine_in" else 35000,
            "order_count": 50 if channel == "dine_in" else 30,
        }
        rows.append(row)
    return rows


def _make_finance_db(
    pnl_row=None,
    channel_rows=None,
    raise_exc: bool = False,
) -> AsyncMock:
    """构造模拟 AsyncSession，支持两次 execute 调用（pnl + channel）。

    第一次 execute 是 set_config，第二次是 pnl 查询，第三次是 channel 查询。
    """
    db = AsyncMock()
    if raise_exc:
        db.execute = AsyncMock(side_effect=SQLAlchemyError("connection refused"))
        return db

    # 第一次调用：set_config（无关返回值）
    set_config_result = MagicMock()

    # 第二次调用：pnl 查询
    pnl_result = MagicMock()
    pnl_result.mappings.return_value.one_or_none.return_value = pnl_row

    # 第三次调用：channel 查询
    channel_result = MagicMock()
    channel_result.mappings.return_value.all.return_value = channel_rows or []

    db.execute = AsyncMock(side_effect=[set_config_result, pnl_result, channel_result])
    return db


@pytest.mark.asyncio
async def test_finance_auditor_mv_normal():
    """正常路径：gross_margin_rate=0.50 → risk_signal=normal，返回 pnl + channel_margins。"""
    agent = FinanceAuditor()

    mock_db = _make_finance_db(
        pnl_row=_make_pnl_row(gross_margin_rate=0.50),
        channel_rows=_make_channel_rows(),
    )

    async def mock_get_db():
        yield mock_db

    with patch("services.tx_brain.src.agents.finance_auditor.get_db", mock_get_db):
        result = await agent.analyze_from_mv("tenant-1", "store-1")

    assert result["inference_layer"] == "mv_fast_path"
    assert result["agent"] == "FinanceAuditor"
    assert result["risk_signal"] == "normal"
    pnl = result["data"]["pnl"]
    assert pnl["gross_margin_rate"] == pytest.approx(0.50)
    assert pnl["order_count"] == 80
    channels = result["data"]["channel_margins"]
    assert len(channels) == 2
    assert channels[0]["channel"] == "dine_in"
    assert channels[0]["gross_margin_rate"] == pytest.approx(0.52)


@pytest.mark.asyncio
async def test_finance_auditor_mv_high_risk():
    """高风险：gross_margin_rate=0.30 < 0.35 → risk_signal=high。"""
    agent = FinanceAuditor()

    mock_db = _make_finance_db(
        pnl_row=_make_pnl_row(gross_margin_rate=0.30),
        channel_rows=[],
    )

    async def mock_get_db():
        yield mock_db

    with patch("services.tx_brain.src.agents.finance_auditor.get_db", mock_get_db):
        result = await agent.analyze_from_mv("tenant-1", "store-1")

    assert result["inference_layer"] == "mv_fast_path"
    assert result["risk_signal"] == "high"
    assert result["data"]["pnl"]["gross_margin_rate"] == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_finance_auditor_mv_empty():
    """空数据：pnl_row=None → pnl={}, channel_margins=[], risk_signal=normal。"""
    agent = FinanceAuditor()

    mock_db = _make_finance_db(pnl_row=None, channel_rows=[])

    async def mock_get_db():
        yield mock_db

    with patch("services.tx_brain.src.agents.finance_auditor.get_db", mock_get_db):
        result = await agent.analyze_from_mv("tenant-1")

    assert result["inference_layer"] == "mv_fast_path"
    assert result["data"]["pnl"] == {}
    assert result["data"]["channel_margins"] == []
    assert result["risk_signal"] == "normal"


@pytest.mark.asyncio
async def test_finance_auditor_mv_db_error():
    """DB 异常：SQLAlchemyError → inference_layer=mv_fast_path_error，error 字段存在。"""
    agent = FinanceAuditor()

    mock_db = _make_finance_db(raise_exc=True)

    async def mock_get_db():
        yield mock_db

    with patch("services.tx_brain.src.agents.finance_auditor.get_db", mock_get_db):
        result = await agent.analyze_from_mv("tenant-1", "store-1")

    assert result["inference_layer"] == "mv_fast_path_error"
    assert result["agent"] == "FinanceAuditor"
    assert "error" in result
    assert result["data"] == {}


# ═══════════════════════════════════════════════════════════════════
# MemberInsightAgent.analyze_from_mv
# ═══════════════════════════════════════════════════════════════════


def _make_clv_row(total_members: int = 100, high_churn_count: int = 10) -> MagicMock:
    """构造 mv_member_clv 聚合查询模拟行。"""
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "total_members": total_members,
        "high_churn_count": high_churn_count,
        "medium_churn_count": 15,
        "avg_clv_fen": 38650.0,
        "total_stored_value_fen": 500000,
        "champions_count": 12,
        "at_risk_count": high_churn_count,
        "avg_visit_count": 4.5,
    }[key]
    row._mapping = {
        "total_members": total_members,
        "high_churn_count": high_churn_count,
        "medium_churn_count": 15,
        "avg_clv_fen": 38650.0,
        "total_stored_value_fen": 500000,
        "champions_count": 12,
        "at_risk_count": high_churn_count,
        "avg_visit_count": 4.5,
    }
    return row


def _make_member_db(row=None, raise_exc: bool = False) -> AsyncMock:
    """构造模拟 AsyncSession（set_config + 聚合查询两次 execute）。"""
    db = AsyncMock()
    if raise_exc:
        db.execute = AsyncMock(side_effect=SQLAlchemyError("timeout"))
        return db

    set_config_result = MagicMock()
    query_result = MagicMock()
    query_result.mappings.return_value.one_or_none.return_value = row

    db.execute = AsyncMock(side_effect=[set_config_result, query_result])
    return db


@pytest.mark.asyncio
async def test_member_insight_mv_normal():
    """正常路径：total=100, high_churn=10 → churn_rate=0.10, risk_signal=medium。"""
    agent = MemberInsightAgent()

    mock_db = _make_member_db(row=_make_clv_row(total_members=100, high_churn_count=10))

    async def mock_get_db():
        yield mock_db

    with patch("services.tx_brain.src.agents.member_insight.get_db", mock_get_db):
        result = await agent.analyze_from_mv("tenant-1")

    assert result["inference_layer"] == "mv_fast_path"
    assert result["agent"] == "MemberInsightAgent"
    assert result["risk_signal"] == "medium"
    assert result["churn_rate"] == pytest.approx(0.10)
    data = result["data"]
    assert data["total_members"] == 100
    assert data["high_churn_count"] == 10
    assert data["avg_clv_fen"] == pytest.approx(38650.0, rel=1e-2)
    assert data["total_stored_value_fen"] == 500000
    assert data["champions_count"] == 12
    assert data["avg_visit_count"] == pytest.approx(4.5, rel=1e-2)


@pytest.mark.asyncio
async def test_member_insight_mv_high_churn():
    """高流失风险：high_churn_count=25, total=100 → churn_rate=0.25 > 0.20 → risk_signal=high。"""
    agent = MemberInsightAgent()

    mock_db = _make_member_db(row=_make_clv_row(total_members=100, high_churn_count=25))

    async def mock_get_db():
        yield mock_db

    with patch("services.tx_brain.src.agents.member_insight.get_db", mock_get_db):
        result = await agent.analyze_from_mv("tenant-1", "store-1")

    assert result["inference_layer"] == "mv_fast_path"
    assert result["risk_signal"] == "high"
    assert result["churn_rate"] == pytest.approx(0.25)
    assert result["data"]["high_churn_count"] == 25


@pytest.mark.asyncio
async def test_member_insight_mv_empty():
    """空数据：total_members=0 → note 字段存在，data={}。"""
    agent = MemberInsightAgent()

    # total_members=0 的模拟行
    row = MagicMock()
    row.__getitem__ = lambda self, key: {"total_members": 0}.get(key)
    row._mapping = {"total_members": 0}

    mock_db = _make_member_db(row=row)

    async def mock_get_db():
        yield mock_db

    with patch("services.tx_brain.src.agents.member_insight.get_db", mock_get_db):
        result = await agent.analyze_from_mv("tenant-1")

    assert result["inference_layer"] == "mv_fast_path"
    assert result["data"] == {}
    assert "note" in result


@pytest.mark.asyncio
async def test_member_insight_mv_db_error():
    """DB 异常：SQLAlchemyError → inference_layer=mv_fast_path_error，error 字段存在。"""
    agent = MemberInsightAgent()

    mock_db = _make_member_db(raise_exc=True)

    async def mock_get_db():
        yield mock_db

    with patch("services.tx_brain.src.agents.member_insight.get_db", mock_get_db):
        result = await agent.analyze_from_mv("tenant-1", "store-1")

    assert result["inference_layer"] == "mv_fast_path_error"
    assert result["agent"] == "MemberInsightAgent"
    assert "error" in result
    assert result["data"] == {}
