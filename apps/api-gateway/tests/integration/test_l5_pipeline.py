"""
tests/integration/test_l5_pipeline.py

L4→L5 行动派发全链路集成测试 — Phase 7 L5 行动层

覆盖：
  Segment 1: ActionDispatchService 纯逻辑验证
    - P1 报告：wechat + task + approval（waste/cost 维度）
    - P1 non-approval 维度：wechat + task，无 approval
    - P2 报告：wechat + task，无 approval
    - P3 报告：仅 wechat
    - OK 报告：直接 skipped
    - 幂等保护：同报告不重复派发

  Segment 2: WeChatActionFSM 状态机
    - CREATED → PUSHED → ACKNOWLEDGED → PROCESSING → RESOLVED 完整链路
    - 升级链路（escalate）：P2 → P1 优先级提升

  Segment 3: outcome 反馈闭环
    - record_outcome 写入 kpi_delta
    - followup_report_id 记录跟进诊断

  Segment 4: 平台统计
    - get_platform_stats 返回结构完整

  Segment 5: _upgrade_priority 修复验证（回归测试）
    - P3→P2, P2→P1, P1→P0, P0→P0
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("WECHAT_CORP_ID", "test_corp")
os.environ.setdefault("WECHAT_CORP_SECRET", "test_secret")
os.environ.setdefault("WECHAT_AGENT_ID", "1")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pipeline-testing-32!!")

sys.modules.setdefault("src.services.agent_service", MagicMock())

from src.models.action_plan import ActionOutcome, ActionPlan, DispatchStatus
from src.models.reasoning import ReasoningReport
from src.services.action_dispatch_service import ActionDispatchService
from src.services.wechat_action_fsm import (
    ActionCategory, ActionPriority, ActionState, WeChatActionFSM,
)


# ── 辅助工厂 ──────────────────────────────────────────────────────────────────

def _report(severity: str = "P1", dimension: str = "waste", store: str = "S001") -> MagicMock:
    r = MagicMock(spec=ReasoningReport)
    r.id = uuid.uuid4()
    r.store_id = store
    r.report_date = date.today()
    r.severity = severity
    r.dimension = dimension
    r.root_cause = f"{dimension} 根因分析"
    r.confidence = 0.85
    r.recommended_actions = ["减少原料采购量", "审查食材存储条件", "培训员工操作规范"]
    r.evidence_chain = ["证据1：损耗率+30%", "证据2：对比门店正常"]
    r.kpi_snapshot = {"waste_rate": 0.15, "cost_rate": 0.38}
    r.is_actioned = False
    return r


def _db(plan: ActionPlan | None = None) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = plan
    result.scalars.return_value.all.return_value = []
    result.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    return db


def _svc(plan: ActionPlan | None = None) -> ActionDispatchService:
    return ActionDispatchService(_db(plan))


# ════════════════════════════════════════════════════════════════════════════════
# Segment 1: ActionDispatchService 纯逻辑
# ════════════════════════════════════════════════════════════════════════════════

class TestDispatchLogic:
    """ActionDispatchService 派发路径验证"""

    @pytest.mark.asyncio
    async def test_p1_waste_calls_all_three_subsystems(self):
        """P1 waste → wechat + task + approval（全三路）"""
        svc = _svc()
        with (
            patch.object(svc, "_push_wechat_action", new_callable=AsyncMock) as m_w,
            patch.object(svc, "_create_task",         new_callable=AsyncMock) as m_t,
            patch.object(svc, "_create_approval",      new_callable=AsyncMock) as m_a,
        ):
            await svc.dispatch_from_report(_report("P1", "waste"))
        m_w.assert_awaited_once()
        m_t.assert_awaited_once()
        m_a.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_p1_cost_calls_all_three_subsystems(self):
        """P1 cost → wechat + task + approval（cost 同样需要审批）"""
        svc = _svc()
        with (
            patch.object(svc, "_push_wechat_action", new_callable=AsyncMock),
            patch.object(svc, "_create_task",         new_callable=AsyncMock),
            patch.object(svc, "_create_approval",      new_callable=AsyncMock) as m_a,
        ):
            await svc.dispatch_from_report(_report("P1", "cost"))
        m_a.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_p1_efficiency_no_approval(self):
        """P1 efficiency → wechat + task，不触发审批"""
        svc = _svc()
        with (
            patch.object(svc, "_push_wechat_action", new_callable=AsyncMock),
            patch.object(svc, "_create_task",         new_callable=AsyncMock),
            patch.object(svc, "_create_approval",      new_callable=AsyncMock) as m_a,
        ):
            await svc.dispatch_from_report(_report("P1", "efficiency"))
        m_a.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_p2_wechat_and_task_no_approval(self):
        """P2 任意维度 → wechat + task，无 approval"""
        svc = _svc()
        with (
            patch.object(svc, "_push_wechat_action", new_callable=AsyncMock) as m_w,
            patch.object(svc, "_create_task",         new_callable=AsyncMock) as m_t,
            patch.object(svc, "_create_approval",      new_callable=AsyncMock) as m_a,
        ):
            await svc.dispatch_from_report(_report("P2", "waste"))
        m_w.assert_awaited_once()
        m_t.assert_awaited_once()
        m_a.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_p3_only_wechat(self):
        """P3 → 仅 wechat，不创建 task 和 approval"""
        svc = _svc()
        with (
            patch.object(svc, "_push_wechat_action", new_callable=AsyncMock) as m_w,
            patch.object(svc, "_create_task",         new_callable=AsyncMock) as m_t,
            patch.object(svc, "_create_approval",      new_callable=AsyncMock) as m_a,
        ):
            await svc.dispatch_from_report(_report("P3", "quality"))
        m_w.assert_awaited_once()
        m_t.assert_not_awaited()
        m_a.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ok_skipped_no_subsystems(self):
        """OK → 直接跳过，三个子系统均不调用"""
        svc = _svc()
        with (
            patch.object(svc, "_push_wechat_action", new_callable=AsyncMock) as m_w,
            patch.object(svc, "_create_task",         new_callable=AsyncMock) as m_t,
        ):
            plan = await svc.dispatch_from_report(_report("OK", "inventory"))
        assert plan.dispatch_status == DispatchStatus.SKIPPED.value
        m_w.assert_not_awaited()
        m_t.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_idempotency_returns_existing_plan(self):
        """同报告幂等：不重复派发，直接返回已有行动计划"""
        existing = MagicMock(spec=ActionPlan)
        existing.dispatch_status = DispatchStatus.DISPATCHED.value
        svc = _svc(plan=existing)
        with (
            patch.object(svc, "_push_wechat_action", new_callable=AsyncMock) as m_w,
        ):
            result = await svc.dispatch_from_report(_report("P1", "waste"))
        assert result is existing
        m_w.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_all_subsystem_failures_result_in_failed_status(self):
        """所有子系统失败 → dispatch_status = failed"""
        svc = _svc()
        async def _fail(*a, **kw): raise RuntimeError("down")
        with (
            patch.object(svc, "_push_wechat_action", side_effect=_fail),
            patch.object(svc, "_create_task",         side_effect=_fail),
            patch.object(svc, "_create_approval",      side_effect=_fail),
        ):
            plan = await svc.dispatch_from_report(_report("P1", "cost"))
        assert plan.dispatch_status == DispatchStatus.FAILED.value

    @pytest.mark.asyncio
    async def test_dispatch_sets_dispatched_at(self):
        """成功派发后：dispatched_at 被设置"""
        svc = _svc()
        with (
            patch.object(svc, "_push_wechat_action", new_callable=AsyncMock),
            patch.object(svc, "_create_task",         new_callable=AsyncMock),
        ):
            plan = await svc.dispatch_from_report(_report("P2", "inventory"))
        assert plan.dispatched_at is not None


# ════════════════════════════════════════════════════════════════════════════════
# Segment 2: WeChatActionFSM 完整生命周期
# ════════════════════════════════════════════════════════════════════════════════

class TestWeChatFSMPipeline:
    """WeChatActionFSM 状态机完整链路"""

    @pytest.mark.asyncio
    async def test_full_happy_path(self):
        """CREATED → PUSHED → ACKNOWLEDGED → PROCESSING → RESOLVED 完整链路"""
        fsm = WeChatActionFSM()
        action = await fsm.create_action(
            store_id="S001", category=ActionCategory.WASTE_ALERT,
            priority=ActionPriority.P1, title="损耗异常", content="海鲜粥+35%",
            receiver_user_id="mgr_001", escalation_user_id="hq_001",
        )
        assert action.state == ActionState.CREATED

        with patch.object(fsm, "_send_wechat_message", new_callable=AsyncMock, return_value=True):
            ok = await fsm.push_to_wechat(action.action_id)
        assert ok is True
        assert action.state == ActionState.PUSHED

        await fsm.acknowledge(action.action_id, "mgr_001")
        assert action.state == ActionState.ACKNOWLEDGED

        await fsm.start_processing(action.action_id)
        assert action.state == ActionState.PROCESSING

        await fsm.resolve(action.action_id, "采购量下调20%，已完成")
        assert action.state == ActionState.RESOLVED
        assert action.resolved_at is not None

    @pytest.mark.asyncio
    async def test_p2_escalation_upgrades_to_p1(self):
        """P2 行动升级后：新行动优先级 = P1"""
        fsm = WeChatActionFSM()
        action = await fsm.create_action(
            store_id="S001", category=ActionCategory.KPI_ALERT,
            priority=ActionPriority.P2, title="效率KPI偏低", content="人效下降15%",
            receiver_user_id="mgr_001", escalation_user_id="hq_001",
        )
        with patch.object(fsm, "_send_wechat_message", new_callable=AsyncMock, return_value=True):
            await fsm.push_to_wechat(action.action_id)
            await fsm.escalate(action.action_id)

        assert action.state == ActionState.ESCALATED
        escalated_actions = [
            a for aid, a in fsm._actions.items() if aid != action.action_id
        ]
        assert len(escalated_actions) == 1
        assert escalated_actions[0].priority == ActionPriority.P1  # P2 → P1


# ════════════════════════════════════════════════════════════════════════════════
# Segment 3: outcome 反馈闭环
# ════════════════════════════════════════════════════════════════════════════════

class TestOutcomeFeedbackLoop:
    """record_outcome 反馈闭环"""

    @pytest.mark.asyncio
    async def test_resolved_outcome_with_kpi_delta(self):
        """resolved + kpi_delta 写入正确"""
        existing = MagicMock(spec=ActionPlan)
        existing.id = uuid.uuid4()
        db = _db()
        svc = ActionDispatchService(db)
        with patch.object(svc, "_get_plan", new_callable=AsyncMock, return_value=existing):
            result = await svc.record_outcome(
                plan_id=existing.id,
                outcome="resolved",
                resolved_by="mgr_001",
                outcome_note="已调整采购计划",
                kpi_delta={
                    "waste_rate": {"before": 0.15, "after": 0.11, "delta": -0.04},
                    "cost_rate":  {"before": 0.38, "after": 0.35, "delta": -0.03},
                },
            )
        assert result.outcome == "resolved"
        assert result.kpi_delta is not None
        assert result.outcome_note == "已调整采购计划"

    @pytest.mark.asyncio
    async def test_escalated_outcome(self):
        """escalated 结果：resolved_by 和 outcome 字段正确"""
        existing = MagicMock(spec=ActionPlan)
        db = _db()
        svc = ActionDispatchService(db)
        with patch.object(svc, "_get_plan", new_callable=AsyncMock, return_value=existing):
            result = await svc.record_outcome(
                plan_id=uuid.uuid4(),
                outcome="escalated",
                resolved_by="HQ_001",
            )
        assert result.outcome == "escalated"
        assert result.resolved_by == "HQ_001"

    @pytest.mark.asyncio
    async def test_followup_report_id_recorded(self):
        """跟进诊断 report_id 被保存到 followup_report_id"""
        existing = MagicMock(spec=ActionPlan)
        db = _db()
        svc = ActionDispatchService(db)
        followup_id = uuid.uuid4()
        with patch.object(svc, "_get_plan", new_callable=AsyncMock, return_value=existing):
            await svc.record_outcome(
                plan_id=uuid.uuid4(),
                outcome="resolved",
                resolved_by="system",
                followup_report_id=followup_id,
            )
        assert existing.followup_report_id == followup_id

    @pytest.mark.asyncio
    async def test_plan_not_found_returns_none(self):
        """行动计划不存在 → 返回 None"""
        db = _db()
        svc = ActionDispatchService(db)
        with patch.object(svc, "_get_plan", new_callable=AsyncMock, return_value=None):
            result = await svc.record_outcome(
                plan_id=uuid.uuid4(), outcome="resolved", resolved_by="x"
            )
        assert result is None


# ════════════════════════════════════════════════════════════════════════════════
# Segment 4: 平台统计结构
# ════════════════════════════════════════════════════════════════════════════════

class TestPlatformStats:
    @pytest.mark.asyncio
    async def test_stats_structure_is_complete(self):
        """get_platform_stats 返回所有预期字段"""
        db = _db()
        svc = ActionDispatchService(db)
        stats = await svc.get_platform_stats(days=7)
        assert "total_plans"   in stats
        assert "dispatch_dist" in stats
        assert "outcome_dist"  in stats
        assert "severity_dist" in stats
        assert stats["days"] == 7

    @pytest.mark.asyncio
    async def test_empty_db_zero_totals(self):
        """空数据库：total_plans = 0"""
        db = _db()
        svc = ActionDispatchService(db)
        stats = await svc.get_platform_stats()
        assert stats["total_plans"] == 0


# ════════════════════════════════════════════════════════════════════════════════
# Segment 5: _upgrade_priority 回归测试
# ════════════════════════════════════════════════════════════════════════════════

class TestUpgradePriorityRegression:
    """回归测试：确保 Phase 7 Month 1 的 _upgrade_priority bug 不再复现"""

    def test_p3_to_p2(self):
        from src.services.wechat_action_fsm import ActionPriority, WeChatActionFSM
        assert WeChatActionFSM._upgrade_priority(ActionPriority.P3) == ActionPriority.P2

    def test_p2_to_p1(self):
        from src.services.wechat_action_fsm import ActionPriority, WeChatActionFSM
        assert WeChatActionFSM._upgrade_priority(ActionPriority.P2) == ActionPriority.P1

    def test_p1_to_p0(self):
        from src.services.wechat_action_fsm import ActionPriority, WeChatActionFSM
        assert WeChatActionFSM._upgrade_priority(ActionPriority.P1) == ActionPriority.P0

    def test_p0_stays_p0(self):
        from src.services.wechat_action_fsm import ActionPriority, WeChatActionFSM
        assert WeChatActionFSM._upgrade_priority(ActionPriority.P0) == ActionPriority.P0
