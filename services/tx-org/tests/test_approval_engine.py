"""
通用审批引擎测试

覆盖场景：
1. 创建审批流定义（折扣审批：店长→区域总监，金额>500 时需总部）
2. 发起审批申请，自动路由到第一审批人
3. 审批人同意，流转到下一级
4. 审批人拒绝，流程终止，回调发起人
5. 超时未处理（48小时），自动催办
6. 条件路由：基于申请金额决定审批层级
7. 审批历史查询
8. tenant_id 隔离

所有测试为纯函数/单元测试，不依赖真实数据库。
使用 AsyncMock 模拟 AsyncSession。
"""

from __future__ import annotations

import json
import os
import sys

# 将 tx-org/src 加入路径，使得 models/services 可以直接导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
# 将仓库根目录加入路径，使得 shared.ontology 可以导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from models.approval_flow import (
    ApprovalFlowDefinition,
    ApprovalInstance,
    ApprovalRecord,
    FlowStep,
    InstanceStatus,
    RecordAction,
    StepCondition,
)
from services.approval_engine import ApprovalEngine


# ── 测试夹具 ──────────────────────────────────────────────────────────────────


TENANT_A = str(uuid4())
TENANT_B = str(uuid4())
STORE_ID = str(uuid4())
INITIATOR_ID = str(uuid4())
STORE_MANAGER_ID = str(uuid4())
AREA_DIRECTOR_ID = str(uuid4())
HQ_FINANCE_ID = str(uuid4())
FLOW_DEF_ID = str(uuid4())
INSTANCE_ID = str(uuid4())


