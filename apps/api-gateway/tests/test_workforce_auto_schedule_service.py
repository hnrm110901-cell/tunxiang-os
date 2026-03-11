from __future__ import annotations

import os
from datetime import date, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-workforce-auto-32!!")
os.environ.setdefault("WECHAT_CORP_ID", "test_corp")
os.environ.setdefault("WECHAT_CORP_SECRET", "test_secret")
os.environ.setdefault("WECHAT_AGENT_ID", "1")

from src.services.workforce_auto_schedule_service import (  # noqa: E402
    WorkforceAutoScheduleService,
    build_schedule_anomalies,
    calculate_shift_hours,
    estimate_labor_cost_yuan,
)


def _result_with_row(row):
    result = MagicMock()
    result.fetchone.return_value = row
    return result


class TestWorkforceAutoSchedulePure:
    def test_calculate_shift_hours_normal(self):
        assert calculate_shift_hours(time(8, 0), time(14, 0)) == 6.0

    def test_calculate_shift_hours_overnight(self):
        assert calculate_shift_hours(time(20, 0), time(2, 0)) == 6.0

    def test_calculate_shift_hours_same_boundary(self):
        # 跨天：结束时间 == 开始时间 → 24小时
        assert calculate_shift_hours(time(8, 0), time(8, 0)) == 24.0

    def test_estimate_labor_cost_yuan(self):
        shifts = [
            {
                "employee_id": "e1",
                "position": "waiter",
                "start_time": time(8, 0),
                "end_time": time(14, 0),
            },
            {
                "employee_id": "e2",
                "position": "chef",
                "start_time": time(14, 0),
                "end_time": time(20, 0),
            },
        ]
        assert estimate_labor_cost_yuan(shifts) == 258.0

    def test_estimate_labor_cost_yuan_empty(self):
        assert estimate_labor_cost_yuan([]) == 0.0

    def test_estimate_labor_cost_yuan_default_position(self):
        shifts = [
            {
                "employee_id": "e1",
                "position": "unknown_role",
                "start_time": time(9, 0),
                "end_time": time(17, 0),
            }
        ]
        cost = estimate_labor_cost_yuan(shifts)
        assert cost == round(8.0 * 20.0, 2)  # default hourly wage

    def test_build_schedule_anomalies_budget_overtime_and_role_gap(self):
        shifts = [
            {
                "employee_id": "e1",
                "position": "waiter",
                "start_time": time(8, 0),
                "end_time": time(14, 0),
            },
            {
                "employee_id": "e1",
                "position": "waiter",
                "start_time": time(14, 0),
                "end_time": time(20, 30),
            },
        ]
        anomalies = build_schedule_anomalies(
            shifts=shifts,
            estimated_cost_yuan=500.0,
            daily_budget_yuan=300.0,
        )
        anomaly_types = {a["type"] for a in anomalies}
        assert "budget_overrun" in anomaly_types
        assert "overtime_risk" in anomaly_types
        assert "role_gap" in anomaly_types

    def test_build_schedule_anomalies_within_budget_no_overtime(self):
        shifts = [
            {
                "employee_id": "e1",
                "position": "waiter",
                "start_time": time(9, 0),
                "end_time": time(15, 0),
            },
            {
                "employee_id": "e2",
                "position": "cashier",
                "start_time": time(9, 0),
                "end_time": time(15, 0),
            },
        ]
        anomalies = build_schedule_anomalies(
            shifts=shifts,
            estimated_cost_yuan=200.0,
            daily_budget_yuan=500.0,
        )
        anomaly_types = {a["type"] for a in anomalies}
        assert "budget_overrun" not in anomaly_types
        assert "overtime_risk" not in anomaly_types

    def test_build_schedule_anomalies_no_budget_skips_overrun(self):
        shifts = [
            {
                "employee_id": "e1",
                "position": "waiter",
                "start_time": time(9, 0),
                "end_time": time(15, 0),
            },
        ]
        anomalies = build_schedule_anomalies(
            shifts=shifts,
            estimated_cost_yuan=9999.0,
            daily_budget_yuan=None,
        )
        anomaly_types = {a["type"] for a in anomalies}
        assert "budget_overrun" not in anomaly_types


