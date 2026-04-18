"""
执行过程审计员 Agent — 单元测试（mock DB）

覆盖：
  1) 多条 high severity → risk_level=high
  2) 无发现 → risk_level=low
"""

import sys
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest  # noqa: E402

from src.services.ai_agent_market.audit_agent import AuditAgent  # noqa: E402


@pytest.mark.asyncio
async def test_scan_high_risk(monkeypatch):
    agent = AuditAgent(db=MagicMock())
    # mock 所有 _count_events
    counts = {"frequent_export": 25, "approval_bypass": 3, "punch_anomaly": 0}
    call_order = ["frequent_export", "approval_bypass", "punch_anomaly"]
    it = iter(call_order)

    async def fake_count(sql, params):
        return counts[next(it)]

    monkeypatch.setattr(agent, "_count_events", fake_count)
    monkeypatch.setattr(agent, "_summarize", AsyncMock(return_value="模拟总结"))

    res = await agent.scan("T1", hours=24)
    assert res["risk_level"] == "high"
    types = {f["type"] for f in res["findings"]}
    assert "frequent_export" in types
    assert "approval_bypass" in types


@pytest.mark.asyncio
async def test_scan_low_risk(monkeypatch):
    agent = AuditAgent(db=MagicMock())

    async def fake_count(sql, params):
        return 0

    monkeypatch.setattr(agent, "_count_events", fake_count)
    monkeypatch.setattr(agent, "_summarize", AsyncMock(return_value="无异常"))

    res = await agent.scan("T2", hours=6)
    assert res["risk_level"] == "low"
    assert res["findings"] == []
