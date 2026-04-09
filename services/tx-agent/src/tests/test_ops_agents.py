"""运营专项Agent测试 — 排位/后厨超时/收银异常/闭店

每个Agent至少3个测试用例（遵循CLAUDE.md审计修复期约束）。
使用 pytest + pytest-asyncio。
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.skills.queue_seating import QueueSeatingAgent
from agents.skills.kitchen_overtime import KitchenOvertimeAgent
from agents.skills.billing_anomaly import BillingAnomalyAgent
from agents.skills.closing_agent import ClosingAgent


TENANT = "test-tenant"
STORE = "test-store"


# ═══════════════════════════════════════════════════════════════════════════════
# 排位Agent
# ═══════════════════════════════════════════════════════════════════════════════

class TestQueueSeatingAgent:
    def _make(self):
        return QueueSeatingAgent(tenant_id=TENANT, store_id=STORE)

    @pytest.mark.asyncio
    async def test_predict_wait_time_no_tables(self):
        agent = self._make()
        result = await agent.run("predict_wait_time", {
            "party_size": 4,
            "queue_position": 3,
            "available_table_count": 0,
            "matching_table_count": 2,
            "avg_turn_minutes": 45,
        })
        assert result.success is True
        assert result.data["estimated_minutes"] > 0
        assert result.data["party_size"] == 4

    @pytest.mark.asyncio
    async def test_predict_wait_time_table_available(self):
        agent = self._make()
        result = await agent.run("predict_wait_time", {
            "party_size": 2,
            "queue_position": 1,
            "available_table_count": 3,
            "matching_table_count": 2,
        })
        assert result.success is True
        assert result.data["estimated_minutes"] == 0

    @pytest.mark.asyncio
    async def test_suggest_seating_perfect_match(self):
        agent = self._make()
        result = await agent.run("suggest_seating", {
            "party_size": 4,
            "is_vip": False,
            "available_tables": [
                {"code": "A-01", "seat_capacity": 2},
                {"code": "A-05", "seat_capacity": 4},
                {"code": "A-10", "seat_capacity": 8},
            ],
        })
        assert result.success is True
        assert result.data["recommended_table"]["code"] == "A-05"  # Perfect match

    @pytest.mark.asyncio
    async def test_suggest_seating_vip_prefers_private(self):
        agent = self._make()
        result = await agent.run("suggest_seating", {
            "party_size": 4,
            "is_vip": True,
            "available_tables": [
                {"code": "A-05", "seat_capacity": 4, "is_private_room": False},
                {"code": "VIP-01", "seat_capacity": 6, "is_private_room": True},
            ],
        })
        assert result.success is True
        assert result.data["recommended_table"]["code"] == "VIP-01"

    @pytest.mark.asyncio
    async def test_auto_call_empty_queue(self):
        agent = self._make()
        result = await agent.run("auto_call_next", {
            "freed_table": {"code": "A-01", "seat_capacity": 4},
            "queue": [],
        })
        assert result.success is True
        assert result.data["called"] is None

    @pytest.mark.asyncio
    async def test_auto_call_vip_priority(self):
        agent = self._make()
        result = await agent.run("auto_call_next", {
            "freed_table": {"code": "A-01", "seat_capacity": 4},
            "queue": [
                {"ticket_no": "Q001", "party_size": 3, "is_vip": False, "is_member": False},
                {"ticket_no": "Q002", "party_size": 2, "is_vip": True, "is_member": True},
            ],
        })
        assert result.success is True
        assert result.data["called_ticket"]["ticket_no"] == "Q002"  # VIP first

    @pytest.mark.asyncio
    async def test_match_table_type(self):
        agent = self._make()
        for size, expected in [(2, "small"), (4, "medium"), (8, "large"), (12, "private_room"), (20, "vip")]:
            result = await agent.run("match_table_type", {"party_size": size})
            assert result.success is True
            assert result.data["recommended_type"] == expected

    @pytest.mark.asyncio
    async def test_unsupported_action(self):
        agent = self._make()
        result = await agent.run("nonexistent_action", {})
        assert result.success is False


# ═══════════════════════════════════════════════════════════════════════════════
# 后厨超时Agent
# ═══════════════════════════════════════════════════════════════════════════════

class TestKitchenOvertimeAgent:
    def _make(self):
        return KitchenOvertimeAgent(tenant_id=TENANT, store_id=STORE)

    @pytest.mark.asyncio
    async def test_scan_overtime_items(self):
        agent = self._make()
        result = await agent.run("scan_overtime_items", {
            "pending_items": [
                {"dish_name": "口味虾", "elapsed_minutes": 30, "table_no": "A01"},
                {"dish_name": "剁椒鱼头", "elapsed_minutes": 10, "table_no": "A02"},
                {"dish_name": "红烧肉", "elapsed_minutes": 18, "table_no": "A03"},
            ],
            "threshold_minutes": 25,
        })
        assert result.success is True
        assert result.data["overtime_count"] == 1  # 口味虾 30 > 25
        assert result.data["warning_count"] == 1   # 红烧肉 18 > 15 (60% of 25)

    @pytest.mark.asyncio
    async def test_scan_no_overtime(self):
        agent = self._make()
        result = await agent.run("scan_overtime_items", {
            "pending_items": [
                {"dish_name": "米饭", "elapsed_minutes": 3},
            ],
            "threshold_minutes": 25,
        })
        assert result.success is True
        assert result.data["overtime_count"] == 0
        assert result.data["warning_count"] == 0

    @pytest.mark.asyncio
    async def test_analyze_overtime_cause_shortage(self):
        agent = self._make()
        result = await agent.run("analyze_overtime_cause", {
            "item": {"kitchen_station": "活鲜档", "elapsed_minutes": 35},
            "ingredient_shortage": True,
            "station_queue_length": 3,
            "station_staff_count": 2,
        })
        assert result.success is True
        assert result.data["primary_cause"] == "ingredient_shortage"

    @pytest.mark.asyncio
    async def test_analyze_overtime_cause_overload(self):
        agent = self._make()
        result = await agent.run("analyze_overtime_cause", {
            "item": {"kitchen_station": "热菜档", "elapsed_minutes": 28},
            "ingredient_shortage": False,
            "equipment_issue": False,
            "station_queue_length": 12,
            "station_staff_count": 2,
        })
        assert result.success is True
        assert result.data["primary_cause"] == "queue_overload"

    @pytest.mark.asyncio
    async def test_auto_rush_notify(self):
        agent = self._make()
        result = await agent.run("auto_rush_notify", {
            "item": {
                "order_no": "ORD-001",
                "dish_name": "口味虾",
                "table_no": "A01",
                "kitchen_station": "热菜档",
            },
        })
        assert result.success is True
        assert result.data["notification_type"] == "kds_rush"

    @pytest.mark.asyncio
    async def test_get_station_bottleneck(self):
        agent = self._make()
        result = await agent.run("get_station_bottleneck", {
            "station_stats": [
                {"station_name": "热菜档", "avg_serve_minutes": 22, "overtime_rate": 0.45, "pending_count": 8},
                {"station_name": "凉菜档", "avg_serve_minutes": 8, "overtime_rate": 0.05, "pending_count": 2},
                {"station_name": "蒸菜档", "avg_serve_minutes": 25, "overtime_rate": 0.30, "pending_count": 5},
            ],
        })
        assert result.success is True
        assert len(result.data["bottlenecks"]) == 2  # 热菜档 + 蒸菜档
        assert result.data["bottlenecks"][0]["station"] == "热菜档"  # Worst first

    @pytest.mark.asyncio
    async def test_predict_serve_time(self):
        agent = self._make()
        result = await agent.run("predict_serve_time", {
            "dish_name": "剁椒鱼头",
            "station": "蒸菜档",
            "queue_ahead": 3,
            "avg_cook_minutes": 20,
        })
        assert result.success is True
        assert result.data["predicted_minutes"] == 29  # 20 + 3*3


# ═══════════════════════════════════════════════════════════════════════════════
# 收银异常Agent
# ═══════════════════════════════════════════════════════════════════════════════

class TestBillingAnomalyAgent:
    def _make(self):
        return BillingAnomalyAgent(tenant_id=TENANT, store_id=STORE)

    @pytest.mark.asyncio
    async def test_detect_reverse_settle_high_risk(self):
        agent = self._make()
        result = await agent.run("detect_reverse_settle_anomaly", {
            "operator_id": "cashier-01",
            "order_id": "ord-001",
            "reverse_count_today": 4,
            "reverse_amount_fen": 68000,
        })
        assert result.success is True
        assert result.data["risk_level"] == "high"
        assert result.data["requires_approval"] is True
        assert len(result.data["alerts"]) >= 1

    @pytest.mark.asyncio
    async def test_detect_reverse_settle_low_risk(self):
        agent = self._make()
        result = await agent.run("detect_reverse_settle_anomaly", {
            "operator_id": "cashier-01",
            "order_id": "ord-001",
            "reverse_count_today": 1,
            "reverse_amount_fen": 3800,
        })
        assert result.success is True
        assert result.data["risk_level"] == "low"

    @pytest.mark.asyncio
    async def test_scan_missing_orders(self):
        agent = self._make()
        result = await agent.run("scan_missing_orders", {
            "occupied_tables": [
                {"table_no": "A01", "status": "dining"},
                {"table_no": "A02", "status": "opened"},
                {"table_no": "A03", "status": "dining"},
            ],
            "active_order_table_nos": ["A01", "A03"],
        })
        assert result.success is True
        assert result.data["missing_count"] == 1  # A02 has no order

    @pytest.mark.asyncio
    async def test_detect_payment_anomaly_large_cash(self):
        agent = self._make()
        result = await agent.run("detect_payment_anomaly", {
            "payment": {
                "method": "cash",
                "amount_fen": 150000,
                "order_total_fen": 150000,
            },
        })
        assert result.success is True
        assert result.data["anomaly_count"] >= 1
        assert any(a["type"] == "large_cash" for a in result.data["anomalies"])

    @pytest.mark.asyncio
    async def test_check_overdue_credit(self):
        agent = self._make()
        result = await agent.run("check_overdue_credit", {
            "credit_orders": [
                {"order_id": "o1", "days_outstanding": 45, "outstanding_fen": 50000},
                {"order_id": "o2", "days_outstanding": 10, "outstanding_fen": 20000},
                {"order_id": "o3", "days_outstanding": 60, "outstanding_fen": 80000},
            ],
            "overdue_days_threshold": 30,
        })
        assert result.success is True
        assert result.data["overdue_count"] == 2  # o1 and o3
        assert result.data["total_overdue_fen"] == 130000

    @pytest.mark.asyncio
    async def test_analyze_shift_variance(self):
        agent = self._make()
        result = await agent.run("analyze_shift_variance", {
            "expected_cash_fen": 125000,
            "actual_cash_fen": 112000,
            "operator_name": "小王",
        })
        assert result.success is True
        assert result.data["risk_level"] == "high"  # 130元差异
        assert result.data["variance_fen"] == -13000


# ═══════════════════════════════════════════════════════════════════════════════
# 闭店Agent
# ═══════════════════════════════════════════════════════════════════════════════

class TestClosingAgent:
    def _make(self):
        return ClosingAgent(tenant_id=TENANT, store_id=STORE)

    @pytest.mark.asyncio
    async def test_pre_closing_check_ready(self):
        agent = self._make()
        result = await agent.run("pre_closing_check", {
            "unsettled_order_count": 0,
            "pending_invoice_count": 0,
            "shift_closed": True,
            "cash_variance_fen": 0,
            "checklist_completed": True,
            "occupied_table_count": 0,
        })
        assert result.success is True
        assert result.data["can_close"] is True
        assert result.data["status"] == "ready"
        assert len(result.data["blockers"]) == 0

    @pytest.mark.asyncio
    async def test_pre_closing_check_blocked(self):
        agent = self._make()
        result = await agent.run("pre_closing_check", {
            "unsettled_order_count": 2,
            "pending_invoice_count": 1,
            "shift_closed": False,
            "cash_variance_fen": 800,
            "checklist_completed": False,
            "occupied_table_count": 1,
        })
        assert result.success is True
        assert result.data["can_close"] is False
        assert result.data["status"] == "blocked"
        assert len(result.data["blockers"]) == 3  # unsettled + occupied + shift

    @pytest.mark.asyncio
    async def test_validate_settlement_pass(self):
        agent = self._make()
        result = await agent.run("validate_daily_settlement", {
            "total_revenue_fen": 856000,
            "payment_sum_fen": 864800,
            "refund_total_fen": 8800,
            "order_count": 42,
            "channel_order_sum": 42,
        })
        assert result.success is True
        assert result.data["passed"] is True

    @pytest.mark.asyncio
    async def test_validate_settlement_mismatch(self):
        agent = self._make()
        result = await agent.run("validate_daily_settlement", {
            "total_revenue_fen": 856000,
            "payment_sum_fen": 800000,
            "refund_total_fen": 0,
            "order_count": 42,
            "channel_order_sum": 42,
        })
        assert result.success is True
        assert result.data["passed"] is False
        assert len(result.data["discrepancies"]) >= 1

    @pytest.mark.asyncio
    async def test_remind_unsettled_empty(self):
        agent = self._make()
        result = await agent.run("remind_unsettled_orders", {
            "unsettled_orders": [],
        })
        assert result.success is True
        assert result.data["count"] == 0

    @pytest.mark.asyncio
    async def test_remind_unsettled_with_orders(self):
        agent = self._make()
        result = await agent.run("remind_unsettled_orders", {
            "unsettled_orders": [
                {"order_id": "o1", "table_no": "A01", "total_fen": 28800},
                {"order_id": "o2", "table_no": "B03", "total_fen": 45600},
            ],
        })
        assert result.success is True
        assert result.data["count"] == 2
        assert result.data["total_fen"] == 74400
        assert result.data["notification"]["type"] == "push"

    @pytest.mark.asyncio
    async def test_check_checklist_status(self):
        agent = self._make()
        result = await agent.run("check_checklist_status", {
            "type": "closing",
            "total_items": 16,
            "checked_items": 12,
            "failed_items": 1,
        })
        assert result.success is True
        assert result.data["progress"] == 75.0
        assert result.data["completed"] is False

    @pytest.mark.asyncio
    async def test_escalate_anomaly(self):
        agent = self._make()
        result = await agent.run("escalate_anomaly", {
            "anomaly_type": "cash_variance",
            "detail": "现金差异超过¥200",
            "store_name": "徐记海鲜·芙蓉店",
        })
        assert result.success is True
        assert result.data["escalated"] is True
        assert result.data["target"] == "regional_manager"
