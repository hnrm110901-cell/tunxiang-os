"""tx-sync-worker · Phase 1 dry_run 集成测试 (W2 P1 issue #758, T2 标准).

覆盖:
  - 5 jobs 注册 + cron trigger 验证
  - 4 个 pinzhi dry_run 路径 (log + metric, 不调 adapter)
  - dry_run env unset 默认 true (强红线 §7.1)
  - scheduler 启停不挂

T2 标准, 不强制 _tier1.py 后缀 (per memory `feedback_tier1_test_filename_workflow_trigger.md`).
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from services.tx_sync_worker.src.jobs import pinzhi_sync


def _safe_shutdown(scheduler) -> None:
    """shutdown scheduler 即便未 start (apscheduler 未 start raises SchedulerNotRunningError)."""
    try:
        _safe_shutdown(scheduler)
    except Exception:  # noqa: BLE001 — test cleanup, 已知 SchedulerNotRunningError
        pass


@pytest.fixture(autouse=True)
def _clean_run_mode_env(monkeypatch):
    """Each test starts with clean RUN_MODE env."""
    monkeypatch.delenv("RUN_MODE", raising=False)
    yield


# ── scheduler registration ──────────────────────────────────────────────────


def test_create_scheduler_registers_five_jobs():
    """create_sync_scheduler() 注册 5 jobs (4 pinzhi + 1 wecom)."""
    from services.tx_sync_worker.src.scheduler import create_sync_scheduler

    scheduler = create_sync_scheduler()
    try:
        job_ids = {j.id for j in scheduler.get_jobs()}
        assert job_ids == {
            "daily_dishes_sync",
            "daily_master_data_sync",
            "hourly_orders_incremental_sync",
            "quarter_members_incremental_sync",
            "wecom_group_daily_sop",
        }
    finally:
        _safe_shutdown(scheduler)


def test_scheduler_timezone_asia_shanghai():
    """scheduler 默认 timezone Asia/Shanghai (Q3 决议 + plan §7.2 缓解)."""
    from services.tx_sync_worker.src.scheduler import create_sync_scheduler

    scheduler = create_sync_scheduler()
    try:
        assert str(scheduler.timezone) == "Asia/Shanghai"
    finally:
        _safe_shutdown(scheduler)


def test_dishes_sync_cron_02_00():
    """daily_dishes_sync 在 02:00 触发 (与 gateway sync_scheduler.py:598 一致)."""
    from services.tx_sync_worker.src.scheduler import create_sync_scheduler

    scheduler = create_sync_scheduler()
    try:
        job = scheduler.get_job("daily_dishes_sync")
        assert job is not None
        # Trigger.fields: cron has multiple fields; hour and minute 在 fields 中
        hour_field = next(f for f in job.trigger.fields if f.name == "hour")
        minute_field = next(f for f in job.trigger.fields if f.name == "minute")
        # 表达式: list[range/single]; .first 是匹配的第一个值
        assert hour_field.expressions[0].first == 2
        assert minute_field.expressions[0].first == 0
    finally:
        _safe_shutdown(scheduler)


def test_master_data_sync_cron_03_00():
    """daily_master_data_sync 在 03:00 触发."""
    from services.tx_sync_worker.src.scheduler import create_sync_scheduler

    scheduler = create_sync_scheduler()
    try:
        job = scheduler.get_job("daily_master_data_sync")
        hour_field = next(f for f in job.trigger.fields if f.name == "hour")
        minute_field = next(f for f in job.trigger.fields if f.name == "minute")
        assert hour_field.expressions[0].first == 3
        assert minute_field.expressions[0].first == 0
    finally:
        _safe_shutdown(scheduler)


def test_wecom_sop_cron_09_00():
    """wecom_group_daily_sop 在 09:00 触发 (gateway main.py:120 一致)."""
    from services.tx_sync_worker.src.scheduler import create_sync_scheduler

    scheduler = create_sync_scheduler()
    try:
        job = scheduler.get_job("wecom_group_daily_sop")
        hour_field = next(f for f in job.trigger.fields if f.name == "hour")
        minute_field = next(f for f in job.trigger.fields if f.name == "minute")
        assert hour_field.expressions[0].first == 9
        assert minute_field.expressions[0].first == 0
    finally:
        _safe_shutdown(scheduler)


# ── dry_run mode (强红线 §7.1) ──────────────────────────────────────────────


def test_is_dry_run_default_true_when_env_unset():
    """env unset → dry_run=true (强红线 Q3 决议)."""
    # autouse fixture 已删 RUN_MODE
    assert "RUN_MODE" not in os.environ
    assert pinzhi_sync._is_dry_run() is True


def test_is_dry_run_true_when_run_mode_dry_run(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "dry_run")
    assert pinzhi_sync._is_dry_run() is True


def test_is_dry_run_false_when_run_mode_live(monkeypatch):
    """RUN_MODE=live 才 false (严格比较防误配置)."""
    monkeypatch.setenv("RUN_MODE", "live")
    assert pinzhi_sync._is_dry_run() is False


def test_is_dry_run_true_when_run_mode_typo(monkeypatch):
    """RUN_MODE 拼写错误 (e.g. 'live ') → fall-back dry_run (防误配置)."""
    monkeypatch.setenv("RUN_MODE", "True")  # 不是 "live"
    assert pinzhi_sync._is_dry_run() is True


def test_is_dry_run_with_whitespace(monkeypatch):
    """RUN_MODE='  live  ' (有空格) → 真路径 (strip + lower)."""
    monkeypatch.setenv("RUN_MODE", "  live  ")
    assert pinzhi_sync._is_dry_run() is False


# ── 4 个 pinzhi job dry_run 路径 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dishes_sync_dry_run_no_adapter_call():
    """dishes job dry_run 模式: 0 调 PinzhiAdapterFactory, 仅 log + metric."""
    # env unset = dry_run true
    with patch.object(
        pinzhi_sync, "_sync_dishes_for_merchant"
    ) as mock_real_sync:
        await pinzhi_sync._run_dishes_sync()
        # 真路径 _sync_dishes_for_merchant 不应被调用
        assert mock_real_sync.call_count == 0


@pytest.mark.asyncio
async def test_master_data_sync_dry_run_no_adapter_call():
    """master_data job dry_run 模式: 0 调 _sync_tables / _sync_employees."""
    with patch.object(pinzhi_sync, "_sync_tables_for_merchant") as mock_tables, patch.object(
        pinzhi_sync, "_sync_employees_for_merchant"
    ) as mock_employees:
        await pinzhi_sync._run_master_data_sync()
        assert mock_tables.call_count == 0
        assert mock_employees.call_count == 0


@pytest.mark.asyncio
async def test_orders_incremental_sync_dry_run_no_adapter_call():
    """orders incremental job dry_run 模式: 0 调 adapter."""
    with patch.object(
        pinzhi_sync, "_sync_orders_incremental_for_merchant"
    ) as mock_orders:
        await pinzhi_sync._run_orders_incremental_sync()
        assert mock_orders.call_count == 0


@pytest.mark.asyncio
async def test_members_incremental_sync_dry_run_no_adapter_call():
    """members incremental job dry_run 模式: 0 调 adapter."""
    with patch.object(
        pinzhi_sync, "_sync_members_incremental_for_merchant"
    ) as mock_members:
        await pinzhi_sync._run_members_incremental_sync()
        assert mock_members.call_count == 0


# ── metric 验证 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dry_run_records_metric():
    """dry_run 路径 inc sync_executions_total{status=dry_run}."""
    from services.tx_sync_worker.src import metrics as m

    # 记录 before count (如果 prometheus_client 不可用是 NoOp 跳过实际数值)
    if not m._PROM_AVAILABLE:
        pytest.skip("prometheus_client not available")

    before = m.sync_executions_total.labels(job="daily_dishes_sync", status="dry_run")._value.get()
    await pinzhi_sync._run_dishes_sync()
    after = m.sync_executions_total.labels(job="daily_dishes_sync", status="dry_run")._value.get()
    assert after == before + 1
