"""调度器测试 — 配置完整性 + 纯函数任务"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


from scheduler import (
    AGENT_SCHEDULES,
    auto_execute_approved_plans,
    collect_decision_outcomes,
    generate_daily_plans_for_all_stores,
    get_schedule_timeline,
    get_task_function,
    remind_unapproved_plans,
    validate_schedules,
)


class TestScheduleConfig:
    """调度配置完整性验证"""

    def test_all_schedules_have_required_fields(self):
        """每条调度必须包含 hour/minute/task"""
        errors = validate_schedules()
        assert errors == [], f"配置校验失败: {errors}"

    def test_schedule_count(self):
        """总共 8 个调度点"""
        assert len(AGENT_SCHEDULES) == 8

    def test_hours_in_valid_range(self):
        """所有 hour 在 0-23 范围内"""
        for name, config in AGENT_SCHEDULES.items():
            assert 0 <= config["hour"] <= 23, f"{name}: hour={config['hour']} 越界"

    def test_minutes_in_valid_range(self):
        """所有 minute 在 0-59 范围内"""
        for name, config in AGENT_SCHEDULES.items():
            assert 0 <= config["minute"] <= 59, f"{name}: minute={config['minute']} 越界"

    def test_no_duplicate_tasks(self):
        """不允许重复的 task 名"""
        tasks = [c["task"] for c in AGENT_SCHEDULES.values()]
        assert len(tasks) == len(set(tasks)), "存在重复的 task 名"

    def test_validate_catches_missing_fields(self):
        """validate_schedules 能检测缺失字段"""
        bad = {"broken": {"hour": 6}}
        errors = validate_schedules(bad)
        assert len(errors) > 0
        assert "缺少必填字段" in errors[0]

    def test_validate_catches_invalid_hour(self):
        """validate_schedules 能检测无效 hour"""
        bad = {"bad_hour": {"hour": 25, "minute": 0, "task": "test"}}
        errors = validate_schedules(bad)
        assert any("hour=25" in e for e in errors)

    def test_timeline_sorted_by_time(self):
        """时间线按时间升序排列"""
        timeline = get_schedule_timeline()
        times = [item["time"] for item in timeline]
        assert times == sorted(times)


class TestTaskFunctions:
    """纯函数任务测试"""

    def test_generate_daily_plans(self):
        """为多门店生成计划"""
        results = generate_daily_plans_for_all_stores(["store_001", "store_002"])
        assert len(results) == 2
        assert results[0]["status"] == "pending_approval"
        assert results[0]["generated"] is True
        assert "store_001" in results[0]["plan_id"]

    def test_remind_unapproved_plans(self):
        """仅提醒 pending_approval 状态的计划"""
        plans = [
            {"plan_id": "P1", "store_id": "S1", "status": "pending_approval"},
            {"plan_id": "P2", "store_id": "S2", "status": "approved"},
            {"plan_id": "P3", "store_id": "S3", "status": "pending_approval"},
        ]
        reminders = remind_unapproved_plans(plans)
        assert len(reminders) == 2
        assert all(r["reminded"] for r in reminders)

    def test_auto_execute_approved_plans(self):
        """仅执行 approved 状态的计划"""
        plans = [
            {"plan_id": "P1", "store_id": "S1", "status": "approved"},
            {"plan_id": "P2", "store_id": "S2", "status": "pending_approval"},
        ]
        results = auto_execute_approved_plans(plans)
        assert len(results) == 1
        assert results[0]["new_status"] == "executing"

    def test_collect_decision_outcomes(self):
        """收集决策效果并计算变化"""
        decisions = [
            {
                "decision_id": "D1",
                "decision_type": "menu_push",
                "before_data": {"sales": 100, "revenue": 5000},
            },
        ]
        metrics = {"D1": {"sales": 140, "revenue": 7000}}
        outcomes = collect_decision_outcomes(decisions, metrics)
        assert len(outcomes) == 1
        assert outcomes[0]["collected"] is True
        assert "sales" in outcomes[0]["metrics_delta"]
        assert outcomes[0]["metrics_delta"]["sales"]["change"] == 40

    def test_get_task_function(self):
        """任务注册表能正确返回函数"""
        fn = get_task_function("generate_daily_plans_for_all_stores")
        assert fn is not None
        assert callable(fn)

    def test_get_task_function_unknown(self):
        """未知任务返回 None"""
        fn = get_task_function("nonexistent_task")
        assert fn is None
