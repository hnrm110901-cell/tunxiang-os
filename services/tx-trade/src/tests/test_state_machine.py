"""桌台/订单状态机测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.state_machine import (
    TABLE_STATES,
    can_order_transition,
    can_table_transition,
    get_order_next_states,
    get_table_next_states,
    sync_table_on_order_change,
    validate_order_lifecycle,
)


class TestTableStateMachine:
    def test_empty_to_dining(self):
        assert can_table_transition("empty", "dining")

    def test_empty_to_reserved(self):
        assert can_table_transition("empty", "reserved")

    def test_dining_cannot_go_to_empty(self):
        assert not can_table_transition("dining", "empty")

    def test_dining_to_checkout(self):
        assert can_table_transition("dining", "pending_checkout")

    def test_cleanup_to_empty(self):
        assert can_table_transition("pending_cleanup", "empty")

    def test_locked_to_empty(self):
        assert can_table_transition("locked", "empty")

    def test_paid_terminal(self):
        """已结账后桌台应进入清台"""
        assert can_table_transition("pending_checkout", "pending_cleanup")

    def test_8_states_defined(self):
        assert len(TABLE_STATES) == 8

    def test_next_states(self):
        nexts = get_table_next_states("empty")
        states = [n["state"] for n in nexts]
        assert "dining" in states
        assert "reserved" in states


class TestOrderStateMachine:
    def test_draft_to_placed(self):
        assert can_order_transition("draft", "placed")

    def test_placed_to_preparing(self):
        assert can_order_transition("placed", "preparing")

    def test_preparing_to_partial(self):
        assert can_order_transition("preparing", "partial_served")

    def test_all_served_to_payment(self):
        assert can_order_transition("all_served", "pending_payment")

    def test_payment_to_paid(self):
        assert can_order_transition("pending_payment", "paid")

    def test_paid_is_terminal(self):
        nexts = get_order_next_states("paid")
        assert len(nexts) == 0

    def test_cancelled_is_terminal(self):
        assert len(get_order_next_states("cancelled")) == 0

    def test_abnormal_can_recover(self):
        assert can_order_transition("abnormal", "preparing")

    def test_abnormal_can_cancel(self):
        assert can_order_transition("abnormal", "cancelled")

    def test_cannot_skip_states(self):
        assert not can_order_transition("draft", "paid")
        assert not can_order_transition("placed", "paid")

    def test_9_states_defined(self):
        from services.state_machine import ORDER_STATES
        assert len(ORDER_STATES) == 9


class TestLifecycleValidation:
    def test_happy_path(self):
        result = validate_order_lifecycle(["draft", "placed", "preparing", "all_served", "pending_payment", "paid"])
        assert result["valid"]

    def test_with_partial_serve(self):
        result = validate_order_lifecycle(["draft", "placed", "preparing", "partial_served", "all_served", "pending_payment", "paid"])
        assert result["valid"]

    def test_invalid_skip(self):
        result = validate_order_lifecycle(["draft", "paid"])
        assert not result["valid"]
        assert result["invalid_at"] == 0

    def test_cancel_path(self):
        result = validate_order_lifecycle(["draft", "placed", "cancelled"])
        assert result["valid"]

    def test_abnormal_recovery(self):
        result = validate_order_lifecycle(["draft", "placed", "preparing", "abnormal", "preparing", "all_served", "pending_payment", "paid"])
        assert result["valid"]


class TestTableOrderSync:
    def test_placed_syncs_dining(self):
        assert sync_table_on_order_change("placed") == "dining"

    def test_paid_syncs_cleanup(self):
        assert sync_table_on_order_change("paid") == "pending_cleanup"

    def test_cancelled_syncs_empty(self):
        assert sync_table_on_order_change("cancelled") == "empty"

    def test_preparing_no_sync(self):
        assert sync_table_on_order_change("preparing") is None
