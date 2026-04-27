"""AgentOrchestrator 测试套件

运行：
  pytest services/tx-agent/src/tests/test_orchestrator.py -v
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# 将 src 目录加入 path，以便无 package 安装时也能导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base import AgentResult
from agents.event_bus import AgentEvent
from agents.orchestrator import (
    AgentOrchestrator,
    ExecutionPlan,
    ExecutionStep,
    OrchestratorResult,
    StepStatus,
)

# ─────────────────────────────────────────────────────────────────────────────
# 辅助工具
# ─────────────────────────────────────────────────────────────────────────────


def _make_mock_router_response(plan_json: str) -> MagicMock:
    """构造 ModelRouter.complete 返回的 mock 响应"""
    response = MagicMock()
    response.content = [MagicMock(text=plan_json)]
    return response


_SIMPLE_PLAN_JSON = (
    '{"trigger_summary": "test trigger", "estimated_impact": "low",'
    ' "steps": [{"step_id": "step_1", "agent_id": "discount_guard",'
    ' "action": "assess", "params": {}, "depends_on": [], "timeout_seconds": 30}]}'
)

_EMPTY_PLAN_JSON = '{"trigger_summary": "empty", "estimated_impact": "none", "steps": []}'


# ─────────────────────────────────────────────────────────────────────────────
# 1. ExecutionPlan / ExecutionStep 数据结构
# ─────────────────────────────────────────────────────────────────────────────


class TestExecutionPlan:
    """ExecutionPlan 数据结构测试"""

    def test_plan_id_auto_generated(self):
        """plan_id 应自动生成，非空"""
        plan = ExecutionPlan(trigger_summary="test")
        assert plan.plan_id
        assert len(plan.plan_id) == 36  # UUID 格式

    def test_plan_default_steps_empty(self):
        """默认 steps 列表为空"""
        plan = ExecutionPlan(trigger_summary="test")
        assert plan.steps == []

    def test_plan_created_at_is_set(self):
        """created_at 自动设置"""
        plan = ExecutionPlan(trigger_summary="test")
        assert plan.created_at is not None

    def test_two_plans_have_different_ids(self):
        """两个 Plan 的 plan_id 不应相同"""
        p1 = ExecutionPlan(trigger_summary="a")
        p2 = ExecutionPlan(trigger_summary="b")
        assert p1.plan_id != p2.plan_id

    def test_step_default_status_is_pending(self):
        """ExecutionStep 默认状态为 PENDING"""
        step = ExecutionStep(
            step_id="step_1",
            agent_id="discount_guard",
            action="assess",
            params={},
        )
        assert step.status == StepStatus.PENDING

    def test_step_default_depends_on_empty(self):
        """ExecutionStep 默认依赖列表为空"""
        step = ExecutionStep(
            step_id="step_1",
            agent_id="discount_guard",
            action="assess",
            params={},
        )
        assert step.depends_on == []

    def test_step_default_timeout(self):
        """ExecutionStep 默认超时为 30 秒"""
        step = ExecutionStep(
            step_id="step_1",
            agent_id="discount_guard",
            action="assess",
            params={},
        )
        assert step.timeout_seconds == 30


# ─────────────────────────────────────────────────────────────────────────────
# 2. AgentOrchestrator fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_master():
    master = MagicMock()
    master.tenant_id = "test-tenant"
    master.store_id = "test-store"
    master.dispatch = AsyncMock(return_value=AgentResult(success=True, action="test", data={"confidence": 0.9}))
    return master


@pytest.fixture
def mock_router():
    router = MagicMock()
    router.complete = AsyncMock(return_value=_make_mock_router_response(_SIMPLE_PLAN_JSON))
    return router


@pytest.fixture
def orchestrator(mock_master, mock_router):
    return AgentOrchestrator(
        master_agent=mock_master,
        model_router=mock_router,
        tenant_id="test-tenant",
        store_id="test-store",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. orchestrate() 主入口
# ─────────────────────────────────────────────────────────────────────────────


class TestOrchestrateEntry:
    """orchestrate() 主入口集成路径"""

    @pytest.mark.asyncio
    async def test_orchestrate_string_intent_returns_result(self, orchestrator):
        """自然语言意图触发后应返回 OrchestratorResult"""
        result = await orchestrator.orchestrate("库存预警：某食材清零")
        assert isinstance(result, OrchestratorResult)
        assert result.plan_id

    @pytest.mark.asyncio
    async def test_orchestrate_agent_event_returns_result(self, orchestrator):
        """AgentEvent 触发后应返回 OrchestratorResult"""
        event = AgentEvent(
            event_type="supply.stock.zero",
            source_agent="tx-supply",
            store_id="test-store",
            data={"ingredient_id": "abc"},
        )
        result = await orchestrator.orchestrate(event)
        assert isinstance(result, OrchestratorResult)
        assert result.plan_id

    @pytest.mark.asyncio
    async def test_orchestrate_result_has_synthesis(self, orchestrator):
        """OrchestratorResult.synthesis 不应为空"""
        result = await orchestrator.orchestrate("测试意图")
        assert result.synthesis


# ─────────────────────────────────────────────────────────────────────────────
# 4. _plan() — 规划阶段
# ─────────────────────────────────────────────────────────────────────────────


class TestPlanPhase:
    """_plan() 规划阶段"""

    @pytest.mark.asyncio
    async def test_plan_returns_execution_plan(self, orchestrator):
        """_plan() 应返回 ExecutionPlan 实例"""
        plan = await orchestrator._plan("测试意图", {})
        assert isinstance(plan, ExecutionPlan)

    @pytest.mark.asyncio
    async def test_plan_parses_steps_from_model_response(self, orchestrator):
        """从模型响应正确解析 steps"""
        plan = await orchestrator._plan("测试意图", {})
        assert len(plan.steps) == 1
        assert plan.steps[0].step_id == "step_1"
        assert plan.steps[0].agent_id == "discount_guard"

    @pytest.mark.asyncio
    async def test_plan_failure_returns_empty_plan(self, mock_master, mock_router):
        """模型调用失败时返回空计划，不抛异常（降级保护）"""
        mock_router.complete = AsyncMock(side_effect=ValueError("model error"))
        orc = AgentOrchestrator(
            master_agent=mock_master,
            model_router=mock_router,
            tenant_id="test-tenant",
        )
        plan = await orc._plan("test intent", {})
        assert plan.steps == []

    @pytest.mark.asyncio
    async def test_plan_json_decode_error_returns_empty_plan(self, mock_master):
        """JSON 解析失败时降级为空计划"""
        bad_router = MagicMock()
        bad_router.complete = AsyncMock(return_value=_make_mock_router_response("not valid json {{{{"))
        orc = AgentOrchestrator(
            master_agent=mock_master,
            model_router=bad_router,
            tenant_id="test-tenant",
        )
        plan = await orc._plan("test intent", {})
        assert plan.steps == []

    @pytest.mark.asyncio
    async def test_plan_sets_trigger_summary(self, orchestrator):
        """trigger_summary 应从模型响应中解析"""
        plan = await orchestrator._plan("test intent", {})
        assert plan.trigger_summary == "test trigger"

    @pytest.mark.asyncio
    async def test_plan_with_agent_event_trigger(self, orchestrator):
        """AgentEvent 触发时应正确生成计划"""
        event = AgentEvent(
            event_type="supply.stock.zero",
            source_agent="tx-supply",
            store_id="test-store",
            data={"ingredient_id": "abc"},
        )
        plan = await orchestrator._plan(event, {})
        assert isinstance(plan, ExecutionPlan)


# ─────────────────────────────────────────────────────────────────────────────
# 5. _execute() — 执行阶段
# ─────────────────────────────────────────────────────────────────────────────


class TestExecutePhase:
    """_execute() 执行阶段"""

    @pytest.mark.asyncio
    async def test_execute_empty_plan_returns_empty_dict(self, orchestrator):
        """空计划返回空结果字典"""
        plan = ExecutionPlan(trigger_summary="empty")
        results = await orchestrator._execute(plan)
        assert results == {}

    @pytest.mark.asyncio
    async def test_execute_single_step_calls_dispatch(self, orchestrator, mock_master):
        """单步骤执行应调用 master.dispatch 一次"""
        plan = ExecutionPlan(
            trigger_summary="single step",
            steps=[ExecutionStep("step_1", "discount_guard", "check", {})],
        )
        results = await orchestrator._execute(plan)
        assert "step_1" in results
        mock_master.dispatch.assert_called_once_with("discount_guard", "check", {})

    @pytest.mark.asyncio
    async def test_execute_parallel_steps_both_complete(self, orchestrator, mock_master):
        """无依赖的步骤应并行执行，全部出现在结果中"""
        plan = ExecutionPlan(
            trigger_summary="parallel",
            steps=[
                ExecutionStep("step_1", "agent_a", "action_a", {}, depends_on=[]),
                ExecutionStep("step_2", "agent_b", "action_b", {}, depends_on=[]),
            ],
        )
        results = await orchestrator._execute(plan)
        assert "step_1" in results
        assert "step_2" in results
        assert mock_master.dispatch.call_count == 2

    @pytest.mark.asyncio
    async def test_execute_sequential_steps_respect_order(self, orchestrator, mock_master):
        """有依赖的步骤应在依赖完成后执行"""
        plan = ExecutionPlan(
            trigger_summary="sequential",
            steps=[
                ExecutionStep("step_1", "agent_a", "action_a", {}, depends_on=[]),
                ExecutionStep("step_2", "agent_b", "action_b", {}, depends_on=["step_1"]),
            ],
        )
        results = await orchestrator._execute(plan)
        assert "step_1" in results
        assert "step_2" in results
        assert mock_master.dispatch.call_count == 2

    @pytest.mark.asyncio
    async def test_execute_step_timeout_returns_failure_result(self, orchestrator, mock_master):
        """单个步骤超时应返回 success=False 且 error 含 'timeout'"""

        async def slow_dispatch(*args, **kwargs):
            await asyncio.sleep(100)
            return AgentResult(success=True, action="test")

        mock_master.dispatch = slow_dispatch
        plan = ExecutionPlan(
            trigger_summary="timeout test",
            steps=[ExecutionStep("step_1", "slow_agent", "slow_action", {}, timeout_seconds=1)],
        )
        results = await orchestrator._execute(plan)
        assert results["step_1"].success is False
        assert "timeout" in (results["step_1"].error or "")

    @pytest.mark.asyncio
    async def test_execute_step_runtime_error_returns_failure_result(self, orchestrator, mock_master):
        """步骤执行时 RuntimeError 应捕获并返回 success=False"""
        mock_master.dispatch = AsyncMock(side_effect=RuntimeError("agent crashed"))
        plan = ExecutionPlan(
            trigger_summary="error test",
            steps=[ExecutionStep("step_1", "bad_agent", "fail_action", {})],
        )
        results = await orchestrator._execute(plan)
        assert results["step_1"].success is False
        assert "agent crashed" in (results["step_1"].error or "")

    @pytest.mark.asyncio
    async def test_execute_one_failure_does_not_block_parallel_steps(self, orchestrator, mock_master):
        """一个步骤失败不影响其他无依赖步骤执行"""
        call_log: list[str] = []

        async def dispatch_side_effect(agent_id: str, *args, **kwargs):
            call_log.append(agent_id)
            if agent_id == "bad_agent":
                raise RuntimeError("forced failure")
            return AgentResult(success=True, action="ok")

        mock_master.dispatch = dispatch_side_effect
        plan = ExecutionPlan(
            trigger_summary="partial failure",
            steps=[
                ExecutionStep("step_1", "bad_agent", "fail", {}, depends_on=[]),
                ExecutionStep("step_2", "good_agent", "work", {}, depends_on=[]),
            ],
        )
        results = await orchestrator._execute(plan)
        assert results["step_1"].success is False
        assert results["step_2"].success is True


# ─────────────────────────────────────────────────────────────────────────────
# 6. _synthesize() — 综合阶段
# ─────────────────────────────────────────────────────────────────────────────


class TestSynthesizePhase:
    """_synthesize() 综合阶段"""

    @pytest.mark.asyncio
    async def test_synthesize_all_success_constraints_passed(self, orchestrator):
        """所有步骤成功且无约束违反时，constraints_passed 应为 True"""
        plan = ExecutionPlan(
            trigger_summary="test",
            steps=[ExecutionStep("step_1", "agent_a", "action", {})],
        )
        step_results = {
            "step_1": AgentResult(success=True, action="action", data={}),
        }
        final = await orchestrator._synthesize(plan, step_results)
        assert final.constraints_passed is True
        assert final.success is True

    @pytest.mark.asyncio
    async def test_synthesize_constraint_violated_flag_fails_constraints(self, orchestrator):
        """Agent 结果中有 constraint_violated=True 时，constraints_passed 应为 False"""
        plan = ExecutionPlan(
            trigger_summary="constraint test",
            steps=[ExecutionStep("step_1", "discount_guard", "check", {})],
        )
        step_results = {
            "step_1": AgentResult(
                success=True,
                action="check",
                data={"constraint_violated": True, "reason": "margin too low"},
            ),
        }
        final = await orchestrator._synthesize(plan, step_results)
        assert final.constraints_passed is False

    @pytest.mark.asyncio
    async def test_synthesize_constraints_passed_false_on_agent_result_flag(self, orchestrator):
        """AgentResult.constraints_passed=False 时，综合结果 constraints_passed 为 False"""
        plan = ExecutionPlan(
            trigger_summary="constraint test",
            steps=[ExecutionStep("step_1", "agent_a", "action", {})],
        )
        step_results = {
            "step_1": AgentResult(success=True, action="action", constraints_passed=False),
        }
        final = await orchestrator._synthesize(plan, step_results)
        assert final.constraints_passed is False

    @pytest.mark.asyncio
    async def test_synthesize_confidence_based_on_completion_rate(self, orchestrator):
        """confidence = 成功步骤数 / 总步骤数"""
        plan = ExecutionPlan(
            trigger_summary="test",
            steps=[
                ExecutionStep("step_1", "a", "act", {}),
                ExecutionStep("step_2", "b", "act", {}),
            ],
        )
        step_results = {
            "step_1": AgentResult(success=True, action="act"),
            "step_2": AgentResult(success=False, action="act", error="fail"),
        }
        final = await orchestrator._synthesize(plan, step_results)
        assert final.confidence == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_synthesize_empty_plan_zero_confidence(self, orchestrator):
        """空计划时 confidence 为 0.0"""
        plan = ExecutionPlan(trigger_summary="empty")
        final = await orchestrator._synthesize(plan, {})
        assert final.confidence == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_synthesize_extracts_recommended_actions(self, orchestrator):
        """Agent 结果中的 recommended_actions 应被提取到综合结果"""
        plan = ExecutionPlan(
            trigger_summary="action extraction",
            steps=[ExecutionStep("step_1", "smart_menu", "recommend", {})],
        )
        step_results = {
            "step_1": AgentResult(
                success=True,
                action="recommend",
                data={"recommended_actions": [{"type": "push_dish", "dish_id": "d1"}]},
            ),
        }
        final = await orchestrator._synthesize(plan, step_results)
        assert len(final.recommended_actions) == 1
        assert final.recommended_actions[0]["type"] == "push_dish"

    @pytest.mark.asyncio
    async def test_synthesize_failed_steps_listed(self, orchestrator):
        """失败步骤应出现在 failed_steps 列表"""
        plan = ExecutionPlan(
            trigger_summary="test",
            steps=[
                ExecutionStep("step_1", "a", "act", {}),
                ExecutionStep("step_2", "b", "act", {}),
            ],
        )
        step_results = {
            "step_1": AgentResult(success=True, action="act"),
            "step_2": AgentResult(success=False, action="act", error="fail"),
        }
        final = await orchestrator._synthesize(plan, step_results)
        assert "step_2" in final.failed_steps
        assert "step_1" in final.completed_steps
        assert final.success is False
