"""Agent OS 框架测试 — 约束校验 + Memory Bus + Master 编排 + Skill Agent"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base import SkillAgent, AgentResult
from agents.constraints import ConstraintChecker, ConstraintResult
from agents.memory_bus import MemoryBus, Finding
from agents.master import MasterAgent
from agents.skills.discount_guard import DiscountGuardAgent
from agents.skills.smart_menu import SmartMenuAgent
from agents.skills.serve_dispatch import ServeDispatchAgent


# ─── 约束校验测试 ───

class TestConstraintChecker:
    def test_all_pass_when_no_data(self):
        checker = ConstraintChecker()
        result = checker.check_all({})
        assert result.passed is True
        assert len(result.violations) == 0

    def test_margin_violation(self):
        checker = ConstraintChecker(min_margin_rate=0.3)
        result = checker.check_margin({"price_fen": 1000, "cost_fen": 800})
        assert result["passed"] is False
        assert result["actual_rate"] == 0.2

    def test_margin_pass(self):
        checker = ConstraintChecker(min_margin_rate=0.15)
        result = checker.check_margin({"price_fen": 1000, "cost_fen": 500})
        assert result["passed"] is True
        assert result["actual_rate"] == 0.5

    def test_food_safety_violation(self):
        checker = ConstraintChecker(expiry_buffer_hours=24)
        result = checker.check_food_safety({
            "ingredients": [
                {"name": "鲈鱼", "remaining_hours": 12},
                {"name": "白菜", "remaining_hours": 48},
            ]
        })
        assert result["passed"] is False
        assert len(result["items"]) == 1

    def test_food_safety_pass(self):
        checker = ConstraintChecker()
        result = checker.check_food_safety({
            "ingredients": [{"name": "鲈鱼", "remaining_hours": 72}]
        })
        assert result["passed"] is True

    def test_experience_violation(self):
        checker = ConstraintChecker(max_serve_minutes=30)
        result = checker.check_experience({"estimated_serve_minutes": 45})
        assert result["passed"] is False

    def test_experience_pass(self):
        checker = ConstraintChecker(max_serve_minutes=30)
        result = checker.check_experience({"estimated_serve_minutes": 20})
        assert result["passed"] is True

    def test_all_violations(self):
        checker = ConstraintChecker(min_margin_rate=0.5, expiry_buffer_hours=48, max_serve_minutes=10)
        result = checker.check_all({
            "price_fen": 1000,
            "cost_fen": 800,
            "ingredients": [{"name": "鱼", "remaining_hours": 12}],
            "estimated_serve_minutes": 25,
        })
        assert result.passed is False
        assert len(result.violations) == 3


# ─── Memory Bus 测试 ───

class TestMemoryBus:
    def test_publish_and_get(self):
        bus = MemoryBus()
        bus.clear()
        bus.publish(Finding(
            agent_id="inventory_alert",
            finding_type="low_stock",
            data={"item": "鲈鱼", "remaining_kg": 2},
            confidence=0.9,
            store_id="store1",
        ))
        results = bus.get_recent("low_stock")
        assert len(results) == 1
        assert results[0].data["item"] == "鲈鱼"

    def test_peer_context_excludes_self(self):
        bus = MemoryBus()
        bus.clear()
        bus.publish(Finding(agent_id="agent_a", finding_type="test", data={"x": 1}, confidence=0.8))
        bus.publish(Finding(agent_id="agent_b", finding_type="test", data={"x": 2}, confidence=0.7))

        ctx = bus.get_peer_context(exclude_agent="agent_a")
        assert len(ctx) == 1
        assert ctx[0]["agent"] == "agent_b"

    def test_confidence_filter(self):
        bus = MemoryBus()
        bus.clear()
        bus.publish(Finding(agent_id="a", finding_type="t", data={}, confidence=0.3))
        bus.publish(Finding(agent_id="a", finding_type="t", data={}, confidence=0.9))

        results = bus.get_recent("t", min_confidence=0.5)
        assert len(results) == 1


# ─── Skill Agent 测试 ───

class TestDiscountGuard:
    def test_normal_discount(self):
        agent = DiscountGuardAgent(tenant_id="00000000-0000-0000-0000-000000000001")
        result = asyncio.run(
            agent.execute("detect_discount_anomaly", {
                "order": {"total_amount_fen": 10000, "discount_amount_fen": 1000}
            })
        )
        assert result.success is True
        assert result.data["is_anomaly"] is False

    def test_excessive_discount(self):
        agent = DiscountGuardAgent(tenant_id="00000000-0000-0000-0000-000000000001")
        result = asyncio.run(
            agent.execute("detect_discount_anomaly", {
                "order": {"total_amount_fen": 10000, "discount_amount_fen": 6000}
            })
        )
        assert result.data["is_anomaly"] is True


class TestSmartMenu:
    def test_cost_simulation(self):
        agent = SmartMenuAgent(tenant_id="00000000-0000-0000-0000-000000000001")
        result = asyncio.run(
            agent.execute("simulate_cost", {
                "bom_items": [
                    {"cost_fen": 500, "quantity": 1},
                    {"cost_fen": 300, "quantity": 2},
                ],
                "target_price_fen": 3800,
            })
        )
        assert result.success is True
        assert result.data["total_cost_fen"] == 1100
        assert result.data["margin_rate"] > 0.5

    def test_quadrant_star(self):
        agent = SmartMenuAgent(tenant_id="00000000-0000-0000-0000-000000000001")
        result = asyncio.run(
            agent.execute("classify_quadrant", {
                "total_sales": 200, "margin_rate": 0.5,
                "avg_sales": 100, "avg_margin": 0.3,
            })
        )
        assert result.data["quadrant"] == "star"

    def test_quadrant_dog(self):
        agent = SmartMenuAgent(tenant_id="00000000-0000-0000-0000-000000000001")
        result = asyncio.run(
            agent.execute("classify_quadrant", {
                "total_sales": 10, "margin_rate": 0.1,
                "avg_sales": 100, "avg_margin": 0.3,
            })
        )
        assert result.data["quadrant"] == "dog"


class TestServeDispatch:
    def test_serve_time_prediction(self):
        agent = ServeDispatchAgent(tenant_id="00000000-0000-0000-0000-000000000001")
        result = asyncio.run(
            agent.execute("predict_serve_time", {"dish_count": 5})
        )
        assert result.success is True
        assert result.data["estimated_serve_minutes"] == 18  # 5 + 5*2.5 rounded
        assert result.inference_layer == "edge"


# ─── Master Agent 测试 ───

class TestMasterAgent:
    def test_register_and_list(self):
        master = MasterAgent(tenant_id="00000000-0000-0000-0000-000000000001")
        master.register(DiscountGuardAgent(tenant_id="00000000-0000-0000-0000-000000000001"))
        master.register(SmartMenuAgent(tenant_id="00000000-0000-0000-0000-000000000001"))
        agents = master.list_agents()
        assert len(agents) == 2
        assert agents[0]["agent_id"] == "discount_guard"

    def test_dispatch(self):
        master = MasterAgent(tenant_id="00000000-0000-0000-0000-000000000001")
        master.register(DiscountGuardAgent(tenant_id="00000000-0000-0000-0000-000000000001"))
        result = asyncio.run(
            master.dispatch("discount_guard", "detect_discount_anomaly", {
                "order": {"total_amount_fen": 10000, "discount_amount_fen": 1000}
            })
        )
        assert result.success is True

    def test_dispatch_unknown_agent(self):
        master = MasterAgent(tenant_id="00000000-0000-0000-0000-000000000001")
        result = asyncio.run(
            master.dispatch("nonexistent", "action", {})
        )
        assert result.success is False
        assert "not found" in result.error

    def test_intent_routing(self):
        master = MasterAgent(tenant_id="00000000-0000-0000-0000-000000000001")
        master.register(DiscountGuardAgent(tenant_id="00000000-0000-0000-0000-000000000001"))
        result = asyncio.run(
            master.route_intent("discount_detect", {
                "order": {"total_amount_fen": 5000, "discount_amount_fen": 500}
            })
        )
        # intent "discount_detect" → agent "discount_guard" → action "discount_detect"
        # Agent 收到未知 action 返回 error，但路由本身成功
        assert result.action == "discount_detect"

    def test_multi_agent_execute(self):
        master = MasterAgent(tenant_id="00000000-0000-0000-0000-000000000001")
        master.register(DiscountGuardAgent(tenant_id="00000000-0000-0000-0000-000000000001"))
        master.register(SmartMenuAgent(tenant_id="00000000-0000-0000-0000-000000000001"))

        results = asyncio.run(
            master.multi_agent_execute([
                {"agent_id": "discount_guard", "action": "scan_store_licenses", "params": {}},
                {"agent_id": "smart_menu", "action": "classify_quadrant", "params": {
                    "total_sales": 150, "margin_rate": 0.4, "avg_sales": 100, "avg_margin": 0.3
                }},
            ])
        )
        assert len(results) == 2
        assert all(r.success for r in results)