class TestWorkforceAutoScheduleService:
    @pytest.mark.asyncio
    async def test_generate_schedule_existing_schedule(self):
        db = AsyncMock()
        existing = MagicMock()
        existing.id = "schedule-1"
        with patch(
            "src.services.workforce_auto_schedule_service.ScheduleRepository.get_by_date",
            new_callable=AsyncMock,
            return_value=existing,
        ):
            result = await WorkforceAutoScheduleService.generate_schedule_with_constraints(
                store_id="S001",
                schedule_date=date(2026, 3, 8),
                db=db,
            )
        assert result["created"] is False
        assert result["reason"] == "exists"

    @pytest.mark.asyncio
    async def test_generate_schedule_no_active_employee_raises(self):
        db = AsyncMock()
        with (
            patch(
                "src.services.workforce_auto_schedule_service.ScheduleRepository.get_by_date",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.services.workforce_auto_schedule_service.EmployeeRepository.get_by_store",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.services.workforce_auto_schedule_service.StaffingPatternService.build_shifts_from_best_pattern",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            with pytest.raises(ValueError, match="暂无在职员工"):
                await WorkforceAutoScheduleService.generate_schedule_with_constraints(
                    store_id="S001",
                    schedule_date=date(2026, 3, 8),
                    db=db,
                )

    @pytest.mark.asyncio
    async def test_generate_schedule_with_anomaly_notify(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(
            return_value=_result_with_row(
                SimpleNamespace(daily_budget_yuan=100.0, max_labor_cost_yuan=3000.0)
            )
        )
        employees = [
            SimpleNamespace(id="E001", name="张三", skills=["waiter"], position="waiter", is_active=True),
            SimpleNamespace(id="E002", name="李四", skills=["chef"], position="chef", is_active=True),
        ]
        shifts = [
            {
                "employee_id": "E001",
                "shift_type": "morning",
                "start_time": time(8, 0),
                "end_time": time(14, 0),
                "position": "waiter",
            },
            {
                "employee_id": "E002",
                "shift_type": "afternoon",
                "start_time": time(14, 0),
                "end_time": time(20, 0),
                "position": "chef",
            },
        ]
        with (
            patch(
                "src.services.workforce_auto_schedule_service.ScheduleRepository.get_by_date",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.services.workforce_auto_schedule_service.EmployeeRepository.get_by_store",
                new_callable=AsyncMock,
                return_value=employees,
            ),
            patch(
                "src.services.workforce_auto_schedule_service.StaffingPatternService.build_shifts_from_best_pattern",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch.object(
                WorkforceAutoScheduleService,
                "_generate_shifts_from_agent",
                new_callable=AsyncMock,
                return_value=shifts,
            ),
            patch.object(
                WorkforceAutoScheduleService,
                "_notify_anomalies",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_notify,
        ):
            result = await WorkforceAutoScheduleService.generate_schedule_with_constraints(
                store_id="S001",
                schedule_date=date(2026, 3, 8),
                db=db,
            )
        assert result["created"] is True
        assert result["anomaly_count"] >= 1
        assert result["notified"] is True
        mock_notify.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_schedule_budget_passed_to_agent(self):
        """daily_budget_yuan 应在调用 _generate_shifts_from_agent 前获取并传入。"""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(
            return_value=_result_with_row(
                SimpleNamespace(daily_budget_yuan=800.0, max_labor_cost_yuan=5000.0)
            )
        )
        employees = [
            SimpleNamespace(id="E001", name="张三", skills=["waiter", "cashier"], position="waiter", is_active=True),
        ]
        shifts = [
            {
                "employee_id": "E001",
                "shift_type": "morning",
                "start_time": time(8, 0),
                "end_time": time(14, 0),
                "position": "cashier",
            },
        ]
        with (
            patch(
                "src.services.workforce_auto_schedule_service.ScheduleRepository.get_by_date",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.services.workforce_auto_schedule_service.EmployeeRepository.get_by_store",
                new_callable=AsyncMock,
                return_value=employees,
            ),
            patch(
                "src.services.workforce_auto_schedule_service.StaffingPatternService.build_shifts_from_best_pattern",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch.object(
                WorkforceAutoScheduleService,
                "_generate_shifts_from_agent",
                new_callable=AsyncMock,
                return_value=shifts,
            ) as mock_agent,
            patch.object(
                WorkforceAutoScheduleService,
                "_notify_anomalies",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await WorkforceAutoScheduleService.generate_schedule_with_constraints(
                store_id="S001",
                schedule_date=date(2026, 3, 10),
                db=db,
            )
        # 验证 budget 被正确传入 agent
        call_kwargs = mock_agent.call_args.kwargs
        assert call_kwargs.get("daily_budget_yuan") == 800.0
        assert result["daily_budget_yuan"] == 800.0

    @pytest.mark.asyncio
    async def test_generate_schedule_within_budget_no_notification(self):
        """在预算内排班不应触发 anomaly 通知。"""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(
            return_value=_result_with_row(
                SimpleNamespace(daily_budget_yuan=5000.0, max_labor_cost_yuan=50000.0)
            )
        )
        employees = [
            SimpleNamespace(id="E001", name="张三", skills=["waiter", "cashier"], position="waiter", is_active=True),
        ]
        shifts = [
            {
                "employee_id": "E001",
                "shift_type": "morning",
                "start_time": time(9, 0),
                "end_time": time(13, 0),
                "position": "cashier",
            },
        ]
        with (
            patch(
                "src.services.workforce_auto_schedule_service.ScheduleRepository.get_by_date",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.services.workforce_auto_schedule_service.EmployeeRepository.get_by_store",
                new_callable=AsyncMock,
                return_value=employees,
            ),
            patch(
                "src.services.workforce_auto_schedule_service.StaffingPatternService.build_shifts_from_best_pattern",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch.object(
                WorkforceAutoScheduleService,
                "_generate_shifts_from_agent",
                new_callable=AsyncMock,
                return_value=shifts,
            ),
            patch.object(
                WorkforceAutoScheduleService,
                "_notify_anomalies",
                new_callable=AsyncMock,
                return_value=False,
            ) as mock_notify,
        ):
            result = await WorkforceAutoScheduleService.generate_schedule_with_constraints(
                store_id="S001",
                schedule_date=date(2026, 3, 10),
                db=db,
            )
        assert result["within_budget"] is True
        mock_notify.assert_not_awaited()

