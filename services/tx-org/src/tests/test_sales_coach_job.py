"""Sprint R2 Track B — SalesCoachJobService 定时作业测试

测试场景（≥5 条）：
  01 test_daily_job_runs_for_each_sales_employee
  02 test_weekly_profile_audit_dispatches_补录_tasks
  03 test_idempotent_job_same_day
  04 test_job_emits_daily_tasks_dispatched_event
  05 test_tenant_isolation

测试策略：
  - Agent 层用 AsyncMock 代替；Job 只负责编排与幂等
  - emit_event 通过模块级 monkeypatch 捕获，避免真 Redis / PG
"""

from __future__ import annotations

import os
import sys
import types
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

# ──────────────────────────────────────────────────────────────────────
# Path shim：支持 services.tx_org.src.* 和 shared.events.* 混合导入
# ──────────────────────────────────────────────────────────────────────
_THIS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.abspath(os.path.join(_THIS_DIR, ".."))
_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", "..", ".."))
for _p in (_SRC_DIR, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ──────────────────────────────────────────────────────────────────────
# 发射器降级：与 test_sales_target_tier1.py 同策略，防测试时触发 Redis/PG
# ──────────────────────────────────────────────────────────────────────

_EVENT_RECORD: list[dict] = []


async def _fake_emit_event(**kwargs):  # noqa: D401
    _EVENT_RECORD.append(kwargs)
    return str(uuid4())


_events_pkg = types.ModuleType("shared.events")
_events_src_pkg = types.ModuleType("shared.events.src")
_emitter_mod = types.ModuleType("shared.events.src.emitter")
_evt_types_mod = types.ModuleType("shared.events.src.event_types")

_emitter_mod.emit_event = _fake_emit_event
_emitter_mod.emits = lambda *a, **k: (lambda f: f)


class _SalesCoachEventType:
    DAILY_TASKS_DISPATCHED = type(
        "E",
        (),
        {"value": "sales_coach.daily_tasks_dispatched"},
    )()
    COACHING_ADVICE = type(
        "E", (), {"value": "sales_coach.coaching_advice"}
    )()
    GAP_ALERT = type("E", (), {"value": "sales_coach.gap_alert"})()


_evt_types_mod.SalesCoachEventType = _SalesCoachEventType

_shared_root = os.path.abspath(os.path.join(_ROOT, "shared"))
_shared_pkg = types.ModuleType("shared")
_shared_pkg.__path__ = [_shared_root]  # type: ignore[attr-defined]

sys.modules.setdefault("shared", _shared_pkg)
sys.modules.setdefault("shared.events", _events_pkg)
sys.modules.setdefault("shared.events.src", _events_src_pkg)
sys.modules["shared.events.src.emitter"] = _emitter_mod
sys.modules["shared.events.src.event_types"] = _evt_types_mod


from services.sales_coach_job_service import (  # noqa: E402
    SalesCoachJobService,
)

# ──────────────────────────────────────────────────────────────────────
# 工具
# ──────────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _FakeAgentResult:
    def __init__(self, success: bool = True, data: dict | None = None) -> None:
        self.success = success
        self.data = data or {}
        self.reasoning = ""
        self.confidence = 0.9
        self.error = None


def _make_agent_mock(dispatched_count: int = 5, has_gap: bool = False) -> AsyncMock:
    """构造 Agent mock：run(action, params) 返回 _FakeAgentResult。"""
    agent = AsyncMock()

    async def _run(action: str, params: dict):
        if action == "dispatch_daily_tasks":
            return _FakeAgentResult(
                True,
                {
                    "dispatched_count": dispatched_count,
                    "dispatched_count_by_type": {},
                },
            )
        if action == "diagnose_gap":
            return _FakeAgentResult(True, {"has_gap": has_gap})
        if action == "audit_coverage":
            return _FakeAgentResult(True, {"dormant_ratio": "0.20", "dormant_alert": False})
        if action == "score_profile_completeness":
            return _FakeAgentResult(
                True,
                {
                    "dispatched_task_count": 1,
                    "below_threshold_customer_ids": [str(uuid4())],
                },
            )
        if action == "decompose_target":
            return _FakeAgentResult(True, {"children_count": 12})
        return _FakeAgentResult(True, {})

    agent.run.side_effect = _run
    return agent


@pytest.fixture(autouse=True)
def clear_events():
    _EVENT_RECORD.clear()
    yield
    _EVENT_RECORD.clear()


# ──────────────────────────────────────────────────────────────────────
# 1. daily_job 对每个销售员工跑一遍
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_daily_job_runs_for_each_sales_employee() -> None:
    agent = _make_agent_mock(dispatched_count=10)
    employees = [
        {"employee_id": str(uuid4()), "store_id": str(uuid4()), "year_target_id": str(uuid4())},
        {"employee_id": str(uuid4()), "store_id": str(uuid4())},
        {"employee_id": str(uuid4())},
    ]

    async def _load_emp(tenant_id):
        return employees

    async def _load_targets(tenant_id, emp_id):
        return [{"target_id": str(uuid4())}]

    service = SalesCoachJobService(
        agent_factory=lambda tenant_id: agent,
        employees_loader=_load_emp,
        active_targets_loader=_load_targets,
    )

    tenant_id = uuid4()
    report = await service.run_daily_coaching_job(tenant_id, now=_utcnow())

    assert report["employees_count"] == 3
    assert report["dispatched_total"] == 3 * 10  # 每员工 10 条
    assert report["idempotent"] is False

    # 每个员工都应该触发 dispatch_daily_tasks
    dispatch_calls = [c for c in agent.run.call_args_list if c.args[0] == "dispatch_daily_tasks"]
    assert len(dispatch_calls) == 3

    # 有 year_target_id 的员工才触发 decompose_target（仅第一个）
    decompose_calls = [c for c in agent.run.call_args_list if c.args[0] == "decompose_target"]
    assert len(decompose_calls) == 1

    # audit_coverage 只在整个 job 结束跑一次
    audit_calls = [c for c in agent.run.call_args_list if c.args[0] == "audit_coverage"]
    assert len(audit_calls) == 1


# ──────────────────────────────────────────────────────────────────────
# 2. weekly profile audit 派发补录任务
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_weekly_profile_audit_dispatches_补录_tasks() -> None:
    agent = _make_agent_mock()

    async def _load_emp(tenant_id):
        return [{"employee_id": str(uuid4())}, {"employee_id": str(uuid4())}]

    async def _load_customers(tenant_id, emp_id):
        return [{"customer_id": str(uuid4()), "name": "张三"}]

    service = SalesCoachJobService(
        agent_factory=lambda tenant_id: agent,
        employees_loader=_load_emp,
        customers_loader=_load_customers,
    )

    report = await service.run_weekly_profile_audit(uuid4(), now=_utcnow())

    assert report["dispatched_task_count"] == 2  # 2 员工 × 每员工 1 条
    assert report["below_threshold_count"] == 2
    assert report["idempotent"] is False

    # 每个员工都触发一次 score_profile_completeness
    score_calls = [
        c for c in agent.run.call_args_list if c.args[0] == "score_profile_completeness"
    ]
    assert len(score_calls) == 2


# ──────────────────────────────────────────────────────────────────────
# 3. 幂等：同一日重复运行不重复派单
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotent_job_same_day() -> None:
    agent = _make_agent_mock(dispatched_count=3)

    async def _load_emp(tenant_id):
        return [{"employee_id": str(uuid4())}]

    async def _load_targets(tenant_id, emp_id):
        return []

    service = SalesCoachJobService(
        agent_factory=lambda tenant_id: agent,
        employees_loader=_load_emp,
        active_targets_loader=_load_targets,
    )

    tenant_id = uuid4()
    now = _utcnow()

    report1 = await service.run_daily_coaching_job(tenant_id, now=now)
    report2 = await service.run_daily_coaching_job(tenant_id, now=now)

    assert report1["idempotent"] is False
    assert report2["idempotent"] is True
    assert report2["dispatched_total"] == 0

    # Agent 只被调用了第一次那批
    dispatch_calls = [c for c in agent.run.call_args_list if c.args[0] == "dispatch_daily_tasks"]
    assert len(dispatch_calls) == 1  # 只跑过一次


# ──────────────────────────────────────────────────────────────────────
# 4. 完成后发射 DAILY_TASKS_DISPATCHED 事件
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_emits_daily_tasks_dispatched_event() -> None:
    agent = _make_agent_mock(dispatched_count=7)

    async def _load_emp(tenant_id):
        return [{"employee_id": str(uuid4())}]

    async def _load_targets(tenant_id, emp_id):
        return []

    service = SalesCoachJobService(
        agent_factory=lambda tenant_id: agent,
        employees_loader=_load_emp,
        active_targets_loader=_load_targets,
    )

    tenant_id = uuid4()
    await service.run_daily_coaching_job(tenant_id, now=_utcnow())

    # 等待 asyncio.create_task 完成
    import asyncio

    await asyncio.sleep(0)

    events = [
        e for e in _EVENT_RECORD
        if getattr(e.get("event_type"), "value", "") == "sales_coach.daily_tasks_dispatched"
    ]
    assert len(events) >= 1
    assert events[0]["tenant_id"] == tenant_id
    assert events[0]["payload"]["dispatched_count"] == 7
    assert events[0]["source_service"] == "tx-org.sales_coach_job"


# ──────────────────────────────────────────────────────────────────────
# 5. 租户隔离：不同租户 ledger 独立
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_isolation() -> None:
    agent = _make_agent_mock(dispatched_count=2)

    async def _load_emp(tenant_id):
        return [{"employee_id": str(uuid4())}]

    async def _load_targets(tenant_id, emp_id):
        return []

    service = SalesCoachJobService(
        agent_factory=lambda tenant_id: agent,
        employees_loader=_load_emp,
        active_targets_loader=_load_targets,
    )

    tenant_a = uuid4()
    tenant_b = uuid4()
    now = _utcnow()

    r1 = await service.run_daily_coaching_job(tenant_a, now=now)
    r2 = await service.run_daily_coaching_job(tenant_b, now=now)
    # 同天，租户 A 再跑一次应被幂等拦截
    r3 = await service.run_daily_coaching_job(tenant_a, now=now)

    assert r1["idempotent"] is False
    assert r2["idempotent"] is False  # 不同租户独立
    assert r3["idempotent"] is True

    assert r1["tenant_id"] == str(tenant_a)
    assert r2["tenant_id"] == str(tenant_b)


# ──────────────────────────────────────────────────────────────────────
# 6. 次日能重新跑（不同日期 ledger 独立）
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_different_day_can_run_again() -> None:
    agent = _make_agent_mock(dispatched_count=1)

    async def _load_emp(tenant_id):
        return [{"employee_id": str(uuid4())}]

    async def _load_targets(tenant_id, emp_id):
        return []

    service = SalesCoachJobService(
        agent_factory=lambda tenant_id: agent,
        employees_loader=_load_emp,
        active_targets_loader=_load_targets,
    )

    tenant = uuid4()
    day1 = datetime(2026, 4, 23, 6, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 4, 24, 6, 0, tzinfo=timezone.utc)

    r1 = await service.run_daily_coaching_job(tenant, now=day1)
    r2 = await service.run_daily_coaching_job(tenant, now=day2)

    assert r1["idempotent"] is False
    assert r2["idempotent"] is False
    assert r1["plan_date"] == date(2026, 4, 23).isoformat()
    assert r2["plan_date"] == date(2026, 4, 24).isoformat()


# ──────────────────────────────────────────────────────────────────────
# 7. 缺少 agent_factory 快速抛错
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_agent_factory_raises() -> None:
    service = SalesCoachJobService(
        agent_factory=None,
        employees_loader=lambda tid: [],
    )
    with pytest.raises(RuntimeError, match="agent_factory"):
        await service.run_daily_coaching_job(uuid4(), now=_utcnow())


# ──────────────────────────────────────────────────────────────────────
# 8. weekly job 缺少 customers_loader 抛错
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_weekly_missing_customers_loader_raises() -> None:
    agent = _make_agent_mock()
    service = SalesCoachJobService(
        agent_factory=lambda tenant_id: agent,
        employees_loader=lambda tid: [],
        # customers_loader 未注入
    )
    with pytest.raises(RuntimeError, match="customers_loader"):
        await service.run_weekly_profile_audit(uuid4(), now=_utcnow())
