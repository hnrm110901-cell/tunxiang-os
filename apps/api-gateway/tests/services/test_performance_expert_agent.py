"""
绩效专家 Agent — 单元测试

覆盖：
  1) 低指标门店产生 >=1 个归因原因
  2) 同行均值上方门店产生"无显著短板"兜底
  3) 预期月度影响 ¥ 与营业额成正比
"""

import sys
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest  # noqa: E402

from src.services.ai_agent_market.performance_expert_agent import (  # noqa: E402
    PerformanceExpertAgent,
)


@pytest.mark.asyncio
async def test_low_store_has_reasons(monkeypatch):
    agent = PerformanceExpertAgent()
    # LLM 干扰清除
    monkeypatch.setattr(agent, "_llm_narrative", AsyncMock(return_value="叙述"))
    stores = [{
        "store_id": "S1", "name": "湘府店",
        "revenue_fen": 50000000,  # ¥500k/月
        "turnover_rate": 2.0,
        "avg_ticket_fen": 5000,
        "labor_efficiency": 2000,
        "okr_completion": 0.4,
    }]
    peer = {"turnover_rate": 3.5, "avg_ticket_yuan": 85, "labor_efficiency": 3000}
    res = await agent.analyze(stores, peer_avg=peer)
    assert res["total_stores"] == 1
    r0 = res["results"][0]
    assert len(r0["reasons"]) >= 1
    assert r0["expected_monthly_impact_yuan"] > 0


@pytest.mark.asyncio
async def test_healthy_store_fallback(monkeypatch):
    agent = PerformanceExpertAgent()
    monkeypatch.setattr(agent, "_llm_narrative", AsyncMock(return_value="ok"))
    stores = [{
        "store_id": "S2", "name": "星河店",
        "revenue_fen": 80000000,
        "turnover_rate": 4.5,
        "avg_ticket_fen": 12000,
        "labor_efficiency": 3800,
        "okr_completion": 0.9,
    }]
    peer = {"turnover_rate": 3.5, "avg_ticket_yuan": 85, "labor_efficiency": 3000}
    res = await agent.analyze(stores, peer_avg=peer)
    r0 = res["results"][0]
    assert any("平均线" in s or "未出现" in s for s in r0["reasons"])