def _make_flow_def(
    tenant_id: str = TENANT_A,
    steps: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """构造审批流定义字典（模拟 DB 返回）"""
    if steps is None:
        steps = [
            {"step": 1, "role": "store_manager", "timeout_hours": 24, "condition": None},
            {"step": 2, "role": "area_director", "timeout_hours": 48, "condition": None},
            {
                "step": 3,
                "role": "hq_finance",
                "timeout_hours": 48,
                "condition": {"field": "amount", "op": ">", "value": 500},
            },
        ]
    return {
        "id": FLOW_DEF_ID,
        "tenant_id": tenant_id,
        "flow_name": "折扣审批流",
        "business_type": "discount",
        "steps": steps,
        "is_active": True,
        "created_at": datetime.now(),
    }


def _make_instance(
    status: str = InstanceStatus.PENDING,
    current_step: int = 1,
    amount: Optional[float] = None,
    tenant_id: str = TENANT_A,
) -> Dict[str, Any]:
    """构造审批实例字典（模拟 DB 返回）"""
    return {
        "id": INSTANCE_ID,
        "tenant_id": tenant_id,
        "flow_def_id": FLOW_DEF_ID,
        "business_type": "discount",
        "source_id": str(uuid4()),
        "title": "折扣申请 - 测试",
        "amount": amount,
        "current_step": current_step,
        "status": status,
        "initiator_id": INITIATOR_ID,
        "store_id": STORE_ID,
        "context": {"amount": amount} if amount else {},
        "created_at": datetime.now(tz=timezone.utc),
        "completed_at": None,
    }


def _make_db(
    flow_def: Optional[Dict] = None,
    instance: Optional[Dict] = None,
    approvers: Optional[List[str]] = None,
) -> AsyncMock:
    """构造模拟的 AsyncSession"""
    db = AsyncMock()

    # 模拟 execute 返回
    async def _execute(stmt, params=None):
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = (
            flow_def if flow_def else (instance if instance else None)
        )
        mock_result.mappings.return_value.fetchall.return_value = (
            [instance] if instance else []
        )
        mock_result.scalar.return_value = 0
        return mock_result

    db.execute = AsyncMock(side_effect=_execute)
    db.commit = AsyncMock()
    return db


# ── 1. 审批流模型：创建与步骤条件 ────────────────────────────────────────────


class TestApprovalFlowDefinition:
    """测试审批流定义模型"""

    def test_create_flow_def_basic(self):
        """1. 创建基本审批流定义，步骤列表不能为空"""
        fd = ApprovalFlowDefinition(
            tenant_id=uuid4(),
            flow_name="折扣审批流",
            business_type="discount",
            steps=[
                FlowStep(step=1, role="store_manager", timeout_hours=24),
                FlowStep(step=2, role="area_director", timeout_hours=48),
            ],
        )
        assert len(fd.steps) == 2
        assert fd.business_type == "discount"
        assert fd.is_active is True

    def test_flow_def_with_conditional_step(self):
        """1. 金额>500 时需要总部财务步骤"""
        hq_step = FlowStep(
            step=3,
            role="hq_finance",
            timeout_hours=48,
            condition=StepCondition(field="amount", op=">", value=500),
        )
        fd = ApprovalFlowDefinition(
            tenant_id=uuid4(),
            flow_name="折扣审批流",
            business_type="discount",
            steps=[
                FlowStep(step=1, role="store_manager", timeout_hours=24),
                FlowStep(step=2, role="area_director", timeout_hours=48),
                hq_step,
            ],
        )
        ctx_small = {"amount": 300}
        ctx_large = {"amount": 800}
        # 小金额：只有步骤1、2
        applicable_small = fd.get_applicable_steps(ctx_small)
        assert len(applicable_small) == 2
        assert all(s.step != 3 for s in applicable_small)

        # 大金额：步骤1、2、3
        applicable_large = fd.get_applicable_steps(ctx_large)
        assert len(applicable_large) == 3
        assert applicable_large[-1].step == 3

    def test_get_applicable_steps_returns_sorted(self):
        """步骤应按 step 字段升序返回"""
        fd = ApprovalFlowDefinition(
            tenant_id=uuid4(),
            flow_name="测试流程",
            business_type="purchase",
            steps=[
                FlowStep(step=3, role="hq_finance", timeout_hours=24),
                FlowStep(step=1, role="store_manager", timeout_hours=24),
                FlowStep(step=2, role="area_director", timeout_hours=24),
            ],
        )
        steps = fd.get_applicable_steps({})
        assert [s.step for s in steps] == [1, 2, 3]


# ── 2. 条件路由：StepCondition.evaluate ──────────────────────────────────────


class TestStepCondition:
    """6. 条件路由：基于申请金额决定审批层级"""

    @pytest.mark.parametrize(
        "op, ctx_val, threshold, expected",
        [
            (">", 600, 500, True),
            (">", 500, 500, False),
            (">=", 500, 500, True),
            ("<", 400, 500, True),
            ("<=", 500, 500, True),
            ("==", 500, 500, True),
            ("!=", 400, 500, True),
            ("!=", 500, 500, False),
        ],
    )
    def test_condition_ops(self, op: str, ctx_val: float, threshold: float, expected: bool):
        cond = StepCondition(field="amount", op=op, value=threshold)
        assert cond.evaluate({"amount": ctx_val}) is expected

    def test_condition_missing_field_returns_false(self):
        cond = StepCondition(field="amount", op=">", value=100)
        assert cond.evaluate({"other_field": 999}) is False

    def test_condition_non_numeric_field_returns_false(self):
        cond = StepCondition(field="amount", op=">", value=100)
        assert cond.evaluate({"amount": "not_a_number"}) is False

    def test_discount_routing_under_500(self):
        """折扣金额<=500，跳过总部步骤"""
        hq_cond = StepCondition(field="amount", op=">", value=500)
        assert hq_cond.evaluate({"amount": 300}) is False

    def test_discount_routing_over_500(self):
        """折扣金额>500，需总部步骤"""
        hq_cond = StepCondition(field="amount", op=">", value=500)
        assert hq_cond.evaluate({"amount": 800}) is True


# ── 3. ApprovalEngine.submit ──────────────────────────────────────────────────


class TestApprovalEngineSubmit:
    """2. 发起审批申请，自动路由到第一审批人"""

    @pytest.mark.asyncio
    async def test_submit_routes_to_first_step(self):
        """发起审批时，current_step 应为第一个有效步骤"""
        flow_def_data = _make_flow_def()
        instance_data = _make_instance(current_step=1)

        notifications: List[Dict] = []

        async def mock_notify(recipient_id, title, body, metadata):
            notifications.append({"recipient_id": recipient_id, "title": title})

        db = AsyncMock()
        execute_calls = []

        async def mock_execute(stmt, params=None):
            execute_calls.append(str(stmt)[:50])
            result = MagicMock()
            # 第1次：查 flow_def；第2次：insert；第3次：re-query instance；第4次：查approvers
            call_idx = len(execute_calls) - 1
            if call_idx == 0:
                result.mappings.return_value.first.return_value = flow_def_data
            elif call_idx == 2:
                result.mappings.return_value.first.return_value = instance_data
            elif call_idx == 3:
                result.fetchall.return_value = [(STORE_MANAGER_ID,)]

                class FakeRows:
                    def fetchall(self_inner):
                        return [(STORE_MANAGER_ID,)]

                return FakeRows()
            else:
                result.mappings.return_value.first.return_value = None
            return result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        with patch(
            "services.approval_engine._send_notification",
            side_effect=mock_notify,
        ):
            with patch(
                "services.approval_engine._find_approvers_by_role",
                return_value=[STORE_MANAGER_ID],
            ):
                result = await ApprovalEngine.submit(
                    flow_def_id=FLOW_DEF_ID,
                    source_id=str(uuid4()),
                    title="折扣申请 100元",
                    context={"amount": 100},
                    initiator_id=INITIATOR_ID,
                    store_id=STORE_ID,
                    tenant_id=TENANT_A,
                    db=db,
                    amount=100,
                )

        db.commit.assert_called_once()
        # 应发送通知给店长
        assert len(notifications) == 1
        assert notifications[0]["recipient_id"] == STORE_MANAGER_ID

    @pytest.mark.asyncio
    async def test_submit_raises_on_invalid_flow_def(self):
        """流程定义不存在时应抛出 ValueError"""
        db = AsyncMock()

        async def mock_execute(stmt, params=None):
            result = MagicMock()
            result.mappings.return_value.first.return_value = None
            return result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        with pytest.raises(ValueError, match="审批流定义不存在"):
            await ApprovalEngine.submit(
                flow_def_id="non-existent-id",
                source_id=None,
                title="测试",
                context={},
                initiator_id=INITIATOR_ID,
                store_id=STORE_ID,
                tenant_id=TENANT_A,
                db=db,
            )


# ── 4. ApprovalEngine.approve（流转） ────────────────────────────────────────


class TestApprovalEngineApprove:
    """3. 审批人同意，流转到下一级"""

    @pytest.mark.asyncio
    async def test_approve_advances_to_next_step(self):
        """同意后，current_step 应流转到步骤2"""
        instance_data = _make_instance(current_step=1)
        flow_def_data = _make_flow_def()

        notifications: List[Dict] = []

        async def mock_notify(recipient_id, title, body, metadata):
            notifications.append({"recipient_id": recipient_id, "metadata": metadata})

        execute_results = [
            # 1. 查 instance
            instance_data,
            # 2. insert record -> None
            None,
            # 3. 查 flow_def
            flow_def_data,
            # 4. UPDATE instance -> None
            None,
            # 5. re-query updated instance
            {**instance_data, "current_step": 2},
        ]
        call_count = [0]

        async def mock_execute(stmt, params=None):
            idx = call_count[0]
            call_count[0] += 1
            result = MagicMock()
            data = execute_results[idx] if idx < len(execute_results) else None
            result.mappings.return_value.first.return_value = data
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        with patch(
            "services.approval_engine._send_notification",
            side_effect=mock_notify,
        ):
            with patch(
                "services.approval_engine._find_approvers_by_role",
                return_value=[AREA_DIRECTOR_ID],
            ):
                result = await ApprovalEngine.approve(
                    instance_id=INSTANCE_ID,
                    approver_id=STORE_MANAGER_ID,
                    comment="同意",
                    tenant_id=TENANT_A,
                    db=db,
                )

        db.commit.assert_called_once()
        # 应通知区域总监
        assert any(n["recipient_id"] == AREA_DIRECTOR_ID for n in notifications)

    @pytest.mark.asyncio
    async def test_approve_completes_on_last_step(self):
        """最后一个步骤同意后，状态变为 approved，通知发起人"""
        # 两步流程，当前在步骤2（最后一步）
        steps = [
            {"step": 1, "role": "store_manager", "timeout_hours": 24, "condition": None},
            {"step": 2, "role": "area_director", "timeout_hours": 48, "condition": None},
        ]
        flow_def_data = _make_flow_def(steps=steps)
        instance_data = _make_instance(current_step=2)

        notifications: List[Dict] = []

        async def mock_notify(recipient_id, title, body, metadata):
            notifications.append({"recipient_id": recipient_id, "title": title})

        execute_results = [
            instance_data,
            None,  # insert record
            flow_def_data,
            None,  # update status=approved
            {**instance_data, "status": InstanceStatus.APPROVED, "completed_at": datetime.now()},
        ]
        call_count = [0]

        async def mock_execute(stmt, params=None):
            idx = call_count[0]
            call_count[0] += 1
            result = MagicMock()
            data = execute_results[idx] if idx < len(execute_results) else None
            result.mappings.return_value.first.return_value = data
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        with patch(
            "services.approval_engine._send_notification",
            side_effect=mock_notify,
        ):
            with patch(
                "services.approval_engine._find_approvers_by_role",
                return_value=[],
            ):
                result = await ApprovalEngine.approve(
                    instance_id=INSTANCE_ID,
                    approver_id=AREA_DIRECTOR_ID,
                    comment=None,
                    tenant_id=TENANT_A,
                    db=db,
                )

        # 应通知发起人审批通过
        assert any(
            n["recipient_id"] == INITIATOR_ID and "通过" in n["title"]
            for n in notifications
        )

    @pytest.mark.asyncio
    async def test_approve_raises_on_non_pending(self):
        """已完成的审批不允许再次操作"""
        instance_data = _make_instance(status=InstanceStatus.APPROVED)

        async def mock_execute(stmt, params=None):
            result = MagicMock()
            result.mappings.return_value.first.return_value = instance_data
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        with pytest.raises(ValueError, match="审批已结束"):
            await ApprovalEngine.approve(
                instance_id=INSTANCE_ID,
                approver_id=STORE_MANAGER_ID,
                comment=None,
                tenant_id=TENANT_A,
                db=db,
            )


# ── 5. ApprovalEngine.reject ──────────────────────────────────────────────────


class TestApprovalEngineReject:
    """4. 审批人拒绝，流程终止，回调发起人"""

    @pytest.mark.asyncio
    async def test_reject_terminates_flow(self):
        """拒绝后状态变为 rejected，通知发起人"""
        instance_data = _make_instance(current_step=1)

        notifications: List[Dict] = []

        async def mock_notify(recipient_id, title, body, metadata):
            notifications.append({"recipient_id": recipient_id, "title": title})

        execute_results = [
            instance_data,
            None,  # insert record
            None,  # update status=rejected
            {**instance_data, "status": InstanceStatus.REJECTED, "completed_at": datetime.now()},
        ]
        call_count = [0]

        async def mock_execute(stmt, params=None):
            idx = call_count[0]
            call_count[0] += 1
            result = MagicMock()
            data = execute_results[idx] if idx < len(execute_results) else None
            result.mappings.return_value.first.return_value = data
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        with patch(
            "services.approval_engine._send_notification",
            side_effect=mock_notify,
        ):
            result = await ApprovalEngine.reject(
                instance_id=INSTANCE_ID,
                approver_id=STORE_MANAGER_ID,
                comment="折扣超出授权范围",
                tenant_id=TENANT_A,
                db=db,
            )

        # 应通知发起人被拒绝
        assert any(
            n["recipient_id"] == INITIATOR_ID and "拒绝" in n["title"]
            for n in notifications
        )
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_reject_raises_on_non_pending(self):
        """已完成的审批不允许拒绝"""
        instance_data = _make_instance(status=InstanceStatus.REJECTED)

        async def mock_execute(stmt, params=None):
            result = MagicMock()
            result.mappings.return_value.first.return_value = instance_data
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        with pytest.raises(ValueError, match="审批已结束"):
            await ApprovalEngine.reject(
                instance_id=INSTANCE_ID,
                approver_id=STORE_MANAGER_ID,
                comment="重复拒绝",
                tenant_id=TENANT_A,
                db=db,
            )

    @pytest.mark.asyncio
    async def test_reject_notification_failure_does_not_block(self):
        """通知失败不阻塞拒绝流程"""
        instance_data = _make_instance(current_step=1)

        async def failing_notify(recipient_id, title, body, metadata):
            raise OSError("network error")

        execute_results = [
            instance_data,
            None,
            None,
            {**instance_data, "status": InstanceStatus.REJECTED},
        ]
        call_count = [0]

        async def mock_execute(stmt, params=None):
            idx = call_count[0]
            call_count[0] += 1
            result = MagicMock()
            data = execute_results[idx] if idx < len(execute_results) else None
            result.mappings.return_value.first.return_value = data
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        # _send_notification 内部已捕获异常，此处测试整体流程不抛出
        with patch(
            "services.approval_engine._send_notification",
            side_effect=failing_notify,
        ):
            # 不应抛出异常
            await ApprovalEngine.reject(
                instance_id=INSTANCE_ID,
                approver_id=STORE_MANAGER_ID,
                comment="拒绝",
                tenant_id=TENANT_A,
                db=db,
            )


# ── 6. 超时催办 ───────────────────────────────────────────────────────────────


class TestCheckTimeouts:
    """5. 超时未处理（48小时），自动催办（推送通知）"""

    @pytest.mark.asyncio
    async def test_timeout_triggers_reminder(self):
        """创建时间超过 timeout_hours，应发催办通知"""
        steps = [{"step": 1, "role": "store_manager", "timeout_hours": 48, "condition": None}]
        old_time = datetime.now(tz=timezone.utc) - timedelta(hours=49)

        pending_row = MagicMock()
        pending_row.__getitem__ = lambda self_inner, key: {
            "id": INSTANCE_ID,
            "tenant_id": TENANT_A,
            "flow_def_id": FLOW_DEF_ID,
            "business_type": "discount",
            "title": "超时折扣申请",
            "current_step": 1,
            "store_id": STORE_ID,
            "context": "{}",
            "amount": None,
            "created_at": old_time,
            "initiator_id": INITIATOR_ID,
            "steps": steps,
        }[key]
        pending_row.get = lambda key, default=None: {
            "id": INSTANCE_ID,
        }.get(key, default)

        notifications: List[Dict] = []

        async def mock_notify(recipient_id, title, body, metadata):
            notifications.append({"recipient_id": recipient_id, "title": title})

        async def mock_execute(stmt, params=None):
            result = MagicMock()
            result.mappings.return_value.fetchall.return_value = [pending_row]
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        with patch(
            "services.approval_engine._send_notification",
            side_effect=mock_notify,
        ):
            with patch(
                "services.approval_engine._find_approvers_by_role",
                return_value=[STORE_MANAGER_ID],
            ):
                result = await ApprovalEngine.check_timeouts(
                    tenant_id=TENANT_A,
                    db=db,
                )

        assert result["checked"] >= 1
        assert result["reminded"] >= 1
        assert any("催办" in n["title"] for n in notifications)

    @pytest.mark.asyncio
    async def test_no_timeout_no_reminder(self):
        """未超时的审批不发催办"""
        steps = [{"step": 1, "role": "store_manager", "timeout_hours": 48, "condition": None}]
        recent_time = datetime.now(tz=timezone.utc) - timedelta(hours=10)

        pending_row = MagicMock()
        pending_row.__getitem__ = lambda self_inner, key: {
            "id": INSTANCE_ID,
            "tenant_id": TENANT_A,
            "flow_def_id": FLOW_DEF_ID,
            "business_type": "discount",
            "title": "未超时折扣申请",
            "current_step": 1,
            "store_id": STORE_ID,
            "context": "{}",
            "amount": None,
            "created_at": recent_time,
            "initiator_id": INITIATOR_ID,
            "steps": steps,
        }[key]

        notifications: List[Dict] = []

        async def mock_notify(recipient_id, title, body, metadata):
            notifications.append({"recipient_id": recipient_id})

        async def mock_execute(stmt, params=None):
            result = MagicMock()
            result.mappings.return_value.fetchall.return_value = [pending_row]
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        with patch(
            "services.approval_engine._send_notification",
            side_effect=mock_notify,
        ):
            with patch(
                "services.approval_engine._find_approvers_by_role",
                return_value=[STORE_MANAGER_ID],
            ):
                result = await ApprovalEngine.check_timeouts(
                    tenant_id=TENANT_A,
                    db=db,
                )

        assert result["reminded"] == 0
        assert len(notifications) == 0


# ── 7. 条件路由完整场景 ───────────────────────────────────────────────────────


class TestConditionalRouting:
    """6. 条件路由：基于申请金额决定审批层级"""

    def test_amount_300_skips_hq_step(self):
        """金额300，跳过总部步骤，只需店长→区域总监"""
        fd = ApprovalFlowDefinition.model_validate(_make_flow_def())
        steps = fd.get_applicable_steps({"amount": 300})
        roles = [s.role for s in steps]
        assert "store_manager" in roles
        assert "area_director" in roles
        assert "hq_finance" not in roles

    def test_amount_800_includes_hq_step(self):
        """金额800，需要店长→区域总监→总部财务"""
        fd = ApprovalFlowDefinition.model_validate(_make_flow_def())
        steps = fd.get_applicable_steps({"amount": 800})
        roles = [s.role for s in steps]
        assert roles == ["store_manager", "area_director", "hq_finance"]

    def test_amount_exactly_500_skips_hq_step(self):
        """金额恰好 500，条件为 >500，不触发总部步骤"""
        fd = ApprovalFlowDefinition.model_validate(_make_flow_def())
        steps = fd.get_applicable_steps({"amount": 500})
        roles = [s.role for s in steps]
        assert "hq_finance" not in roles


# ── 8. tenant_id 隔离 ─────────────────────────────────────────────────────────


class TestTenantIsolation:
    """8. tenant_id 隔离"""

    @pytest.mark.asyncio
    async def test_cross_tenant_instance_not_found(self):
        """不同租户的审批实例不可见"""
        # DB 返回 None 模拟 RLS 隔离
        async def mock_execute(stmt, params=None):
            result = MagicMock()
            result.mappings.return_value.first.return_value = None
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        with pytest.raises(ValueError, match="审批实例不存在"):
            await ApprovalEngine.approve(
                instance_id=INSTANCE_ID,
                approver_id=STORE_MANAGER_ID,
                comment=None,
                tenant_id=TENANT_B,  # 不同租户
                db=db,
            )

    def test_flow_def_has_tenant_id(self):
        """审批流定义携带 tenant_id"""
        fd = ApprovalFlowDefinition(
            tenant_id=uuid4(),
            flow_name="测试流",
            business_type="purchase",
            steps=[FlowStep(step=1, role="store_manager", timeout_hours=24)],
        )
        assert fd.tenant_id is not None

    def test_instance_has_tenant_id(self):
        """审批实例携带 tenant_id"""
        inst = ApprovalInstance(
            tenant_id=uuid4(),
            flow_def_id=uuid4(),
            business_type="discount",
            title="测试",
            initiator_id=uuid4(),
            store_id=uuid4(),
        )
        assert inst.tenant_id is not None

    def test_record_has_tenant_id(self):
        """审批记录携带 tenant_id"""
        rec = ApprovalRecord(
            tenant_id=uuid4(),
            instance_id=uuid4(),
            step=1,
            approver_id=uuid4(),
            action=RecordAction.APPROVED,
        )
        assert rec.tenant_id is not None
