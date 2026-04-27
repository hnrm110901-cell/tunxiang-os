"""
假期管理服务 -- 纯函数实现（无 DB 依赖）

从 V2.x hr/leave_service.py 迁移提取。
所有函数接受参数、返回结果，不依赖数据库或外部服务。

核心能力：
- 假期类型与年度默认配额
- 请假申请校验
- 余额扣减计算
- 余额充足性模拟
- 年假发放逻辑
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# ── 假期类型 → 默认年度配额（天） ────────────────────────────────

DEFAULT_ANNUAL_QUOTAS: Dict[str, float] = {
    "annual": 5.0,  # 年假
    "sick": 15.0,  # 病假
    "personal": 5.0,  # 事假
    "marriage": 3.0,  # 婚假
    "maternity": 98.0,  # 产假
    "paternity": 15.0,  # 陪产假
    "bereavement": 3.0,  # 丧假
}

VALID_LEAVE_TYPES = set(DEFAULT_ANNUAL_QUOTAS.keys())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请假申请校验
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def validate_leave_request(
    leave_type: str,
    start_datetime: datetime,
    end_datetime: datetime,
    days: float,
) -> List[str]:
    """
    校验请假申请参数。

    Args:
        leave_type: 假期类型
        start_datetime: 开始时间
        end_datetime: 结束时间
        days: 请假天数

    Returns:
        错误列表（空列表表示校验通过）
    """
    errors: List[str] = []

    if leave_type not in VALID_LEAVE_TYPES:
        errors.append(f"无效的假期类型: {leave_type!r}，支持: {', '.join(sorted(VALID_LEAVE_TYPES))}")

    if end_datetime <= start_datetime:
        errors.append("结束时间必须晚于开始时间")

    if days <= 0:
        errors.append("请假天数必须为正数")

    return errors


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  余额计算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_balance_after_deduction(
    total_days: float,
    used_days: float,
    requested_days: float,
) -> Dict[str, Any]:
    """
    计算扣减请假天数后的余额。

    Args:
        total_days: 年度总配额
        used_days: 已使用天数
        requested_days: 本次申请天数

    Returns:
        {
            "sufficient": bool,
            "new_used_days": float,
            "new_remaining_days": float,
            "shortfall": float,  # 不足天数（sufficient=True 时为 0）
        }
    """
    remaining = total_days - used_days
    sufficient = remaining >= requested_days

    if sufficient:
        new_used = used_days + requested_days
        new_remaining = total_days - new_used
        return {
            "sufficient": True,
            "new_used_days": new_used,
            "new_remaining_days": new_remaining,
            "shortfall": 0.0,
        }
    else:
        return {
            "sufficient": False,
            "new_used_days": used_days,
            "new_remaining_days": remaining,
            "shortfall": requested_days - remaining,
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  模拟请假
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def simulate_leave(
    leave_type: str,
    requested_days: float,
    current_remaining: float,
) -> Dict[str, Any]:
    """
    模拟请假：检查余额是否足够。

    Args:
        leave_type: 假期类型
        requested_days: 申请天数
        current_remaining: 当前剩余天数

    Returns:
        {
            "leave_type": str,
            "requested_days": float,
            "current_remaining": float,
            "sufficient": bool,
            "shortfall": float,
        }
    """
    sufficient = current_remaining >= requested_days
    return {
        "leave_type": leave_type,
        "requested_days": requested_days,
        "current_remaining": current_remaining,
        "sufficient": sufficient,
        "shortfall": max(0.0, requested_days - current_remaining) if not sufficient else 0.0,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  年假发放
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_annual_leave_quota(
    seniority_years: int,
    custom_quota: Optional[float] = None,
) -> float:
    """
    计算年假配额。

    按工龄计算（中国劳动法规定）：
    - 工龄 < 1 年: 0 天
    - 1 <= 工龄 < 10 年: 5 天
    - 10 <= 工龄 < 20 年: 10 天
    - 工龄 >= 20 年: 15 天

    Args:
        seniority_years: 工龄（年）
        custom_quota: 自定义配额（覆盖默认规则）

    Returns:
        年假天数
    """
    if custom_quota is not None:
        return custom_quota

    if seniority_years < 1:
        return 0.0
    elif seniority_years < 10:
        return 5.0
    elif seniority_years < 20:
        return 10.0
    else:
        return 15.0


def init_leave_balance(
    leave_type: str,
    year: int,
    custom_quota: Optional[float] = None,
    seniority_years: int = 0,
) -> Dict[str, Any]:
    """
    初始化假期余额记录。

    Args:
        leave_type: 假期类型
        year: 年度
        custom_quota: 自定义配额
        seniority_years: 工龄年数（仅 annual 类型使用）

    Returns:
        {
            "leave_type": str,
            "year": int,
            "total_days": float,
            "used_days": float,
            "remaining_days": float,
        }
    """
    if leave_type not in VALID_LEAVE_TYPES:
        raise ValueError(f"无效的假期类型: {leave_type!r}")

    if leave_type == "annual":
        quota = custom_quota if custom_quota is not None else compute_annual_leave_quota(seniority_years)
    else:
        quota = custom_quota if custom_quota is not None else DEFAULT_ANNUAL_QUOTAS.get(leave_type, 0.0)

    return {
        "leave_type": leave_type,
        "year": year,
        "total_days": quota,
        "used_days": 0.0,
        "remaining_days": quota,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请假天数计算（工作日模式）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def count_leave_work_days(
    start_date: datetime,
    end_date: datetime,
    holidays: Optional[List[datetime]] = None,
) -> float:
    """
    计算请假区间内的工作日天数（排除周末和法定假日）。

    Args:
        start_date: 开始日期
        end_date: 结束日期
        holidays: 法定节假日列表（可选）

    Returns:
        工作日天数
    """
    if end_date <= start_date:
        return 0.0

    holiday_set = set()
    if holidays:
        holiday_set = {h.date() if isinstance(h, datetime) else h for h in holidays}

    count = 0.0
    current = start_date
    while current < end_date:
        d = current.date() if isinstance(current, datetime) else current
        # 排除周末（周六=5, 周日=6）
        if d.weekday() < 5 and d not in holiday_set:
            count += 1.0
        current = datetime(d.year, d.month, d.day) + timedelta(days=1)

    return count
