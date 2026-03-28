"""TableDispatch + CostDiagnosis + ReviewSummary Agent 测试"""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.skills.table_dispatch import TableDispatchAgent
from agents.skills.cost_diagnosis import CostDiagnosisAgent
from agents.skills.review_summary import ReviewSummaryAgent

TID = "00000000-0000-0000-0000-000000000001"


# ─── TableDispatch 测试 ───

class TestSuggestSeating:
    def test_best_table_for_party(self):
        agent = TableDispatchAgent(tenant_id=TID)
        tables = [
            {"table_id": "T1", "capacity": 2, "table_type": "small_2", "idle_minutes": 15},
            {"table_id": "T2", "capacity": 4, "table_type": "medium_4", "idle_minutes": 5},
            {"table_id": "T3", "capacity": 6, "table_type": "large_6", "idle_minutes": 20},
        ]
        result = asyncio.run(agent.execute("suggest_seating", {
            "party_size": 2, "available_tables": tables,
        }))
        assert result.success
        assert result.data["recommended_table"]["table_id"] == "T1"
        assert result.confidence > 0

    def test_vip_prefers_vip_room(self):
        agent = TableDispatchAgent(tenant_id=TID)
        tables = [
            {"table_id": "T1", "capacity": 4, "table_type": "medium_4", "idle_minutes": 10},
            {"table_id": "VIP1", "capacity": 12, "table_type": "vip_room", "idle_minutes": 10},
        ]
        result = asyncio.run(agent.execute("suggest_seating", {
            "party_size": 4, "is_vip": True, "available_tables": tables,
        }))
        assert result.success
        assert result.data["recommended_table"]["table_id"] == "VIP1"

    def test_no_available_tables(self):
        agent = TableDispatchAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("suggest_seating", {
            "party_size": 4, "available_tables": [],
        }))
        assert result.success
        assert result.data["recommended_table"] is None


class TestPredictWait:
    def test_no_wait_when_tables_available(self):
        agent = TableDispatchAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("predict_wait", {
            "store_id": "S001", "current_queue": 3,
            "available_tables_count": 2, "total_tables": 20,
        }))
        assert result.success
        assert result.data["predicted_wait_minutes"] == 0

    def test_wait_time_increases_with_queue(self):
        agent = TableDispatchAgent(tenant_id=TID)
        r1 = asyncio.run(agent.execute("predict_wait", {
            "store_id": "S001", "current_queue": 2,
            "available_tables_count": 0, "total_tables": 20,
        }))
        r2 = asyncio.run(agent.execute("predict_wait", {
            "store_id": "S001", "current_queue": 10,
            "available_tables_count": 0, "total_tables": 20,
        }))
        assert r2.data["predicted_wait_minutes"] > r1.data["predicted_wait_minutes"]


# ─── CostDiagnosis 测试 ───

class TestDiagnoseCost:
    def test_detects_severe_variance(self):
        agent = CostDiagnosisAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("diagnose", {
            "store_id": "S001", "date": "2026-03-26",
            "dishes": [
                {"name": "水煮鱼", "expected_cost_fen": 2000, "actual_cost_fen": 2800, "quantity_sold": 50},
                {"name": "宫保鸡丁", "expected_cost_fen": 1500, "actual_cost_fen": 1550, "quantity_sold": 80},
            ],
        }))
        assert result.success
        assert result.data["variance_count"] >= 1
        # 水煮鱼偏差 40%，应为 severe
        top = result.data["top_variances"][0]
        assert top["dish_name"] == "水煮鱼"
        assert top["severity"] == "severe"

    def test_no_dishes_returns_error(self):
        agent = CostDiagnosisAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("diagnose", {
            "store_id": "S001", "date": "2026-03-26", "dishes": [],
        }))
        assert not result.success


class TestRootCause:
    def test_identifies_price_increase(self):
        agent = CostDiagnosisAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("root_cause", {
            "dish_id": "D001", "dish_name": "水煮鱼",
            "bom_items": [
                {"ingredient_id": "I1", "ingredient_name": "鲈鱼", "standard_quantity": 1.0, "standard_price_fen": 3000},
            ],
            "actual_usage": [
                {"ingredient_id": "I1", "actual_quantity": 1.0, "actual_price_fen": 3600, "waste_rate": 0.03},
            ],
        }))
        assert result.success
        assert result.data["primary_cause"] == "采购价上涨"
        assert result.confidence > 0
        assert result.reasoning  # 决策留痕有 reasoning


