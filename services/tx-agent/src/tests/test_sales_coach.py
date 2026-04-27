"""Sprint R2 Track B — SalesCoachAgent 测试（Tier 2 高标准）

覆盖场景：
  01 test_decompose_target_calls_r1_api
  02 test_dispatch_daily_tasks_creates_10_task_types
  03 test_diagnose_gap_emits_alert_when_deviation_over_15pct
  04 test_coach_action_emits_advice_event
  05 test_audit_coverage_alerts_on_dormant_over_40pct
  06 test_score_profile_completeness_weights_correct
  07 test_low_completeness_triggers_task_dispatch
  08 test_constraint_scope_is_empty_with_waived_reason
  09 test_decision_log_written_for_every_action

所有对 R1 的 HTTP 调用通过 mock 的 ``_SalesCoachHttpClient`` 拦截，
emit_event 通过 monkeypatch 成 AsyncMock 捕获。
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.skills.sales_coach import (
    DEFAULT_DAILY_TASK_TYPES,
    DEFAULT_GAP_THRESHOLD,
    PROFILE_FIELD_WEIGHTS,
    SalesCoachAgent,
    compute_profile_completeness,
)

from shared.ontology.src.extensions.tasks import TaskType

# ──────────────────────────────────────────────────────────────────────
# 夹具
# ──────────────────────────────────────────────────────────────────────


class _FakeHttp:
    """轻量 mock，用于代替 ``_SalesCoachHttpClient``。"""

    def __init__(self) -> None:
        self.decompose_target = AsyncMock()
        self.get_achievement = AsyncMock()
        self.dispatch_task = AsyncMock()
        self.get_lifecycle_summary = AsyncMock()


@pytest.fixture
def fake_http() -> _FakeHttp:
    return _FakeHttp()


@pytest.fixture
def agent(fake_http: _FakeHttp) -> SalesCoachAgent:
    return SalesCoachAgent(
        tenant_id=str(uuid4()),
        http_client=fake_http,  # type: ignore[arg-type]
    )


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """捕获所有 emit_event 调用。"""
    events: list[dict] = []

    async def _capture(**kwargs):
        events.append(kwargs)
        return str(uuid4())

    # 关键：patch 两处 import 路径（Agent 模块 from-import 后形成本模块别名）
    import agents.skills.sales_coach as sc_mod

    monkeypatch.setattr(sc_mod, "emit_event", _capture)
    return events


# ──────────────────────────────────────────────────────────────────────
# 1. decompose_target
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decompose_target_calls_r1_api(
    agent: SalesCoachAgent, fake_http: _FakeHttp
) -> None:
    target_id = uuid4()
    fake_http.decompose_target.return_value = {
        "ok": True,
        "data": {
            "total": 12,
            "children": [{"target_id": str(uuid4()), "target_value": 1000}] * 12,
        },
        "error": None,
    }

    result = await agent.run("decompose_target", {"year_target_id": str(target_id)})

    assert result.success is True
    assert result.data["children_count"] == 12
    assert result.data["year_target_id"] == str(target_id)
    fake_http.decompose_target.assert_awaited_once()
    call_kwargs = fake_http.decompose_target.call_args.kwargs
    assert call_kwargs["tenant_id"] == agent.tenant_id
    assert str(call_kwargs["target_id"]) == str(target_id)


# ──────────────────────────────────────────────────────────────────────
# 2. dispatch_daily_tasks：默认 10 类
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_daily_tasks_creates_10_task_types(
    agent: SalesCoachAgent,
    fake_http: _FakeHttp,
    captured_events: list[dict],
) -> None:
    fake_http.dispatch_task.return_value = {
        "ok": True,
        "data": {"task_id": str(uuid4()), "task_type": "adhoc"},
        "error": None,
    }

    result = await agent.run(
        "dispatch_daily_tasks",
        {
            "employee_id": str(uuid4()),
            "plan_date": "2026-04-24",
        },
    )

    assert result.success is True
    assert result.data["dispatched_count"] == len(DEFAULT_DAILY_TASK_TYPES)
    assert len(result.data["dispatched_count_by_type"]) == 10
    # 10 类 TaskType 全覆盖
    assert set(result.data["dispatched_count_by_type"].keys()) == {
        t.value for t in DEFAULT_DAILY_TASK_TYPES
    }
    assert fake_http.dispatch_task.await_count == 10

    # 等待事件 task 完成
    import asyncio

    await asyncio.sleep(0)
    assert any(
        e.get("event_type").value == "sales_coach.daily_tasks_dispatched"
        for e in captured_events
    )


# ──────────────────────────────────────────────────────────────────────
# 3. diagnose_gap：偏差 > 15% 触发告警
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_diagnose_gap_emits_alert_when_deviation_over_15pct(
    agent: SalesCoachAgent,
    fake_http: _FakeHttp,
    captured_events: list[dict],
) -> None:
    target_id = uuid4()
    # 达成率 70% → 偏差 30% > 15% 阈值
    fake_http.get_achievement.return_value = {
        "ok": True,
        "data": {
            "target_id": str(target_id),
            "target_value": 10_000_00,  # 10 万元 = 1000000 分
            "actual_value": 7_000_00,
            "achievement_rate": "0.7000",
            "snapshot_at": datetime.now(timezone.utc).isoformat(),
        },
        "error": None,
    }

    result = await agent.run("diagnose_gap", {"target_id": str(target_id)})

    assert result.success is True
    assert result.data["has_gap"] is True
    assert Decimal(result.data["deviation"]) > DEFAULT_GAP_THRESHOLD
    assert len(result.data["remediations"]) >= 1

    import asyncio

    await asyncio.sleep(0)
    gap_alerts = [
        e for e in captured_events
        if e.get("event_type").value == "sales_coach.gap_alert"
    ]
    assert len(gap_alerts) == 1


@pytest.mark.asyncio
async def test_diagnose_gap_no_alert_when_on_track(
    agent: SalesCoachAgent,
    fake_http: _FakeHttp,
    captured_events: list[dict],
) -> None:
    fake_http.get_achievement.return_value = {
        "ok": True,
        "data": {
            "target_value": 1000,
            "actual_value": 950,
            "achievement_rate": "0.9500",
        },
        "error": None,
    }
    result = await agent.run("diagnose_gap", {"target_id": str(uuid4())})

    assert result.success is True
    assert result.data["has_gap"] is False

    import asyncio

    await asyncio.sleep(0)
    gap_alerts = [
        e for e in captured_events
        if e.get("event_type").value == "sales_coach.gap_alert"
    ]
    assert gap_alerts == []


# ──────────────────────────────────────────────────────────────────────
# 4. coach_action 发射 COACHING_ADVICE
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_coach_action_emits_advice_event(
    agent: SalesCoachAgent,
    captured_events: list[dict],
) -> None:
    employee_id = uuid4()
    result = await agent.run(
        "coach_action", {"employee_id": str(employee_id), "focus": "dormant"}
    )

    assert result.success is True
    assert result.data["focus"] == "dormant"
    assert len(result.data["advice"]) >= 1

    import asyncio

    await asyncio.sleep(0)
    advice_events = [
        e for e in captured_events
        if e.get("event_type").value == "sales_coach.coaching_advice"
    ]
    assert len(advice_events) == 1
    assert advice_events[0]["payload"]["focus"] == "dormant"


# ──────────────────────────────────────────────────────────────────────
# 5. audit_coverage 沉睡 > 40% 告警
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_coverage_alerts_on_dormant_over_40pct(
    agent: SalesCoachAgent,
    fake_http: _FakeHttp,
) -> None:
    fake_http.get_lifecycle_summary.return_value = {
        "ok": True,
        "data": {
            "counts": {
                "no_order": 100,
                "active": 100,
                "dormant": 500,  # 500 / 900 ≈ 55.5% > 40%
                "churned": 200,
            },
            "flows": {},
            "as_of": datetime.now(timezone.utc).isoformat(),
        },
        "error": None,
    }

    result = await agent.run("audit_coverage", {})

    assert result.success is True
    assert result.data["dormant_alert"] is True
    assert Decimal(result.data["dormant_ratio"]) > Decimal("0.40")


@pytest.mark.asyncio
async def test_audit_coverage_no_alert_on_healthy_mix(
    agent: SalesCoachAgent,
    fake_http: _FakeHttp,
) -> None:
    fake_http.get_lifecycle_summary.return_value = {
        "ok": True,
        "data": {
            "counts": {"no_order": 100, "active": 800, "dormant": 100, "churned": 0},
            "flows": {},
        },
        "error": None,
    }
    result = await agent.run("audit_coverage", {})
    assert result.success is True
    assert result.data["dormant_alert"] is False


# ──────────────────────────────────────────────────────────────────────
# 6. profile completeness 权重
# ──────────────────────────────────────────────────────────────────────


def test_score_profile_completeness_weights_correct() -> None:
    """姓名 20% + 手机 20% + 生日 15% + 纪念日 10% + 单位 10% + 喜好 10% + 忌口 10% + 服务要求 5% = 100%"""
    assert PROFILE_FIELD_WEIGHTS["name"] == Decimal("0.20")
    assert PROFILE_FIELD_WEIGHTS["phone"] == Decimal("0.20")
    assert PROFILE_FIELD_WEIGHTS["birthday"] == Decimal("0.15")
    assert PROFILE_FIELD_WEIGHTS["anniversary"] == Decimal("0.10")
    assert PROFILE_FIELD_WEIGHTS["organization"] == Decimal("0.10")
    assert PROFILE_FIELD_WEIGHTS["preferences"] == Decimal("0.10")
    assert PROFILE_FIELD_WEIGHTS["taboo"] == Decimal("0.10")
    assert PROFILE_FIELD_WEIGHTS["service_requirement"] == Decimal("0.05")
    assert sum(PROFILE_FIELD_WEIGHTS.values()) == Decimal("1.00")

    # 全字段齐 = 1.0
    full = {
        "name": "张三",
        "phone": "13800000000",
        "birthday": "1990-01-01",
        "anniversary": "2020-05-20",
        "organization": "屯象科技",
        "preferences": ["辣", "海鲜"],
        "taboo": ["花生"],
        "service_requirement": "靠窗",
    }
    assert compute_profile_completeness(full) == Decimal("1.00")

    # 只填姓名 + 手机 = 40%
    partial = {"name": "李四", "phone": "13900000000"}
    assert compute_profile_completeness(partial) == Decimal("0.40")

    # 空字符串 / 空列表不计分
    empty_values = {
        "name": "   ",
        "phone": "",
        "preferences": [],
        "taboo": None,
    }
    assert compute_profile_completeness(empty_values) == Decimal("0")


# ──────────────────────────────────────────────────────────────────────
# 7. 低完整度 < 50% 触发 adhoc 补录派单
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_low_completeness_triggers_task_dispatch(
    agent: SalesCoachAgent,
    fake_http: _FakeHttp,
) -> None:
    fake_http.dispatch_task.return_value = {
        "ok": True,
        "data": {"task_id": str(uuid4())},
        "error": None,
    }

    employee_id = uuid4()
    low_customer_id = uuid4()
    high_customer_id = uuid4()
    result = await agent.run(
        "score_profile_completeness",
        {
            "employee_id": str(employee_id),
            "customers": [
                # 仅姓名 = 20% < 50%
                {"customer_id": str(low_customer_id), "name": "低分客户"},
                # 全字段 = 100% >= 50%
                {
                    "customer_id": str(high_customer_id),
                    "name": "高分客户",
                    "phone": "13800000000",
                    "birthday": "1990-01-01",
                    "anniversary": "2020-05-20",
                    "organization": "屯象",
                    "preferences": ["辣"],
                    "taboo": ["花生"],
                    "service_requirement": "靠窗",
                },
            ],
        },
    )

    assert result.success is True
    assert result.data["customer_count"] == 2
    assert str(low_customer_id) in result.data["below_threshold_customer_ids"]
    assert str(high_customer_id) not in result.data["below_threshold_customer_ids"]
    # 低分客户应触发一次 dispatch_task
    assert result.data["dispatched_task_count"] == 1

    # HTTP 调用验证：task_type 为 adhoc
    assert fake_http.dispatch_task.await_count == 1
    call = fake_http.dispatch_task.call_args.kwargs
    assert call["task_type"] == TaskType.ADHOC
    assert str(call["customer_id"]) == str(low_customer_id)


@pytest.mark.asyncio
async def test_profile_completeness_skips_dispatch_when_disabled(
    agent: SalesCoachAgent,
    fake_http: _FakeHttp,
) -> None:
    result = await agent.run(
        "score_profile_completeness",
        {
            "employee_id": str(uuid4()),
            "customers": [{"customer_id": str(uuid4()), "name": "低分"}],
            "dispatch_tasks_on_low": False,
        },
    )
    assert result.success is True
    assert result.data["dispatched_task_count"] == 0
    fake_http.dispatch_task.assert_not_awaited()


# ──────────────────────────────────────────────────────────────────────
# 8. constraint_scope / waived_reason
# ──────────────────────────────────────────────────────────────────────


def test_constraint_scope_is_empty_with_waived_reason() -> None:
    assert SalesCoachAgent.constraint_scope == set()
    reason = SalesCoachAgent.constraint_waived_reason
    assert reason is not None
    assert len(reason) >= 30
    # 禁用黑名单说辞
    for blacklist in ("N/A", "不适用", "跳过"):
        assert blacklist not in reason, f"waived_reason 含黑名单词 {blacklist}"


@pytest.mark.asyncio
async def test_run_waived_scope_passes_constraints(
    agent: SalesCoachAgent,
    fake_http: _FakeHttp,
) -> None:
    """豁免类 Agent 的 run() 应走 waived 路径（constraints_detail.scope == 'waived'）。"""
    fake_http.decompose_target.return_value = {
        "ok": True,
        "data": {"children": [], "total": 0},
        "error": None,
    }
    result = await agent.run(
        "decompose_target", {"year_target_id": str(uuid4())}
    )
    assert result.constraints_passed is True
    assert result.constraints_detail["scope"] == "waived"
    assert result.constraints_detail["waived_reason"] == (
        SalesCoachAgent.constraint_waived_reason
    )


# ──────────────────────────────────────────────────────────────────────
# 9. 决策留痕：每个 action 都写 AgentResult.reasoning + confidence
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decision_log_written_for_every_action(
    agent: SalesCoachAgent,
    fake_http: _FakeHttp,
    captured_events: list[dict],
) -> None:
    """SkillAgent.run() 基类负责写决策留痕：验证 reasoning/confidence 齐备。"""
    fake_http.decompose_target.return_value = {
        "ok": True, "data": {"children": [], "total": 0}, "error": None,
    }
    fake_http.dispatch_task.return_value = {
        "ok": True, "data": {"task_id": str(uuid4())}, "error": None,
    }
    fake_http.get_achievement.return_value = {
        "ok": True,
        "data": {"target_value": 100, "actual_value": 90, "achievement_rate": "0.9"},
        "error": None,
    }
    fake_http.get_lifecycle_summary.return_value = {
        "ok": True,
        "data": {"counts": {"active": 10, "dormant": 2}, "flows": {}},
        "error": None,
    }

    emp = str(uuid4())
    actions_to_test = [
        ("decompose_target", {"year_target_id": str(uuid4())}),
        ("dispatch_daily_tasks", {"employee_id": emp}),
        ("diagnose_gap", {"target_id": str(uuid4())}),
        ("coach_action", {"employee_id": emp}),
        ("audit_coverage", {}),
        (
            "score_profile_completeness",
            {
                "employee_id": emp,
                "customers": [{"customer_id": str(uuid4()), "name": "张"}],
                "dispatch_tasks_on_low": False,
            },
        ),
    ]

    for action, params in actions_to_test:
        result = await agent.run(action, params)
        assert result.success is True, f"{action} 失败：{result.error}"
        # 决策留痕三要素
        assert result.reasoning, f"{action} 缺 reasoning"
        assert 0.0 <= result.confidence <= 1.0, f"{action} confidence 越界"
        assert result.constraints_detail["scope"] == "waived"


# ──────────────────────────────────────────────────────────────────────
# 边界：未知 action
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_action_returns_error(agent: SalesCoachAgent) -> None:
    result = await agent.run("not_a_real_action", {})
    assert result.success is False
    assert result.error is not None
    assert "not_a_real_action" in result.error


# ──────────────────────────────────────────────────────────────────────
# agent_id / 注册一致
# ──────────────────────────────────────────────────────────────────────


def test_sales_coach_registered_in_skill_registry() -> None:
    from agents.skills import SKILL_REGISTRY

    assert "sales_coach" in SKILL_REGISTRY
    cls = SKILL_REGISTRY["sales_coach"]
    assert cls.agent_id == "sales_coach"
    assert cls.priority == "P1"
    assert cls.run_location == "cloud"
    assert cls.constraint_scope == set()


def test_r2_track_b_actions_fully_enumerated() -> None:
    """6 个 action 必须与 agent_actions.py 契约一致（r2-contracts §3.3）。"""
    agent = SalesCoachAgent(tenant_id=str(uuid4()))
    supported = set(agent.get_supported_actions())
    expected = {
        "decompose_target",
        "dispatch_daily_tasks",
        "diagnose_gap",
        "coach_action",
        "audit_coverage",
        "score_profile_completeness",
    }
    assert supported == expected


# ──────────────────────────────────────────────────────────────────────
# date 工具冒烟
# ──────────────────────────────────────────────────────────────────────


def test_date_fixture_is_today_when_absent() -> None:
    """dispatch_daily_tasks 不传 plan_date 时，默认取当日。"""
    from agents.skills.sales_coach import _coerce_date

    # 明确覆盖 _coerce_date 异常路径
    assert _coerce_date("2026-04-23") == date(2026, 4, 23)
    today = date.today()
    assert _coerce_date(None) == today  # type: ignore[arg-type]
    assert _coerce_date("not-a-date") == today


def test_uuid_coerce_safe() -> None:
    from agents.skills.sales_coach import _coerce_uuid

    assert _coerce_uuid(None) is None
    u = uuid4()
    assert _coerce_uuid(u) == u
    assert _coerce_uuid(str(u)) == u
    assert _coerce_uuid("not-a-uuid") is None
    assert isinstance(_coerce_uuid(str(UUID(int=0))), UUID)
