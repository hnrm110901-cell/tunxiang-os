"""InventoryAlert + FinanceAudit Agent 算法测试"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.skills.finance_audit import FinanceAuditAgent
from agents.skills.inventory_alert import InventoryAlertAgent

TID = "00000000-0000-0000-0000-000000000001"


# ─── InventoryAlert 测试 ───


class TestPredictConsumption:
    def test_basic_prediction(self):
        agent = InventoryAlertAgent(tenant_id=TID)
        result = asyncio.run(
            agent.execute(
                "predict_consumption",
                {
                    "daily_usage": [10, 12, 11, 13, 10, 14, 12, 11, 13, 10, 12, 11, 13, 14],
                    "days_ahead": 7,
                    "current_stock": 100,
                },
            )
        )
        assert result.success
        assert result.data["algorithm"] in ("moving_avg", "weighted_avg", "linear", "seasonal")
        assert result.data["total_predicted"] > 0
        assert result.data["days_until_stockout"] > 0

    def test_insufficient_history(self):
        agent = InventoryAlertAgent(tenant_id=TID)
        result = asyncio.run(
            agent.execute(
                "predict_consumption",
                {
                    "daily_usage": [10, 12],
                    "days_ahead": 7,
                },
            )
        )
        assert not result.success
        assert "3天" in result.error

    def test_all_algorithms_produce_values(self):
        agent = InventoryAlertAgent(tenant_id=TID)
        result = asyncio.run(
            agent.execute(
                "predict_consumption",
                {
                    "daily_usage": [10, 12, 11, 13, 10, 14, 12],
                    "days_ahead": 3,
                    "current_stock": 50,
                },
            )
        )
        assert len(result.data["all_algorithms"]) == 4


class TestRestockAlerts:
    def test_generates_alerts(self):
        agent = InventoryAlertAgent(tenant_id=TID)
        result = asyncio.run(
            agent.execute(
                "generate_restock_alerts",
                {
                    "items": [
                        {"name": "鲈鱼", "current_qty": 2, "min_qty": 5, "daily_usage": 3},
                        {"name": "白菜", "current_qty": 50, "min_qty": 10, "daily_usage": 5},
                        {"name": "鸡蛋", "current_qty": 5, "min_qty": 10, "daily_usage": 8},
                    ],
                },
            )
        )
        assert result.success
        assert len(result.data["alerts"]) == 2  # 鲈鱼(critical) + 鸡蛋(critical)
        assert result.data["alerts"][0]["level"] == "critical"

    def test_no_alerts_when_sufficient(self):
        agent = InventoryAlertAgent(tenant_id=TID)
        result = asyncio.run(
            agent.execute(
                "generate_restock_alerts",
                {
                    "items": [
                        {"name": "米", "current_qty": 200, "min_qty": 10, "daily_usage": 5},
                    ],
                },
            )
        )
        assert result.data["total"] == 0


class TestExpiration:
    def test_expired_item(self):
        agent = InventoryAlertAgent(tenant_id=TID)
        result = asyncio.run(
            agent.execute(
                "check_expiration",
                {
                    "items": [
                        {"name": "牛奶", "remaining_hours": 0},
                        {"name": "鸡蛋", "remaining_hours": 12},
                        {"name": "米", "remaining_hours": 720},
                    ],
                },
            )
        )
        assert result.data["total"] == 2
        assert result.data["warnings"][0]["status"] == "expired"


class TestOptimizeStockLevels:
    def test_basic(self):
        agent = InventoryAlertAgent(tenant_id=TID)
        result = asyncio.run(
            agent.execute(
                "optimize_stock_levels",
                {
                    "daily_usage": [10, 12, 11, 13, 10, 14, 12, 11, 13, 10, 12, 11, 13, 14],
                    "lead_days": 3,
                },
            )
        )
        assert result.success
        assert result.data["safety_stock"] > 0
        assert result.data["min_stock"] > result.data["safety_stock"]
        assert result.data["max_stock"] > result.data["min_stock"]

    def test_insufficient_data(self):
        agent = InventoryAlertAgent(tenant_id=TID)
        result = asyncio.run(
            agent.execute(
                "optimize_stock_levels",
                {
                    "daily_usage": [10, 12, 11],
                    "lead_days": 3,
                },
            )
        )
        assert not result.success


class TestSupplierEval:
    def test_grade_a(self):
        agent = InventoryAlertAgent(tenant_id=TID)
        result = asyncio.run(
            agent.execute(
                "evaluate_supplier",
                {
                    "on_time_rate": 0.95,
                    "quality_rate": 0.98,
                    "price_stability": 0.9,
                    "avg_response_hours": 4,
                },
            )
        )
        assert result.data["grade"] == "A"

    def test_grade_d(self):
        agent = InventoryAlertAgent(tenant_id=TID)
        result = asyncio.run(
            agent.execute(
                "evaluate_supplier",
                {
                    "on_time_rate": 0.3,
                    "quality_rate": 0.4,
                    "price_stability": 0.2,
                    "avg_response_hours": 48,
                },
            )
        )
        assert result.data["grade"] == "D"


# ─── FinanceAudit 测试 ───


class TestRevenueAnomaly:
    def test_normal_revenue(self):
        agent = FinanceAuditAgent(tenant_id=TID)
        result = asyncio.run(
            agent.execute(
                "detect_revenue_anomaly",
                {
                    "actual_revenue_fen": 850000,
                    "history_daily_fen": [800000, 820000, 810000, 830000, 850000, 820000, 810000],
                },
            )
        )
        assert result.success
        assert not result.data["is_anomaly"]

    def test_anomaly_detected(self):
        agent = FinanceAuditAgent(tenant_id=TID)
        result = asyncio.run(
            agent.execute(
                "detect_revenue_anomaly",
                {
                    "actual_revenue_fen": 200000,
                    "history_daily_fen": [800000, 820000, 810000, 830000, 850000, 820000, 810000],
                },
            )
        )
        assert result.data["is_anomaly"]
        assert result.data["direction"] == "below"


class TestKPISnapshot:
    def test_good_kpis(self):
        agent = FinanceAuditAgent(tenant_id=TID)
        result = asyncio.run(
            agent.execute(
                "snapshot_kpi",
                {
                    "kpis": {"revenue": 95000, "orders": 180},
                    "targets": {"revenue": 100000, "orders": 200},
                },
            )
        )
        assert result.success
        assert result.data["overall_completion_pct"] > 80


class TestForecastOrders:
    def test_basic_forecast(self):
        agent = FinanceAuditAgent(tenant_id=TID)
        result = asyncio.run(
            agent.execute(
                "forecast_orders",
                {
                    "daily_orders": [150, 140, 160, 180, 200, 190, 170, 155, 145, 165, 175, 195, 185, 175],
                    "days_ahead": 7,
                },
            )
        )
        assert result.success
        assert len(result.data["daily_forecast"]) == 7
        assert result.data["total_forecast"] > 0


class TestMatchScenario:
    def test_high_cost(self):
        agent = FinanceAuditAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("match_scenario", {"cost_rate_pct": 45}))
        assert result.data["scenario"] == "high_cost"

    def test_holiday(self):
        agent = FinanceAuditAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("match_scenario", {"is_holiday": True, "cost_rate_pct": 30}))
        assert result.data["scenario"] == "holiday_peak"

    def test_normal_weekday(self):
        agent = FinanceAuditAgent(tenant_id=TID)
        result = asyncio.run(agent.execute("match_scenario", {}))
        assert result.data["scenario"] == "weekday_normal"


class TestOrderTrend:
    def test_upward_trend(self):
        agent = FinanceAuditAgent(tenant_id=TID)
        result = asyncio.run(
            agent.execute(
                "analyze_order_trend",
                {
                    "daily_orders": [100, 110, 120, 130, 140],
                    "daily_revenue_fen": [500000, 550000, 600000, 650000, 700000],
                },
            )
        )
        assert result.data["order_trend"] == "up"
        assert result.data["avg_ticket_yuan"] > 0
