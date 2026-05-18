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


@pytest.mark.asyncio
async def test_daily_sop_live_path_imports_resolve(monkeypatch):
    """P0-3 hotfix #815 regression: live 路径 import 不应 ImportError.

    原 BUG: `services.gateway.src.database` 不存在 (gateway 实际用
    `shared.ontology.src.database.async_session_factory`). Phase 1 dry_run gate
    挡住此路径不可达, 但 Phase 2 翻 RUN_MODE=live 直接 ImportError 静默
    (status='error' counter inc, 0 业务执行).

    本测试 mock 全 import 路径 (避 shared.ontology.src __init__ 触
    entities.py PEP 604 union type 真实 SQLAlchemy 初始化), 仅 verify
    wecom_sop._run_daily_sop() live 路径不再 ImportError.
    """
    import sys
    import types
    from unittest.mock import AsyncMock, MagicMock

    monkeypatch.setenv("RUN_MODE", "live")

    # mock shared.ontology.src.database 单文件 (绕开 __init__.py entities 导入)
    fake_session = AsyncMock()
    fake_result = MagicMock()
    fake_result.scalars.return_value.all.return_value = []  # 0 active tenants
    fake_session.execute = AsyncMock(return_value=fake_result)
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)

    def _fake_factory():
        return fake_session

    fake_shared_db = types.ModuleType("shared.ontology.src.database")
    fake_shared_db.async_session_factory = _fake_factory
    original_shared_db = sys.modules.get("shared.ontology.src.database")
    sys.modules["shared.ontology.src.database"] = fake_shared_db

    # 同时 mock 跨服务 gateway import (避免真依赖 gateway models init).
    fake_gw_models = types.ModuleType("services.gateway.src.models.wecom_group")
    fake_gw_models.WecomGroupConfig = MagicMock(tenant_id="tenant_id_col", status="status_col")
    sys.modules["services.gateway.src.models.wecom_group"] = fake_gw_models

    fake_gw_svc = types.ModuleType("services.gateway.src.wecom_group_service")
    fake_svc_inst = MagicMock()
    fake_svc_inst.scan_and_execute_daily_sop = AsyncMock(return_value={"scanned": 0})
    fake_gw_svc.WecomGroupService = MagicMock(return_value=fake_svc_inst)
    sys.modules["services.gateway.src.wecom_group_service"] = fake_gw_svc

    try:
        # 跑真路径; 0 tenants → 不进 for loop, 直接 status='success' inc.
        await wecom_sop._run_daily_sop()

        # verify SELECT distinct tenant_id 被调过 (跨租户聚合 SELECT step 1)
        assert fake_session.execute.await_count >= 1
    finally:
        sys.modules.pop("services.gateway.src.models.wecom_group", None)
        sys.modules.pop("services.gateway.src.wecom_group_service", None)
        if original_shared_db is not None:
            sys.modules["shared.ontology.src.database"] = original_shared_db
        else:
            sys.modules.pop("shared.ontology.src.database", None)
