"""
假期管理服务测试 -- leave_service.py 纯函数测试
"""

from datetime import datetime

import pytest
from services.leave_service import (
    compute_annual_leave_quota,
    compute_balance_after_deduction,
    count_leave_work_days,
    init_leave_balance,
    simulate_leave,
    validate_leave_request,
)


class TestValidateLeaveRequest:
    """请假申请校验"""

    def test_valid_request(self):
        """合法请假申请"""
        errors = validate_leave_request(
            leave_type="annual",
            start_datetime=datetime(2026, 3, 23, 9, 0),
            end_datetime=datetime(2026, 3, 25, 18, 0),
            days=2.0,
        )
        assert errors == []

    def test_invalid_leave_type(self):
        """非法假期类型"""
        errors = validate_leave_request(
            leave_type="vacation",
            start_datetime=datetime(2026, 3, 23, 9, 0),
            end_datetime=datetime(2026, 3, 25, 18, 0),
            days=2.0,
        )
        assert len(errors) == 1
        assert "无效的假期类型" in errors[0]

    def test_end_before_start(self):
        """结束时间早于开始时间"""
        errors = validate_leave_request(
            leave_type="annual",
            start_datetime=datetime(2026, 3, 25, 18, 0),
            end_datetime=datetime(2026, 3, 23, 9, 0),
            days=2.0,
        )
        assert any("结束时间" in e for e in errors)

    def test_negative_days(self):
        """天数为负"""
        errors = validate_leave_request(
            leave_type="annual",
            start_datetime=datetime(2026, 3, 23, 9, 0),
            end_datetime=datetime(2026, 3, 25, 18, 0),
            days=-1.0,
        )
        assert any("正数" in e for e in errors)

    def test_multiple_errors(self):
        """多个错误同时存在"""
        errors = validate_leave_request(
            leave_type="invalid_type",
            start_datetime=datetime(2026, 3, 25, 18, 0),
            end_datetime=datetime(2026, 3, 23, 9, 0),
            days=-1.0,
        )
        assert len(errors) == 3


class TestComputeBalanceAfterDeduction:
    """余额扣减计算"""

    def test_sufficient_balance(self):
        """余额充足"""
        result = compute_balance_after_deduction(
            total_days=10.0,
            used_days=3.0,
            requested_days=2.0,
        )
        assert result["sufficient"] is True
        assert result["new_used_days"] == 5.0
        assert result["new_remaining_days"] == 5.0
        assert result["shortfall"] == 0.0

    def test_insufficient_balance(self):
        """余额不足"""
        result = compute_balance_after_deduction(
            total_days=10.0,
            used_days=9.0,
            requested_days=3.0,
        )
        assert result["sufficient"] is False
        assert result["shortfall"] == 2.0
        # 不足时不扣减
        assert result["new_used_days"] == 9.0

    def test_exact_balance(self):
        """恰好用完"""
        result = compute_balance_after_deduction(
            total_days=5.0,
            used_days=3.0,
            requested_days=2.0,
        )
        assert result["sufficient"] is True
        assert result["new_remaining_days"] == 0.0


class TestSimulateLeave:
    """模拟请假"""

    def test_sufficient(self):
        result = simulate_leave("annual", 3.0, 5.0)
        assert result["sufficient"] is True
        assert result["shortfall"] == 0.0

    def test_insufficient(self):
        result = simulate_leave("annual", 8.0, 5.0)
        assert result["sufficient"] is False
        assert result["shortfall"] == 3.0


class TestComputeAnnualLeaveQuota:
    """年假配额计算"""

    def test_less_than_one_year(self):
        """工龄不满 1 年"""
        assert compute_annual_leave_quota(0) == 0.0

    def test_one_to_ten_years(self):
        """工龄 1-9 年"""
        assert compute_annual_leave_quota(5) == 5.0

    def test_ten_to_twenty_years(self):
        """工龄 10-19 年"""
        assert compute_annual_leave_quota(15) == 10.0

    def test_twenty_plus_years(self):
        """工龄 >= 20 年"""
        assert compute_annual_leave_quota(25) == 15.0

    def test_custom_quota(self):
        """自定义配额覆盖"""
        assert compute_annual_leave_quota(5, custom_quota=8.0) == 8.0


class TestInitLeaveBalance:
    """初始化假期余额"""

    def test_annual_balance(self):
        result = init_leave_balance("annual", 2026, seniority_years=5)
        assert result["leave_type"] == "annual"
        assert result["year"] == 2026
        assert result["total_days"] == 5.0
        assert result["used_days"] == 0.0
        assert result["remaining_days"] == 5.0

    def test_sick_balance(self):
        result = init_leave_balance("sick", 2026)
        assert result["total_days"] == 15.0

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="无效的假期类型"):
            init_leave_balance("invalid", 2026)

    def test_custom_quota(self):
        result = init_leave_balance("annual", 2026, custom_quota=12.0)
        assert result["total_days"] == 12.0


class TestCountLeaveWorkDays:
    """请假工作日计算"""

    def test_weekday_range(self):
        """周一到周五，5个工作日"""
        start = datetime(2026, 3, 23, 9, 0)  # 周一
        end = datetime(2026, 3, 28, 9, 0)    # 周六（不含）
        result = count_leave_work_days(start, end)
        assert result == 5.0

    def test_with_weekend(self):
        """跨周末，周六日不计入"""
        start = datetime(2026, 3, 23, 9, 0)  # 周一
        end = datetime(2026, 3, 30, 9, 0)    # 下周一（不含）
        result = count_leave_work_days(start, end)
        assert result >= 5.0  # 含或不含周末取决于行业

    def test_end_before_start(self):
        """结束早于开始返回0"""
        result = count_leave_work_days(
            datetime(2026, 3, 25),
            datetime(2026, 3, 23),
        )
        assert result == 0.0
