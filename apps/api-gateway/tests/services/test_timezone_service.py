"""
timezone_service 单元测试
覆盖：
  1) UTC → 员工本地（香港、新加坡）
  2) 员工本地 → UTC
  3) 工资月份边界跨时区
"""

import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest  # noqa: E402

from src.services.timezone_service import TimezoneService  # noqa: E402


def _mk_db_with_employee(tz: str):
    emp = MagicMock()
    emp.timezone = tz
    db = MagicMock()
    db.get = AsyncMock(return_value=emp)
    return db


@pytest.mark.asyncio
async def test_utc_to_hk_local():
    svc = TimezoneService(_mk_db_with_employee("Asia/Hong_Kong"))
    utc_dt = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)
    local = await svc.to_employee_local_time(utc_dt, "EMP001")
    # HK UTC+8
    assert local.hour == 8
    assert local.tzinfo.key == "Asia/Hong_Kong"


@pytest.mark.asyncio
async def test_local_to_utc_naive():
    svc = TimezoneService(_mk_db_with_employee("Asia/Singapore"))
    naive_local = datetime(2026, 4, 17, 9, 0, 0)  # 当作 SG 本地时间
    utc = await svc.from_employee_local_time(naive_local, "EMP001")
    assert utc.tzinfo == timezone.utc
    # SG UTC+8 → UTC 1:00
    assert utc.hour == 1


@pytest.mark.asyncio
async def test_pay_month_boundaries_hk():
    svc = TimezoneService(_mk_db_with_employee("Asia/Hong_Kong"))
    start, end = await svc.get_employee_pay_month_boundaries("EMP001", 2026, 9)
    # HK 9/1 00:00 = UTC 8/31 16:00
    assert start == datetime(2026, 8, 31, 16, 0, 0, tzinfo=timezone.utc)
    # HK 10/1 00:00 = UTC 9/30 16:00
    assert end == datetime(2026, 9, 30, 16, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_format_date_display():
    svc = TimezoneService(_mk_db_with_employee("Asia/Hong_Kong"))
    utc_dt = datetime(2026, 4, 17, 16, 0, 0, tzinfo=timezone.utc)  # HK 24:00 → 次日
    formatted = await svc.format_datetime_for_display(utc_dt, "EMP001", "date")
    assert formatted == "2026-04-18"
