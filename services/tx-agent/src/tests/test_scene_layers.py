"""L1-L5 八层架构核心测试

覆盖：
- L1 场景会话层：意图识别、角色路由、会话管理
- L2 Agent 编排层：Dispatcher 路由、多 Agent 协同
- L3 Tool 网关：权限校验、确认拦截
- L5 状态机：桌态、订单、出品、结算状态流转
- 业务流矩阵：配置正确性
"""
import pytest

from ..layers.scene_session import (
    IntentType,
    SceneSessionManager,
    SessionContext,
    ShiftPeriod,
    UserRole,
)
from ..layers.state_machines import (
    KitchenItemState,
    KitchenStateMachine,
    OrderState,
    OrderStateMachine,
    SettlementState,
    SettlementStateMachine,
    StateMachineRegistry,
    TableState,
    TableStateMachine,
    TransitionError,
)
from ..layers.tool_gateway import (
    TOOL_INDEX,
    ToolGateway,
    _AGENT_TOOL_MAPPING,
)
from ..layers.flow_matrix import (
    BUSINESS_FLOWS,
    AdaptationMode,
    get_agent_led_flows,
    get_agent_flows,
)
from ..layers.orchestrator import Dispatcher, create_dispatcher


# ─── L1 场景会话层测试 ───────────────────────────────────────────────────────

class TestSceneSession:
    def setup_method(self):
        self.mgr = SceneSessionManager()

    def test_create_session(self):
        ctx = self.mgr.create_session(
            tenant_id="t-001",
            user_role=UserRole.STORE_MANAGER,
            store_id="s-001",
        )
        assert ctx.tenant_id == "t-001"
        assert ctx.user_role == UserRole.STORE_MANAGER
        assert ctx.store_id == "s-001"
        assert ctx.session_id is not None

    def test_get_session(self):
        ctx = self.mgr.create_session(tenant_id="t-001", user_role=UserRole.HOST)
        found = self.mgr.get_session(ctx.session_id)
        assert found is not None
        assert found.session_id == ctx.session_id

    def test_parse_intent_reservation(self):
        ctx = self.mgr.create_session(tenant_id="t-001", user_role=UserRole.HOST)
        intent = self.mgr.parse_intent("帮我安排今晚包厢预订", ctx)
        assert intent.target_agent == "reception"
        assert intent.confidence >= 0.8
        assert intent.intent_type == IntentType.ACTION

    def test_parse_intent_kpi(self):
        ctx = self.mgr.create_session(tenant_id="t-001", user_role=UserRole.STORE_MANAGER)
        intent = self.mgr.parse_intent("今天翻台率怎么样", ctx)
        assert intent.target_agent == "store_ops"
        assert intent.action == "kpi_query"

    def test_parse_intent_kitchen(self):
        ctx = self.mgr.create_session(tenant_id="t-001", user_role=UserRole.CHEF)
        intent = self.mgr.parse_intent("哪些桌催菜了", ctx)
        assert intent.target_agent == "kitchen"

    def test_parse_intent_member(self):
        ctx = self.mgr.create_session(tenant_id="t-001", user_role=UserRole.WAITER)
        intent = self.mgr.parse_intent("这位客人是会员吗", ctx)
        assert intent.target_agent == "member_growth"

    def test_parse_intent_report(self):
        ctx = self.mgr.create_session(tenant_id="t-001", user_role=UserRole.HQ_EXECUTIVE)
        intent = self.mgr.parse_intent("生成本周周报", ctx)
        assert intent.target_agent == "hq_analytics"
        assert intent.action == "generate_report"

    def test_parse_intent_waitlist(self):
        ctx = self.mgr.create_session(tenant_id="t-001", user_role=UserRole.HOST)
        intent = self.mgr.parse_intent("现在等位多少桌", ctx)
        assert intent.target_agent == "waitlist_table"

    def test_parse_intent_fallback_by_role(self):
        ctx = self.mgr.create_session(tenant_id="t-001", user_role=UserRole.CASHIER)
        intent = self.mgr.parse_intent("今天有什么问题吗", ctx)
        # 无法匹配关键词时，按角色路由
        assert intent.target_agent == "checkout_risk"  # 收银员默认路由
        assert intent.confidence < 0.5

    def test_session_conversation_history(self):
        ctx = self.mgr.create_session(tenant_id="t-001", user_role=UserRole.STORE_MANAGER)
        ctx.add_turn("user", "午市复盘")
        ctx.add_turn("assistant", "午市营业额12万...")
        assert len(ctx.conversation_history) == 2

    def test_cleanup_expired(self):
        self.mgr.create_session(tenant_id="t-001", user_role=UserRole.HOST)
        removed = self.mgr.cleanup_expired(max_age_seconds=0)
        assert removed == 1


# ─── L5 状态机测试 ────────────────────────────────────────────────────────────

