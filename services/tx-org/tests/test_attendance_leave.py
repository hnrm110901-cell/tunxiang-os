"""考勤打卡与请假管理闭环测试

覆盖场景：
1. 正常打卡识别（on_time）
2. 迟到自动标记
3. 早退自动标记
4. 缺勤自动标记（有排班无打卡）
5. 请假申请触发余额检查
6. 请假申请创建（pending 状态）
7. 审批通过后余额扣减
8. 审批通过后 daily_attendance 标记 on_leave
9. 月度考勤汇总正确性
10. 薪资数据接口
"""

from __future__ import annotations

import os
import sys

# 将 tx-org/src 加入路径，使得 models/services 可以直接导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
# 将仓库根目录加入路径，使得 shared.ontology 可以导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from datetime import date, datetime, time, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import pytest

from services.attendance_engine import (
    GRACE_PERIOD_MINUTES,
    AttendanceEngine,
)
from services.leave_service import (
    VALID_LEAVE_TYPES,
    compute_balance_after_deduction,
    count_leave_work_days,
    validate_leave_request,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  AttendanceEngine (内存版) 测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCHEDULE = {
    "EMP001": {
        "2026-03-31": "morning",   # 8:00 - 15:00
        "2026-04-01": "morning",
        "2026-04-02": "evening",   # 15:00 - 22:00
    }
}


@pytest.fixture
def engine() -> AttendanceEngine:
    return AttendanceEngine(scheduled_shifts=SCHEDULE)


class TestClockIn:
    def test_on_time_clock_in(self, engine: AttendanceEngine) -> None:
        """正常打卡：班次开始时间±5分钟内，状态为 on_time"""
        clock_time = datetime(2026, 3, 31, 8, 3, 0)  # 8:03，宽限内
        result = engine.clock_in("EMP001", "STORE001", clock_time=clock_time)
        assert result["ok"] is True
        assert result["status"] == "on_time"
        assert result["diff_min"] == 3

    def test_late_clock_in_minor(self, engine: AttendanceEngine) -> None:
        """迟到打卡：超过宽限（5分钟），状态为 late"""
        clock_time = datetime(2026, 3, 31, 8, 20, 0)  # 8:20，迟到15分钟
        result = engine.clock_in("EMP001", "STORE001", clock_time=clock_time)
        assert result["ok"] is True
        assert result["status"] == "late"
        assert result["diff_min"] == 20

    def test_early_arrival(self, engine: AttendanceEngine) -> None:
        """提前超过1小时打卡：状态为 early"""
        clock_time = datetime(2026, 3, 31, 6, 30, 0)  # 6:30，提前90分钟
        result = engine.clock_in("EMP001", "STORE001", clock_time=clock_time)
        assert result["ok"] is True
        assert result["status"] == "early"

    def test_unscheduled_clock_in(self, engine: AttendanceEngine) -> None:
        """无排班打卡：状态为 unscheduled"""
        clock_time = datetime(2026, 4, 3, 9, 0, 0)  # 无排班日
        result = engine.clock_in("EMP001", "STORE001", clock_time=clock_time)
        assert result["ok"] is True
        assert result["status"] == "unscheduled"

    def test_invalid_method(self, engine: AttendanceEngine) -> None:
        """非法打卡方式"""
        result = engine.clock_in("EMP001", "STORE001", method="wifi")
        assert result["ok"] is False
        assert "Invalid method" in result["error"]


class TestClockOut:
    def test_normal_clock_out(self, engine: AttendanceEngine) -> None:
        """正常下班打卡：在班次结束时间±5分钟内"""
        engine.clock_in("EMP001", "STORE001", clock_time=datetime(2026, 3, 31, 8, 0))
        result = engine.clock_out("EMP001", "STORE001", clock_time=datetime(2026, 3, 31, 15, 0))
        assert result["ok"] is True
        assert result["status"] == "on_time"
        assert result["work_hours"] == pytest.approx(7.0, abs=0.05)

    def test_early_leave(self, engine: AttendanceEngine) -> None:
        """早退：提前超过宽限下班"""
        engine.clock_in("EMP001", "STORE001", clock_time=datetime(2026, 3, 31, 8, 0))
        result = engine.clock_out("EMP001", "STORE001", clock_time=datetime(2026, 3, 31, 14, 0))
        assert result["ok"] is True
        assert result["status"] == "early_leave"

    def test_overtime(self, engine: AttendanceEngine) -> None:
        """加班：超过班次结束时间30分钟+"""
        engine.clock_in("EMP001", "STORE001", clock_time=datetime(2026, 3, 31, 8, 0))
        result = engine.clock_out("EMP001", "STORE001", clock_time=datetime(2026, 3, 31, 15, 40))
        assert result["ok"] is True
        assert result["status"] == "overtime"
        assert result["diff_min"] == 40

    def test_no_clock_in_record(self, engine: AttendanceEngine) -> None:
        """无打卡上班记录时打卡下班"""
        result = engine.clock_out("EMP999", "STORE001", clock_time=datetime(2026, 3, 31, 15, 0))
        assert result["ok"] is False


class TestAbsenceDetection:
    def test_absent_employee(self, engine: AttendanceEngine) -> None:
        """有排班但未打卡：应出现在 absent 状态"""
        # EMP001 有排班但没有打卡
        daily = engine.get_daily_attendance("STORE001", date(2026, 3, 31))
        emp_record = next((r for r in daily if r["employee_id"] == "EMP001"), None)
        assert emp_record is not None
        assert emp_record["status"] == "absent"

    def test_no_schedule_no_clock_is_day_off(self, engine: AttendanceEngine) -> None:
        """无排班无打卡：应为 day_off"""
        engine2 = AttendanceEngine(scheduled_shifts={})
        engine2.clock_in("EMP001", "STORE001", clock_time=datetime(2026, 3, 31, 8, 0))
        engine2.clock_out("EMP001", "STORE001", clock_time=datetime(2026, 3, 31, 15, 0))
        daily = engine2.get_daily_attendance("STORE001", date(2026, 4, 5))
        # 无排班无打卡的员工不出现在日考勤列表中
        emp_record = next((r for r in daily if r["employee_id"] == "EMP001"), None)
        assert emp_record is None or emp_record["status"] == "day_off"


class TestMonthlySummary:
    def test_monthly_summary_counts(self, engine: AttendanceEngine) -> None:
        """月度汇总：正确统计出勤/迟到/旷工天数"""
        # 2026-03-31: 正常出勤
        engine.clock_in("EMP001", "STORE001", clock_time=datetime(2026, 3, 31, 8, 0))
        engine.clock_out("EMP001", "STORE001", clock_time=datetime(2026, 3, 31, 15, 0))

        # 2026-04-01: 迟到出勤
        engine.clock_in("EMP001", "STORE001", clock_time=datetime(2026, 4, 1, 8, 30))
        engine.clock_out("EMP001", "STORE001", clock_time=datetime(2026, 4, 1, 15, 0))

        summary_march = engine.get_monthly_summary("EMP001", "2026-03")
        assert summary_march["work_days"] == 1
        assert summary_march["late_count"] == 0

        summary_april = engine.get_monthly_summary("EMP001", "2026-04")
        assert summary_april["work_days"] == 1
        assert summary_april["late_count"] == 1

    def test_absent_count_in_summary(self, engine: AttendanceEngine) -> None:
        """月度汇总：旷工天数正确（有排班无打卡）"""
        # EMP001 在 2026-04-01 有排班但不打卡
        summary = engine.get_monthly_summary("EMP001", "2026-04")
        # 排班1天但work_days=0 → absent_count应为1
        assert summary["absent_count"] >= 1


class TestAnomalyDetection:
    def test_anomaly_detection(self, engine: AttendanceEngine) -> None:
        """考勤异常检测：缺勤被正确识别"""
        anomalies = engine.get_attendance_anomalies("STORE001", date(2026, 3, 31))
        absent_anomalies = [a for a in anomalies if a["anomaly_type"] == "absent"]
        assert len(absent_anomalies) >= 1
        assert absent_anomalies[0]["employee_id"] == "EMP001"

    def test_late_anomaly(self, engine: AttendanceEngine) -> None:
        """考勤异常检测：迟到被识别"""
        engine.clock_in("EMP001", "STORE001", clock_time=datetime(2026, 3, 31, 8, 30))
        anomalies = engine.get_attendance_anomalies("STORE001", date(2026, 3, 31))
        late_anomalies = [a for a in anomalies if a["anomaly_type"] == "late"]
        assert len(late_anomalies) >= 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LeaveService 测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestLeaveService:
    def test_valid_leave_request(self) -> None:
        """合法请假申请校验通过"""
        errors = validate_leave_request(
            leave_type="annual",
            start_datetime=datetime(2026, 4, 1),
            end_datetime=datetime(2026, 4, 5),
            days=5.0,
        )
        assert errors == []

    def test_invalid_leave_type(self) -> None:
        """非法假期类型返回错误"""
        errors = validate_leave_request(
            leave_type="vacation",
            start_datetime=datetime(2026, 4, 1),
            end_datetime=datetime(2026, 4, 5),
            days=5.0,
        )
        assert len(errors) > 0
        assert "vacation" in errors[0]

    def test_end_before_start(self) -> None:
        """结束日早于开始日返回错误"""
        errors = validate_leave_request(
            leave_type="annual",
            start_datetime=datetime(2026, 4, 5),
            end_datetime=datetime(2026, 4, 1),
            days=1.0,
        )
        assert len(errors) > 0

    def test_count_work_days_excludes_weekend(self) -> None:
        """工作日计算排除周末"""
        # 2026-03-30(周一) ~ 2026-04-03(周五): 5工作日
        days = count_leave_work_days(
            datetime(2026, 3, 30),
            datetime(2026, 4, 3, 23, 59, 59),
        )
        assert days == 5.0

    def test_count_work_days_over_weekend(self) -> None:
        """跨周末请假工作日计算"""
        # 2026-03-28(周六) ~ 2026-04-01(周三): 3工作日（周一/二/三）
        days = count_leave_work_days(
            datetime(2026, 3, 28),
            datetime(2026, 4, 1, 23, 59),
        )
        assert days == 3.0

    def test_balance_sufficient(self) -> None:
        """余额充足场景"""
        result = compute_balance_after_deduction(
            total_days=5.0,
            used_days=1.0,
            requested_days=3.0,
        )
        assert result["sufficient"] is True
        assert result["new_used_days"] == 4.0
        assert result["new_remaining_days"] == 1.0
        assert result["shortfall"] == 0.0

    def test_balance_insufficient(self) -> None:
        """余额不足场景"""
        result = compute_balance_after_deduction(
            total_days=5.0,
            used_days=4.0,
            requested_days=3.0,
        )
        assert result["sufficient"] is False
        assert result["shortfall"] == 2.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  AttendanceEngine 请假与 daily_attendance 集成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestLeaveIntegration:
    def test_apply_and_approve_leave(self, engine: AttendanceEngine) -> None:
        """请假申请 → 审批通过 → 余额扣减"""
        # 初始化余额
        balance = engine.init_leave_balance("EMP001")
        assert balance["annual"] == 5.0

        # 申请年假
        result = engine.apply_leave(
            employee_id="EMP001",
            leave_type="annual",
            start_date="2026-04-07",
            end_date="2026-04-09",
            reason="休假",
        )
        assert result["ok"] is True
        assert result["status"] == "pending"
        leave_id = result["leave_id"]

        # 审批通过
        approve_result = engine.approve_leave(leave_id, approved_by="MGR001", approved=True)
        assert approve_result["ok"] is True
        assert approve_result["status"] == "approved"

        # 验证余额扣减
        balance_after = engine.get_leave_balance("EMP001")
        annual = next(b for b in balance_after["balances"] if b["leave_type"] == "annual")
        # 申请3天（weekdays: 7,8,9 Apr 2026 = Mon-Wed）
        assert annual["remaining_days"] < 5.0

    def test_apply_leave_insufficient_balance(self, engine: AttendanceEngine) -> None:
        """余额不足时申请请假被拒绝"""
        engine.init_leave_balance("EMP001")
        # 一次申请超过余额
        result = engine.apply_leave(
            employee_id="EMP001",
            leave_type="annual",
            start_date="2026-04-01",
            end_date="2026-04-10",
            reason="长假",
        )
        assert result["ok"] is False
        assert "Insufficient" in result["error"]

    def test_on_leave_daily_status(self, engine: AttendanceEngine) -> None:
        """请假期间：daily_attendance 状态为 on_leave"""
        engine.init_leave_balance("EMP001")
        apply_result = engine.apply_leave(
            employee_id="EMP001",
            leave_type="annual",
            start_date="2026-04-01",
            end_date="2026-04-01",
            reason="单日休假",
        )
        engine.approve_leave(apply_result["leave_id"], "MGR001", approved=True)

        # 2026-04-01 有排班（morning）
        daily = engine.get_daily_attendance("STORE001", date(2026, 4, 1))
        emp_record = next((r for r in daily if r["employee_id"] == "EMP001"), None)
        assert emp_record is not None
        assert "on_leave" in emp_record["status"]

    def test_reject_leave(self, engine: AttendanceEngine) -> None:
        """拒绝请假：状态变为 rejected，余额不扣减"""
        engine.init_leave_balance("EMP001")
        apply_result = engine.apply_leave(
            employee_id="EMP001",
            leave_type="annual",
            start_date="2026-04-01",
            end_date="2026-04-01",
            reason="申请",
        )
        leave_id = apply_result["leave_id"]

        # 拒绝
        reject_result = engine.approve_leave(leave_id, "MGR001", approved=False)
        assert reject_result["status"] == "rejected"

        # 余额不扣减
        balance_after = engine.get_leave_balance("EMP001")
        annual = next(b for b in balance_after["balances"] if b["leave_type"] == "annual")
        assert annual["remaining_days"] == 5.0  # 未扣减


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  attendance_repository 辅助函数单元测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestAttendanceRepositoryHelpers:
    """测试 attendance_routes.py 内的状态计算函数（通过直接导入）"""

    def test_calculate_clock_in_on_time(self) -> None:
        """上班打卡：宽限内 → on_time"""
        from api.attendance_routes import _calculate_clock_in_status

        clock_time = datetime(2026, 3, 31, 8, 3, tzinfo=timezone.utc)
        shift_start = time(8, 0)
        status, diff = _calculate_clock_in_status(clock_time, shift_start, grace_minutes=5)
        assert status == "on_time"
        assert diff == 3

    def test_calculate_clock_in_late(self) -> None:
        """上班打卡：超宽限 → late"""
        from api.attendance_routes import _calculate_clock_in_status

        clock_time = datetime(2026, 3, 31, 8, 20, tzinfo=timezone.utc)
        shift_start = time(8, 0)
        status, diff = _calculate_clock_in_status(clock_time, shift_start, grace_minutes=5)
        assert status == "late"
        assert diff == 20

    def test_calculate_clock_out_early_leave(self) -> None:
        """下班打卡：提前 → early_leave"""
        from api.attendance_routes import _calculate_clock_out_status

        clock_time = datetime(2026, 3, 31, 14, 30, tzinfo=timezone.utc)
        shift_end = time(15, 0)
        status, diff, ot = _calculate_clock_out_status(
            clock_time, shift_end, grace_minutes=5, overtime_min=30
        )
        assert status == "early_leave"
        assert diff == -30
        assert ot == 0.0

    def test_calculate_clock_out_overtime(self) -> None:
        """下班打卡：加班超30分钟 → overtime"""
        from api.attendance_routes import _calculate_clock_out_status

        clock_time = datetime(2026, 3, 31, 15, 45, tzinfo=timezone.utc)
        shift_end = time(15, 0)
        status, diff, ot = _calculate_clock_out_status(
            clock_time, shift_end, grace_minutes=5, overtime_min=30
        )
        assert status == "overtime"
        assert diff == 45
        assert ot == pytest.approx(0.75, abs=0.01)

    def test_calculate_clock_out_no_schedule(self) -> None:
        """无排班下班打卡：unscheduled"""
        from api.attendance_routes import _calculate_clock_out_status

        clock_time = datetime(2026, 3, 31, 15, 0, tzinfo=timezone.utc)
        status, diff, ot = _calculate_clock_out_status(
            clock_time, None, grace_minutes=5, overtime_min=30
        )
        assert status == "unscheduled"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  leave_repository 回调函数测试（Mock DB）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestLeaveRepositoryCallbacks:
    """测试审批回调逻辑（Mock DB）"""

    @pytest.mark.asyncio
    async def test_on_leave_approved_calls_deduct(self) -> None:
        """审批通过：调用余额扣减和 daily_attendance 更新"""
        from services.leave_repository import on_leave_approved, BALANCE_CHECKED_TYPES

        # Mock DB
        db = AsyncMock()

        # Mock get_leave_request 返回一条 annual 请假
        leave_data = {
            "id": "abc123",
            "tenant_id": "t1",
            "store_id": "s1",
            "employee_id": "EMP001",
            "leave_type": "annual",
            "start_date": date(2026, 4, 1),
            "end_date": date(2026, 4, 2),
            "days_requested": 2.0,
            "status": "pending",
        }

        with patch(
            "services.leave_repository.get_leave_request",
            new_callable=AsyncMock,
            return_value=leave_data,
        ), patch(
            "services.leave_repository.deduct_leave_balance",
            new_callable=AsyncMock,
        ) as mock_deduct, patch(
            "services.leave_repository.update_daily_attendance_on_leave",
            new_callable=AsyncMock,
        ) as mock_update_da:
            result = await on_leave_approved("abc123", "t1", db)

            assert result["status"] == "approved"
            assert result["days_approved"] == 2.0
            # 年假应触发余额扣减
            mock_deduct.assert_called_once()
            # 两天 → 两次 daily_attendance 更新
            assert mock_update_da.call_count == 2

    @pytest.mark.asyncio
    async def test_on_leave_approved_no_deduct_for_sick(self) -> None:
        """病假审批通过：不扣减余额（病假不在 BALANCE_CHECKED_TYPES）"""
        from services.leave_repository import on_leave_approved, BALANCE_CHECKED_TYPES

        assert "sick" not in BALANCE_CHECKED_TYPES

        db = AsyncMock()
        leave_data = {
            "id": "xyz456",
            "tenant_id": "t1",
            "store_id": "s1",
            "employee_id": "EMP001",
            "leave_type": "sick",
            "start_date": date(2026, 4, 1),
            "end_date": date(2026, 4, 1),
            "days_requested": 1.0,
            "status": "pending",
        }

        with patch(
            "services.leave_repository.get_leave_request",
            new_callable=AsyncMock,
            return_value=leave_data,
        ), patch(
            "services.leave_repository.deduct_leave_balance",
            new_callable=AsyncMock,
        ) as mock_deduct, patch(
            "services.leave_repository.update_daily_attendance_on_leave",
            new_callable=AsyncMock,
        ):
            await on_leave_approved("xyz456", "t1", db)
            # 病假不扣减余额
            mock_deduct.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_leave_approved_raises_for_nonexistent(self) -> None:
        """审批回调：不存在的请假申请抛出 ValueError"""
        from services.leave_repository import on_leave_approved

        db = AsyncMock()

        with patch(
            "services.leave_repository.get_leave_request",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(ValueError, match="请假申请不存在"):
                await on_leave_approved("nonexistent", "t1", db)
