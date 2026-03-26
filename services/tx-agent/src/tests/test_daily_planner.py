"""日计划 Agent 测试"""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.planner import DailyPlannerAgent


class TestGeneratePlan:
    def test_generates_complete_plan(self):
        agent = DailyPlannerAgent(tenant_id="t1", store_id="s1")
        plan = asyncio.run(agent.generate_daily_plan("2026-03-25"))
        assert plan["status"] == "pending_approval"
        assert plan["store_id"] == "s1"
        assert plan["summary"]["total_items"] > 0

    def test_has_all_5_dimensions(self):
        agent = DailyPlannerAgent(tenant_id="t1", store_id="s1")
        plan = asyncio.run(agent.generate_daily_plan())
        assert "menu_suggestions" in plan
        assert "procurement_list" in plan
        assert "staffing_adjustments" in plan
        assert "marketing_triggers" in plan
        assert "risk_alerts" in plan

    def test_menu_suggestions_from_inventory(self):
        agent = DailyPlannerAgent(tenant_id="t1", store_id="s1")
        plan = asyncio.run(agent.generate_daily_plan())
        menu = plan["menu_suggestions"]
        assert len(menu) >= 2  # surplus push + shortage reduce
        actions = [m["action"] for m in menu]
        assert "push" in actions
        assert "reduce" in actions

    def test_procurement_from_shortage(self):
        agent = DailyPlannerAgent(tenant_id="t1", store_id="s1")
        plan = asyncio.run(agent.generate_daily_plan())
        procurement = plan["procurement_list"]
        assert len(procurement) >= 1
        assert procurement[0]["urgency"] in ("urgent", "normal")

    def test_staffing_on_high_traffic(self):
        agent = DailyPlannerAgent(tenant_id="t1", store_id="s1")
        plan = asyncio.run(agent.generate_daily_plan())
        staffing = plan["staffing_adjustments"]
        assert len(staffing) >= 1  # traffic +15% triggers add

    def test_marketing_for_inactive_members(self):
        agent = DailyPlannerAgent(tenant_id="t1", store_id="s1")
        plan = asyncio.run(agent.generate_daily_plan())
        marketing = plan["marketing_triggers"]
        assert len(marketing) >= 1
        assert any("inactive" in m.get("target", "") for m in marketing)

    def test_birthday_marketing(self):
        agent = DailyPlannerAgent(tenant_id="t1", store_id="s1")
        plan = asyncio.run(agent.generate_daily_plan())
        marketing = plan["marketing_triggers"]
        assert any("birthday" in m.get("target", "") for m in marketing)

    def test_risk_alerts_for_banquet(self):
        agent = DailyPlannerAgent(tenant_id="t1", store_id="s1")
        plan = asyncio.run(agent.generate_daily_plan())
        risks = plan["risk_alerts"]
        assert any("banquet" in r.get("type", "") for r in risks)

    def test_summary_counts(self):
        agent = DailyPlannerAgent(tenant_id="t1", store_id="s1")
        plan = asyncio.run(agent.generate_daily_plan())
        s = plan["summary"]
        assert s["total_items"] == s["menu_count"] + s["procurement_count"] + s["staffing_count"] + s["marketing_count"] + s["risk_count"]

    def test_expected_saving(self):
        agent = DailyPlannerAgent(tenant_id="t1", store_id="s1")
        plan = asyncio.run(agent.generate_daily_plan())
        assert plan["summary"]["expected_saving_fen"] > 0

    def test_plan_id_format(self):
        agent = DailyPlannerAgent(tenant_id="t1", store_id="s1")
        plan = asyncio.run(agent.generate_daily_plan("2026-03-25"))
        assert plan["plan_id"].startswith("PLAN_")


class TestApprovePlan:
    def test_full_approve(self):
        plan = {"summary": {"total_items": 3}, "status": "pending_approval"}
        result = DailyPlannerAgent.approve_plan(plan, ["a", "b", "c"], [])
        assert result["status"] == "approved"

    def test_partial_approve(self):
        plan = {"summary": {"total_items": 3}, "status": "pending_approval"}
        result = DailyPlannerAgent.approve_plan(plan, ["a"], ["b", "c"])
        assert result["status"] == "partial"

    def test_full_reject(self):
        plan = {"summary": {"total_items": 3}, "status": "pending_approval"}
        result = DailyPlannerAgent.approve_plan(plan, [], ["a", "b", "c"])
        assert result["status"] == "rejected"

    def test_approval_timestamp(self):
        plan = {"summary": {"total_items": 1}, "status": "pending_approval"}
        result = DailyPlannerAgent.approve_plan(plan, ["a"], [])
        assert "approved_at" in result
