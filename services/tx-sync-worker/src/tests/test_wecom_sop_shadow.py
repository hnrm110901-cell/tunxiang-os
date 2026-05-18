"""tx-sync-worker · wecom_group_daily_sop dry_run 测试 (W2 P1 issue #758, T2 标准)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services.tx_sync_worker.src.jobs import wecom_sop


@pytest.fixture(autouse=True)
def _clean_run_mode_env(monkeypatch):
    """Each test starts with clean RUN_MODE env."""
    monkeypatch.delenv("RUN_MODE", raising=False)
    yield


@pytest.mark.asyncio
async def test_daily_sop_dry_run_does_not_import_gateway_modules():
    """dry_run 模式: gateway.wecom_group_service 路径不应触, 仅 log + metric.

    强红线: env unset = dry_run = true → 提前 return, 不进 try 块 (无 import gateway).
    验证方法: 直接 monkey-patch module-level logger, 检查调用顺序.
    """
    # 直接 patch attribute (避 string lookup 走 services 顶级 ns)
    with patch.object(wecom_sop, "logger") as mock_logger:
        await wecom_sop._run_daily_sop()
        # 期望: 至少 info(...) 调过 dry_run_skip event
        info_calls = mock_logger.bind.return_value.info.call_args_list
        events = [
            (call.args[0] if call.args else call.kwargs.get("event", ""))
            for call in info_calls
        ]
        assert "dry_run_skip" in events, f"expected dry_run_skip log, got {events}"


@pytest.mark.asyncio
async def test_daily_sop_dry_run_default_true():
    """env unset 时 wecom_sop._is_dry_run() 默认 true."""
    assert wecom_sop._is_dry_run() is True


@pytest.mark.asyncio
async def test_daily_sop_dry_run_records_metric():
    """dry_run 路径 inc sync_executions_total{job=wecom_group_daily_sop, status=dry_run}."""
    from services.tx_sync_worker.src import metrics as m

    if not m._PROM_AVAILABLE:
        pytest.skip("prometheus_client not available")

    before = m.sync_executions_total.labels(
        job="wecom_group_daily_sop", status="dry_run"
    )._value.get()
    await wecom_sop._run_daily_sop()
    after = m.sync_executions_total.labels(
        job="wecom_group_daily_sop", status="dry_run"
    )._value.get()
    assert after == before + 1
