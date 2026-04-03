"""发布方案纯函数测试 — >=6 个测试用例"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.publish_service import (
    create_price_adjustment,
    create_publish_plan,
    execute_publish,
)

# ---------- create_publish_plan ----------

class TestCreatePublishPlan:
    def test_basic_creation(self):
        plan = create_publish_plan(
            plan_name="午市新品上架",
            dish_ids=["d1", "d2"],
            target_store_ids=["s1", "s2", "s3"],
        )
        assert plan["plan_name"] == "午市新品上架"
        assert plan["dish_ids"] == ["d1", "d2"]
        assert plan["target_store_ids"] == ["s1", "s2", "s3"]
        assert plan["status"] == "draft"
        assert plan["schedule_time"] is None
        assert "plan_id" in plan
        assert "created_at" in plan

    def test_with_schedule_time(self):
        plan = create_publish_plan(
            plan_name="定时发布",
            dish_ids=["d1"],
            target_store_ids=["s1"],
            schedule_time="2026-04-01T10:00:00",
        )
        assert plan["schedule_time"] == "2026-04-01T10:00:00"

    def test_empty_plan_name_raises(self):
        with pytest.raises(ValueError, match="plan_name"):
            create_publish_plan(plan_name="", dish_ids=["d1"], target_store_ids=["s1"])

    def test_empty_dish_ids_raises(self):
        with pytest.raises(ValueError, match="dish_ids"):
            create_publish_plan(plan_name="X", dish_ids=[], target_store_ids=["s1"])

    def test_empty_target_stores_raises(self):
        with pytest.raises(ValueError, match="target_store_ids"):
            create_publish_plan(plan_name="X", dish_ids=["d1"], target_store_ids=[])


# ---------- execute_publish ----------

class TestExecutePublish:
    def test_basic_execution(self):
        result = execute_publish(
            plan_id="plan-001",
            dish_data=[{"dish_id": "d1", "name": "鱼香肉丝"}, {"dish_id": "d2", "name": "宫保鸡丁"}],
            target_stores=["s1", "s2"],
        )
        assert result["plan_id"] == "plan-001"
        assert result["status"] == "completed"
        assert result["total_stores"] == 2
        assert result["success_count"] == 2
        assert result["fail_count"] == 0
        assert "s1" in result["results"]
        assert result["results"]["s1"]["dish_count"] == 2

    def test_empty_plan_id_raises(self):
        with pytest.raises(ValueError, match="plan_id"):
            execute_publish(plan_id="", dish_data=[{"dish_id": "d1"}], target_stores=["s1"])

    def test_empty_dish_data_raises(self):
        with pytest.raises(ValueError, match="dish_data"):
            execute_publish(plan_id="p1", dish_data=[], target_stores=["s1"])


# ---------- create_price_adjustment ----------

class TestCreatePriceAdjustment:
    def test_time_period_adjustment(self):
        adj = create_price_adjustment(
            store_id="store-001",
            adjustment_type="time_period",
            rules=[
                {"condition": "lunch", "price_modifier": -500},
                {"condition": "dinner", "price_modifier": 300},
            ],
        )
        assert adj["store_id"] == "store-001"
        assert adj["adjustment_type"] == "time_period"
        assert len(adj["rules"]) == 2
        assert adj["rules"][0]["price_modifier"] == -500
        assert adj["status"] == "active"

    def test_holiday_adjustment(self):
        adj = create_price_adjustment(
            store_id="store-002",
            adjustment_type="holiday",
            rules=[{"condition": "spring_festival", "price_modifier": 800}],
        )
        assert adj["adjustment_type"] == "holiday"
        assert adj["rules"][0]["condition"] == "spring_festival"

    def test_delivery_adjustment(self):
        adj = create_price_adjustment(
            store_id="store-003",
            adjustment_type="delivery",
            rules=[{"condition": "meituan", "price_modifier": 200}],
        )
        assert adj["adjustment_type"] == "delivery"

    def test_invalid_adjustment_type_raises(self):
        with pytest.raises(ValueError, match="adjustment_type"):
            create_price_adjustment(
                store_id="s1",
                adjustment_type="invalid_type",
                rules=[{"condition": "x", "price_modifier": 0}],
            )

    def test_missing_condition_raises(self):
        with pytest.raises(ValueError, match="condition"):
            create_price_adjustment(
                store_id="s1",
                adjustment_type="time_period",
                rules=[{"price_modifier": 100}],
            )

    def test_missing_price_modifier_raises(self):
        with pytest.raises(ValueError, match="price_modifier"):
            create_price_adjustment(
                store_id="s1",
                adjustment_type="time_period",
                rules=[{"condition": "lunch"}],
            )

    def test_empty_rules_raises(self):
        with pytest.raises(ValueError, match="rules"):
            create_price_adjustment(
                store_id="s1",
                adjustment_type="time_period",
                rules=[],
            )
