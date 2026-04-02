"""
工作流 & 审批工单引擎测试 -- workflow_engine.py 纯函数测试
"""

from datetime import date, datetime

import pytest
from services.workflow_engine import (
    WorkflowStatus,
    build_approval_chain,
    calc_phase_deadline,
    can_transition,
    check_countersign_complete,
    get_positions_for_role,
    is_phase_expired,
    process_approve,
    process_escalate,
    process_reject,
    resolve_role_from_position,
    simple_diff,
    transition,
)

# ── 基础审批链配置（测试用） ──────────────────────────────────────

SAMPLE_CHAIN = [
    {"level": 1, "role": "store_manager", "timeout_hours": 24, "node_type": "single"},
    {"level": 2, "role": "area_manager", "timeout_hours": 48, "node_type": "single"},
    {"level": 3, "role": "ceo", "timeout_hours": 72, "node_type": "single"},
]


class TestStateMachine:
    """状态机转换测试"""

    def test_pending_to_approved(self):
        """pending -> approved 合法"""
        assert can_transition(WorkflowStatus.PENDING, WorkflowStatus.APPROVED) is True
        result = transition(WorkflowStatus.PENDING, WorkflowStatus.APPROVED)
        assert result == WorkflowStatus.APPROVED

    def test_pending_to_rejected(self):
        """pending -> rejected 合法"""
        assert can_transition(WorkflowStatus.PENDING, WorkflowStatus.REJECTED) is True

    def test_approved_to_executed(self):
        """approved -> executed 合法"""
        assert can_transition(WorkflowStatus.APPROVED, WorkflowStatus.EXECUTED) is True

    def test_rejected_to_approved_illegal(self):
        """rejected -> approved 非法"""
        assert can_transition(WorkflowStatus.REJECTED, WorkflowStatus.APPROVED) is False
        with pytest.raises(ValueError, match="非法状态转换"):
            transition(WorkflowStatus.REJECTED, WorkflowStatus.APPROVED)

    def test_executed_is_terminal(self):
        """executed 是终态，不能转换到任何状态"""
        assert can_transition(WorkflowStatus.EXECUTED, WorkflowStatus.PENDING) is False

    def test_escalated_to_approved(self):
        """escalated -> approved 合法"""
        assert can_transition(WorkflowStatus.ESCALATED, WorkflowStatus.APPROVED) is True

    def test_pending_to_cancelled(self):
        """pending -> cancelled 合法"""
        assert can_transition(WorkflowStatus.PENDING, WorkflowStatus.CANCELLED) is True


class TestBuildApprovalChain:
    """审批链构建测试"""

    def test_basic_chain(self):
        """无金额阈值时返回原始链"""
        chain = build_approval_chain(SAMPLE_CHAIN)
        assert len(chain) == 3
        assert chain[0]["role"] == "store_manager"

    def test_amount_threshold_adds_level(self):
        """金额超过阈值时自动添加审批层级"""
        thresholds = [
            {"threshold_fen": 100_000, "extra_approver_role": "finance_director"},
        ]
        chain = build_approval_chain(
            SAMPLE_CHAIN,
            amount_fen=200_000,
            amount_thresholds=thresholds,
        )
        assert len(chain) == 4
        roles = [s["role"] for s in chain]
        assert "finance_director" in roles

    def test_amount_below_threshold_no_change(self):
        """金额未达阈值时不添加"""
        thresholds = [
            {"threshold_fen": 100_000, "extra_approver_role": "finance_director"},
        ]
        chain = build_approval_chain(
            SAMPLE_CHAIN,
            amount_fen=50_000,
            amount_thresholds=thresholds,
        )
        assert len(chain) == 3

    def test_no_duplicate_roles(self):
        """已存在角色不重复添加"""
        thresholds = [
            {"threshold_fen": 100_000, "extra_approver_role": "ceo"},  # ceo 已在链中
        ]
        chain = build_approval_chain(
            SAMPLE_CHAIN,
            amount_fen=200_000,
            amount_thresholds=thresholds,
        )
        assert len(chain) == 3  # 不增加


