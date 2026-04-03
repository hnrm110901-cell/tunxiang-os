"""MemberInsight + PrivateOps Agent 测试"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.skills.member_insight import MemberInsightAgent
from agents.skills.private_ops import PrivateOpsAgent

TID = "00000000-0000-0000-0000-000000000001"

SAMPLE_MEMBERS = [
    {"customer_id": "c1", "name": "张三", "recency_days": 5, "frequency": 15, "monetary_fen": 800000},
    {"customer_id": "c2", "name": "李四", "recency_days": 45, "frequency": 3, "monetary_fen": 50000},
    {"customer_id": "c3", "name": "王五", "recency_days": 120, "frequency": 1, "monetary_fen": 10000},
    {"customer_id": "c4", "name": "赵六", "recency_days": 200, "frequency": 0, "monetary_fen": 5000, "birth_date": "03-25"},
]


class TestRFMAnalysis:
    def test_basic(self):
        agent = MemberInsightAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("analyze_rfm", {"members": SAMPLE_MEMBERS}))
        assert result.success
        assert result.data["total"] == 4
        assert sum(v["count"] for v in result.data["distribution"].values()) == 4

    def test_empty_members(self):
        agent = MemberInsightAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("analyze_rfm", {"members": []}))
        assert not result.success


class TestChurnRisks:
    def test_finds_at_risk(self):
        agent = MemberInsightAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("get_churn_risks", {"members": SAMPLE_MEMBERS, "risk_threshold": 0.3}))
        assert result.success
        assert result.data["total"] >= 2  # 王五和赵六应该高风险

    def test_high_threshold(self):
        agent = MemberInsightAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("get_churn_risks", {"members": SAMPLE_MEMBERS, "risk_threshold": 0.9}))
        assert result.data["total"] >= 1  # 至少赵六


class TestJourney:
    def test_trigger_reactivation(self):
        agent = MemberInsightAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("trigger_journey", {"journey_type": "reactivation", "customer_id": "c3"}))
        assert result.success
        assert len(result.data["steps"]) == 4

    def test_unknown_journey(self):
        agent = MemberInsightAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("trigger_journey", {"journey_type": "nonexistent"}))
        assert not result.success


class TestBadReview:
    def test_high_severity(self):
        agent = MemberInsightAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("process_bad_review", {
            "review_text": "太难吃了，等太久，服务差", "rating": 1,
        }))
        assert result.data["severity"] == "high"
        assert len(result.data["detected_issues"]) >= 2

    def test_low_severity(self):
        agent = MemberInsightAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("process_bad_review", {
            "review_text": "还可以", "rating": 4,
        }))
        assert result.data["severity"] == "low"


class TestSignals:
    def test_detects_churn(self):
        agent = MemberInsightAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("detect_signals", {"members": SAMPLE_MEMBERS}))
        assert result.success
        churn_signals = [s for s in result.data["signals"] if s["type"] == "churn_risk"]
        assert len(churn_signals) >= 2


class TestServiceQuality:
    def test_good_quality(self):
        agent = MemberInsightAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("monitor_service_quality", {
            "feedbacks": [{"rating": 5}, {"rating": 4}, {"rating": 5}, {"rating": 4}],
        }))
        assert result.data["status"] == "good"
        assert result.data["avg_rating"] > 4

    def test_critical_quality(self):
        agent = MemberInsightAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("monitor_service_quality", {
            "feedbacks": [{"rating": 1}, {"rating": 2}, {"rating": 1}, {"rating": 3}],
        }))
        assert result.data["status"] == "critical"


# ─── PrivateOps 测试 ───

class TestPerformance:
    def test_good_score(self):
        agent = PrivateOpsAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("score_performance", {
            "role": "waiter",
            "metrics": {"service_count": 90, "tips": 85, "complaints": 95, "upsell": 80, "attendance": 100},
        }))
        assert result.data["grade"] in ("A", "B")
        assert result.data["commission_fen"] > 0

    def test_food_safety_penalty(self):
        agent = PrivateOpsAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("score_performance", {
            "role": "chef",
            "metrics": {"dish_quality": 90, "speed": 85, "waste": 80, "consistency": 85, "hygiene": 90,
                        "food_safety_violation": True},
        }))
        assert result.data["total_score"] <= 30
        assert "食安" in result.data["penalties"][0]


class TestLaborCost:
    def test_within_budget(self):
        agent = PrivateOpsAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("analyze_labor_cost", {
            "total_wage_fen": 20000000, "revenue_fen": 100000000, "staff_count": 25, "target_rate": 0.25,
        }))
        assert result.data["status"] == "ok"
        assert result.data["labor_cost_rate_pct"] == 20.0

    def test_over_budget(self):
        agent = PrivateOpsAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("analyze_labor_cost", {
            "total_wage_fen": 40000000, "revenue_fen": 100000000, "staff_count": 30, "target_rate": 0.25,
        }))
        assert result.data["status"] == "critical"


class TestAttendance:
    def test_detects_issues(self):
        agent = PrivateOpsAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("warn_attendance", {
            "records": [
                {"name": "张三", "late_count": 5, "absent_count": 1, "early_leave_count": 2},
                {"name": "李四", "late_count": 0, "absent_count": 0, "early_leave_count": 0},
            ],
        }))
        assert result.data["total"] == 1
        assert result.data["warnings"][0]["employee"] == "张三"


class TestSeating:
    def test_allocates_best_match(self):
        agent = PrivateOpsAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("allocate_seating", {
            "guest_count": 4,
            "preferences": ["包间"],
            "available_tables": [
                {"table_no": "A01", "seats": 4, "area": "大厅"},
                {"table_no": "B01", "seats": 6, "area": "包间"},
                {"table_no": "B02", "seats": 8, "area": "包间"},
            ],
        }))
        assert result.success
        assert result.data["area"] == "包间"

    def test_no_tables(self):
        agent = PrivateOpsAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("allocate_seating", {"guest_count": 4, "available_tables": []}))
        assert not result.success


class TestBEO:
    def test_generates_beo(self):
        agent = PrivateOpsAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("generate_beo", {
            "event_name": "张总寿宴",
            "guest_count": 30,
            "event_date": "2026-04-15",
            "menu_items": [
                {"name": "龙虾", "price_fen": 28800, "quantity": 3},
                {"name": "鲍鱼", "price_fen": 18800, "quantity": 3},
            ],
            "special_requests": ["无花生", "红色主题布置"],
        }))
        assert result.success
        assert result.data["guest_count"] == 30
        assert len(result.data["timeline"]) == 5
        assert result.data["total_cost_yuan"] > 0