class TestSuggestFix:
    def test_generates_actions_for_causes(self):
        agent = CostDiagnosisAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("suggest_fix", {
            "dish_name": "水煮鱼",
            "diagnosis": {
                "dish_name": "水煮鱼",
                "all_causes": [
                    {"cause_type": "采购价上涨", "ingredient": "鲈鱼", "variance_rate": 0.20, "impact_fen": 600},
                    {"cause_type": "份量超标", "ingredient": "花椒", "variance_rate": 0.15, "impact_fen": 100},
                ],
            },
        }))
        assert result.success
        assert result.data["action_count"] == 2
        categories = {a["category"] for a in result.data["actions"]}
        assert "采购" in categories
        assert "出品" in categories


# ─── ReviewSummary 测试 ───

class TestDailySummary:
    def test_good_day_gets_high_grade(self):
        agent = ReviewSummaryAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("daily_summary", {
            "store_id": "S001", "date": "2026-03-26",
            "metrics": {
                "revenue_fen": 6000000, "covers": 250,
                "margin_rate": 0.33, "turnover_rate": 3.0,
                "food_cost_fen": 2000000, "labor_cost_fen": 1000000,
                "waste_fen": 50000, "complaints": 0,
                "top_dishes": ["水煮鱼", "宫保鸡丁"],
            },
        }))
        assert result.success
        assert result.data["grade"] in ("优秀", "良好")
        assert result.data["score"] >= 70
        assert len(result.data["highlights"]) > 0

    def test_bad_day_generates_warnings(self):
        agent = ReviewSummaryAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("daily_summary", {
            "store_id": "S001", "date": "2026-03-26",
            "metrics": {
                "revenue_fen": 3000000, "covers": 100,
                "margin_rate": 0.20, "turnover_rate": 1.5,
                "food_cost_fen": 2400000, "labor_cost_fen": 1000000,
                "waste_fen": 200000, "complaints": 5,
            },
        }))
        assert result.success
        assert len(result.data["warnings"]) >= 2


class TestWeeklyPattern:
    def test_detects_weekend_uplift(self):
        agent = ReviewSummaryAgent(tenant_id=TID)
        daily_data = []
        for i in range(14):
            is_weekend = i % 7 in (5, 6)
            daily_data.append({
                "revenue_fen": 8000000 if is_weekend else 4000000,
                "covers": 300 if is_weekend else 150,
                "is_weekend": is_weekend,
            })
        result = asyncio.run(agent.execute("weekly_pattern", {
            "store_id": "S001", "daily_data": daily_data, "days": 14,
        }))
        assert result.success
        assert result.data["pattern_count"] >= 1
        # 应该检测到周末营收高于工作日
        weekend_pattern = next(
            (p for p in result.data["patterns"] if p["type"] == "weekday_vs_weekend"), None
        )
        assert weekend_pattern is not None
        assert weekend_pattern["weekend_uplift_pct"] > 50

    def test_insufficient_data_returns_error(self):
        agent = ReviewSummaryAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("weekly_pattern", {
            "store_id": "S001", "daily_data": [{"revenue_fen": 5000000}] * 3,
        }))
        assert not result.success


class TestActionPlan:
    def test_generates_actions_from_warnings(self):
        agent = ReviewSummaryAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("action_plan", {
            "store_id": "S001",
            "summary": {
                "warnings": ["毛利率 20.0% 低于目标 30.0%", "投诉 5 单，需关注"],
            },
            "patterns": [],
        }))
        assert result.success
        assert result.data["action_count"] >= 2
        assert result.data["high_priority_count"] >= 2

    def test_default_action_when_all_good(self):
        agent = ReviewSummaryAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("action_plan", {
            "store_id": "S001", "summary": {"warnings": []}, "patterns": [],
        }))
        assert result.success
        assert result.data["action_count"] >= 1