class TestProcessApprove:
    """审批通过处理"""

    def test_approve_first_level(self):
        """第一级通过，推进到第二级"""
        result = process_approve(
            current_status=WorkflowStatus.PENDING,
            current_level=1,
            chain=SAMPLE_CHAIN,
            approver_id="user_001",
        )
        assert result["is_final"] is False
        assert result["new_level"] == 2
        assert result["next_step"]["role"] == "area_manager"

    def test_approve_final_level(self):
        """最后一级通过，审批完成"""
        result = process_approve(
            current_status=WorkflowStatus.PENDING,
            current_level=3,
            chain=SAMPLE_CHAIN,
            approver_id="user_003",
        )
        assert result["is_final"] is True
        assert result["new_status"] == WorkflowStatus.APPROVED

    def test_approve_rejected_raises(self):
        """已驳回状态不能审批"""
        with pytest.raises(ValueError):
            process_approve(
                current_status=WorkflowStatus.REJECTED,
                current_level=1,
                chain=SAMPLE_CHAIN,
                approver_id="user_001",
            )


class TestProcessReject:
    """审批驳回处理"""

    def test_reject(self):
        """驳回"""
        result = process_reject(
            current_status=WorkflowStatus.PENDING,
            current_level=1,
            chain=SAMPLE_CHAIN,
            approver_id="user_001",
            reason="信息不全",
        )
        assert result["new_status"] == WorkflowStatus.REJECTED
        assert result["record"]["action"] == "reject"
        assert result["record"]["comment"] == "信息不全"


class TestProcessEscalate:
    """超时升级处理"""

    def test_escalate_to_next(self):
        """超时自动升级到下一级"""
        result = process_escalate(
            current_status=WorkflowStatus.PENDING,
            current_level=1,
            chain=SAMPLE_CHAIN,
        )
        assert result["escalated"] is True
        assert result["new_status"] == WorkflowStatus.ESCALATED
        assert result["new_level"] == 2

    def test_escalate_at_last_level(self):
        """最后一级超时，无法升级"""
        result = process_escalate(
            current_status=WorkflowStatus.PENDING,
            current_level=3,
            chain=SAMPLE_CHAIN,
        )
        assert result["escalated"] is False
        assert result["new_level"] == 3


class TestCountersign:
    """会签测试"""

    def test_all_approved(self):
        """全部通过"""
        complete, remaining = check_countersign_complete(
            required_approvers=["A", "B", "C"],
            approved_by=["A", "B", "C"],
        )
        assert complete is True
        assert remaining == []

    def test_partial_approved(self):
        """部分通过"""
        complete, remaining = check_countersign_complete(
            required_approvers=["A", "B", "C"],
            approved_by=["A"],
        )
        assert complete is False
        assert set(remaining) == {"B", "C"}


class TestDeadline:
    """Deadline 计算测试"""

    def test_phase_deadline(self):
        result = calc_phase_deadline(
            trigger_date=date(2026, 3, 23),
            deadline_hour=18,
            deadline_minute=30,
        )
        assert result == datetime(2026, 3, 23, 18, 30, 0)

    def test_custom_deadline_override(self):
        result = calc_phase_deadline(
            trigger_date=date(2026, 3, 23),
            deadline_hour=18,
            deadline_minute=0,
            custom_deadline="20:30",
        )
        assert result == datetime(2026, 3, 23, 20, 30, 0)

    def test_is_expired(self):
        past = datetime(2026, 1, 1, 12, 0, 0)
        assert is_phase_expired(past, now=datetime(2026, 3, 23)) is True

    def test_not_expired(self):
        future = datetime(2026, 12, 31, 23, 59, 59)
        assert is_phase_expired(future, now=datetime(2026, 3, 23)) is False


class TestSimpleDiff:
    """版本 Diff 测试"""

    def test_diff(self):
        prev = {"a": 1, "b": 2, "c": 3}
        curr = {"a": 1, "b": 99, "d": 4}
        result = simple_diff(prev, curr)
        assert result["added"] == {"d": 4}
        assert result["removed"] == {"c": 3}
        assert result["modified"]["b"] == {"before": 2, "after": 99}


class TestRoleMapping:
    """角色映射测试"""

    def test_resolve_store_manager(self):
        assert resolve_role_from_position("店长") == "store_manager"

    def test_resolve_unknown(self):
        assert resolve_role_from_position("unknown_position") is None

    def test_get_positions(self):
        positions = get_positions_for_role("ceo")
        assert "老板" in positions
        assert "总经理" in positions