class TestTableStateMachine:
    def test_normal_flow(self):
        sm = TableStateMachine("table-01")
        assert sm.current_state == TableState.AVAILABLE.value

        sm.transition(TableState.RESERVED.value, "reservation", actor_id="host-1")
        assert sm.current_state == TableState.RESERVED.value

        sm.transition(TableState.SEATING.value, "guest_arrived")
        sm.transition(TableState.OCCUPIED.value, "order_placed")
        sm.transition(TableState.CLEANING.value, "payment_done")
        sm.transition(TableState.AVAILABLE.value, "cleaning_done")

        assert sm.current_state == TableState.AVAILABLE.value
        assert len(sm.history) == 5

    def test_cancel_reservation(self):
        sm = TableStateMachine("table-02")
        sm.transition(TableState.RESERVED.value, "reservation")
        sm.transition(TableState.AVAILABLE.value, "cancel_reservation")
        assert sm.current_state == TableState.AVAILABLE.value

    def test_invalid_transition(self):
        sm = TableStateMachine("table-03")
        sm.transition(TableState.OCCUPIED.value, "direct_seat")
        with pytest.raises(TransitionError):
            sm.transition(TableState.AVAILABLE.value, "skip_cleaning")

    def test_allowed_transitions(self):
        sm = TableStateMachine("table-04")
        allowed = sm.get_allowed_transitions()
        assert TableState.RESERVED.value in allowed
        assert TableState.SEATING.value in allowed


class TestOrderStateMachine:
    def test_normal_flow(self):
        sm = OrderStateMachine("order-001")
        sm.transition(OrderState.CONFIRMED.value, "staff_confirm")
        sm.transition(OrderState.PREPARING.value, "kitchen_accept")
        sm.transition(OrderState.SERVED.value, "all_dishes_served")
        sm.transition(OrderState.PAYING.value, "request_bill")
        sm.transition(OrderState.PAID.value, "payment_success")
        sm.transition(OrderState.COMPLETED.value, "auto_complete")
        assert sm.current_state == OrderState.COMPLETED.value

    def test_cancel_before_pay(self):
        sm = OrderStateMachine("order-002")
        sm.transition(OrderState.CONFIRMED.value, "confirm")
        sm.transition(OrderState.CANCELLED.value, "customer_cancel")
        assert sm.current_state == OrderState.CANCELLED.value

    def test_refund_after_pay(self):
        sm = OrderStateMachine("order-003")
        sm.transition(OrderState.CONFIRMED.value, "confirm")
        sm.transition(OrderState.PREPARING.value, "accept")
        sm.transition(OrderState.SERVED.value, "served")
        sm.transition(OrderState.PAYING.value, "bill")
        sm.transition(OrderState.PAID.value, "paid")
        sm.transition(OrderState.REFUNDING.value, "refund_request")
        sm.transition(OrderState.REFUNDED.value, "refund_done")
        assert sm.current_state == OrderState.REFUNDED.value

    def test_cannot_cancel_after_pay(self):
        sm = OrderStateMachine("order-004")
        sm.transition(OrderState.CONFIRMED.value, "c")
        sm.transition(OrderState.PREPARING.value, "p")
        sm.transition(OrderState.SERVED.value, "s")
        sm.transition(OrderState.PAYING.value, "b")
        sm.transition(OrderState.PAID.value, "pay")
        with pytest.raises(TransitionError):
            sm.transition(OrderState.CANCELLED.value, "try_cancel")


class TestKitchenStateMachine:
    def test_normal_flow(self):
        sm = KitchenStateMachine("item-001")
        sm.transition(KitchenItemState.ACCEPTED.value, "accept")
        sm.transition(KitchenItemState.PREPARING.value, "start_cook")
        sm.transition(KitchenItemState.QUALITY_CHECK.value, "cook_done")
        sm.transition(KitchenItemState.READY.value, "pass_check")
        sm.transition(KitchenItemState.DELIVERING.value, "pickup")
        sm.transition(KitchenItemState.DELIVERED.value, "served")
        assert sm.current_state == KitchenItemState.DELIVERED.value

    def test_return_before_prepare(self):
        sm = KitchenStateMachine("item-002")
        sm.transition(KitchenItemState.ACCEPTED.value, "accept")
        sm.transition(KitchenItemState.RETURNED.value, "customer_cancel")
        assert sm.current_state == KitchenItemState.RETURNED.value

    def test_quality_fail_redo(self):
        sm = KitchenStateMachine("item-003")
        sm.transition(KitchenItemState.ACCEPTED.value, "accept")
        sm.transition(KitchenItemState.PREPARING.value, "cook")
        sm.transition(KitchenItemState.QUALITY_CHECK.value, "done")
        sm.transition(KitchenItemState.PREPARING.value, "redo")  # 重做
        assert sm.current_state == KitchenItemState.PREPARING.value


