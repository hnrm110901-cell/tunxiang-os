"""StoreInspect + SmartService Agent 测试"""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.skills.store_inspect import StoreInspectAgent
from agents.skills.smart_service import SmartServiceAgent

TID = "00000000-0000-0000-0000-000000000001"


# ─── StoreInspect 测试 ───

class TestHealthCheck:
    def test_all_healthy(self):
        agent = StoreInspectAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("health_check", {"devices": {}}))
        assert result.success
        assert result.data["overall_score"] == 100

    def test_some_issues(self):
        agent = StoreInspectAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("health_check", {
            "devices": {"printer_ok": False, "internet_ok": False, "mac_station_running": True},
        }))
        assert result.data["overall_score"] < 100
        assert len(result.data["issues"]) == 2


class TestDiagnoseFault:
    def test_printer_issue(self):
        agent = StoreInspectAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("diagnose_fault", {"symptom": "打印机不出纸"}))
        assert result.data["fault_id"] == "printer_jam"

    def test_network_issue(self):
        agent = StoreInspectAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("diagnose_fault", {"symptom": "网络连不上"}))
        assert result.data["fault_id"] == "network_down"

    def test_unknown_issue(self):
        agent = StoreInspectAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("diagnose_fault", {"symptom": "咖啡机冒烟"}))
        assert result.data["diagnosis"] == "unknown"


class TestRunbook:
    def test_valid_runbook(self):
        agent = StoreInspectAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("suggest_runbook", {"fault_id": "printer_jam"}))
        assert result.success
        assert len(result.data["steps"]) == 4

    def test_invalid_fault(self):
        agent = StoreInspectAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("suggest_runbook", {"fault_id": "alien_invasion"}))
        assert not result.success


class TestMaintenance:
    def test_overdue(self):
        agent = StoreInspectAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("predict_maintenance", {
            "devices": [
                {"type": "printer", "last_maintained_days_ago": 120},
                {"type": "scale", "last_maintained_days_ago": 50},
            ],
        }))
        assert result.data["predictions"][0]["urgency"] == "overdue"


class TestFoodSafety:
    def test_good_compliance(self):
        agent = StoreInspectAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("food_safety_status", {
            "violations": [], "total_inspections": 100,
        }))
        assert result.data["status"] == "good"
        assert result.data["compliance_rate_pct"] == 100.0

    def test_critical(self):
        agent = StoreInspectAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("food_safety_status", {
            "violations": [{"type": "temp", "resolved": False}] * 15,
            "total_inspections": 100,
        }))
        assert result.data["status"] == "critical"


# ─── SmartService 测试 ───

class TestComplaint:
    def test_food_quality(self):
        agent = SmartServiceAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("handle_complaint", {"type": "food_quality"}))
        assert result.data["priority"] == 1
        assert result.data["auto_assign_manager"]

    def test_billing(self):
        agent = SmartServiceAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("handle_complaint", {"type": "billing"}))
        assert result.data["priority"] == 3


class TestTrainingNeeds:
    def test_finds_needs(self):
        agent = SmartServiceAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("assess_training_needs", {
            "employees": [
                {"name": "张三", "role": "waiter", "skills": ["服务礼仪"], "performance_score": 45},
                {"name": "李四", "role": "waiter", "skills": ["服务礼仪", "点菜推荐", "投诉处理", "结账操作", "卫生规范"], "performance_score": 90},
            ],
        }))
        assert result.data["total"] == 1  # 只有张三
        assert result.data["needs"][0]["urgency"] == "high"


class TestSkillGaps:
    def test_identifies_gaps(self):
        agent = SmartServiceAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("analyze_skill_gaps", {
            "role": "waiter",
            "skill_scores": {"服务礼仪": 90, "点菜推荐": 40, "投诉处理": 30},
        }))
        assert len(result.data["gaps"]) >= 2
        assert result.data["total_gap_impact_yuan"] > 0


class TestEffectiveness:
    def test_high_improvement(self):
        agent = SmartServiceAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("evaluate_effectiveness", {
            "pre_scores": [50, 55, 45, 60],
            "post_scores": [80, 85, 75, 90],
            "attendance_rate": 95,
        }))
        assert result.data["effectiveness"] == "high"
        assert result.data["improvement"] > 15

    def test_no_data(self):
        agent = SmartServiceAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("evaluate_effectiveness", {}))
        assert not result.success


class TestImprovements:
    def test_generates_suggestions(self):
        agent = SmartServiceAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("generate_improvements", {
            "top_issues": [
                {"type": "wait_time", "count": 8},
                {"type": "food_quality", "count": 3},
            ],
        }))
        assert result.data["total"] == 2
        assert result.data["improvements"][0]["priority"] == "high"