class TestSettlementStateMachine:
    def test_normal_flow(self):
        sm = SettlementStateMachine("store-001-2026-04-01")
        sm.transition(SettlementState.PRE_CLOSING.value, "shift_end")
        sm.transition(SettlementState.CLOSING.value, "start_close")
        sm.transition(SettlementState.CLOSED.value, "close_done")
        sm.transition(SettlementState.AUDITED.value, "audit_pass")
        sm.transition(SettlementState.LOCKED.value, "lock")
        assert sm.current_state == SettlementState.LOCKED.value

    def test_audit_reject(self):
        sm = SettlementStateMachine("store-002-2026-04-01")
        sm.transition(SettlementState.PRE_CLOSING.value, "end")
        sm.transition(SettlementState.CLOSING.value, "close")
        sm.transition(SettlementState.CLOSED.value, "done")
        sm.transition(SettlementState.AUDITED.value, "audit")
        sm.transition(SettlementState.CLOSED.value, "audit_reject")  # 回退
        assert sm.current_state == SettlementState.CLOSED.value


class TestStateMachineRegistry:
    def test_registry(self):
        reg = StateMachineRegistry()
        t = reg.get_or_create_table("t1")
        assert t.current_state == TableState.AVAILABLE.value
        # 再次获取是同一个实例
        t2 = reg.get_or_create_table("t1")
        assert t is t2


# ─── L3 Tool 网关测试 ─────────────────────────────────────────────────────────

class TestToolGateway:
    def test_tool_definitions_exist(self):
        assert len(TOOL_INDEX) > 20
        assert "query_reservations" in TOOL_INDEX
        assert "create_order" in TOOL_INDEX

    def test_agent_tool_mapping(self):
        # 每个专业 Agent 都有工具映射
        expected_agents = [
            "reception", "waitlist_table", "ordering", "kitchen",
            "member_growth", "checkout_risk", "store_ops", "hq_analytics",
        ]
        for agent_id in expected_agents:
            assert agent_id in _AGENT_TOOL_MAPPING, f"{agent_id} 缺少工具映射"
            assert len(_AGENT_TOOL_MAPPING[agent_id]) > 0

    @pytest.mark.asyncio
    async def test_role_permission_check(self):
        gw = ToolGateway()
        # 顾客不能查预订
        result = await gw.call_tool(
            "query_reservations", {"date": "today"},
            caller_role=UserRole.CUSTOMER,
            caller_agent="test",
            tenant_id="t-001",
        )
        assert not result.success
        assert "无权" in (result.error or "")

    @pytest.mark.asyncio
    async def test_confirmation_required(self):
        gw = ToolGateway()
        result = await gw.call_tool(
            "create_reservation",
            {"customer_phone": "13800138000", "party_size": 4, "date": "2026-04-01", "time": "19:00"},
            caller_role=UserRole.HOST,
            caller_agent="reception",
            tenant_id="t-001",
        )
        assert result.requires_confirmation
        assert result.success

    @pytest.mark.asyncio
    async def test_read_only_tool_no_confirmation(self):
        gw = ToolGateway()
        result = await gw.call_tool(
            "query_table_status",
            {"store_id": "s-001"},
            caller_role=UserRole.HOST,
            caller_agent="waitlist_table",
            tenant_id="t-001",
        )
        assert result.success
        assert not result.requires_confirmation

    def test_get_tools_for_agent(self):
        gw = ToolGateway()
        tools = gw.get_tools_for_agent("reception")
        assert len(tools) > 0
        tool_names = {t["name"] for t in tools}
        assert "query_reservations" in tool_names
        assert "create_reservation" in tool_names


# ─── 业务流矩阵测试 ──────────────────────────────────────────────────────────

class TestFlowMatrix:
    def test_all_flows_defined(self):
        assert len(BUSINESS_FLOWS) == 12

    def test_agent_led_flows(self):
        led = get_agent_led_flows()
        assert len(led) >= 4  # 营销、报表、巡店、总部预警
        for f in led:
            assert f.mode == AdaptationMode.AGENT_LED

    def test_get_agent_flows(self):
        reception_flows = get_agent_flows("reception")
        assert any(f.flow_id == "reservation" for f in reception_flows)

    def test_p0_flows_have_agents(self):
        p0 = [f for f in BUSINESS_FLOWS if f.priority == "P0"]
        for f in p0:
            assert len(f.primary_agents) > 0, f"{f.flow_id} 缺少 primary_agents"


# ─── L2 编排层测试 ────────────────────────────────────────────────────────────

class TestDispatcher:
    def test_create_dispatcher(self):
        d = create_dispatcher()
        specialists = d.list_specialists()
        assert len(specialists) == 8

    def test_specialist_ids(self):
        d = create_dispatcher()
        expected = {
            "reception", "waitlist_table", "ordering", "kitchen",
            "member_growth", "checkout_risk", "store_ops", "hq_analytics",
        }
        actual = {s["agent_id"] for s in d.list_specialists()}
        assert expected == actual

    @pytest.mark.asyncio
    async def test_dispatch_unknown_agent(self):
        d = create_dispatcher()
        ctx = SessionContext(tenant_id="t-001", user_role=UserRole.STORE_MANAGER)
        result = await d.dispatch("nonexistent", "test", {}, ctx)
        assert not result.success
        assert "未找到" in (result.error or "")
